import re
import json
from pathlib import Path
from tools.dispatcher import dispatch
from tools.registry import get_tool

READONLY_TOOLS = {
    "list_files",
    "find_file",
    "read_file",
    "search_files",
    "analyze_file",
    "git_status",
    "git_diff",
    "git_log",
}

FORBIDDEN_MUTATIONS = {
    "git_add",
    "git_commit",
    "git_push",
}


class TeamworkResearcher:
    """
    Роль Researcher в Teamwork Preview.
    Выполняет исключительно read-only сбор информации по проекту.
    Никогда не изменяет файлы и не запрашивает подтверждений у пользователя.
    """

    def __init__(self, agent):
        self.agent = agent

    def research(self, user_request):
        """
        Выполняет предварительное исследование кодовой базы под задачу пользователя.
        """
        findings = []
        files_examined = []

        # 1. Поиск упоминаний конкретных файлов в запросе и контексте памяти
        search_scope = user_request
        if hasattr(self.agent, "context_manager") and self.agent.context_manager:
            relevant_mems = self.agent.context_manager.retrieve_relevant_memories(user_request, limit=2)
            for rm in relevant_mems:
                search_scope += " " + rm.get("text", "")

        file_patterns = [
            r"([a-zA-Z0-9_\-\./\\]+\.py)",
            r"([a-zA-Z0-9_\-\./\\]+\.json)",
            r"([a-zA-Z0-9_\-\./\\]+\.md)",
        ]
        mentioned_files = []
        for p in file_patterns:
            matches = re.findall(p, search_scope)
            for m in matches:
                clean_path = m.strip().replace("\\", "/")
                if clean_path not in mentioned_files:
                    mentioned_files.append(clean_path)

        # 2. Read-only изучение упомянутых файлов
        for target_file in mentioned_files:
            read_res = dispatch("read_file", filename=target_file)
            if read_res.get("success"):
                files_examined.append(target_file)
                content = read_res.get("result", {}).get("content", "")
                findings.append(f"Изучен файл {target_file} ({len(content.splitlines())} строк).")
            else:
                findings.append(f"Файл {target_file} не найден на диске или не прочитан.")

        # 3. Если файлы не упомянуты напрямую, но есть запрос на анализ структуры/модулей
        req_lower = user_request.lower()
        if not files_examined and any(w in req_lower for w in ["структур", "модул", "файлы", "инструмент", "маршрутизац", "архитектур"]):
            list_res = dispatch("list_files")
            if list_res.get("success"):
                all_files = list_res.get("result", {}).get("files", [])
                py_files = [f for f in all_files if f.endswith(".py")]
                findings.append(f"В проекте обнаружено {len(py_files)} Python-файлов: {', '.join(py_files[:10])}")

        # 4. Проверка git-статуса (read-only)
        git_res = dispatch("git_status")
        if git_res.get("success"):
            git_out = git_res.get("result", {}).get("stdout", "").strip()
            if git_out:
                changed_items = [l.strip() for l in git_out.splitlines() if l.strip()]
                findings.append(f"Некоммиченных изменений в Git: {len(changed_items)}.")

        summary = "\n".join(findings) if findings else "Предварительное исследование завершено. Специфических дефектов до планирования не зафиксировано."
        return {
            "success": True,
            "findings": findings,
            "files_examined": files_examined,
            "summary": summary
        }


class TeamworkPlanner:
    """
    Роль Planner в Teamwork Preview.
    Использует существующий tools/planner.py.
    Не создаёт второй системы планирования.
    """

    def __init__(self, agent):
        self.agent = agent

    def plan(self, user_request, research_context=None):
        """
        Делегирует генерацию плана существующему объекту Planner.
        """
        return self.agent.create_plan(user_request, research_context=research_context)


class TeamworkImplementer:
    """
    Роль Implementer в Teamwork Preview.
    Использует существующий PlanExecutor -> Dispatcher -> Tools.
    Все мутации строго требуют подтверждения пользователя.
    """

    def __init__(self, agent):
        self.agent = agent

    def implement(self, plan):
        """
        Выполняет план через существующий PlanExecutor.
        """
        return self.agent.execute_plan(plan)


class TeamworkVerifier:
    """
    Роль Verifier в Teamwork Preview.
    Использует существующий validate_project и механизм self-healing Акакия.
    """

    def __init__(self, agent):
        self.agent = agent

    def verify(self, execution_result=None):
        """
        Проверяет состояние проекта после выполнения шагов плана.
        Если шаг валидации уже выполнялся в рамках плана, используем его результат.
        """
        if execution_result and isinstance(execution_result, dict):
            step_results = execution_result.get("results", [])
            val_steps = [s for s in step_results if s.get("action") == "validate"]
            if val_steps:
                last_val = val_steps[-1]
                return {
                    "success": last_val.get("success", False),
                    "validation_result": last_val.get("result"),
                    "self_healing": last_val.get("self_healing")
                }

        val_res = dispatch("validate_project")
        val_success = val_res.get("success", False)
        tool_res = val_res.get("result", {}) if isinstance(val_res, dict) else {}
        errors = []
        if isinstance(tool_res, dict) and "errors" in tool_res:
            errors = tool_res.get("errors", [])
        elif isinstance(val_res, dict) and "errors" in val_res:
            errors = val_res.get("errors", [])

        heal_result = None
        if (not val_success or errors) and hasattr(self.agent, "run_single_correction"):
            heal_result = self.agent.run_single_correction(errors or [val_res])
            if heal_result.get("success"):
                val_success = True
                val_res = heal_result.get("validation_result", val_res)

        return {
            "success": val_success,
            "validation_result": val_res,
            "self_healing": heal_result
        }


