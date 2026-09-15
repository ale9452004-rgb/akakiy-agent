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

    def ask(self, user_message, add_to_history=True):
        request_messages = self.messages.copy()

        request_messages.append({
            "role": "user",
            "content": user_message
        })

        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": request_messages,
                "stream": False
            },
            timeout=120
        )

        response.raise_for_status()

        data = response.json()
        answer = data["message"]["content"]

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