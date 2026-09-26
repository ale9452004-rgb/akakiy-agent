from ollama_client import OllamaClient
import json
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union


class PlanStep:
    """
    Структурированный шаг плана выполнения задачи (Task Planner v2).

    Атрибуты:
    - id: Уникальный идентификатор шага (int или str);
    - action: Имя действия (стандартное или имя субагента);
    - description: Краткое описание шага для человека;
    - details: Детальные инструкции для исполнителя (по умолчанию равно description);
    - depends_on: Список идентификаторов шагов, от которых зависит данный шаг;
    - subagent: Опциональное имя специализированного Sub-Agent'а;
    - target: Опциональный целевой файл или путь;
    - command: Опциональная команда терминала или git;
    - query: Опциональный поисковый запрос;
    - task: Опциональная конкретная инструкция для шага/субагента;
    - files: Опциональный список входных файлов;
    - metadata: Произвольные метаданные шага.
    """

    def __init__(
        self,
        id: Union[int, str],
        action: str,
        description: str = "",
        details: Optional[str] = None,
        depends_on: Optional[Union[List[Union[int, str]], Union[int, str]]] = None,
        subagent: Optional[str] = None,
        target: Optional[str] = None,
        command: Optional[str] = None,
        query: Optional[str] = None,
        task: Optional[str] = None,
        files: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **extra_kwargs
    ):
        self.id = id
        self.action = str(action).strip() if action else ""
        self.description = str(description or details or f"Шаг {id}").strip()
        self.details = str(details or description or self.description).strip()

        if depends_on is None:
            self.depends_on: List[Union[int, str]] = []
        elif isinstance(depends_on, (list, tuple, set)):
            self.depends_on = list(depends_on)
        else:
            self.depends_on = [depends_on]

        self.subagent = str(subagent).strip() if subagent else None
        self.target = str(target).strip() if target else None
        self.command = str(command).strip() if command else None
        self.query = str(query).strip() if query else None
        self.task = str(task).strip() if task else None
        self.files = list(files or [])
        self.metadata = dict(metadata or {})
        if extra_kwargs:
            self.metadata.update(extra_kwargs)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "action": self.action,
            "description": self.description,
            "details": self.details,
            "depends_on": list(self.depends_on),
        }
        if self.subagent:
            d["subagent"] = self.subagent
        if self.target:
            d["target"] = self.target
        if self.command:
            d["command"] = self.command
        if self.query:
            d["query"] = self.query
        if self.task:
            d["task"] = self.task
        if self.files:
            d["files"] = list(self.files)
        if self.metadata:
            d["metadata"] = dict(self.metadata)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanStep":
        if not isinstance(data, dict):
            raise ValueError(f"Ожидается словарь для PlanStep, получено: {type(data)}")

        step_id = data.get("id", 1)
        action = data.get("action", "")
        description = data.get("description", "")
        details = data.get("details", "")
        depends_on = data.get("depends_on", [])
        subagent = data.get("subagent") or data.get("agent") or data.get("agent_name")
        target = data.get("target")
        command = data.get("command")
        query = data.get("query")
        task = data.get("task") or data.get("instruction")
        files = data.get("files")
        meta = dict(data.get("metadata") or {})

        known_keys = {
            "id", "action", "description", "details", "depends_on",
            "subagent", "agent", "agent_name", "target", "command",
            "query", "task", "instruction", "files", "metadata"
        }
        for k, v in data.items():
            if k not in known_keys and k not in meta:
                meta[k] = v

        return cls(
            id=step_id,
            action=action,
            description=description,
            details=details,
            depends_on=depends_on,
            subagent=subagent,
            target=target,
            command=command,
            query=query,
            task=task,
            files=files,
            metadata=meta
        )

    def to_pipeline_step(self, registry=None) -> Any:
        from tools.teamwork import PipelineStep

        agent_name = self.subagent
        if not agent_name:
            act_norm = self.action.lower().strip()
            subagents_known = {"research", "document", "coding", "file", "presentation", "image", "echo"}
            if act_norm in subagents_known:
                agent_name = act_norm
            elif act_norm in ("edit", "patch", "code"):
                agent_name = "coding"
            elif act_norm in ("read", "create", "write", "copy", "move", "files"):
                agent_name = "file"
            elif act_norm == "search":
                agent_name = "file"
            elif registry and getattr(registry, "has", None) and registry.has(act_norm):
                agent_name = act_norm
            else:
                agent_name = self.action

        task_str = self.task or self.details or self.description
        step_files = list(self.files)
        if self.target and self.target not in step_files:
            step_files.append(self.target)

        step_meta = dict(self.metadata)
        if self.action:
            step_meta["action"] = self.action
        if self.target:
            step_meta["target"] = self.target
            step_meta["file"] = self.target
        if self.command:
            step_meta["command"] = self.command
        if self.query:
            step_meta["query"] = self.query
        if self.depends_on:
            step_meta["depends_on"] = list(self.depends_on)
        step_meta["step_id"] = self.id

        return PipelineStep(
            agent=agent_name,
            task=task_str,
            metadata=step_meta,
            files=step_files,
            name=str(self.id)
        )

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if key in self.metadata:
            return self.metadata[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            val = getattr(self, key)
            return val if val is not None else default
        return self.metadata.get(key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or key in self.metadata

    def __repr__(self) -> str:
        sub_str = f", subagent='{self.subagent}'" if self.subagent else ""
        dep_str = f", depends_on={self.depends_on}" if self.depends_on else ""
        return f"PlanStep(id={self.id}, action='{self.action}', desc='{self.description}'{sub_str}{dep_str})"


class TaskPlan:
    """
    Структурированный план выполнения задачи (Task Planner v2).

    Содержит упорядоченный набор шагов PlanStep, граф зависимостей,
    методы валидации, топологической сортировки и конвертации в Teamwork Pipeline.
    """

    def __init__(
        self,
        steps: Optional[List[Union[PlanStep, Dict[str, Any]]]] = None,
        goal: str = "",
        user_request: Optional[str] = None,
        expected_result: Optional[str] = None,
        verification: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "created"
    ):
        self.goal = str(goal or user_request or "").strip()
        self.user_request = self.goal
        self.expected_result = expected_result
        self.verification = verification
        self.metadata = dict(metadata or {})
        self.status = status
        self.steps: List[PlanStep] = []
        if steps:
            for s in steps:
                self.add_step(s)

    def add_step(self, step: Union[PlanStep, Dict[str, Any]]) -> "TaskPlan":
        """Добавляет шаг в план (fluent API)."""
        if isinstance(step, PlanStep):
            self.steps.append(step)
        elif isinstance(step, dict):
            if "id" not in step:
                step_dict = dict(step)
                step_dict["id"] = len(self.steps) + 1
                self.steps.append(PlanStep.from_dict(step_dict))
            else:
                self.steps.append(PlanStep.from_dict(step))
        else:
            raise ValueError(f"Некорректный формат шага: {type(step)}")
        return self

    def get_step(self, step_id: Union[int, str]) -> Optional[PlanStep]:
        """Возвращает шаг плана по его ID."""
        target_str = str(step_id).strip()
        for s in self.steps:
            if str(s.id).strip() == target_str:
                return s
        return None

    def validate(self) -> Tuple[bool, Optional[str]]:
        """
        Выполняет валидацию плана:
        - наличие шагов;
        - уникальность ID;
        - обязательные поля каждого шага (action, description/details);
        - специфичные параметры действий (query для search, target для read/edit/analyze, command для command/git);
        - валидность зависимостей (отсутствие ссылок на несуществующие ID, отсутствие самозависимости);
        - отсутствие циклических зависимостей в графе выполнения.

        Возвращает (True, None) или (False, "описание ошибки").
        """
        if not self.steps:
            return False, "В плане отсутствуют шаги."

        seen_ids = set()
        for s in self.steps:
            sid_str = str(s.id).strip()
            if sid_str in seen_ids:
                return False, f"Дублирующийся идентификатор шага в плане: {s.id}"
            seen_ids.add(sid_str)

        for s in self.steps:
            if not s.action:
                return False, f"Шаг {s.id}: не указано действие (action)."
            if not s.description and not s.details:
                return False, f"Шаг {s.id}: отсутствует описание (description)."

            if s.action == "search":
                if not s.query:
                    return False, f"Шаг {s.id}: для действия 'search' не указан query."
            elif s.action in ("analyze", "read", "edit"):
                if not s.target:
                    return False, f"Шаг {s.id}: для действия '{s.action}' не указан target."
            elif s.action in ("command", "git"):
                if not s.command:
                    return False, f"Шаг {s.id}: для действия '{s.action}' не указана команда."

            for dep in s.depends_on:
                dep_str = str(dep).strip()
                if dep_str == str(s.id).strip():
                    return False, f"Шаг {s.id} зависит от самого себя."
                if dep_str not in seen_ids:
                    return False, f"Шаг {s.id} ссылается на несуществующую зависимость: {dep}."

        # Проверка циклических зависимостей алгоритмом Кана (in-degree)
        in_degree = {str(s.id).strip(): 0 for s in self.steps}
        dependents: Dict[str, List[str]] = {str(s.id).strip(): [] for s in self.steps}

        for s in self.steps:
            sid = str(s.id).strip()
            for dep in s.depends_on:
                dep_str = str(dep).strip()
                in_degree[sid] += 1
                dependents[dep_str].append(sid)

        queue = [str(s.id).strip() for s in self.steps if in_degree[str(s.id).strip()] == 0]
        visited_count = 0

        while queue:
            curr = queue.pop(0)
            visited_count += 1
            for child in dependents[curr]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if visited_count < len(self.steps):
            cycle_nodes = [s.id for s in self.steps if in_degree[str(s.id).strip()] > 0]
            return False, f"Обнаружена циклическая зависимость между шагами: {cycle_nodes}."

        return True, None

    def get_execution_order(self) -> List[PlanStep]:
        """
        Возвращает упорядоченный список шагов с учетом зависимостей (топологическая сортировка).
        """
        is_ok, err = self.validate()
        if not is_ok:
            raise ValueError(f"Невалидный план: {err}")

        step_map = {str(s.id).strip(): s for s in self.steps}
        in_degree = {str(s.id).strip(): 0 for s in self.steps}
        dependents: Dict[str, List[str]] = {str(s.id).strip(): [] for s in self.steps}

        for s in self.steps:
            sid = str(s.id).strip()
            for dep in s.depends_on:
                dep_str = str(dep).strip()
                in_degree[sid] += 1
                dependents[dep_str].append(sid)

        queue = [str(s.id).strip() for s in self.steps if in_degree[str(s.id).strip()] == 0]
        ordered: List[PlanStep] = []

        while queue:
            curr = queue.pop(0)
            ordered.append(step_map[curr])
            for child in dependents[curr]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(ordered) < len(self.steps):
            cycle_nodes = [s.id for s in self.steps if in_degree[str(s.id).strip()] > 0]
            raise ValueError(f"Обнаружена циклическая зависимость между шагами: {cycle_nodes}")

        return ordered

    def to_pipeline_steps(self, registry=None) -> List[Any]:
        """
        Преобразует шаги плана в список PipelineStep для TeamworkPipeline.
        """
        ordered = self.get_execution_order()
        return [s.to_pipeline_step(registry=registry) for s in ordered]

    def to_pipeline(self, registry=None, stop_on_error: bool = True) -> Any:
        """
        Создаёт и возвращает сконфигурированный TeamworkPipeline.
        """
        from tools.teamwork import TeamworkPipeline
        steps = self.to_pipeline_steps(registry=registry)
        return TeamworkPipeline(steps=steps, registry=registry, stop_on_error=stop_on_error)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "request": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "expected_result": self.expected_result,
            "verification": self.verification,
            "metadata": dict(self.metadata),
            "status": self.status
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskPlan":
        if not isinstance(data, dict):
            raise ValueError(f"Ожидается словарь для TaskPlan, получено: {type(data)}")
        goal = data.get("goal") or data.get("request") or data.get("user_request") or ""
        expected = data.get("expected_result")
        verif = data.get("verification")
        meta = dict(data.get("metadata") or {})
        status = data.get("status", "created")
        raw_steps = data.get("steps") or []
        steps = [PlanStep.from_dict(s) if isinstance(s, dict) else s for s in raw_steps]
        return cls(
            steps=steps,
            goal=goal,
            expected_result=expected,
            verification=verif,
            metadata=meta,
            status=status
        )

    def __getitem__(self, key: str) -> Any:
        if key == "steps":
            return [s.to_dict() for s in self.steps]
        if hasattr(self, key):
            return getattr(self, key)
        if key in self.metadata:
            return self.metadata[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "steps":
            return [s.to_dict() for s in self.steps]
        if hasattr(self, key):
            val = getattr(self, key)
            return val if val is not None else default
        return self.metadata.get(key, default)

    def __contains__(self, key: str) -> bool:
        if key == "steps":
            return True
        return hasattr(self, key) or key in self.metadata

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self):
        return iter(self.steps)

    def __repr__(self) -> str:
        return f"TaskPlan(goal='{self.goal}', steps_count={len(self.steps)}, status='{self.status}')"


class Planner:
    """
    Создаёт и хранит текущий структурированный план выполнения задачи (Task Planner v2).

    Планирование не изменяет файлы и не выполняет команды.
    Поддерживает:
    - генерацию планов через LLM с контекстом диалога;
    - программное создание структурированных планов (create_structured_plan);
    - проверку графа последовательных зависимостей (validate_plan);
    - конвертацию планов в шаги PipelineStep и TeamworkPipeline.
    """

    ALLOWED_ACTIONS = {
        "search",
        "analyze",
        "read",
        "edit",
        "command",
        "validate",
        "git",
        "subagent",
        "research",
        "document",
        "presentation",
        "coding",
        "file",
        "image",
        "echo",
    }

    def __init__(self, context_manager=None, ai_client=None):
        self.ai = ai_client or OllamaClient()
        self.context_manager = context_manager

        self.current_plan = None
        self.current_request = None
        self.current_research_context = None
        self.current_status = None
        self.current_step = 0

    def create_plan(self, user_request, research_context=None, planning_context=None):
        """
        Создаёт новый структурированный план
        и сохраняет его как текущий.
        При наличии research_context использует результаты предварительного исследования.
        При наличии context_manager или planning_context учитывает контекст диалога и факты пользователя.
        """

        dialogue_context = planning_context
        if dialogue_context is None and self.context_manager is not None:
            dialogue_context = self.context_manager.get_planning_context(user_request)

        context_block = ""
        if dialogue_context:
            context_block += f"""
КОНТЕКСТ ДИАЛОГА И ДАННЫЕ ПОЛЬЗОВАТЕЛЯ:
{dialogue_context}
"""

        if research_context:
            context_block += f"""
РЕЗУЛЬТАТЫ ПРЕДВАРИТЕЛЬНОГО ИССЛЕДОВАНИЯ:
{research_context}

ПРАВИЛО ИСПОЛЬЗОВАНИЯ ИССЛЕДОВАНИЯ:
Если результаты предварительного исследования уже содержат целевой файл и найденную проблему, используй эти данные напрямую (указывай найденный файл в target) и не дублируй поиск заново.
"""

        prompt = f"""
Ты — планировщик локального ИИ-ассистента Акакия.

Твоя задача — составить точный план выполнения
запроса пользователя.

Запрос пользователя:

{user_request}
{context_block}
Ты НЕ выполняешь задачу.
Ты только составляешь план.

Допустимые действия:

"search"
— поиск функции, класса, текста или другого
фрагмента по всему проекту.

"analyze"
— анализ проекта, архитектуры или проблемы.

"read"
— чтение конкретного файла.

"edit"
— изменение конкретного файла.

"command"
— выполнение конкретной команды.

"validate"
— проверка результата после выполнения изменений.

"git"
— операция Git.

СТРОГИЕ ПРАВИЛА:

1. Сначала определи, чего хочет пользователь.

2. Если пользователь хочет только анализ,
   поиск ошибок или получение информации,
   НЕ добавляй "edit".

3. Если пользователь явно просит найти конкретную
   функцию, класс или другой объект кода,
   ОБЯЗАТЕЛЬНО используй "search",
   даже если имя файла уже известно.

4. Если после поиска необходимо изучить
   найденный файл, после "search" используй
   "read".

5. Если пользователь просит проанализировать
   конкретную функцию, класс или участок кода,
   сначала найди его через "search", затем
   прочитай найденный файл через "read",
   затем используй "analyze".

6. Если пользователь просто просит прочитать
   или изменить конкретный уже известный файл
   и НЕ просит предварительно найти конкретную
   функцию, класс или объект, "search" не обязателен.

7. Если пользователь хочет изменить код,
   добавить функцию, исправить ошибку или
   изменить существующую функциональность,
   ОБЯЗАТЕЛЬНО добавь "edit".

8. После "edit" ОБЯЗАТЕЛЬНО должен идти
   "validate".

9. Не добавляй Git, если пользователь
   явно не просил использовать Git.

10. Не добавляй terminal-команды без необходимости.

11. Если действие относится к конкретному файлу,
    ОБЯЗАТЕЛЬНО укажи "target".

12. Для действия "search"
    ОБЯЗАТЕЛЬНО укажи "query".

13. Если действие является "command",
    ОБЯЗАТЕЛЬНО укажи "command".

14. Для действия "git"
    ОБЯЗАТЕЛЬНО укажи "command".

15. Для действия "validate"
    НЕ указывай target или command.

16. Каждый шаг должен быть конкретным.

17. Шаги должны идти в правильном порядке.

18. Не выполняй действия самостоятельно.

19. Не пиши код.

20. Отвечай только корректным JSON.

21. Не используй Markdown.

22. "expected_result" должен соответствовать
    реальной цели пользователя.

23. "verification" должен описывать,
    как проверить результат.

24. Каждый шаг ОБЯЗАТЕЛЬНО должен содержать
    поле "details".

25. "details" должно объяснять исполнителю,
    что именно нужно сделать на этом шаге.

26. Для "search" details должны объяснять,
    что именно необходимо найти.

27. Для "read" details должны описывать,
    какую информацию необходимо получить
    из файла.

28. Для "analyze" details должны описывать,
    что именно необходимо проанализировать.

29. Для "edit" details должны описывать,
    какое изменение необходимо выполнить.

30. Для "edit" НЕ указывай old_text и new_text.
    Они будут определены отдельным этапом
    подготовки изменения.

31. Для "command" details должны объяснять,
    зачем выполняется команда.

32. Для "validate" details должны объяснять,
    какой результат необходимо проверить.

33. Не утверждай, что конкретная ошибка существует,
    если пользователь её не указал и она ещё
    не была обнаружена.

34. Если задача требует сначала найти проблему
    или конкретный элемент проекта,
    сначала используй "search" или "analyze".

35. Не добавляй validate, если задача не требует
    изменения и проверки результата.

36. Для поиска функции используй в поле "query"
    определение функции в формате:

    "def имя_функции"

37. Для поиска класса используй определение класса
    в формате:

    "class ИмяКласса"

38. Если пользователь просит проанализировать
    конкретную функцию, search должен искать
    именно её определение, а не просто имя.

39. Если после search необходимо определить,
    в каком файле находится найденный объект,
    следующий read должен использовать файл,
    найденный на предыдущем шаге.

40. Не придумывай название файла, если оно ещё
    неизвестно и должно быть найдено через search.

41. Если запрос содержит одновременно:
    - просьбу найти конкретную функцию;
    - известное имя файла;
    - последующий анализ или изменение функции,

    ОБЯЗАТЕЛЬНА последовательность:

    search → read → analyze → edit → validate

42. Если присутствует search для конкретной функции,
    search должен идти раньше read и analyze.

43. Если присутствуют search и read,
    read должен идти после search.

44. Если присутствуют read и analyze,
    analyze должен идти после read.

45. Если присутствует edit,
    validate должен идти после edit.

ФОРМАТ ШАГА ПОИСКА:

{{
    "id": 1,
    "description": "Найти функцию process",
    "action": "search",
    "query": "def process",
    "details": "Найти определение функции process во всех файлах проекта и определить файл, в котором она находится"
}}

ФОРМАТ ШАГА ЧТЕНИЯ:

{{
    "id": 2,
    "description": "Прочитать найденный файл",
    "action": "read",
    "target": "tools/agent.py",
    "details": "Получить содержимое файла, в котором найдена функция process, для дальнейшего анализа"
}}

ФОРМАТ ШАГА АНАЛИЗА:

{{
    "id": 3,
    "description": "Проанализировать функцию process",
    "action": "analyze",
    "target": "tools/agent.py",
    "details": "Проанализировать функцию process и определить её назначение, логику работы и потенциальные проблемы"
}}

ФОРМАТ ШАГА ИЗМЕНЕНИЯ:

{{
    "id": 4,
    "description": "Исправить найденную проблему",
    "action": "edit",
    "target": "tools/agent.py",
    "details": "Исправить проблему, обнаруженную на предыдущем этапе анализа"
}}

ФОРМАТ ШАГА КОМАНДЫ:

{{
    "id": 5,
    "description": "Проверить синтаксис",
    "action": "command",
    "command": "python -m py_compile tools/agent.py",
    "details": "Проверить, что после изменения файл не содержит синтаксических ошибок"
}}

ФОРМАТ ШАГА ПРОВЕРКИ:

{{
    "id": 6,
    "description": "Проверить результат",
    "action": "validate",
    "details": "Проверить результат внесённых изменений с помощью встроенной проверки проекта"
}}

ФОРМАТ GIT-ШАГА:

{{
    "id": 7,
    "description": "Проверить статус Git",
    "action": "git",
    "command": "git status",
    "details": "Проверить состояние рабочего дерева после изменений"
}}

ОБЩИЙ ФОРМАТ:

{{
    "steps": [
        {{
            "id": 1,
            "description": "...",
            "action": "search",
            "query": "...",
            "details": "..."
        }}
    ],
    "verification": "...",
    "expected_result": "..."
}}

ВАЖНО:

- search требует query.
- analyze, read и edit требуют target.
- command и git требуют command.
- validate НЕ требует target.
- validate НЕ требует command.
- Каждый шаг обязан иметь details.
- Не добавляй одновременно target и query,
  если они не нужны.
- Не добавляй одновременно target и command,
  если они не нужны.
- Не придумывай конкретные ошибки,
  если они ещё не обнаружены.
- Не придумывай файл, если его необходимо
  сначала найти через search.
- Не добавляй Git без запроса пользователя.
- Верни только JSON.
"""

        response = self.ai.ask(
            prompt,
            add_to_history=False
        )

        try:
            plan = json.loads(response)

        except json.JSONDecodeError:
            return {
                "success": False,
                "message": (
                    "Планировщик вернул "
                    "некорректный JSON."
                ),
                "raw_response": response,
            }

        if not isinstance(plan, dict):
            return {
                "success": False,
                "message": (
                    "План имеет некорректный формат."
                ),
            }

        steps = plan.get("steps")

        if not isinstance(steps, list) or not steps:
            return {
                "success": False,
                "message": (
                    "В плане отсутствуют шаги."
                ),
            }

        validation_error = self._validate_plan(
            steps,
            user_request
        )

        if validation_error:
            return {
                "success": False,
                "message": validation_error,
                "raw_plan": plan,
            }

        self.current_request = user_request
        self.current_plan = plan
        self.current_research_context = research_context
        self.current_status = "created"
        self.current_step = 0

        return {
            "success": True,
            "request": self.current_request,
            "status": self.current_status,
            "current_step": self.current_step,
            "plan": self.current_plan,
        }

    def _validate_plan(self, steps, user_request=""):
        """
        Проверяет структуру и последовательность плана.
        """

        has_edit = False
        edit_index = None

        for index, step in enumerate(steps):

            if not isinstance(step, dict):
                return (
                    f"Шаг {index + 1} имеет "
                    f"некорректный формат."
                )

            action = step.get("action")
            description = step.get("description")
            details = step.get("details")

            if action not in self.ALLOWED_ACTIONS:
                return (
                    f"Недопустимое действие: "
                    f"{action}"
                )

            if not description:
                if details:
                    step["description"] = details
                else:
                    step["description"] = (
                        f"Выполнить действие: {action}"
                    )

            if not details:
                step["details"] = (
                    step["description"]
                )

            # =============================================
            # Search
            # =============================================

            if action == "search":

                query = step.get("query")

                if not query:
                    return (
                        f"Шаг {index + 1}: "
                        "для действия 'search' "
                        "не указан query."
                    )

                if step.get("target"):
                    return (
                        f"Шаг {index + 1}: "
                        "search не должен содержать "
                        "target."
                    )

                if step.get("command"):
                    return (
                        f"Шаг {index + 1}: "
                        "search не должен содержать "
                        "command."
                    )

            # =============================================
            # Analyze / Read / Edit
            # =============================================

            if action in {
                "analyze",
                "read",
                "edit",
            }:

                target = step.get("target")

                if not target:
                    return (
                        f"Шаг {index + 1}: "
                        f"для действия '{action}' "
                        "не указан target."
                    )

            # =============================================
            # Command / Git
            # =============================================

            if action in {
                "command",
                "git",
            }:

                command = step.get("command")

                if not command:
                    return (
                        f"Шаг {index + 1}: "
                        f"для действия '{action}' "
                        "не указана команда."
                    )

            # =============================================
            # Validate
            # =============================================

            if action == "validate":

                if step.get("target"):
                    return (
                        f"Шаг {index + 1}: "
                        "validate не должен содержать "
                        "target."
                    )

                if step.get("command"):
                    return (
                        f"Шаг {index + 1}: "
                        "validate не должен содержать "
                        "command."
                    )

            # =============================================
            # Edit
            # =============================================

            if action == "edit":

                has_edit = True
                edit_index = index

        # =============================================
        # Проверка последовательности поиска функции
        # =============================================

        function_match = re.search(
            r"(?:найди|найти)\s+"
            r"(?:функцию|метод)\s+"
            r"([A-Za-z_][A-Za-z0-9_]*)",
            user_request.lower()
        )

        if function_match:

            expected_function = function_match.group(1)

            search_indices = [
                index
                for index, step in enumerate(steps)
                if step.get("action") == "search"
            ]

            if not search_indices:
                return (
                    "Для запроса на поиск конкретной "
                    f"функции '{expected_function}' "
                    "план обязан содержать действие search."
                )

            search_index = search_indices[0]
            search_step = steps[search_index]

            expected_query = f"def {expected_function}"

            if search_step.get("query") != expected_query:
                return (
                    "Для поиска функции "
                    f"'{expected_function}' "
                    f"search должен использовать query "
                    f"'{expected_query}'."
                )

            for index, step in enumerate(steps):

                if step.get("action") in {
                    "read",
                    "analyze",
                } and index < search_index:

                    return (
                        "Для поиска функции действие "
                        "search должно идти раньше "
                        "read и analyze."
                    )

            read_indices = [
                index
                for index, step in enumerate(steps)
                if step.get("action") == "read"
            ]

            analyze_indices = [
                index
                for index, step in enumerate(steps)
                if step.get("action") == "analyze"
            ]

            if analyze_indices:

                analyze_index = analyze_indices[0]

                if not read_indices:
                    return (
                        "После поиска функции перед analyze "
                        "должен присутствовать read."
                    )

                read_index = read_indices[0]

                if read_index < search_index:
                    return (
                        "После search должен идти read."
                    )

                if analyze_index < read_index:
                    return (
                        "После read должен идти analyze."
                    )

        # =============================================
        # После edit должен быть validate
        # =============================================

        if has_edit:

            validate_after_edit = False

            for step in steps[edit_index + 1:]:

                if step.get("action") == "validate":

                    validate_after_edit = True
                    break

            if not validate_after_edit:
                return (
                    "После edit отсутствует "
                    "действие validate."
                )

        return None

    def get_current_plan(self):

        if not self.current_plan:

            return {
                "success": False,
                "message": (
                    "Текущий план отсутствует."
                ),
            }

        return {
            "success": True,
            "request": self.current_request,
            "status": self.current_status,
            "current_step": self.current_step,
            "plan": self.current_plan,
        }

    def clear_plan(self):

        self.current_plan = None
        self.current_request = None
        self.current_research_context = None
        self.current_status = None
        self.current_step = 0

        return {
            "success": True,
            "message": (
                "Текущий план удалён."
            ),
        }

    # =========================================================================
    # Методы Task Planner v2: программное создание, валидация и Teamwork Pipeline
    # =========================================================================

    def create_structured_plan(
        self,
        steps: List[Union[PlanStep, Dict[str, Any]]],
        user_request: str = "",
        goal: Optional[str] = None,
        expected_result: Optional[str] = None,
        verification: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> TaskPlan:
        """
        Программно создаёт и валидирует структурированный TaskPlan v2 без вызова LLM.
        Сохраняет план как current_plan.
        """
        final_goal = goal if goal is not None else user_request
        plan = TaskPlan(
            steps=steps,
            goal=final_goal,
            expected_result=expected_result,
            verification=verification,
            metadata=metadata
        )
        is_ok, err = plan.validate()
        if not is_ok:
            raise ValueError(f"Ошибка валидации созданного плана: {err}")

        self.current_request = final_goal
        self.current_plan = plan.to_dict()
        self.current_status = "created"
        self.current_step = 0
        return plan

    def validate_plan(
        self,
        plan_or_steps: Union[TaskPlan, Dict[str, Any], List[Any]]
    ) -> Tuple[bool, Optional[str]]:
        """
        Публичный метод валидации плана (TaskPlan, dict или список шагов).
        """
        if isinstance(plan_or_steps, TaskPlan):
            return plan_or_steps.validate()
        elif isinstance(plan_or_steps, dict):
            try:
                p = TaskPlan.from_dict(plan_or_steps)
                return p.validate()
            except Exception as ex:
                return False, f"Ошибка разбора структуры плана: {ex}"
        elif isinstance(plan_or_steps, list):
            try:
                p = TaskPlan(steps=plan_or_steps)
                return p.validate()
            except Exception as ex:
                return False, f"Ошибка разбора списка шагов: {ex}"
        return False, f"Неподдерживаемый тип плана: {type(plan_or_steps)}"

    def to_pipeline_steps(
        self,
        plan: Optional[Union[TaskPlan, Dict[str, Any]]] = None,
        registry=None
    ) -> List[Any]:
        """
        Преобразует переданный план (или current_plan) в список PipelineStep.
        """
        target = plan or self.current_plan
        if not target:
            raise ValueError("План не задан и current_plan отсутствует.")
        if not isinstance(target, TaskPlan):
            target = TaskPlan.from_dict(target)
        return target.to_pipeline_steps(registry=registry)

    def to_pipeline(
        self,
        plan: Optional[Union[TaskPlan, Dict[str, Any]]] = None,
        registry=None,
        stop_on_error: bool = True
    ) -> Any:
        """
        Преобразует переданный план (или current_plan) в готовый TeamworkPipeline.
        """
        target = plan or self.current_plan
        if not target:
            raise ValueError("План не задан и current_plan отсутствует.")
        if not isinstance(target, TaskPlan):
            target = TaskPlan.from_dict(target)
        return target.to_pipeline(registry=registry, stop_on_error=stop_on_error)