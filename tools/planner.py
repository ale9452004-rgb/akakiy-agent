from ollama_client import OllamaClient
import json
import re


class Planner:
    """
    Создаёт и хранит текущий структурированный план выполнения задачи.

    Планирование не изменяет файлы и не выполняет команды.
    """

    ALLOWED_ACTIONS = {
        "search",
        "analyze",
        "read",
        "edit",
        "command",
        "validate",
        "git",
    }

    def __init__(self):
        self.ai = OllamaClient()

        self.current_plan = None
        self.current_request = None
        self.current_status = None
        self.current_step = 0

    def create_plan(self, user_request):
        """
        Создаёт новый структурированный план
        и сохраняет его как текущий.
        """

        prompt = f"""
Ты — планировщик локального ИИ-ассистента Акакия.

Твоя задача — составить точный план выполнения
запроса пользователя.

Запрос пользователя:

{user_request}

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
        self.current_status = None
        self.current_step = 0

        return {
            "success": True,
            "message": (
                "Текущий план удалён."
            ),
        }