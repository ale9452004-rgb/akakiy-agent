"""
Единый слой разрешений и безопасности (Permissions & Safety Layer) Акакия.

Обеспечивает:
- Определение уровней риска (RiskLevel: SAFE, LOW, MEDIUM, HIGH, CRITICAL);
- Четкое разделение безопасных операций и операций, требующих подтверждения пользователя;
- Контекстный анализ риска (перезапись существующих файлов, опасные команды PowerShell, git-мутации, удаление);
- Централизованный перехват и валидацию разрешений ДО фактического выполнения действия;
- Поддержку GUI модальных окон (request_confirmation) и CLI-диалогов подтверждения;
- Интеграцию с Dispatcher, Sub-Agent Pipeline, Task Planner и PlanExecutor;
- Защиту от дублирования логики разрешений в каждом отдельном инструменте.
"""

from dataclasses import dataclass, field
from enum import Enum
import os
from pathlib import Path
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from config import PROJECT_PATH


class RiskLevel(str, Enum):
    """
    Уровни риска для операций и действий Акакия.
    """
    SAFE = "safe"          # Read-only, поиск, анализ, валидация синтаксиса
    LOW = "low"            # Безопасные добавления (задачи, заметки, списки, факты в память, артефакты)
    MEDIUM = "medium"      # Файловые правки, создание файлов, git commit, удаление единичных записей
    HIGH = "high"          # Терминальные команды PowerShell, git push, перезапись файлов, перемещение, удаление списков
    CRITICAL = "critical"  # Деструктивные команды ОС, жесткий сброс git reset --hard, удаление системных файлов

    @property
    def rank(self) -> int:
        ranks = {
            RiskLevel.SAFE: 0,
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4,
        }
        return ranks.get(self, 0)

    def is_safe(self) -> bool:
        return self in (RiskLevel.SAFE, RiskLevel.LOW)

    def is_dangerous(self) -> bool:
        return self in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)


class SecurityPolicy(str, Enum):
    """
    Политика безопасности приложения.
    """
    NORMAL = "normal"          # MEDIUM, HIGH, CRITICAL требуют подтверждения пользователя
    STRICT = "strict"          # Все мутации (LOW, MEDIUM, HIGH, CRITICAL) требуют подтверждения
    PERMISSIVE = "permissive"  # Только HIGH и CRITICAL требуют подтверждения (MEDIUM авто-одобряется)
    READ_ONLY = "read_only"    # Любые мутации и выполнение команд запрещены


@dataclass
class ActionDescriptor:
    """
    Описание планируемого действия перед оценкой разрешений.
    """
    action_type: str                  # "tool", "subagent", "file", "command", "git"
    name: str                         # имя инструмента, субагента или действия
    params: Dict[str, Any] = field(default_factory=dict)
    target: Optional[str] = None      # целевой файл, ресурс или идентификатор
    description: Optional[str] = None # описание для человека
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionAssessment:
    """
    Результат проверки разрешений и оценки безопасности действия.
    """
    action_type: str
    name: str
    risk_level: RiskLevel
    requires_confirmation: bool
    allowed: bool = True
    reason: str = ""
    details: str = ""
    is_destructive: bool = False
    params: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "name": self.name,
            "risk_level": self.risk_level.value,
            "requires_confirmation": self.requires_confirmation,
            "allowed": self.allowed,
            "reason": self.reason,
            "details": self.details,
            "is_destructive": self.is_destructive,
            "params": self.params,
            "metadata": self.metadata,
        }


