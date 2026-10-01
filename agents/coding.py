"""
Доменный агент разработки и модификации кода (CodingAgent) multi-agent архитектуры Акакия.

Отвечает за:
- прием пользовательских задач по анализу и изменению кода;
- валидацию и определение параметров задачи (целевые файлы, правки, режим проверки);
- делегирование исполнения специализированному worker (tools/agents/coding.py);
- передачу реального прогресса выполнения через AgentContext (report_progress);
- формирование стандартизированного результата AgentResult с артефактами (ArtifactType.CODE).

Архитектурный принцип:
Domain CodingAgent является высокоуровневой сущностью (Domain Agent), наследующей BaseAgent.
Он не создает второй инструмент анализа/редактирования кода и не дублирует CommandRouter.match_coding,
а использует существующие механизмы worker-слоя проекта.
"""

import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union

from agents.base import BaseAgent
from config import PROJECT_PATH
from tools.agents.context import AgentContext
from tools.agents.coding import CodingAgent as SubAgentCodingWorker
from tools.agents.result import AgentResult

logger = logging.getLogger(__name__)


class CodingAgent(BaseAgent):
    """
    Высокоуровневый доменный агент разработки и модификации кода Акакия.
    """

    name: str = "coding"
    display_name: str = "Разработка"
    description: str = "Анализ, модификация и безопасная точечная верификация исходного кода проекта."
    capabilities: List[str] = [
        "coding",
        "code",
        "edit",
        "patch",
        "refactor",
        "verify",
    ]
    tools: List[str] = [
        "read_file",
        "edit_file",
        "write_file",
        "analyze_file",
        "validate_python_file",
        "run_command",
        "git_status",
        "git_diff",
    ]

    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        tools: Optional[List[str]] = None,
        enabled: bool = True,
        worker: Optional[SubAgentCodingWorker] = None,
        project_path: Optional[Union[str, Path]] = None,
        display_name: Optional[str] = None,
        **kwargs: Any
    ):
        super().__init__(
            name=name if name is not None else self.name,
            description=description if description is not None else self.description,
            capabilities=capabilities,
            tools=tools,
            enabled=enabled,
            display_name=display_name if display_name is not None else self.display_name,
            **kwargs
        )
        self.worker = worker
        self.project_path = (
            Path(project_path).resolve()
            if project_path
            else PROJECT_PATH
        )

    def _get_worker(self, context: Optional[AgentContext] = None) -> SubAgentCodingWorker:
        """Возвращает внедрённый или стандартный экземпляр SubAgent worker."""
        if self.worker is not None:
            return self.worker

        # 1. Попытка получить custom_worker из context (parent_agent.agent_registry)
        if context is not None:
            parent = getattr(context, "parent_agent", None)
            if parent is not None and hasattr(parent, "agent_registry"):
                custom_worker = parent.agent_registry.get("coding")
                if custom_worker is not None and isinstance(custom_worker, SubAgentCodingWorker):
                    return custom_worker

        # 2. Попытка получить из глобального subagent registry
        try:
            from tools.agents.registry import get_agent_registry
            custom_worker = get_agent_registry().get("coding")
            if custom_worker is not None and isinstance(custom_worker, SubAgentCodingWorker):
                return custom_worker
        except Exception:
            pass

        # 3. Дефолтный экземпляр воркера
        return SubAgentCodingWorker(project_path=self.project_path)

    def can_handle(self, task: str) -> float:
        """
        Оценка релевантности запроса для доменного агента разработки (CodingAgent).
        Использует существующий CommandRouter как основной сигнал детерминированной маршрутизации.
        Не создаёт второй независимый механизм определения coding intent.
        """
        if not task or not isinstance(task, str) or not task.strip():
            return 0.0

        clean_task = task.strip()

        # Исключаем явные команды бытового домена
        norm = clean_task.lower()
        if re.search(r"^(?:создай|добавь|удали|выполни|отметь|закрой)\s+(?:задач[а-я]*|напоминани[а-я]*|заметк[а-я]*|список\b)", norm):
            return 0.0
        if re.search(r"^(?:напомни|будильник|список\s+(?:покупок|дел|продуктов))", norm):
            return 0.0

        # Основной сигнал: существующий CommandRouter
        try:
            from tools.router import get_router
            router = get_router()
            route = router.route(clean_task)
            r_type = route.get("type")
            if r_type == "coding":
                return 1.0
            if r_type == "subagent" and route.get("agent") in ("coding", "code"):
                return 1.0
        except Exception as exc:
            logger.debug("Ошибка вызова CommandRouter в CodingAgent.can_handle: %s", exc)

        return 0.0

    def _is_foreign_domain_task(self, task: str) -> bool:
        """
        Проверяет, относится ли запрос явно к другому домену (бытовому или обычному диалогу),
        не имея контекста работы с кодом.
        """
        norm = task.strip().lower()

        # Если есть явные маркеры кода или префикс кодинга, это не чужой домен
        if re.search(r"\b(?:кодинг|код\b|исходн[а-я]+\s+код|рефакторинг|синтаксис|патч\b|правк[а-я]*)\b", norm):
            return False

        # Бытовые маркеры
        if re.search(r"^(?:создай|добавь|удали|выполни|отметь)\s+(?:задач[а-я]*|напоминани[а-я]*|заметк[а-я]*|список\b)", norm):
            return True
        if re.search(r"^(?:напомни|будильник|список\s+(?:покупок|дел|продуктов))", norm):
            return True

        return False

    def execute(
        self,
        task: str,
        context: Optional[Union[Dict[str, Any], AgentContext]] = None,
        **kwargs: Any
    ) -> AgentResult:
        """
        Основная точка входа для исполнения задачи по коду.

        :param task: Текст задачи по коду или имя файла.
        :param context: Опциональный контекст сессии или экземпляр AgentContext.
        :param kwargs: Дополнительные параметры (target_files, edits, allowed_files, mode, verify, test_command).
        :return: Канонический AgentResult.
        """
        task_str = str(task).strip() if task is not None else ""

        # 1. Проверка на отключённого агента
        if not self.enabled:
            return AgentResult.fail(
                error=f"Доменный агент '{self.name}' отключен.",
                message=f"Агент '{self.name}' в данный момент неактивен.",
                data={"agent": self.name}
            )

        # 2. Проверка чужого домена
        if task_str and self._is_foreign_domain_task(task_str):
            return AgentResult.fail(
                error=f"Запрос '{task_str}' не относится к разработке или коду.",
                message="Данная задача относится к другому домену и не поддерживается CodingAgent.",
                data={"agent": self.name, "task": task_str}
            )

        # 3. Подготовка контекста и метаданных
        merged_meta: Dict[str, Any] = {}
        files: List[str] = []
        progress_cb = None

        if isinstance(context, AgentContext):
            if context.metadata:
                merged_meta.update(context.metadata)
            files.extend(context.files or [])
            progress_cb = context.progress_callback
        elif isinstance(context, dict):
            merged_meta.update(context)
            if "files" in context and isinstance(context["files"], list):
                files.extend([str(f) for f in context["files"]])
            progress_cb = context.get("progress_callback")
        elif context is not None:
            if hasattr(context, "metadata") and isinstance(context.metadata, dict):
                merged_meta.update(context.metadata)
            if hasattr(context, "files") and isinstance(context.files, list):
                files.extend([str(f) for f in context.files])
            progress_cb = getattr(context, "progress_callback", None)

        merged_meta.update(kwargs)
        if "files" in kwargs and isinstance(kwargs["files"], list):
            files.extend([str(f) for f in kwargs["files"]])

        # Проверка пустого запроса при отсутствии правок и файлов
        has_files = bool(files or merged_meta.get("target_files") or merged_meta.get("files"))
        has_edits = bool(merged_meta.get("edits") or merged_meta.get("replacements"))
        if not task_str and not has_files and not has_edits:
            return AgentResult.fail(
                error="Не указана задача или целевые файлы для CodingAgent.",
                message="Запрос по коду не может быть пустым.",
                data={"agent": self.name}
            )

        # Извлечение чистого prompt из CommandRouter при явных префиксах (например: "кодинг: ...")
        actual_task = task_str
        try:
            from tools.router import get_router
            route = get_router().route(task_str)
            if route.get("type") == "coding" and route.get("prompt"):
                actual_task = route["prompt"]
        except Exception:
            pass

        # 4. Формирование рабочего контекста для worker
        agent_ctx = AgentContext(
            task=actual_task,
            metadata=merged_meta,
            files=files,
            progress_callback=progress_cb
        )
        if isinstance(context, dict) and "parent_agent" in context:
            agent_ctx.parent_agent = context["parent_agent"]
        elif hasattr(context, "parent_agent"):
            agent_ctx.parent_agent = getattr(context, "parent_agent")

        worker = self._get_worker(context=agent_ctx)

        # 5. Подключение наблюдателя за реальными этапами выполнения
        # Этапы прогресса вызываются строго по мере их фактического наступления воркером:
        #   - "Анализирую код…" — всегда перед началом анализа файлов;
        #   - "Применяю изменения…" — только если есть правки и вызван apply_edits;
        #   - "Проверяю результат…" — только если включена верификация и вызван verify_changes.
        orig_apply_edits = worker.apply_edits
        orig_verify_changes = worker.verify_changes

        def _tracked_apply_edits(*args: Any, **kw: Any) -> Any:
            if context and hasattr(context, "report_progress") and callable(context.report_progress):
                try:
                    context.report_progress("Применяю изменения…")
                except Exception:
                    pass
            elif progress_cb and callable(progress_cb):
                try:
                    progress_cb("Применяю изменения…")
                except Exception:
                    pass
            return orig_apply_edits(*args, **kw)

        def _tracked_verify_changes(*args: Any, **kw: Any) -> Any:
            if context and hasattr(context, "report_progress") and callable(context.report_progress):
                try:
                    context.report_progress("Проверяю результат…")
                except Exception:
                    pass
            elif progress_cb and callable(progress_cb):
                try:
                    progress_cb("Проверяю результат…")
                except Exception:
                    pass
            return orig_verify_changes(*args, **kw)

        # Этап 1: Старт анализа
        if context and hasattr(context, "report_progress") and callable(context.report_progress):
            try:
                context.report_progress("Анализирую код…")
            except Exception:
                pass
        elif progress_cb and callable(progress_cb):
            try:
                progress_cb("Анализирую код…")
            except Exception:
                pass

        try:
            worker.apply_edits = _tracked_apply_edits
            worker.verify_changes = _tracked_verify_changes
            worker_result = worker.run(agent_ctx)
        except Exception as ex:
            logger.error(f"Исключение при вызове CodingWorker: {ex}", exc_info=True)
            return AgentResult.fail(
                error=f"Ошибка слоя CodingWorker ({type(ex).__name__}): {ex}",
                message=f"Сбой при выполнении задачи по коду: {ex}",
                data={"agent": self.name, "task": task_str}
            )
        finally:
            worker.apply_edits = orig_apply_edits
            worker.verify_changes = orig_verify_changes

        # 6. Возврат результата
        if isinstance(worker_result, AgentResult):
            if isinstance(worker_result.data, dict):
                worker_result.data.setdefault("domain_agent", self.name)
                worker_result.data.setdefault("display_name", self.display_name)
            return worker_result

        return AgentResult.ok(
            message="Задача по коду выполнена.",
            data={"result": worker_result, "domain_agent": self.name, "display_name": self.display_name}
        )
