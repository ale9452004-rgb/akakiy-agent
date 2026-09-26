"""
Модуль специализированного Sub-Agent'а анализа и точечного изменения кода (CodingAgent).

Обеспечивает:
- приём задач по анализу и модификации кода через AgentContext;
- статический анализ указанных файлов и выявление проблем (синтаксис, структура);
- формирование структурированного плана изменений;
- безопасное выполнение точечных замен строго в разрешённых файлах (allowed_files);
- проведение targeted verification (проверка синтаксиса py_compile, запуск точечных тестов);
- возврат стандартизированного AgentResult с моделью Artifact (тип code) и метаданными верификации;
- строгую защиту от несанкционированного изменения файлов за пределами скоупа задачи.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from config import PROJECT_PATH
from tools.agents.base import SubAgent
from tools.agents.context import AgentContext
from tools.agents.result import AgentResult, Artifact, ArtifactType
from tools.files import (
    edit_file,
    read_file,
    resolve_safe_path,
    validate_python_file,
)
from tools.terminal import run_command


class CodingAgent(SubAgent):
    """
    Специализированный Sub-Agent анализа и безопасного точечного изменения кода.
    """

    name: str = "coding"
    description: str = "Специализированный sub-agent анализа и точечного изменения кода (CodingAgent)."
    capabilities: List[str] = ["coding", "code", "edit", "patch", "refactor", "verify"]

    def __init__(
        self,
        project_path: Optional[Union[str, Path]] = None,
        enabled: bool = True
    ):
        super().__init__(
            name=self.name,
            description=self.description,
            capabilities=self.capabilities,
            enabled=enabled
        )
        self.project_path = (
            Path(project_path).resolve()
            if project_path
            else PROJECT_PATH
        )

    # =========================================================================
    # Разбор задачи, целевых файлов и инструкций
    # =========================================================================

    def parse_task(
        self,
        task: str,
        metadata: Optional[Dict[str, Any]] = None,
        context_files: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Извлекает целевые файлы, белый список разрешённых файлов, правки и параметры верификации.
        """
        meta = metadata or {}
        task_str = task.strip()

        # 1. Сбор целевых файлов
        target_files: List[str] = []
        if meta.get("target_files"):
            target_files.extend(meta["target_files"])
        elif meta.get("files"):
            target_files.extend(meta["files"])
        elif context_files:
            target_files.extend(context_files)

        # Поиск упоминаний файлов в тексте задачи (например: "в файле tools/agent.py" или "file.py")
        file_matches = re.findall(
            r"\b([a-zA-Z0-9_\-\./\\]+\.(?:py|json|md|txt|html|css|js|ts|sh|ps1))\b",
            task_str,
            re.IGNORECASE
        )
        for fm in file_matches:
            if fm not in target_files:
                target_files.append(fm)

        # 2. Белый список разрешённых для изменения файлов (allowed_files)
        allowed_files: Set[str] = set()
        if meta.get("allowed_files"):
            allowed_files.update(self._normalize_path_str(f) for f in meta["allowed_files"])
        elif target_files:
            allowed_files.update(self._normalize_path_str(f) for f in target_files)

        # 3. Извлечение правок (edits)
        edits: List[Dict[str, str]] = []
        raw_edits = meta.get("edits") or meta.get("replacements")
        if raw_edits and isinstance(raw_edits, list):
            for e in raw_edits:
                if isinstance(e, dict):
                    old_t = e.get("old_text") if "old_text" in e else (e.get("old_str") if "old_str" in e else e.get("target"))
                    new_t = e.get("new_text") if "new_text" in e else (e.get("new_str") if "new_str" in e else e.get("replacement"))
                    if old_t is not None and new_t is not None:
                        e_file = e.get("file") or (target_files[0] if target_files else None)
                        if e_file:
                            edits.append({
                                "file": e_file,
                                "old_text": str(old_t),
                                "new_text": str(new_t)
                            })
        elif ("old_text" in meta or "old_str" in meta) and ("new_text" in meta or "new_str" in meta):
            old_t = meta.get("old_text") if "old_text" in meta else meta.get("old_str")
            new_t = meta.get("new_text") if "new_text" in meta else meta.get("new_str")
            e_file = meta.get("file") or (target_files[0] if target_files else None)
            if e_file and old_t is not None and new_t is not None:
                edits.append({
                    "file": e_file,
                    "old_text": str(old_t),
                    "new_text": str(new_t)
                })

        # Парсинг простых шаблонов замены из текста задачи:
        # 'замени "old" на "new" [в файле file.py]'
        if not edits and target_files:
            replace_pattern = re.compile(
                r"замени(?:ть)?\s+[\"'](.+?)[\"']\s+на\s+[\"'](.*?)[\"']",
                re.IGNORECASE
            )
            m = replace_pattern.search(task_str)
            if m:
                edits.append({
                    "file": target_files[0],
                    "old_text": m.group(1),
                    "new_text": m.group(2)
                })

        # 4. Режим работы (analyze / edit)
        mode = meta.get("mode")
        if not mode:
            if meta.get("dry_run") or meta.get("read_only"):
                mode = "analyze"
            elif edits:
                mode = "edit"
            elif any(w in task_str.lower() for w in ["анализ", "проверь", "проанализируй", "найди ошибки"]):
                mode = "analyze"
            else:
                mode = "edit"

        verify = meta.get("verify", True)
        test_command = meta.get("test_command")

        return {
            "task": task_str,
            "target_files": target_files,
            "allowed_files": allowed_files,
            "edits": edits,
            "mode": mode,
            "verify": verify,
            "test_command": test_command
        }

    def _normalize_path_str(self, p: Union[str, Path]) -> str:
        """Приводит путь к нормализованному строковому виду относительно project_path."""
        try:
            path_obj = Path(p)
            if path_obj.is_absolute():
                return str(path_obj.relative_to(self.project_path)).replace("\\", "/")
            return str(path_obj).replace("\\", "/")
        except Exception:
            return str(p).replace("\\", "/")

    # =========================================================================
    # Анализ файлов и планирование (Analyze Phase)
    # =========================================================================

    def analyze_files(
        self,
        target_files: List[str]
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Выполняет статический анализ указанных файлов.
        Возвращает (problems, plan_steps).
        """
        problems: List[Dict[str, Any]] = []
        plan_steps: List[str] = []

        if not target_files:
            plan_steps.append("Целевые файлы не указаны явно. Требуется уточнение контекста.")
            return problems, plan_steps

        for filename in target_files:
            file_path, err = resolve_safe_path(filename, base_path=self.project_path)
            if err:
                problems.append({
                    "file": filename,
                    "type": "path_error",
                    "error": err.get("error", "Небезопасный путь")
                })
                plan_steps.append(f"Проверить корректность пути к файлу '{filename}'.")
                continue

            if not file_path.exists():
                problems.append({
                    "file": filename,
                    "type": "file_not_found",
                    "error": f"Файл не найден: {filename}"
                })
                plan_steps.append(f"Создать или восстановить файл '{filename}'.")
                continue

            # Читаем файл
            read_res = read_file(filename, base_path=self.project_path)
            if not read_res.get("success"):
                problems.append({
                    "file": filename,
                    "type": "read_error",
                    "error": read_res.get("error", "Ошибка чтения файла")
                })
                plan_steps.append(f"Устранить проблемы доступа к файлу '{filename}'.")
                continue

            # Синтаксическая проверка для Python
            if file_path.suffix.lower() == ".py":
                val_res = validate_python_file(file_path)
                if not val_res.get("success"):
                    problems.append({
                        "file": filename,
                        "type": "syntax_error",
                        "error": val_res.get("error", "Синтаксическая ошибка в коде")
                    })
                    plan_steps.append(f"Исправить синтаксическую ошибку в '{filename}'.")
                else:
                    plan_steps.append(f"Синтаксис '{filename}' корректен. Подготовить точечные изменения.")
            else:
                plan_steps.append(f"Файл '{filename}' проверен и готов к точечным правкам.")

        return problems, plan_steps

    # =========================================================================
    # Безопасное применение правок (Apply Edits Phase)
    # =========================================================================

    def apply_edits(
        self,
        edits: List[Dict[str, str]],
        allowed_files: Set[str]
    ) -> Tuple[bool, List[str], List[Dict[str, Any]], Optional[str]]:
        """
        Применяет список точечных правок через edit_file строго в рамках allowed_files.
        Возвращает (success, modified_files, edit_results, error_message).
        """
        modified_files: List[str] = []
        edit_results: List[Dict[str, Any]] = []

        for e in edits:
            fname = e["file"]
            norm_fname = self._normalize_path_str(fname)

            # Проверка белого списка файлов
            if allowed_files and norm_fname not in allowed_files:
                err_msg = (
                    f"Безопасность: файл '{fname}' не входит в список разрешённых для изменения файлов. "
                    f"Разрешены: {list(allowed_files)}."
                )
                return False, modified_files, edit_results, err_msg

            old_text = e["old_text"]
            new_text = e["new_text"]

            res = edit_file(
                filename=fname,
                old_text=old_text,
                new_text=new_text,
                base_path=self.project_path
            )

            edit_results.append({
                "file": fname,
                "success": res.get("success", False),
                "details": res
            })

            if not res.get("success"):
                err_detail = res.get("error") or res.get("message") or "Ошибка редактирования"
                return False, modified_files, edit_results, f"Ошибка правки в {fname}: {err_detail}"

            if fname not in modified_files:
                modified_files.append(fname)

        return True, modified_files, edit_results, None

    # =========================================================================
    # Targeted Verification Phase
    # =========================================================================

    def verify_changes(
        self,
        modified_files: List[str],
        test_command: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Выполняет точечную проверку синтаксиса изменённых файлов и опциональный запуск тестов.
        """
        verification_report: Dict[str, Any] = {
            "syntax_ok": True,
            "tests_ok": True,
            "syntax_errors": [],
            "test_output": None
        }

        # 1. Проверка синтаксиса изменённых файлов
        for mf in modified_files:
            fpath, err = resolve_safe_path(mf)
            if not err and fpath.exists() and fpath.suffix.lower() == ".py":
                v_res = validate_python_file(fpath)
                if not v_res.get("success"):
                    verification_report["syntax_ok"] = False
                    verification_report["syntax_errors"].append({
                        "file": mf,
                        "error": v_res.get("error")
                    })

        if not verification_report["syntax_ok"]:
            return False, verification_report

        # 2. Опциональный точечный запуск тестов
        if test_command:
            cmd_res = run_command(test_command)
            verification_report["tests_ok"] = cmd_res.get("success", False)
            verification_report["test_output"] = {
                "command": test_command,
                "return_code": cmd_res.get("return_code"),
                "stdout": cmd_res.get("stdout", "")[:500],
                "stderr": cmd_res.get("stderr", "")[:500]
            }
            if not cmd_res.get("success"):
                return False, verification_report

        return True, verification_report

    # =========================================================================
    # Основной контракт выполнения SubAgent.run()
    # =========================================================================

    def run(self, context: AgentContext) -> AgentResult:
        """
        Основной метод выполнения задачи анализа и изменения кода.
        """
        # 1. Валидация входного контекста
        if not self.validate_context(context):
            return AgentResult.fail(
                error="Некорректный контекст: ожидается экземпляр AgentContext."
            )

        if not self.enabled:
            return AgentResult.fail(
                error=f"Sub-agent '{self.name}' отключен."
            )

        task_str = str(context.task or "").strip()
        if not task_str and not context.get("edits") and not context.files:
            return AgentResult.fail(
                error="Не указана задача или файлы для CodingAgent.",
                message="Необходимо указать задачу по коду или целевые файлы."
            )

        try:
            # 2. Разбор параметров задачи
            parsed = self.parse_task(
                task=task_str,
                metadata=context.metadata,
                context_files=context.files
            )

            target_files = parsed["target_files"]
            allowed_files = parsed["allowed_files"]
            edits = parsed["edits"]
            mode = parsed["mode"]
            should_verify = parsed["verify"]
            test_command = parsed["test_command"]

            # 3. Фаза анализа файлов
            problems, plan_steps = self.analyze_files(target_files)

            # Если режим "только анализ" (analyze / dry_run) или нет правок
            if mode == "analyze" or not edits:
                msg = (
                    f"Анализ кода завершён для {len(target_files)} файлов. "
                    f"Обнаружено проблем: {len(problems)}."
                )
                res_data = {
                    "task": task_str,
                    "mode": "analyze",
                    "target_files": target_files,
                    "problems": problems,
                    "plan": plan_steps,
                    "modified_files": []
                }
                return AgentResult.ok(
                    message=msg,
                    data=res_data,
                    created_files=[]
                )

            # 4. Фаза применения изменений (только в allowed_files)
            success, modified_files, edit_results, err_msg = self.apply_edits(
                edits=edits,
                allowed_files=allowed_files
            )

            if not success:
                return AgentResult.fail(
                    error=err_msg or "Ошибка применения правок.",
                    message=f"Не удалось применить изменения: {err_msg}",
                    data={
                        "task": task_str,
                        "problems": problems,
                        "plan": plan_steps,
                        "edit_results": edit_results,
                        "modified_files": modified_files
                    }
                )

            # 5. Targeted verification
            verification_report: Dict[str, Any] = {}
            if should_verify and modified_files:
                v_ok, verification_report = self.verify_changes(
                    modified_files=modified_files,
                    test_command=test_command
                )
                if not v_ok:
                    syntax_errs = verification_report.get("syntax_errors", [])
                    test_out = verification_report.get("test_output", {})
                    err_info = "Ошибка синтаксиса" if syntax_errs else "Сбой проверочных тестов"
                    return AgentResult.fail(
                        error=f"Верификация после правок не пройдена: {err_info}.",
                        message=f"Правки внесены, но верификация не пройдена: {err_info}.",
                        created_files=modified_files,
                        data={
                            "task": task_str,
                            "problems": problems,
                            "modified_files": modified_files,
                            "verification": verification_report
                        }
                    )

            # 6. Формирование артефактов и итогового результата
            artifacts: List[Artifact] = []
            for mf in modified_files:
                fpath, _ = resolve_safe_path(mf, base_path=self.project_path)
                if fpath and fpath.exists():
                    artifacts.append(
                        Artifact.from_code(
                            path=str(fpath),
                            name=fpath.name,
                            language="python" if fpath.suffix.lower() == ".py" else fpath.suffix.lstrip("."),
                            task=task_str
                        )
                    )

            msg = (
                f"Успешно применены изменения в {len(modified_files)} файлах. "
                f"Верификация пройдена."
            )

            res_data = {
                "task": task_str,
                "mode": "edit",
                "problems": problems,
                "plan": plan_steps,
                "modified_files": modified_files,
                "edit_results": edit_results,
                "verification": verification_report
            }

            return AgentResult.ok(
                message=msg,
                created_files=modified_files,
                artifacts=artifacts,
                data=res_data
            )

        except Exception as ex:
            return AgentResult.fail(
                error=f"Внутренняя ошибка CodingAgent: {ex}",
                message=f"Произошла ошибка при выполнении задачи по коду: {ex}"
            )