class PermissionManager:
    """
    Централизованный менеджер разрешений и безопасности Акакия.
    """

    # Шаблоны критически деструктивных терминальных команд
    CRITICAL_COMMAND_PATTERNS = [
        re.compile(r"\b(remove-item|rmdir|rm)\b.*(-recurse|-r|-force|-f)", re.IGNORECASE),
        re.compile(r"\bformat(-volume)?\b", re.IGNORECASE),
        re.compile(r"\bdel\b.*(/[fF]|/[sS]|/[qQ])", re.IGNORECASE),
        re.compile(r"\bgit\s+(reset\s+--hard|clean\s+-[fF]|checkout\s+-f)\b", re.IGNORECASE),
        re.compile(r"\b(drop\s+database|truncate\s+table)\b", re.IGNORECASE),
        re.compile(r"\b(rm\s+-rf|rm\s+-fr)\b", re.IGNORECASE),
        re.compile(r"\bshutdown(\.exe)?\b", re.IGNORECASE),
        re.compile(r"\bstop-computer\b", re.IGNORECASE),
    ]

    # Шаблоны безопасных проверочных команд
    SAFE_COMMAND_PATTERNS = [
        re.compile(r"^\s*git\s+(status|diff|log|branch|show)\b", re.IGNORECASE),
        re.compile(r"^\s*(dir|ls|Get-ChildItem)\b", re.IGNORECASE),
        re.compile(r"^\s*(echo|Write-Host|Get-Date)\b", re.IGNORECASE),
        re.compile(r"^\s*(\.\\)?\.venv\\Scripts\\python(\.exe)?\s+-m\s+(py_compile|unittest)\b", re.IGNORECASE),
        re.compile(r"^\s*python(\.exe)?\s+-m\s+(py_compile|unittest)\b", re.IGNORECASE),
    ]

    # Защищенные системные файлы и папки
    PROTECTED_FILE_PATTERNS = [
        re.compile(r"(^|[/\\])\.git([/\\]|$)", re.IGNORECASE),
        re.compile(r"(^|[/\\])\.env(\.[a-zA-Z0-9_\-]+)?$", re.IGNORECASE),
        re.compile(r"\.(pem|key|pfx|pkcs12)$", re.IGNORECASE),
        re.compile(r"(^|[/\\])id_rsa(_[a-zA-Z0-9_\-]+)?$", re.IGNORECASE),
    ]

    def __init__(
        self,
        policy: SecurityPolicy = SecurityPolicy.NORMAL,
        project_path: Optional[Union[str, Path]] = None,
        confirmation_handler: Optional[Callable[[str, Dict[str, Any]], bool]] = None
    ):
        self.policy = policy
        self.project_path = Path(project_path).resolve() if project_path else PROJECT_PATH.resolve()
        self._confirmation_handler = confirmation_handler
        self._lock = threading.RLock()

    # =========================================================================
    # Настройка политики и обработчиков
    # =========================================================================

    def set_policy(self, policy: SecurityPolicy) -> None:
        with self._lock:
            self.policy = policy

    def get_policy(self) -> SecurityPolicy:
        with self._lock:
            return self.policy

    def set_confirmation_handler(self, handler: Optional[Callable[[str, Dict[str, Any]], bool]]) -> None:
        with self._lock:
            self._confirmation_handler = handler

    def get_confirmation_handler(self) -> Optional[Callable[[str, Dict[str, Any]], bool]]:
        with self._lock:
            return self._confirmation_handler

    # =========================================================================
    # Оценка разрешений инструмента (Tool Assessment)
    # =========================================================================

    def assess_tool(self, tool_name: str, kwargs: Optional[Dict[str, Any]] = None) -> PermissionAssessment:
        """
        Централизованная оценка разрешений и уровня риска для инструмента.
        """
        params = dict(kwargs or {})
        t_name = str(tool_name).strip()

        # 1. Проверка политики READ_ONLY
        if self.policy == SecurityPolicy.READ_ONLY:
            if t_name not in self._get_readonly_tools():
                return PermissionAssessment(
                    action_type="tool",
                    name=t_name,
                    risk_level=RiskLevel.HIGH,
                    requires_confirmation=False,
                    allowed=False,
                    reason="Политика безопасности READ_ONLY запрещает любые мутации и выполнение команд.",
                    details="Операция заблокирована: активен режим 'Только для чтения'.",
                    params=params
                )

        # 2. Оценка по типам инструментов
        if t_name == "run_command":
            return self._assess_run_command(params)

        elif t_name == "write_file":
            return self._assess_write_file(params)

        elif t_name == "edit_file":
            return self._assess_edit_file(params)

        elif t_name == "git_commit":
            return self._assess_git_commit(params)

        elif t_name == "git_push":
            return self._assess_git_push(params)

        elif t_name in ("delete_task", "delete_reminder", "delete_note", "delete_list_item", "forget_memory"):
            return self._assess_item_deletion(t_name, params)

        elif t_name == "delete_list":
            return self._assess_list_deletion(params)

        elif t_name in (
            "list_files", "find_file", "read_file", "search_files", "analyze_file",
            "validate_project", "git_status", "git_diff", "git_log",
            "recall_memory", "list_tasks", "list_reminders", "list_notes",
            "show_list", "check_due_reminders", "daily_briefing"
        ):
            # Read-only инструменты
            return PermissionAssessment(
                action_type="tool",
                name=t_name,
                risk_level=RiskLevel.SAFE,
                requires_confirmation=False,
                allowed=True,
                reason="Безопасная операция чтения/инспекции.",
                details=f"Инструмент: {t_name}",
                params=params
            )

        elif t_name in (
            "create_task", "create_reminder", "complete_task", "complete_reminder",
            "create_note", "create_list", "add_list_item", "complete_list_item", "remember"
        ):
            # Безопасные локальные добавления/отметки
            req_confirm = (self.policy == SecurityPolicy.STRICT)
            return PermissionAssessment(
                action_type="tool",
                name=t_name,
                risk_level=RiskLevel.LOW,
                requires_confirmation=req_confirm,
                allowed=True,
                reason="Безопасная операция создания/обновления пользовательских данных.",
                details=self._format_generic_tool_details(t_name, params),
                params=params
            )

        # Неизвестный инструмент
        req_confirm = self._requires_confirmation_for_risk(RiskLevel.MEDIUM)
        return PermissionAssessment(
            action_type="tool",
            name=t_name,
            risk_level=RiskLevel.MEDIUM,
            requires_confirmation=req_confirm,
            allowed=True,
            reason=f"Пользовательский инструмент: {t_name}",
            details=self._format_generic_tool_details(t_name, params),
            params=params
        )

    # =========================================================================
    # Оценка разрешений Sub-Agent (SubAgent Assessment)
    # =========================================================================

    def assess_subagent(
        self,
        agent_name: str,
        context: Optional[Any] = None,
        step: Optional[Any] = None
    ) -> PermissionAssessment:
        """
        Централизованная оценка разрешений и уровня риска для Sub-Agent действия.
        """
        name = str(agent_name).strip().lower()
        meta: Dict[str, Any] = {}
        task_str = ""
        files: List[str] = []

        if context is not None:
            if hasattr(context, "metadata") and isinstance(context.metadata, dict):
                meta.update(context.metadata)
            if hasattr(context, "task"):
                task_str = str(context.task or "")
            if hasattr(context, "files") and isinstance(context.files, (list, tuple)):
                files = [str(f) for f in context.files]

        if step is not None:
            if hasattr(step, "metadata") and isinstance(step.metadata, dict):
                meta.update(step.metadata)
            if hasattr(step, "task") and step.task:
                task_str = str(step.task)
            elif hasattr(step, "description") and not task_str:
                task_str = str(step.description)
            if hasattr(step, "files") and step.files:
                files.extend([str(f) for f in step.files])

        # 1. FileAgent
        if name == "file":
            return self._assess_file_agent(task_str, meta, files)

        # 2. CodingAgent
        elif name == "coding":
            return self._assess_coding_agent(task_str, meta, files)

        # 3. EchoAgent и ResearchAgent (безопасные read-only агенты)
        elif name in ("echo", "research"):
            return PermissionAssessment(
                action_type="subagent",
                name=name,
                risk_level=RiskLevel.SAFE,
                requires_confirmation=False,
                allowed=True,
                reason=f"Безопасный агент инспекции/исследования '{name}'.",
                details=f"Субагент: {name}\nЗадача: {task_str or 'Исследование'}",
                params=meta,
                metadata={"task": task_str, "files": files}
            )

        # 4. Презентации, изображения и документы (генерация новых артефактов)
        elif name in ("presentation", "document", "image"):
            req_confirm = (self.policy == SecurityPolicy.STRICT)
            return PermissionAssessment(
                action_type="subagent",
                name=name,
                risk_level=RiskLevel.LOW,
                requires_confirmation=req_confirm,
                allowed=True,
                reason=f"Генерация нового артефакта через субагента '{name}'.",
                details=f"Субагент: {name}\nЗадача: {task_str or 'Создание артефакта'}",
                params=meta,
                metadata={"task": task_str, "files": files}
            )

        # 5. Произвольный субагент
        action = str(meta.get("action") or "").lower()
        has_mutating_action = (
            action in ("create", "write", "edit", "move", "copy", "delete", "execute", "run")
            or bool(meta.get("edits"))
            or any(w in task_str.lower() for w in ["перезапиши", "удали", "стереть", "move", "delete"])
        )
        if has_mutating_action:
            risk = RiskLevel.MEDIUM
            req_confirm = self._requires_confirmation_for_risk(risk)
            reason = f"Модифицирующее действие субагента '{name}'."
        else:
            risk = RiskLevel.LOW
            req_confirm = (self.policy == SecurityPolicy.STRICT)
            reason = f"Безопасный запуск субагента '{name}'."

        return PermissionAssessment(
            action_type="subagent",
            name=name,
            risk_level=risk,
            requires_confirmation=req_confirm,
            allowed=True,
            reason=reason,
            details=f"Субагент: {name}\nЗадача: {task_str or 'Выполнение задачи'}\nУровень риска: [{risk.value.upper()}]",
            params=meta,
            metadata={"task": task_str, "files": files}
        )

    # =========================================================================
    # Централизованный метод запроса подтверждения (Request Confirmation)
    # =========================================================================

    def check_and_confirm(
        self,
        action_type: str,
        name: str,
        params: Optional[Dict[str, Any]] = None,
        context: Optional[Any] = None
    ) -> Tuple[bool, str, PermissionAssessment]:
        """
        Проверяет разрешение и при необходимости запрашивает подтверждение пользователя.

        Возвращает:
        (approved: bool, message: str, assessment: PermissionAssessment)
        """
        params_dict = dict(params or {})

        if action_type == "tool":
            assessment = self.assess_tool(name, params_dict)
        elif action_type == "subagent":
            assessment = self.assess_subagent(name, context=context)
        else:
            assessment = PermissionAssessment(
                action_type=action_type,
                name=name,
                risk_level=RiskLevel.MEDIUM,
                requires_confirmation=self._requires_confirmation_for_risk(RiskLevel.MEDIUM),
                allowed=True,
                reason=f"Действие: {action_type}:{name}",
                details=f"Тип: {action_type}\nДействие: {name}",
                params=params_dict
            )

        # 1. Если действие полностью заблокировано политикой безопасности
        if not assessment.allowed:
            return False, f"Заблокировано политикой безопасности: {assessment.reason}", assessment

        # 2. Если подтверждение не требуется — автоматическое одобрение
        if not assessment.requires_confirmation:
            return True, "Автоматически разрешено политикой безопасности.", assessment

        # 3. Вызов обработчика подтверждения
        approved = self.request_confirmation(assessment)
        if approved:
            return True, "Действие одобрено пользователем.", assessment
        else:
            return False, "Пользователь отменил выполнение.", assessment

    def request_confirmation(
        self,
        assessment: PermissionAssessment,
        handler: Optional[Callable[[str, Dict[str, Any]], bool]] = None
    ) -> bool:
        """
        Запрашивает подтверждение у пользователя через GUI-обработчик или CLI-диалог.
        """
        if not assessment.requires_confirmation:
            return True
        if not assessment.allowed:
            return False

        effective_handler = handler or self._confirmation_handler

        # Если задан кастомный обработчик (например, GUI через очередь)
        if effective_handler is not None:
            try:
                # Передаем имя и параметры в существующей сигнатуре GUI
                approved = effective_handler(assessment.name, assessment.params)
                if isinstance(approved, str):
                    return approved.strip().lower() in ("да", "д", "yes", "y", "true", "1")
                return bool(approved)
            except Exception:
                return False

        # Консольный режим (CLI)
        import sys
        if not getattr(sys.stdin, "isatty", lambda: False)():
            # В неинтерактивном headless-режиме без установленного обработчика
            # одобряем некритические действия для сохранения обратной совместимости API
            return assessment.risk_level != RiskLevel.CRITICAL

        print("\n--- ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ БЕЗОПАСНОСТИ ---")
        badge = assessment.risk_level.value.upper()
        print(f"Действие: [{badge}] {assessment.name}")
        if assessment.reason:
            print(f"Причина: {assessment.reason}")
        if assessment.details:
            print(assessment.details)

        try:
            prompt = "\nРазрешить выполнение? (да/нет): "
            response = input(prompt).strip().lower()
            return response in ("да", "д", "yes", "y")
        except (EOFError, KeyboardInterrupt):
            return False

    # =========================================================================
    # Внутренние классификаторы рисков
    # =========================================================================

    def _assess_run_command(self, params: Dict[str, Any]) -> PermissionAssessment:
        command = str(params.get("command", "")).strip()

        # 1. Проверка на деструктивные команды ОС
        for pattern in self.CRITICAL_COMMAND_PATTERNS:
            if pattern.search(command):
                return PermissionAssessment(
                    action_type="command",
                    name="run_command",
                    risk_level=RiskLevel.CRITICAL,
                    requires_confirmation=True,
                    allowed=True,
                    is_destructive=True,
                    reason="Обнаружена потенциально деструктивная системная команда.",
                    details=(
                        "Действие: Выполнение команды оболочки PowerShell\n"
                        f"Команда: {command}\n"
                        "Уровень риска: [CRITICAL]\n"
                        "ВНИМАНИЕ: Команда может привести к безвозвратной потере файлов или состояния системы!"
                    ),
                    params=params
                )

        # 2. Проверка на безопасные команды чтения/статуса
        for pattern in self.SAFE_COMMAND_PATTERNS:
            if pattern.search(command):
                req_confirm = (self.policy == SecurityPolicy.STRICT)
                return PermissionAssessment(
                    action_type="command",
                    name="run_command",
                    risk_level=RiskLevel.SAFE,
                    requires_confirmation=req_confirm,
                    allowed=True,
                    reason="Безопасная информационная команда PowerShell.",
                    details=f"Действие: Выполнение проверочной команды\nКоманда: {command}\nУровень риска: [SAFE]",
                    params=params
                )

        # 3. Стандартная команда PowerShell
        req_confirm = self._requires_confirmation_for_risk(RiskLevel.HIGH)
        return PermissionAssessment(
            action_type="command",
            name="run_command",
            risk_level=RiskLevel.HIGH,
            requires_confirmation=req_confirm,
            allowed=True,
            reason="Выполнение внешней команды оболочки PowerShell.",
            details=(
                "Действие: Выполнение команды оболочки PowerShell\n"
                f"Команда: {command}\n"
                "Уровень риска: [HIGH]"
            ),
            params=params
        )

    def _assess_write_file(self, params: Dict[str, Any]) -> PermissionAssessment:
        filename = str(params.get("filename", "")).strip()
        content = params.get("content", "")
        size_bytes = len(content.encode("utf-8")) if isinstance(content, str) else 0

        # 1. Проверка защищенных системных файлов
        if self._is_protected_file(filename):
            return PermissionAssessment(
                action_type="file",
                name="write_file",
                risk_level=RiskLevel.CRITICAL,
                requires_confirmation=False,
                allowed=False,
                reason="Запись в защищённый системный файл запрещена политикой безопасности.",
                details=f"Заблокирована попытка записи в файл: {filename}",
                params=params
            )

        # 2. Проверка существования файла (риск перезаписи)
        resolved = self._resolve_project_path(filename)
        is_overwrite = resolved is not None and resolved.exists()

        risk = RiskLevel.HIGH if is_overwrite else RiskLevel.MEDIUM
        req_confirm = self._requires_confirmation_for_risk(risk)

        status_text = "Внимание: файл уже существует и будет полностью перезаписан!" if is_overwrite else "Создание нового файла."

        lines = [
            f"Файл: {filename}",
            f"Размер содержимого: {size_bytes} байт",
            f"Статус: {status_text}",
            f"Уровень риска: [{risk.value.upper()}]"
        ]

        return PermissionAssessment(
            action_type="file",
            name="write_file",
            risk_level=risk,
            requires_confirmation=req_confirm,
            allowed=True,
            is_destructive=is_overwrite,
            reason="Перезапись существующего файла." if is_overwrite else "Создание нового файла.",
            details="\n".join(lines),
            params=params
        )

    def _assess_edit_file(self, params: Dict[str, Any]) -> PermissionAssessment:
        filename = str(params.get("filename", "")).strip()
        old_text = str(params.get("old_text", ""))
        new_text = str(params.get("new_text", ""))

        if self._is_protected_file(filename):
            return PermissionAssessment(
                action_type="file",
                name="edit_file",
                risk_level=RiskLevel.CRITICAL,
                requires_confirmation=False,
                allowed=False,
                reason="Редактирование защищённого системного файла запрещено.",
                details=f"Заблокирована попытка модификации файла: {filename}",
                params=params
            )

        old_preview = old_text if len(old_text) <= 120 else old_text[:117] + "..."
        new_preview = new_text if len(new_text) <= 120 else new_text[:117] + "..."

        lines = [
            f"Файл: {filename}",
            "Замена текста:",
            f"  Было:  {old_preview}",
            f"  Стало: {new_preview}",
            "Уровень риска: [MEDIUM]"
        ]

        req_confirm = self._requires_confirmation_for_risk(RiskLevel.MEDIUM)
        return PermissionAssessment(
            action_type="file",
            name="edit_file",
            risk_level=RiskLevel.MEDIUM,
            requires_confirmation=req_confirm,
            allowed=True,
            reason="Точечная модификация содержимого файла проекта.",
            details="\n".join(lines),
            params=params
        )

    def _assess_git_commit(self, params: Dict[str, Any]) -> PermissionAssessment:
        message = str(params.get("message", "")).strip()

        lines = [f"Сообщение коммита: {message}"]
        try:
            from tools.git import git_status
            status = git_status()
            if status.get("success") and status.get("stdout", "").strip():
                lines.append("Изменения для коммита:")
                for line in status["stdout"].splitlines()[:15]:
                    lines.append(f"  {line}")
            else:
                lines.append("Изменения: нет обнаруженных изменений")
        except Exception:
            pass

        lines.append("Уровень риска: [MEDIUM]")

        req_confirm = self._requires_confirmation_for_risk(RiskLevel.MEDIUM)
        return PermissionAssessment(
            action_type="git",
            name="git_commit",
            risk_level=RiskLevel.MEDIUM,
            requires_confirmation=req_confirm,
            allowed=True,
            reason="Фиксация изменений в локальном Git-репозитории.",
            details="\n".join(lines),
            params=params
        )

    def _assess_git_push(self, params: Dict[str, Any]) -> PermissionAssessment:
        lines = []
        try:
            from tools.git import run_git_command
            branch_res = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])
            branch = branch_res.get("stdout", "").strip() if branch_res.get("success") else "неизвестно"
            remote_res = run_git_command(["remote", "-v"])
            remote = remote_res.get("stdout", "").strip() if remote_res.get("success") else "не настроен"
            lines.append(f"Ветка: {branch}")
            lines.append(f"Удалённый репозиторий:\n{remote}")
        except Exception:
            lines.append("Отправка текущей ветки в remote")

        lines.append("Уровень риска: [HIGH]")

        req_confirm = self._requires_confirmation_for_risk(RiskLevel.HIGH)
        return PermissionAssessment(
            action_type="git",
            name="git_push",
            risk_level=RiskLevel.HIGH,
            requires_confirmation=req_confirm,
            allowed=True,
            reason="Отправка локальных коммитов в удалённый Git-репозиторий.",
            details="\n".join(lines),
            params=params
        )

    def _assess_item_deletion(self, tool_name: str, params: Dict[str, Any]) -> PermissionAssessment:
        req_confirm = self._requires_confirmation_for_risk(RiskLevel.MEDIUM)
        details = self._format_generic_tool_details(tool_name, params)
        details += "\nУровень риска: [MEDIUM]"

        return PermissionAssessment(
            action_type="deletion",
            name=tool_name,
            risk_level=RiskLevel.MEDIUM,
            requires_confirmation=req_confirm,
            allowed=True,
            is_destructive=True,
            reason=f"Удаление элемента: {tool_name}",
            details=details,
            params=params
        )

    def _assess_list_deletion(self, params: Dict[str, Any]) -> PermissionAssessment:
        name = str(params.get("name", "")).strip()
        req_confirm = self._requires_confirmation_for_risk(RiskLevel.HIGH)
        details = (
            "Действие: Удаление списка целиком со всеми пунктами\n"
            f"Имя списка: {name}\n"
            "Уровень риска: [HIGH]\n"
            "Внимание: Все пункты списка будут безвозвратно удалены!"
        )

        return PermissionAssessment(
            action_type="deletion",
            name="delete_list",
            risk_level=RiskLevel.HIGH,
            requires_confirmation=req_confirm,
            allowed=True,
            is_destructive=True,
            reason="Полное удаление списка со всеми вложенными элементами.",
            details=details,
            params=params
        )

    def _assess_file_agent(
        self,
        task: str,
        meta: Dict[str, Any],
        context_files: List[str]
    ) -> PermissionAssessment:
        action = str(meta.get("action") or "").lower()
        task_lower = task.lower()

        # Разрешение действия
        if not action:
            if any(w in task_lower for w in ["создай", "запиши", "сформируй", "create", "write"]):
                action = "create"
            elif any(w in task_lower for w in ["перемести", "переименуй", "move", "rename"]):
                action = "move"
            elif any(w in task_lower for w in ["скопируй", "копируй", "copy"]):
                action = "copy"
            elif any(w in task_lower for w in ["удали", "стереть", "delete", "remove"]):
                action = "delete"
            else:
                action = "read"

        # Удаление файлов через FileAgent строго запрещено
        if action in ("delete", "remove"):
            return PermissionAssessment(
                action_type="subagent",
                name="file",
                risk_level=RiskLevel.CRITICAL,
                requires_confirmation=False,
                allowed=False,
                reason="Удаление файлов через FileAgent запрещено архитектурным регламентом.",
                details="FileAgent не поддерживает удаление файлов в целях безопасности.",
                params=meta
            )

        if action in ("search", "find", "read", "metadata", "stat"):
            return PermissionAssessment(
                action_type="subagent",
                name="file",
                risk_level=RiskLevel.SAFE,
                requires_confirmation=False,
                allowed=True,
                reason="Безопасная операция чтения/поиска файлов через FileAgent.",
                details=f"Субагент: FileAgent\nОперация: {action}\nЗадача: {task}",
                params=meta
            )

        # Модифицирующие операции (create, copy, move)
        target = meta.get("filename") or meta.get("destination") or meta.get("target")
        if not target and context_files:
            target = context_files[0]

        is_overwrite = False
        if target:
            res_path = self._resolve_project_path(str(target))
            if res_path and res_path.exists():
                is_overwrite = True

        if action == "move":
            risk = RiskLevel.HIGH
            reason = "Перемещение/переименование файла (исходный файл будет перемещён)."
        elif is_overwrite:
            risk = RiskLevel.HIGH
            reason = "Перезапись существующего файла через FileAgent."
        else:
            risk = RiskLevel.MEDIUM
            reason = f"Операция '{action}' через FileAgent."

        req_confirm = self._requires_confirmation_for_risk(risk)
        details = (
            f"Субагент: FileAgent\n"
            f"Операция: {action}\n"
            f"Целевой файл: {target or 'не указан'}\n"
            f"Статус: {'Перезапись существующего файла!' if is_overwrite else 'Создание/копирование'}\n"
            f"Уровень риска: [{risk.value.upper()}]"
        )

        return PermissionAssessment(
            action_type="subagent",
            name="file",
            risk_level=risk,
            requires_confirmation=req_confirm,
            allowed=True,
            is_destructive=is_overwrite or (action == "move"),
            reason=reason,
            details=details,
            params=meta
        )

    def _assess_coding_agent(
        self,
        task: str,
        meta: Dict[str, Any],
        context_files: List[str]
    ) -> PermissionAssessment:
        mode = str(meta.get("mode") or "").lower()
        edits = meta.get("edits") or []

        # Анализ кода без изменений — SAFE
        if mode == "analyze" or ("анализ" in task.lower() and not edits and "измени" not in task.lower()):
            return PermissionAssessment(
                action_type="subagent",
                name="coding",
                risk_level=RiskLevel.SAFE,
                requires_confirmation=False,
                allowed=True,
                reason="Статический анализ кода без изменения файлов проекта.",
                details=f"Субагент: CodingAgent\nРежим: Анализ кода\nЗадача: {task}",
                params=meta
            )

        # Применение правок кода — MEDIUM
        target_files = meta.get("target_files") or meta.get("files") or context_files
        target_str = ", ".join(target_files) if target_files else "указанные в задаче файлы"

        req_confirm = self._requires_confirmation_for_risk(RiskLevel.MEDIUM)
        details = (
            "Субагент: CodingAgent\n"
            "Режим: Модификация кода\n"
            f"Целевые файлы: {target_str}\n"
            f"Задача: {task}\n"
            "Уровень риска: [MEDIUM]"
        )

        return PermissionAssessment(
            action_type="subagent",
            name="coding",
            risk_level=RiskLevel.MEDIUM,
            requires_confirmation=req_confirm,
            allowed=True,
            reason="Модификация кода проекта через CodingAgent.",
            details=details,
            params=meta
        )

    # =========================================================================
    # Вспомогательные утилиты
    # =========================================================================

    def _requires_confirmation_for_risk(self, risk: RiskLevel) -> bool:
        if self.policy == SecurityPolicy.STRICT:
            return risk != RiskLevel.SAFE
        elif self.policy == SecurityPolicy.PERMISSIVE:
            return risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        elif self.policy == SecurityPolicy.NORMAL:
            return risk in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)
        elif self.policy == SecurityPolicy.READ_ONLY:
            return risk != RiskLevel.SAFE
        return False

    def _is_protected_file(self, filename: str) -> bool:
        norm = str(filename).replace("\\", "/").strip()
        for p in self.PROTECTED_FILE_PATTERNS:
            if p.search(norm):
                return True
        return False

    def _resolve_project_path(self, filename: str) -> Optional[Path]:
        try:
            p = Path(filename)
            if not p.is_absolute():
                p = self.project_path / p
            return p.resolve()
        except Exception:
            return None

    def _get_readonly_tools(self) -> Set[str]:
        return {
            "list_files", "find_file", "read_file", "search_files", "analyze_file",
            "validate_project", "git_status", "git_diff", "git_log",
            "recall_memory", "list_tasks", "list_reminders", "list_notes",
            "show_list", "check_due_reminders", "daily_briefing"
        }

    def _format_generic_tool_details(self, tool_name: str, params: Dict[str, Any]) -> str:
        lines = []
        if tool_name == "delete_task":
            task_id = params.get("task_id", "")
            lines.append("Действие: Удаление бытовой задачи")
            lines.append(f"Идентификатор / название задачи: {task_id}")
        elif tool_name == "delete_reminder":
            reminder_id = params.get("reminder_id", "")
            lines.append("Действие: Удаление напоминания")
            lines.append(f"Идентификатор / текст напоминания: {reminder_id}")
        elif tool_name == "delete_note":
            note_id = params.get("note_id", "")
            lines.append("Действие: Удаление заметки")
            lines.append(f"Идентификатор / заголовок заметки: {note_id}")
        elif tool_name == "delete_list_item":
            list_name = params.get("list_name", "")
            item_id = params.get("item_id", "")
            lines.append("Действие: Удаление пункта из списка")
            lines.append(f"Список: {list_name}, Пункт: {item_id}")
        elif tool_name == "forget_memory":
            target = params.get("target", "")
            lines.append("Действие: Удаление записи из долговременной памяти")
            lines.append(f"Идентификатор / текст: {target}")
        else:
            lines.append(f"Действие: {tool_name}")
            if params:
                lines.append(f"Параметры: {params}")
        return "\n".join(lines)


# =============================================================================
# Глобальный синглтон PermissionManager
# =============================================================================

_permission_manager_instance: Optional[PermissionManager] = None
_perm_lock = threading.RLock()


def get_permission_manager() -> PermissionManager:
    """Возвращает глобальный синглтон PermissionManager."""
    global _permission_manager_instance
    with _perm_lock:
        if _permission_manager_instance is None:
            _permission_manager_instance = PermissionManager()
        return _permission_manager_instance


def reset_permission_manager() -> None:
    """Сбрасывает синглтон PermissionManager (для изоляции тестов)."""
    global _permission_manager_instance
    with _perm_lock:
        _permission_manager_instance = None
