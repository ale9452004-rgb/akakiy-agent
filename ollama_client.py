import requests


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3:8b"


class OllamaClient:
    def __init__(self):
        self.messages = [
            {
                "role": "system",
                "content": (
                    "Ты Акакий — локальный ИИ-ассистент пользователя. "
                    "Отвечай на русском языке."
                )
            }
        ]

    def send_chat(self, messages, tools=None):
        """
        Отправляет список сообщений в Ollama /api/chat.
        """
        payload = {
            "model": MODEL,
            "messages": messages,
            "stream": False
        }

        if tools is not None:
            payload["tools"] = tools

        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=120
        )

        response.raise_for_status()

        data = response.json()
        message = data.get("message", {})
        answer = message.get("content", "")
        tool_calls = message.get("tool_calls") or []

        return {
            "content": answer,
            "tool_calls": tool_calls,
            "message": message
        }

    def send_tool_step(self, turn_messages, tools=None):
        """
        Отправляет сообщения текущего хода (turn_messages) вместе с историей сообщений.
        """
        messages = self.messages + turn_messages
        return self.send_chat(messages, tools=tools)

    def commit_turn(self, turn_messages):
        """
        Атомарно фиксирует завершённый диалоговый ход в истории сообщений.
        """
        self.messages.extend(turn_messages)

    def ask(self, user_message, add_to_history=True, tools=None):
        request_messages = self.messages.copy()

        request_messages.append({
            "role": "user",
            "content": user_message
        })

        result = self.send_chat(request_messages, tools=tools)
        answer = result["content"]
        tool_calls = result["tool_calls"]

        if tools is None:
            if add_to_history:
                self.messages.append({
                    "role": "user",
                    "content": user_message
                })

                self.messages.append({
                    "role": "assistant",
                    "content": answer
                })

            return answer

        if add_to_history and not tool_calls:
            self.messages.append({
                "role": "user",
                "content": user_message
            })

            self.messages.append({
                "role": "assistant",
                "content": answer
            })

        return result