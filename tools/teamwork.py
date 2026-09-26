import json
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from tools.agents.base import SubAgent
from tools.agents.context import AgentContext
from tools.agents.registry import AgentRegistry, get_agent_registry
from tools.agents.result import AgentResult, Artifact
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

    def run_pipeline(
        self,
        steps: List[Union["PipelineStep", Tuple[str, str], Dict[str, Any]]],
        initial_context: Optional[AgentContext] = None,
        stop_on_error: bool = True,
        **kwargs
    ) -> AgentResult:
        """
        Запускает последовательный конвейер Sub-Agent'ов через внутренний TeamworkPipeline.
        """
        reg = getattr(self.agent, "agent_registry", None) or get_agent_registry()
        return run_agent_pipeline(
            steps=steps,
            initial_context=initial_context,
            registry=reg,
            stop_on_error=stop_on_error,
            **kwargs
        )


# =============================================================================
# Agent Teamwork Foundation v1: Последовательный Sub-Agent Pipeline
# =============================================================================

class PipelineStep:
    """
    Описание одного шага в конвейере взаимодействия субагентов.
    """

    def __init__(
        self,
        agent: Union[str, SubAgent],
        task: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        files: Optional[List[str]] = None,
        name: Optional[str] = None,
        input_transform: Optional[Callable[[AgentContext, Optional[AgentResult]], AgentContext]] = None,
    ):
        if hasattr(agent, "name"):
            self.agent_name = str(agent.name).strip()
            self.agent_instance = agent
        else:
            self.agent_name = str(agent).strip()
            self.agent_instance = None

        self.task = str(task)
        self.metadata = dict(metadata or {})
        self.files = list(files or [])
        self.name = str(name) if name else self.agent_name
        self.step_id = str(self.metadata.get("step_id") or name or self.agent_name)
        self.input_transform = input_transform

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "agent": self.agent_name,
            "task": self.task,
            "metadata": dict(self.metadata),
            "files": list(self.files)
        }


def normalize_step(step: Union[PipelineStep, Tuple[str, str], Dict[str, Any], Any]) -> PipelineStep:
    """
    Приводит произвольный шаг (объект, кортеж, словарь, PlanStep) к PipelineStep.
    """
    if isinstance(step, PipelineStep):
        return step
    if hasattr(step, "to_pipeline_step"):
        return step.to_pipeline_step()
    if isinstance(step, (list, tuple)):
        agent = step[0]
        task = step[1] if len(step) > 1 else ""
        meta = step[2] if len(step) > 2 and isinstance(step[2], dict) else {}
        return PipelineStep(agent=agent, task=task, metadata=meta)
    if isinstance(step, dict):
        agent = step.get("subagent") or step.get("agent") or step.get("agent_name") or step.get("name")
        if not agent:
            action = step.get("action")
            known_agents = {"research", "document", "coding", "file", "presentation", "image", "echo"}
            if action and str(action).lower() in known_agents:
                agent = str(action).lower()
            elif action in ("edit", "patch", "code"):
                agent = "coding"
            elif action in ("read", "create", "write", "copy", "move", "files", "search"):
                agent = "file"
        if not agent:
            raise ValueError(f"В словаре шага не указан агент: {step}")
        task = step.get("task") or step.get("instruction") or step.get("details") or step.get("description") or ""
        meta = step.get("metadata") or {
            k: v for k, v in step.items()
            if k not in ("agent", "agent_name", "subagent", "task", "instruction", "files", "name", "input_transform", "details", "description")
        }
        files = step.get("files")
        if step.get("target"):
            files = list(files or [])
            if step["target"] not in files:
                files.append(step["target"])
        name = step.get("name") or (f"step_{step['id']}" if "id" in step else None)
        transform = step.get("input_transform")
        return PipelineStep(
            agent=agent,
            task=task,
            metadata=meta,
            files=files,
            name=name,
            input_transform=transform
        )
    raise ValueError(f"Некорректный формат шага pipeline: {step}")


