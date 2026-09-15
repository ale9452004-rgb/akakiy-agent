import json

from ollama_client import OllamaClient
from tools.registry import get_tools_description
from tools.dispatcher import dispatch
from tools.files import read_file


class Agent:
    def __init__(self):
        self.ai = OllamaClient()

    def choose_tool(self, user_input):
        tools = get_tools_description()

        prompt = f"""
Ты — диспетчер инструментов локального ИИ-ассистента Акакия.

Доступные инструменты:

{tools}

Запрос пользователя:

{user_input}

Выбери подходящий инструмент.

Для read_file:
{{
    "tool": "read_file",
    "arguments": {{
        "filename": "имя файла"
    }}
}}

Для analyze_file:
{{
    "tool": "analyze_file",
    "arguments": {{
        "filename": "имя файла"
    }}
}}

Для write_file:
{{
    "tool": "write_file",
    "arguments": {{
        "filename": "имя файла",
        "content": "полное новое содержимое файла"
    }}
}}

Для edit_file:
{{
    "tool": "edit_file",
    "arguments": {{
        "filename": "имя файла"
    }}
}}

Для run_command:
{{
    "tool": "run_command",
    "arguments": {{
        "command": "PowerShell команда"
    }}
}}

Для list_files:
{{
    "tool": "list_files",
    "arguments": {{}}
}}

Для validate_project:
{{
    "tool": "validate_project",
    "arguments": {{}}
}}

Для git_status:
{{
    "tool": "git_status",
    "arguments": {{}}
}}

Для git_diff:
{{
    "tool": "git_diff",
    "arguments": {{}}
}}

Для git_commit:
{{
    "tool": "git_commit",
    "arguments": {{
        "message": "краткое описание изменений"
    }}
}}

Если инструмент не нужен:

{{
    "tool": null,
    "arguments": {{}}
}}

Правила:

1. Используй только инструменты из списка.
2. Не придумывай новые инструменты.
3. Для read_file используй аргумент filename.
4. Для analyze_file используй аргумент filename.
5. Для write_file используй filename и content.
6. Для edit_file используй только filename на первом этапе.
7. Для run_command используй command.
8. Для git_commit используй message.
9. Не выполняй команды самостоятельно.
10. Не добавляй пояснения.
11. Отвечай только валидным JSON.
"""

        answer = self.ai.ask(
            prompt,
            add_to_history=False
        )

        try:
            cleaned = answer.strip()

            if cleaned.startswith("```"):
                cleaned = cleaned.replace("```json", "")
                cleaned = cleaned.replace("```", "")
                cleaned = cleaned.strip()

            decision = json.loads(cleaned)

        except json.JSONDecodeError:
            return {
                "tool": None,
                "arguments": {}
            }

        self.normalize_arguments(
            decision,
            user_input
        )

        return decision

    def prepare_edit(self, filename, user_request):
        """
        Читает текущий файл и просит модель
        подготовить точечное изменение.
        """

        content, error = read_file(filename)

        if error:
            return {
                "success": False,
                "message": error
            }

        prompt = f"""
Ты редактируешь файл проекта.

Имя файла:
{filename}

Запрос пользователя:
{user_request}

Текущее содержимое файла:

----- НАЧАЛО ФАЙЛА -----

{content}

----- КОНЕЦ ФАЙЛА -----

Подготовь ТОЧЕЧНОЕ изменение существующего файла.

Верни строго JSON:

{{
    "old_text": "точный существующий фрагмент",
    "new_text": "новый фрагмент"
}}

Правила:

1. old_text должен существовать в текущем файле ДО изменения.
2. old_text должен быть максимально небольшим, но однозначным.
3. old_text должен совпадать с исходным текстом символ в символ.
4. Не используй номера строк вместо текста.
5. Не переписывай весь файл.
6. new_text должен содержать только замену old_text.
7. Не добавляй пояснения.
8. Отвечай только валидным JSON.
"""

        answer = self.ai.ask(
            prompt,
            add_to_history=False
        )

        try:
            cleaned = answer.strip()

            if cleaned.startswith("```"):
                cleaned = cleaned.replace("```json", "")
                cleaned = cleaned.replace("```", "")
                cleaned = cleaned.strip()

            change = json.loads(cleaned)

        except json.JSONDecodeError:
            return {
                "success": False,
                "message": "Qwen вернул некорректный JSON для изменения файла."
            }

        old_text = change.get("old_text")
        new_text = change.get("new_text")

        if not isinstance(old_text, str):
            return {
                "success": False,
                "message": "Qwen не вернул корректный old_text."
            }

        if not isinstance(new_text, str):
            return {
                "success": False,
                "message": "Qwen не вернул корректный new_text."
            }

        return {
            "success": True,
            "filename": filename,
            "old_text": old_text,
            "new_text": new_text
        }

    def normalize_arguments(self, decision, user_input):
        """
        Исправляет распространённые варианты аргументов,
        которые может вернуть модель.
        """

        tool_name = decision.get("tool")
        arguments = decision.get("arguments", {})

        if not isinstance(arguments, dict):
            decision["arguments"] = {}
            return

        if tool_name in [
            "read_file",
            "analyze_file",
            "write_file",
            "edit_file"
        ]:

            if "file" in arguments and "filename" not in arguments:
                arguments["filename"] = arguments.pop("file")

            if "path" in arguments and "filename" not in arguments:
                arguments["filename"] = arguments.pop("path")

        if tool_name == "run_command":

            if "cmd" in arguments and "command" not in arguments:
                arguments["command"] = arguments.pop("cmd")

        if tool_name == "write_file":

            if "text" in arguments and "content" not in arguments:
                arguments["content"] = arguments.pop("text")

            if "code" in arguments and "content" not in arguments:
                arguments["content"] = arguments.pop("code")

        if tool_name == "git_commit":

            if "message" not in arguments:
                arguments["message"] = user_input

        decision["arguments"] = arguments

    def process(self, user_input):
        decision = self.choose_tool(user_input)

        tool_name = decision.get("tool")
        arguments = decision.get("arguments", {})

        if not tool_name:
            return {
                "type": "chat",
                "answer": self.ai.ask(user_input)
            }

        # Специальный двухэтапный процесс редактирования
        if tool_name == "edit_file":

            filename = arguments.get("filename")

            if not filename:
                return {
                    "type": "tool",
                    "tool": "edit_file",
                    "result": {
                        "success": False,
                        "message": "Не указано имя файла."
                    }
                }

            prepared = self.prepare_edit(
                filename,
                user_input
            )

            if not prepared.get("success"):
                return {
                    "type": "tool",
                    "tool": "edit_file",
                    "result": prepared
                }

            result = dispatch(
                "edit_file",
                filename=prepared["filename"],
                old_text=prepared["old_text"],
                new_text=prepared["new_text"]
            )

            return {
                "type": "tool",
                "tool": "edit_file",
                "result": result
            }

        result = dispatch(
            tool_name,
            **arguments
        )

        return {
            "type": "tool",
            "tool": tool_name,
            "result": result
        }