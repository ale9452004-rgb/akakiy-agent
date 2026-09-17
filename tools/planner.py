from ollama_client import OllamaClient
import json


class Planner:
    """
    Создаёт и хранит текущий структурированный план выполнения задачи.

    Планирование не изменяет файлы и не выполняет команды.
    """

    ALLOWED_ACTIONS = {
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

"analyze"
— анализ проекта, архитектуры или проблемы.

"read"
— чтение конкретного файла.

"edit"
— изменение конкретного файла.

"command"
— выполнение конкретной команды.

"validate"
— проверка результата.

"git"
— операция Git.

СТРОГИЕ ПРАВИЛА:

1. Сначала определи, чего хочет пользователь.

2. Если пользователь хочет только анализ,
   поиск ошибок или получение информации,
   НЕ добавляй "edit".

3. Если пользователь хочет изменить код,
   добавить функцию, исправить ошибку или
   изменить существующую функциональность,
   ОБЯЗАТЕЛЬНО добавь "edit".

4. После "edit" ОБЯЗАТЕЛЬНО должен идти
   "validate".

5. Не добавляй Git, если пользователь
   явно не просил использовать Git.

6. Не добавляй terminal-команды без необходимости.

7. Если действие относится к конкретному файлу,
   ОБЯЗАТЕЛЬНО укажи "target".

8. Если действие является командой,
   ОБЯЗАТЕЛЬНО укажи "command".

9. Не придумывай названия файлов,
   которых ты не знаешь.

10. Если точный файл неизвестен,
    сначала используй "analyze".

11. Каждый шаг должен быть конкретным.

12. Шаги должны идти в правильном порядке.

13. Не выполняй действия самостоятельно.

14. Не пиши код.

15. Отвечай только корректным JSON.

16. Не используй Markdown.

17. "expected_result" должен соответствовать
    реальной цели пользователя.

18. "verification" должен описывать,
    как проверить результат.

19. Каждый шаг ОБЯЗАТЕЛЬНО должен содержать
    поле "details".

20. "details" должно объяснять исполнителю,
    что именно нужно сделать на этом шаге.

21. Для "analyze" details должны описывать,
    что именно необходимо исследовать.

22. Для "read" details должны описывать,
    какую информацию необходимо получить
    из файла.

23. Для "edit" details должны описывать,
    какое изменение необходимо выполнить.
    НЕ указывай old_text и new_text.
    Они будут определены отдельным этапом
    подготовки изменения.

24. Для "command" details должны объяснять,
    зачем выполняется команда.

25. Для "validate" details должны объяснять,
    какой именно результат необходимо проверить.

26. Не утверждай, что конкретная ошибка существует,
    если пользователь её не указал и она ещё
    не была обнаружена.

27. Если задача требует сначала найти проблему,
    сначала используй analyze или read.

ФОРМАТ ШАГА:

Для анализа:

{{
    "id": 1,
    "description": "Проанализировать файл",
    "action": "analyze",
    "target": "main.py",
    "details": "Найти потенциальные ошибки и проблемные участки в файле"
}}

Для чтения:

{{
    "id": 2,
    "description": "Прочитать файл",
    "action": "read",
    "target": "main.py",
    "details": "Получить содержимое файла для дальнейшего анализа"
}}

Для изменения:

{{
    "id": 3,
    "description": "Исправить найденную проблему",
    "action": "edit",
    "target": "main.py",
    "details": "Исправить проблему, обнаруженную на предыдущем этапе анализа"
}}

Для команды:

{{
    "id": 4,
    "description": "Проверить синтаксис",
    "action": "command",
    "command": "python -m py_compile main.py",
    "details": "Проверить, что после изменения файл не содержит синтаксических ошибок"
}}

Для проверки:

{{
    "id": 5,
    "description": "Проверить результат",
    "action": "validate",
    "details": "Убедиться, что исходная проблема устранена"
}}

Для Git:

{{
    "id": 6,
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
            "action": "analyze",
            "target": "...",
            "details": "..."
        }}
    ],
    "verification": "...",
    "expected_result": "..."
}}

Важно:

- У "analyze", "read" и "edit" используй "target".
- У "command" и "git" используй "command".
- У "validate" target и command не обязательны.
- Каждый шаг обязан иметь "details".
- Не добавляй одновременно target и command,
  если они не нужны.
- Если точный target неизвестен, сначала
  используй analyze.
- Не придумывай конкретные ошибки,
  если они ещё не обнаружены.
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
                "message": "Планировщик вернул некорректный JSON.",
                "raw_response": response,
            }

        if not isinstance(plan, dict):
            return {
                "success": False,
                "message": "План имеет некорректный формат.",
            }

        steps = plan.get("steps")

        if not isinstance(steps, list) or not steps:
            return {
                "success": False,
                "message": "В плане отсутствуют шаги.",
            }

        validation_error = self._validate_plan(
            steps
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

    def _validate_plan(self, steps):
        """
        Проверяет структуру плана
        и восстанавливает отсутствующие описания.
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

            # Если Qwen не вернул description,
            # создаём его автоматически.
            if not description:
                if details:
                    step["description"] = details
                else:
                    step["description"] = (
                        f"Выполнить действие: {action}"
                    )

            # Если details отсутствует,
            # используем description как details.
            if not details:
                step["details"] = step["description"]

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
                        f"не указан target."
                    )

            if action in {
                "command",
                "git",
            }:
                command = step.get("command")

                if not command:
                    return (
                        f"Шаг {index + 1}: "
                        f"для действия '{action}' "
                        f"не указана команда."
                    )

            if action == "edit":
                has_edit = True
                edit_index = index

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
        """
        Возвращает текущий план.
        """

        if not self.current_plan:
            return {
                "success": False,
                "message": "Текущий план отсутствует.",
            }

        return {
            "success": True,
            "request": self.current_request,
            "status": self.current_status,
            "current_step": self.current_step,
            "plan": self.current_plan,
        }

    def clear_plan(self):
        """
        Удаляет текущий план.
        """

        self.current_plan = None
        self.current_request = None
        self.current_status = None
        self.current_step = 0

        return {
            "success": True,
            "message": "Текущий план удалён.",
        }