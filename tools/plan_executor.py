from typing import Any, Dict, List, Optional, Union
from tools.dispatcher import dispatch
from tools.agents.context import AgentContext
from tools.agents.result import AgentResult, Artifact, ArtifactType
from tools.agents.registry import get_agent_registry, AgentRegistry
from tools.planner import PlanStep, TaskPlan
from tools.teamwork import TeamworkPipeline, PipelineStep
from tools.self_healing import ErrorCategory, ErrorContext, ErrorClassifier, SelfHealingManager


class PlanExecutor:
    """
    Выполняет структурированный план по шагам (Task Executor v2 + Self-Healing).

    Поддерживает:
    - TaskPlan (v2) с валидацией целостности графа и топологическим порядком исполнения;
    - Legacy-планы (словари и списки) с сохранением обратной совместимости;
    - Делегирование Sub-Agent шагов в TeamworkPipeline;
    - Накопление результатов, созданных файлов и артефактов в AgentContext и итоговом AgentResult;
    - Контроль ошибок и досрочной остановки (stop_on_error);
    - Контролируемый механизм восстановления ошибок (Self-Healing) с защитой от циклов.
    """

    def __init__(
        self,
        agent=None,
        stop_on_error: bool = True,
        max_retries: int = 1,
        enable_self_healing: bool = True,
        max_total_recoveries: int = 5,
        healing_manager: Optional[SelfHealingManager] = None
    ):
        self.agent = agent
        self.stop_on_error = stop_on_error
        self.max_retries = max(0, int(max_retries))
        self.enable_self_healing = bool(enable_self_healing)
        self.max_total_recoveries = max(0, int(max_total_recoveries))
        self.healing_manager = healing_manager or SelfHealingManager(
            default_max_retries=self.max_retries,
            max_total_recoveries=self.max_total_recoveries
        )

    def execute(
        self,
        plan: Any,
        initial_context: Optional[AgentContext] = None,
        stop_on_error: Optional[bool] = None,
        max_retries: Optional[int] = None,
        enable_self_healing: Optional[bool] = None,
        **kwargs
    ) -> AgentResult:
        """
        Выполняет переданный план (TaskPlan или legacy-план).
        Возвращает стандартизированный итоговый AgentResult.
        """
        should_stop = self.stop_on_error if stop_on_error is None else bool(stop_on_error)
        self_healing_enabled = self.enable_self_healing if enable_self_healing is None else bool(enable_self_healing)
        effective_max_retries = self.max_retries if max_retries is None else max(0, int(max_retries))

        healing_mgr = SelfHealingManager(
            default_max_retries=effective_max_retries if self_healing_enabled else 0,
            max_total_recoveries=self.max_total_recoveries
        )
        reg = getattr(self.agent, "agent_registry", None) or get_agent_registry()

        # 1. Приведение плана к TaskPlan
        if isinstance(plan, TaskPlan):
            task_plan = plan
        elif isinstance(plan, dict):
            if "steps" in plan:
                try:
                    task_plan = TaskPlan.from_dict(plan)
                except Exception as ex:
                    return AgentResult.fail(
                        error=f"Ошибка структуры плана: {ex}",
                        message="План имеет некорректный формат.",
                        data={"success": False, "message": "План имеет некорректный формат.", "raw_plan": plan}
                    )
            else:
                return AgentResult.fail(
                    error="В плане отсутствуют шаги.",
                    message="В плане отсутствуют шаги.",
                    data={"success": False, "message": "В плане отсутствуют шаги.", "raw_plan": plan}
                )
        elif isinstance(plan, list):
            try:
                task_plan = TaskPlan(steps=plan)
            except Exception as ex:
                return AgentResult.fail(
                    error=f"Ошибка структуры шагов: {ex}",
                    message="Список шагов имеет некорректный формат.",
                    data={"success": False, "message": "Список шагов имеет некорректный формат."}
                )
        else:
            return AgentResult.fail(
                error="План имеет некорректный формат.",
                message="План имеет некорректный формат.",
                data={"success": False, "message": "План имеет некорректный формат."}
            )

        # 2. Валидация плана перед запуском
        is_valid, validation_err = task_plan.validate()
        if not is_valid:
            return AgentResult.fail(
                error=validation_err,
                message=f"Ошибка валидации плана: {validation_err}",
                data={
                    "success": False,
                    "message": f"Ошибка валидации плана: {validation_err}",
                    "plan": task_plan.to_dict(),
                    "validation_error": validation_err
                }
            )

        # 3. Исполнение в порядке топологических зависимостей
        ordered_steps = task_plan.get_execution_order()

        # 4. Инициализация рабочего контекста
        plan_goal = task_plan.goal or ""
        plan_meta = dict(task_plan.metadata or {})
        plan_meta.update(kwargs)

        if initial_context is not None:
            current_context = initial_context
            if not current_context.task:
                current_context.task = plan_goal
            current_context.update_metadata(plan_meta)
        else:
            current_context = AgentContext(task=plan_goal, metadata=plan_meta)

        results: List[Dict[str, Any]] = []
        step_history: List[Dict[str, Any]] = []
        accumulated_artifacts: List[Artifact] = list(getattr(current_context, "artifacts", []))
        accumulated_files: List[str] = list(getattr(current_context, "files", []))
        mutations_executed: List[str] = []
        has_failures = False

        # 5. Цикл выполнения шагов плана с контролируемым механизмом Self-Healing
        for idx, step in enumerate(ordered_steps, start=1):
            step_dict = step.to_dict() if hasattr(step, "to_dict") else dict(step)
            step_id = step.id if hasattr(step, "id") else step_dict.get("id", idx)
            step_action = step.action if hasattr(step, "action") else step_dict.get("action")
            step_subagent = step.subagent if hasattr(step, "subagent") else step_dict.get("subagent")

            is_subagent = bool(
                step_subagent
                or step_action == "subagent"
                or self._is_registered_subagent(step_action, registry=reg)
            )

            step_retries = healing_mgr.get_step_max_retries(step) if self_healing_enabled else 0
            max_attempts = 1 + step_retries
            attempt = 1
            step_success = False
            last_error_context: Optional[ErrorContext] = None
            step_recovery_attempts: List[Dict[str, Any]] = []
            pipeline_res: Optional[AgentResult] = None
            tool_res: Optional[Dict[str, Any]] = None

            # 5.1. Цикл попыток исполнения шага с детерминированным recovery
            while attempt <= max_attempts:
                if is_subagent:
                    # Sub-Agent шаг: делегирование в TeamworkPipeline
                    step_pipeline = TeamworkPipeline(
                        steps=[step],
                        registry=reg,
                        stop_on_error=True
                    )
                    pipeline_res = step_pipeline.run(
                        initial_task=step.task or step.details or step.description,
                        initial_context=current_context
                    )
                    step_success = pipeline_res.success
                    last_step_res = pipeline_res
                else:
                    # Стандартный шаг инструмента (search, analyze, read, edit, command, validate, git)
                    tool_res = self._execute_step(step, results)
                    step_success = bool(tool_res.get("success", False))
                    last_step_res = tool_res

                if step_success:
                    break

                # Шаг завершился с ошибкой: строим структурированный контекст ошибки
                error_ctx = healing_mgr.classify_error(
                    step=step,
                    result=last_step_res,
                    attempt=attempt,
                    max_attempts=max_attempts
                )
                last_error_context = error_ctx
                attempt_record = error_ctx.to_dict()

                # Сохраняем попытку в AgentContext перед повтором
                current_context.record_recovery_attempt(attempt_record)
                step_recovery_attempts.append(attempt_record)

                # Проверяем возможность повторной попытки восстановления
                if (
                    self_healing_enabled
                    and error_ctx.is_recoverable
                    and attempt < max_attempts
                    and healing_mgr.can_attempt_recovery()
                ):
                    healing_mgr.record_recovery()
                    attempt += 1
                    continue
                else:
                    break

            was_recovered = bool(step_success and len(step_recovery_attempts) > 0)

            # 5.2. Обработка завершения шага
            if is_subagent:
                assert pipeline_res is not None
                if step_success:
                    # Аккумулируем артефакты и созданные файлы
                    for art in pipeline_res.artifacts:
                        if art not in accumulated_artifacts:
                            accumulated_artifacts.append(art)
                    for cf in pipeline_res.created_files:
                        if cf not in accumulated_files:
                            accumulated_files.append(cf)

                    # Фиксируем результат в AgentContext
                    current_context.add_result(
                        pipeline_res,
                        agent_name=step_subagent or step_action
                    )

                    step_res_dict = {
                        "success": True,
                        "message": pipeline_res.message,
                        "result": pipeline_res.to_dict(),
                        "data": pipeline_res.data,
                        "subagent": step_subagent or step_action,
                        "action": step_action,
                        "id": step_id,
                        "created_files": list(pipeline_res.created_files),
                        "artifacts": [a.to_dict() for a in pipeline_res.artifacts],
                        "error": None,
                        "attempts": attempt,
                        "recovered": was_recovered,
                        "recovery_attempts": len(step_recovery_attempts)
                    }
                    results.append(step_res_dict)

                    step_history.append({
                        "step": idx,
                        "id": step_id,
                        "name": str(step_id),
                        "step_id": str(step_id),
                        "action": step_action,
                        "subagent": step_subagent or step_action,
                        "task": step.task or step.details or step.description,
                        "success": True,
                        "message": pipeline_res.message,
                        "created_files": list(pipeline_res.created_files),
                        "artifacts": [a.to_dict() for a in pipeline_res.artifacts],
                        "error": None,
                        "attempts": attempt,
                        "recovered": was_recovered,
                        "recovery_attempts": len(step_recovery_attempts)
                    })
                else:
                    has_failures = True
                    if mutations_executed:
                        dispatch("validate_project")

                    step_res_dict = {
                        "success": False,
                        "message": pipeline_res.message,
                        "result": pipeline_res.to_dict(),
                        "data": pipeline_res.data,
                        "subagent": step_subagent or step_action,
                        "action": step_action,
                        "id": step_id,
                        "created_files": list(pipeline_res.created_files),
                        "artifacts": [a.to_dict() for a in pipeline_res.artifacts],
                        "error": pipeline_res.error or pipeline_res.message,
                        "attempts": attempt,
                        "recovered": False,
                        "recovery_attempts": len(step_recovery_attempts),
                        "error_context": last_error_context.to_dict() if last_error_context else None
                    }
                    results.append(step_res_dict)

                    step_history.append({
                        "step": idx,
                        "id": step_id,
                        "name": str(step_id),
                        "step_id": str(step_id),
                        "action": step_action,
                        "subagent": step_subagent or step_action,
                        "task": step.task or step.details or step.description,
                        "success": False,
                        "message": pipeline_res.message,
                        "created_files": list(pipeline_res.created_files),
                        "artifacts": [a.to_dict() for a in pipeline_res.artifacts],
                        "error": pipeline_res.error or pipeline_res.message,
                        "attempts": attempt,
                        "recovered": False,
                        "recovery_attempts": len(step_recovery_attempts),
                        "error_context": last_error_context.to_dict() if last_error_context else None
                    })

                    if should_stop:
                        err_msg = f"Выполнение остановлено на шаге {step_id}: {pipeline_res.error or pipeline_res.message}"
                        return AgentResult.fail(
                            error=pipeline_res.error or pipeline_res.message,
                            message=err_msg,
                            created_files=accumulated_files,
                            artifacts=accumulated_artifacts,
                            data={
                                "success": False,
                                "message": err_msg,
                                "step": step_dict,
                                "results": results,
                                "history": step_history,
                                "recovery_history": current_context.recovery_history,
                                "failed_step": step_id,
                                "plan": task_plan.to_dict()
                            }
                        )

            else:
                # Стандартный шаг инструмента (search, analyze, read, edit, command, validate, git)
                assert tool_res is not None
                target = step.target if hasattr(step, "target") else step_dict.get("target")

                if step_success:
                    if step_action in ("edit", "write") and target:
                        mutations_executed.append(target)
                        if target not in accumulated_files:
                            accumulated_files.append(target)
                        accumulated_artifacts.append(Artifact.from_file(target, type=ArtifactType.CODE))
                    elif step_action == "read" and target:
                        if target not in accumulated_files:
                            accumulated_files.append(target)
                        accumulated_artifacts.append(Artifact.from_file(target, type=ArtifactType.FILE))

                    tool_agent_res = AgentResult(
                        success=True,
                        message=tool_res.get("message", ""),
                        created_files=[target] if target else [],
                        data=tool_res,
                        error=None
                    )
                    current_context.add_result(tool_agent_res, agent_name=step_action)

                    tool_res_dict = dict(tool_res)
                    tool_res_dict.update({
                        "attempts": attempt,
                        "recovered": was_recovered,
                        "recovery_attempts": len(step_recovery_attempts)
                    })
                    results.append(tool_res_dict)

                    step_history.append({
                        "step": idx,
                        "id": step_id,
                        "name": str(step_id),
                        "step_id": str(step_id),
                        "action": step_action,
                        "success": True,
                        "message": tool_res.get("message", ""),
                        "created_files": [target] if target else [],
                        "artifacts": [a.to_dict() for a in tool_agent_res.artifacts],
                        "error": None,
                        "attempts": attempt,
                        "recovered": was_recovered,
                        "recovery_attempts": len(step_recovery_attempts)
                    })
                else:
                    has_failures = True
                    if mutations_executed:
                        dispatch("validate_project")

                    tool_agent_res = AgentResult(
                        success=False,
                        message=tool_res.get("message", ""),
                        created_files=[],
                        data=tool_res,
                        error=tool_res.get("error") or tool_res.get("message")
                    )
                    current_context.add_result(tool_agent_res, agent_name=step_action)

                    tool_res_dict = dict(tool_res)
                    tool_res_dict.update({
                        "attempts": attempt,
                        "recovered": False,
                        "recovery_attempts": len(step_recovery_attempts),
                        "error_context": last_error_context.to_dict() if last_error_context else None
                    })
                    results.append(tool_res_dict)

                    step_history.append({
                        "step": idx,
                        "id": step_id,
                        "name": str(step_id),
                        "step_id": str(step_id),
                        "action": step_action,
                        "success": False,
                        "message": tool_res.get("message", ""),
                        "created_files": [],
                        "artifacts": [],
                        "error": tool_res.get("error") or tool_res.get("message"),
                        "attempts": attempt,
                        "recovered": False,
                        "recovery_attempts": len(step_recovery_attempts),
                        "error_context": last_error_context.to_dict() if last_error_context else None
                    })

                    is_cancelled = (
                        "отменил" in str(tool_res.get("result", {}).get("error", ""))
                        or "отменил" in str(tool_res.get("message", ""))
                    )
                    if is_cancelled:
                        msg = (
                            f"План остановлен. "
                            f"Действие {step_id} отменено пользователем. "
                            f"Последующие действия не выполнены."
                        )
                    else:
                        msg = f"Выполнение остановлено на шаге {step_id}."

                    if should_stop:
                        return AgentResult.fail(
                            error=tool_res.get("message") or msg,
                            message=msg,
                            created_files=accumulated_files,
                            artifacts=accumulated_artifacts,
                            data={
                                "success": False,
                                "message": msg,
                                "step": step_dict,
                                "results": results,
                                "history": step_history,
                                "recovery_history": current_context.recovery_history,
                                "failed_step": step_id,
                                "plan": task_plan.to_dict()
                            }
                        )

        # 6. Формирование итогового AgentResult
        has_recovered_steps = any(bool(r.get("recovered")) for r in results)
        if has_failures:
            return AgentResult.fail(
                error="Один или несколько шагов плана завершились с ошибкой.",
                message="План завершён с ошибками.",
                created_files=accumulated_files,
                artifacts=accumulated_artifacts,
                data={
                    "success": False,
                    "message": "План завершён с ошибками.",
                    "results": results,
                    "history": step_history,
                    "recovery_history": current_context.recovery_history,
                    "recovered": has_recovered_steps,
                    "plan": task_plan.to_dict(),
                    "total_steps": len(ordered_steps),
                    "completed_steps": len([r for r in results if r.get("success")])
                }
            )

        return AgentResult.ok(
            message="План выполнен успешно.",
            created_files=accumulated_files,
            artifacts=accumulated_artifacts,
            data={
                "success": True,
                "message": "План выполнен успешно.",
                "results": results,
                "history": step_history,
                "recovery_history": current_context.recovery_history,
                "recovered": has_recovered_steps,
                "plan": task_plan.to_dict(),
                "total_steps": len(ordered_steps),
                "completed_steps": len(results)
            }
        )

    def _execute_step(self, step, previous_results):
        """
        Выполняет один шаг плана.
        """
        if hasattr(step, "to_dict"):
            step = step.to_dict()

        if not isinstance(step, dict):
            return {
                "success": False,
                "message": "Шаг имеет некорректный формат."
            }

        action = step.get("action")
        subagent = step.get("subagent")
        target = step.get("target")
        command = step.get("command")
        query = step.get("query")
        details = step.get("details", "")

        context = self._build_context(
            previous_results
        )

        # Вызов специализированного Sub-Agent (Task Planner v2)
        if subagent or action == "subagent" or self._is_registered_subagent(action):
            return self._execute_subagent(step, previous_results, context)

        if action == "search":
            return self._execute_search(
                query,
                details,
                context
            )

        if action == "analyze":

            resolved_target = self._resolve_target(
                target,
                previous_results
            )

            content = self._get_read_content(
                resolved_target,
                previous_results
            )

            return self._execute_analyze(
                resolved_target,
                details,
                context,
                content
            )

        if action == "read":

            resolved_target = self._resolve_target(
                target,
                previous_results
            )

            return self._execute_read(
                resolved_target,
                details,
                context
            )

        if action == "edit":
            return self._execute_edit(
                target,
                details,
                context
            )

        if action == "command":
            return self._execute_command(
                command,
                details,
                context
            )

        if action == "validate":
            return self._execute_validate(
                details,
                context
            )

        if action == "git":
            return self._execute_git(
                command,
                details,
                context
            )

        return {
            "success": False,
            "message": (
                f"Неизвестное действие: {action}"
            )
        }

    def _execute_search(
        self,
        query,
        details,
        context
    ):
        """
        Выполняет поиск по проекту.
        """

        if not query:
            return {
                "success": False,
                "message": (
                    "Для search не указан query."
                )
            }

        result = dispatch(
            "search_files",
            query=query
        )

        return {
            "success": result.get("success", False),
            "action": "search",
            "query": query,
            "details": details,
            "result": result,
            "context": context
        }

    def _execute_analyze(
        self,
        target,
        details,
        context,
        content=None
    ):
        """
        Анализирует файл.

        Если content уже получен предыдущим шагом read,
        повторное чтение файла не выполняется.
        """

        if not target:
            return {
                "success": False,
                "message": (
                    "Для analyze не указан target."
                )
            }

        if content is not None:

            result = dispatch(
                "analyze_file",
                filename=target,
                task=details,
                content=content
            )

        else:

            result = dispatch(
                "analyze_file",
                filename=target,
                task=details
            )

        return {
            "success": result.get("success", False),
            "action": "analyze",
            "target": target,
            "details": details,
            "result": result,
            "context": context
        }

    def _execute_read(
        self,
        target,
        details,
        context
    ):
        """
        Читает файл.
        """

        if not target:
            return {
                "success": False,
                "message": (
                    "Для read не указан target."
                )
            }

        result = dispatch(
            "read_file",
            filename=target
        )

        return {
            "success": result.get("success", False),
            "action": "read",
            "target": target,
            "details": details,
            "result": result,
            "context": context
        }

    def _execute_edit(
        self,
        target,
        details,
        context
    ):
        """
        Подготавливает и выполняет изменение файла.
        """

        if not target:
            return {
                "success": False,
                "message": (
                    "Для edit не указан target."
                )
            }

        if self.agent is None:
            return {
                "success": False,
                "message": (
                    "PlanExecutor не получил Agent."
                )
            }

        user_request = self._build_edit_request(
            target,
            details,
            context
        )

        prepared = self.agent.prepare_edit(
            target,
            user_request
        )

        if not prepared.get("success"):
            return {
                "success": False,
                "action": "edit",
                "target": target,
                "details": details,
                "result": prepared,
                "context": context
            }

        edit_result = dispatch(
            "edit_file",
            filename=target,
            old_text=prepared["old_text"],
            new_text=prepared["new_text"]
        )

        return {
            "success": edit_result.get("success", False),
            "action": "edit",
            "target": target,
            "details": details,
            "result": edit_result,
            "context": context
        }

    def _execute_command(
        self,
        command,
        details,
        context
    ):
        """
        Выполняет команду.
        """

        if not command:
            return {
                "success": False,
                "message": (
                    "Для command не указана команда."
                )
            }

        result = dispatch(
            "run_command",
            command=command
        )

        return {
            "success": result.get("success", False),
            "action": "command",
            "command": command,
            "details": details,
            "result": result,
            "context": context
        }

    def _execute_validate(
        self,
        details,
        context
    ):
        """
        Выполняет полную проверку Python-проекта.
        При обнаружении синтаксических ошибок использует механизм self-healing агента.
        """

        result = dispatch(
            "validate_project"
        )

        val_success = result.get("success", False)
        tool_res = result.get("result", {}) if isinstance(result, dict) else {}
        errors = []
        if isinstance(tool_res, dict) and "errors" in tool_res:
            errors = tool_res.get("errors", [])
        elif isinstance(result, dict) and "errors" in result:
            errors = result.get("errors", [])

        # Если валидация выявила ошибки синтаксиса и у нас есть ссылка на agent
        if (not val_success or errors) and self.agent is not None and hasattr(self.agent, "run_single_correction"):
            heal_result = self.agent.run_single_correction(errors or [result])
            if heal_result.get("success"):
                return {
                    "success": True,
                    "action": "validate",
                    "details": details,
                    "result": heal_result.get("validation_result", result),
                    "context": context,
                    "self_healing": {
                        "attempted": True,
                        "success": True,
                        "edit_result": heal_result.get("edit_result")
                    }
                }
            else:
                return {
                    "success": False,
                    "action": "validate",
                    "details": details,
                    "result": result,
                    "context": context,
                    "self_healing": {
                        "attempted": True,
                        "success": False,
                        "error": heal_result.get("error")
                    }
                }

        return {
            "success": val_success and not errors,
            "action": "validate",
            "details": details,
            "result": result,
            "context": context
        }

    def _execute_git(
        self,
        command,
        details,
        context
    ):
        """
        Выполняет Git-команду.
        """

        if not command:
            return {
                "success": False,
                "message": (
                    "Для git не указана команда."
                )
            }

        result = dispatch(
            "run_command",
            command=command
        )

        return {
            "success": result.get("success", False),
            "action": "git",
            "command": command,
            "details": details,
            "result": result,
            "context": context
        }

    def _resolve_target(
        self,
        target,
        previous_results
    ):
        """
        Определяет файл для read/analyze.

        Приоритет:

        1. target из плана, если он указан.
        2. Файл из последнего успешного search.
        3. None.

        target из плана имеет приоритет, потому что search_files()
        ищет текст внутри файлов и не гарантирует, что первое
        совпадение является целевым файлом.
        """

        if target:
            return target

        for result in reversed(previous_results):

            if result.get("action") != "search":
                continue

            if not result.get("success"):
                continue

            tool_result = result.get("result")

            if not isinstance(tool_result, dict):
                continue

            if not tool_result.get("success"):
                continue

            search_result = tool_result.get(
                "result"
            )

            if not isinstance(search_result, dict):
                continue

            if not search_result.get("success"):
                continue

            matches = search_result.get(
                "matches",
                []
            )

            if not isinstance(matches, list):
                continue

            if not matches:
                continue

            first_match = matches[0]

            if not isinstance(first_match, dict):
                continue

            file_name = first_match.get(
                "file"
            )

            if file_name:
                return file_name

        return None

    def _get_read_content(
        self,
        target,
        previous_results
    ):
        """
        Получает содержимое файла из предыдущего
        успешного шага read.

        Возвращает None, если подходящего результата
        read нет.
        """

        if not target:
            return None

        for result in reversed(previous_results):

            if result.get("action") != "read":
                continue

            if not result.get("success"):
                continue

            if result.get("target") != target:
                continue

            tool_result = result.get("result")

            if not isinstance(tool_result, dict):
                continue

            if not tool_result.get("success"):
                continue

            read_result = tool_result.get(
                "result"
            )

            if not isinstance(read_result, dict):
                continue

            if not read_result.get("success"):
                continue

            content = read_result.get(
                "content"
            )

            if content is not None:
                return content

        return None

    def _build_context(
        self,
        previous_results
    ):
        """
        Формирует контекст из предыдущих шагов.
        """

        context = []

        for item in previous_results:

            context.append({
                "action": item.get("action"),
                "target": item.get("target"),
                "query": item.get("query"),
                "command": item.get("command"),
                "success": item.get("success"),
                "result": item.get("result")
            })

        return context

    def _build_edit_request(
        self,
        target,
        details,
        context
    ):
        """
        Формирует запрос для подготовки изменения файла.
        """

        request = (
            f"Измени файл {target}.\n\n"
            f"Задача текущего шага:\n"
            f"{details}\n"
        )

        if context:

            request += (
                "\nРезультаты предыдущих шагов:\n"
            )

            for item in context:

                request += (
                    f"\nДействие: "
                    f"{item.get('action')}\n"
                    f"Цель: "
                    f"{item.get('target')}\n"
                    f"Поиск: "
                    f"{item.get('query')}\n"
                    f"Успешно: "
                    f"{item.get('success')}\n"
                )
        return request

    # =========================================================================
    # Поддержка Sub-Agent в Task Executor v2 через TeamworkPipeline
    # =========================================================================

    def _is_registered_subagent(self, action: Optional[str], registry=None) -> bool:
        """Проверяет, зарегистрирован ли субагент с таким именем."""
        if not action or not isinstance(action, str):
            return False
        if action in ("search", "analyze", "read", "edit", "command", "validate", "git"):
            return False
        reg = registry or getattr(self.agent, "agent_registry", None) or get_agent_registry()
        return reg.has(action)

    def _execute_subagent(self, step, previous_results, context):
        """
        Выполняет шаг, привязанный к Sub-Agent через TeamworkPipeline (Task Executor v2).
        """
        agent_name = step.get("subagent") or step.get("action")
        task_str = step.get("task") or step.get("details") or step.get("description") or ""
        meta = dict(step.get("metadata") or {})
        files = list(step.get("files") or [])
        if step.get("target") and step.get("target") not in files:
            files.append(step.get("target"))

        reg = getattr(self.agent, "agent_registry", None) or get_agent_registry()
        if not reg.has(agent_name):
            return {
                "success": False,
                "message": f"Субагент '{agent_name}' не найден в реестре.",
                "step": step
            }

        pipe_step = PipelineStep(
            agent=agent_name,
            task=task_str,
            metadata=meta,
            files=files,
            name=str(step.get("id") or agent_name)
        )
        pipeline = TeamworkPipeline(
            steps=[pipe_step],
            registry=reg,
            stop_on_error=self.stop_on_error
        )
        if isinstance(context, AgentContext):
            step_context = context
        else:
            step_context = AgentContext(task=task_str, files=files, metadata=meta)

        res = pipeline.run(initial_task=task_str, initial_context=step_context)
        return {
            "success": res.success,
            "message": res.message,
            "result": res.to_dict(),
            "data": res.data,
            "subagent": agent_name,
            "action": step.get("action") or agent_name,
            "id": step.get("id"),
            "created_files": list(res.created_files),
            "artifacts": [a.to_dict() for a in res.artifacts],
            "error": res.error
        }