class TeamworkPipeline:
    """
    Конвейер последовательного взаимодействия нескольких Sub-Agent'ов.

    Обеспечивает:
    - передачу результатов и контекста от шага к шагу через AgentContext.previous_results;
    - аккумуляцию артефактов и созданных файлов каждого шага;
    - обработку ошибок и досрочную остановку при сбое любого шага;
    - формирование единого итогового AgentResult со структурированной историей.
    """

    def __init__(
        self,
        steps: Optional[Union[List[Union[PipelineStep, Tuple[str, str], Dict[str, Any]]], Any]] = None,
        registry: Optional[AgentRegistry] = None,
        stop_on_error: bool = True
    ):
        self.registry = registry or get_agent_registry()
        self.stop_on_error = stop_on_error
        self.steps: List[PipelineStep] = []
        if steps:
            if hasattr(steps, "to_pipeline_steps"):
                steps = steps.to_pipeline_steps(registry=self.registry)
            for s in steps:
                self.add_step(s)

    def add_step(
        self,
        step: Union[PipelineStep, Tuple[str, str], Dict[str, Any]]
    ) -> "TeamworkPipeline":
        """Добавляет шаг в конвейер (fluent API)."""
        self.steps.append(normalize_step(step))
        return self

    def run(
        self,
        initial_task: str = "",
        initial_context: Optional[AgentContext] = None,
        **kwargs
    ) -> AgentResult:
        """
        Исполняет конвейер шагов субагентов.
        """
        if not self.steps:
            return AgentResult.fail(
                error="Pipeline не содержит шагов для выполнения.",
                message="Пустой pipeline."
            )

        root_context = initial_context or AgentContext(
            task=initial_task,
            metadata=kwargs
        )

        accumulated_artifacts: List[Artifact] = []
        accumulated_files: List[str] = list(root_context.files)
        step_history: List[Dict[str, Any]] = []
        last_result: Optional[AgentResult] = None
        current_context = root_context

        for idx, step in enumerate(self.steps, start=1):
            # 1. Поиск агента в реестре
            agent = step.agent_instance or self.registry.get(step.agent_name)
            if agent is None:
                err_msg = f"Субагент '{step.agent_name}' не найден в реестре (шаг {idx})."
                return AgentResult.fail(
                    error=err_msg,
                    message=f"Pipeline прерван: {err_msg}",
                    created_files=accumulated_files,
                    artifacts=accumulated_artifacts,
                    data={
                        "total_steps": len(self.steps),
                        "completed_steps": idx - 1,
                        "failed_step": idx,
                        "failed_agent": step.agent_name,
                        "history": step_history
                    }
                )

            # 2. Подготовка метаданных и контекста для текущего шага
            step_meta = dict(step.metadata)
            if last_result:
                step_meta["previous_result"] = last_result.data
                step_meta["previous_message"] = last_result.message
                if last_result.created_files:
                    step_meta["previous_files"] = list(last_result.created_files)

                # Умный трансфер данных между связанными агентами
                if isinstance(last_result.data, dict):
                    if "topic" in last_result.data and not step_meta.get("topic") and not step_meta.get("title"):
                        step_meta["topic"] = last_result.data["topic"]
                    if "title" in last_result.data and not step_meta.get("title"):
                        step_meta["title"] = last_result.data["title"]
                    if "findings" in last_result.data:
                        findings = last_result.data["findings"]
                        if isinstance(findings, list):
                            if not step_meta.get("sections"):
                                step_meta["sections"] = [
                                    {"title": f.get("question", "Тезис"), "content": f.get("finding", "")}
                                    if isinstance(f, dict) else {"title": "Тезис", "content": str(f)}
                                    for f in findings
                                ]
                            if not step_meta.get("slides"):
                                step_meta["slides"] = [
                                    {"title": f.get("question", "Тезис"), "bullets": [f.get("finding", "")]}
                                    if isinstance(f, dict) else {"title": "Тезис", "bullets": [str(f)]}
                                    for f in findings
                                ]

            # Разрешение текста задачи шага
            step_task = step.task
            if not step_task and last_result:
                step_task = last_result.message
            elif last_result and ("{" in step_task and "}" in step_task):
                try:
                    format_vars = {
                        "previous_message": last_result.message,
                        "previous_file": last_result.created_files[0] if last_result.created_files else "",
                        "task": root_context.task,
                    }
                    if isinstance(last_result.data, dict):
                        format_vars.update(last_result.data)
                    step_task = step_task.format(**format_vars)
                except Exception:
                    pass

            step_context = current_context.create_child_context(
                task=step_task,
                files=list(dict.fromkeys(accumulated_files + step.files)),
                metadata=step_meta
            )
            step_context.instruction = step_task

            # Пользовательская трансформация (если передана)
            if callable(step.input_transform):
                try:
                    old_inst = step_context.instruction
                    old_task = step_context.task
                    step_context = step.input_transform(step_context, last_result) or step_context
                    if step_context.instruction != old_inst and step_context.task == old_task:
                        step_context.task = step_context.instruction
                    elif step_context.task != old_task and step_context.instruction == old_inst:
                        step_context.instruction = step_context.task
                    elif step_context.instruction and not step_context.task:
                        step_context.task = step_context.instruction
                    elif step_context.task and not step_context.instruction:
                        step_context.instruction = step_context.task
                    step_task = step_context.instruction or step_context.task
                except Exception as ex:
                    err_msg = f"Ошибка input_transform на шаге {idx} ({step.agent_name}): {ex}"
                    return AgentResult.fail(
                        error=err_msg,
                        message=err_msg,
                        created_files=accumulated_files,
                        artifacts=accumulated_artifacts,
                        data={
                            "total_steps": len(self.steps),
                            "completed_steps": idx - 1,
                            "failed_step": idx,
                            "history": step_history
                        }
                    )

            # 3. Исполнение шага субагентом
            try:
                res = agent.run(step_context)
            except Exception as ex:
                res = AgentResult.fail(
                    error=f"Исключение при выполнении {step.agent_name}: {ex}",
                    message=f"Ошибка на шаге {idx}: {ex}"
                )

            # 4. Регистрация шага в истории и аккумуляция артефактов
            step_rec = {
                "step": idx,
                "name": step.name,
                "step_id": getattr(step, "step_id", step.name),
                "agent": agent.name,
                "task": step_task,
                "success": res.success,
                "message": res.message,
                "created_files": list(res.created_files),
                "artifacts": [a.to_dict() for a in res.artifacts],
                "error": res.error
            }
            step_history.append(step_rec)

            for art in res.artifacts:
                accumulated_artifacts.append(art)
            for cf in res.created_files:
                if cf not in accumulated_files:
                    accumulated_files.append(cf)

            # Индексируем результат в контексте
            current_context.add_result(res, agent_name=agent.name)
            last_result = res

            # 5. Обработка ошибки
            if not res.success:
                if self.stop_on_error:
                    err_msg = f"Сбой на шаге {idx} ({agent.name}): {res.error or res.message}"
                    return AgentResult.fail(
                        error=err_msg,
                        message=f"Pipeline прерван: {err_msg}",
                        created_files=accumulated_files,
                        artifacts=accumulated_artifacts,
                        data={
                            "total_steps": len(self.steps),
                            "completed_steps": idx - 1,
                            "failed_step": idx,
                            "failed_agent": agent.name,
                            "history": step_history,
                            "last_result": res.to_dict()
                        }
                    )

        # 6. Успешный финал
        agents_flow = " -> ".join(s["agent"] for s in step_history)
        msg = f"Pipeline из {len(self.steps)} шагов успешно выполнен ({agents_flow})."

        return AgentResult.ok(
            message=msg,
            created_files=accumulated_files,
            artifacts=accumulated_artifacts,
            data={
                "total_steps": len(self.steps),
                "completed_steps": len(self.steps),
                "pipeline": [s["agent"] for s in step_history],
                "history": step_history,
                "last_result": last_result.to_dict() if last_result else None
            }
        )


def run_agent_pipeline(
    steps: List[Union[PipelineStep, Tuple[str, str], Dict[str, Any]]],
    initial_context: Optional[AgentContext] = None,
    registry: Optional[AgentRegistry] = None,
    stop_on_error: bool = True,
    **kwargs
) -> AgentResult:
    """
    Минимальный публичный API для запуска последовательного конвейера взаимодействия субагентов.
    """
    pipeline = TeamworkPipeline(registry=registry, stop_on_error=stop_on_error)
    for s in steps:
        pipeline.add_step(s)
    return pipeline.run(initial_context=initial_context, **kwargs)