class TeamworkCoordinator:
    """
    Единый координатор Teamwork Preview.
    Координирует работу ролей:
    Researcher -> Planner -> Implementer -> Verifier -> Result
    вокруг существующей инфраструктуры Акакия.
    """

    def __init__(self, agent):
        self.agent = agent
        self.researcher = TeamworkResearcher(agent)
        self.planner = TeamworkPlanner(agent)
        self.implementer = TeamworkImplementer(agent)
        self.verifier = TeamworkVerifier(agent)
        self.context = {}
        self.reset()

    def reset(self):
        """
        Гарантирует изоляцию контекста: сбрасывает состояние предыдущей задачи.
        """
        self.context = {
            "user_request": None,
            "research_results": None,
            "plan": None,
            "execution_results": None,
            "validation_results": None,
        }

    def is_complex_task(self, user_input):
        """
        Разделяет простые запросы (Native Tool Calling) и сложные задачи (Teamwork).
        """
        normalized_lower = user_input.strip().lower()

        # Исключаем явные простые CLI/чат запросы
        simple_prefixes = (
            "прочитай ", "покажи ", "найди файл ", "найди в проекте файл ",
            "найди функцию ", "что делает ", "что такое ", "привет", "статус"
        )
        # Если это простой атомарный запрос без указания "и исправь" / "и проверь" / "и предложи"
        has_compound_action = any(
            re.search(p, normalized_lower)
            for p in [
                r"\bи\s+исправь\b",
                r"\bи\s+почини\b",
                r"\bи\s+проверь\b",
                r"\bи\s+протестируй\b",
                r"\bи\s+предложи\b",
                r"\bисправь\s+проблему\b",
                r"\bисправь\s+найденные\s+проблемы\b",
                r"\bвнеси\s+необходимые\s+изменения\b",
            ]
        )

        is_propose_only = any(
            phrase in normalized_lower
            for phrase in [
                "ничего не меняй",
                "без изменений",
                "только исследуй",
                "предложи, что нужно изменить",
                "предложи что нужно изменить",
                "предложи что изменить",
                "предложи, что изменить",
            ]
        )

        research_patterns = {
            "проанализируй структуру проекта",
            "анализ структуры проекта",
            "исследуй структуру проекта",
            "изучи структуру проекта",
            "разберись, как устроена система инструментов акакия и какие модули отвечают за их выполнение",
            "разберись как устроена система инструментов акакия и какие модули отвечают за их выполнение",
        }

        # Если явно указан префикс плана или teamwork
        is_explicit_teamwork = normalized_lower.startswith("teamwork:") or normalized_lower.startswith("команда:")

        if is_explicit_teamwork:
            return True

        if has_compound_action or is_propose_only or normalized_lower.rstrip(".,!?;:") in research_patterns:
            return True

        return False

    def run(self, user_request):
        """
        Запускает полный цикл Teamwork Preview:
        Research -> Planning -> Implementation -> Verification -> Result
        """
        # Сброс контекста для гарантии изоляции между задачами
        self.reset()
        self.context["user_request"] = user_request

        # Проверка безопасности: блокировка опасных мутаций Git
        req_lower = user_request.lower()
        if any(f in req_lower for f in FORBIDDEN_MUTATIONS) or "git add" in req_lower or "git commit" in req_lower or "git push" in req_lower:
            err_msg = "Операции 'git add', 'git commit', 'git push' запрещены регламентом безопасности Teamwork."
            return {
                "success": False,
                "message": err_msg,
                "summary": f"## Ошибка безопасности\n{err_msg}"
            }

        # -------------------------------------------------------------
        # 1. RESEARCH
        # -------------------------------------------------------------
        research_res = self.researcher.research(user_request)
        self.context["research_results"] = research_res
        research_context = research_res.get("summary", "")

        # -------------------------------------------------------------
        # 2. PLANNING
        # -------------------------------------------------------------
        clean_request = user_request
        for prefix in ["teamwork:", "команда:"]:
            if clean_request.lower().startswith(prefix):
                clean_request = clean_request[len(prefix):].strip()

        plan_res = self.planner.plan(clean_request, research_context=research_context)
        self.context["plan"] = plan_res

        if not plan_res.get("success"):
            return {
                "success": False,
                "message": plan_res.get("message", "Не удалось составить план."),
                "research": research_res,
                "plan": plan_res,
                "summary": f"## Исследование\n{research_context}\n\n## План\nОшибка планирования: {plan_res.get('message')}\n\n## Результат\nЗадача не выполнена."
            }

        plan_data = plan_res.get("plan", {})

        # -------------------------------------------------------------
        # 3. IMPLEMENTATION
        # -------------------------------------------------------------
        exec_res = self.implementer.implement(plan_data)
        self.context["execution_results"] = exec_res

        # -------------------------------------------------------------
        # 4. VERIFICATION
        # -------------------------------------------------------------
        # Если план завершился успешно или были выполнены мутации, запускаем Verifier
        verify_res = self.verifier.verify(exec_res)
        self.context["validation_results"] = verify_res

        # Если валидация выявила ошибку, а self-healing не исправил её
        if not verify_res.get("success") and exec_res.get("success"):
            exec_res["success"] = False
            exec_res["message"] = "Проверка синтаксиса проекта после выполнения выявила ошибки."

        # -------------------------------------------------------------
        # 5. RESULT (Правдивая агрегированная сводка)
        # -------------------------------------------------------------
        summary = self.agent.format_task_summary(
            plan_data,
            exec_res,
            research_info=research_context
        )
        exec_res["summary"] = summary

        # Очищаем внутренний контекст после формирования отчёта (изоляция)
        self.reset()

        return exec_res
