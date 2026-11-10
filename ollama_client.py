import base64
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import requests


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3:8b"
DEFAULT_VISION_MODEL = "qwen3-vl:4b"


def encode_images_base64(images: Union[str, Path, bytes, bytearray, List[Any], tuple]) -> List[str]:
    """
    Кодирует одно или несколько изображений (пути к файлам или bytes) в base64-строки
    для мультимодального Ollama /api/chat.
    """
    if images is None:
        return []
    if isinstance(images, (str, Path, bytes, bytearray)):
        items = [images]
    else:
        items = list(images)

    encoded: List[str] = []
    for item in items:
        if isinstance(item, (bytes, bytearray)):
            encoded.append(base64.b64encode(bytes(item)).decode("ascii"))
        elif isinstance(item, (str, Path)):
            p = Path(item)
            if not p.is_file():
                raise FileNotFoundError(f"Изображение для Vision-запроса не найдено: {p}")
            encoded.append(base64.b64encode(p.read_bytes()).decode("ascii"))
        else:
            raise TypeError(f"Неподдерживаемый тип изображения: {type(item).__name__}")
    return encoded


class OllamaClient:
    def __init__(self, max_history: int = 24, model: Optional[str] = None):
        self.max_history = max_history
        self.model = model or MODEL
        self.base_system_prompt = (
            "Ты Акакий — локальный ИИ-ассистент пользователя. "
            "Отвечай на русском языке."
        )
        self.messages = [
            {
                "role": "system",
                "content": self.base_system_prompt
            }
        ]

    def set_system_prompt(self, content: str):
        """Обновляет системный промпт модели (включая факты из долговременной памяти)."""
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0]["content"] = content
        else:
            self.messages.insert(0, {"role": "system", "content": content})

    def get_system_prompt(self) -> str:
        """Возвращает текущий системный промпт."""
        if self.messages and self.messages[0].get("role") == "system":
            return self.messages[0].get("content", "")
        return self.base_system_prompt

    def _trim_history(self):
        """Ограничивает историю сообщений скользящим окном, сохраняя системный промпт."""
        if len(self.messages) > self.max_history:
            system_msg = self.messages[0] if (self.messages and self.messages[0].get("role") == "system") else None
            recent = self.messages[-(self.max_history - 1):]
            if system_msg:
                self.messages = [system_msg] + [m for m in recent if m.get("role") != "system"]
            else:
                self.messages = recent

    def add_interaction(self, user_text: str, assistant_text: str):
        """Добавляет завершённый диалоговый ход в историю для сохранения контекста."""
        self.messages.append({
            "role": "user",
            "content": str(user_text)
        })
        self.messages.append({
            "role": "assistant",
            "content": str(assistant_text)
        })
        self._trim_history()

    def reset_history(self, keep_system: bool = True):
        """Очищает историю диалога текущей сессии."""
        if keep_system and self.messages and self.messages[0].get("role") == "system":
            self.messages = [self.messages[0]]
        else:
            self.messages = []

    def send_chat(
        self,
        messages,
        tools=None,
        model: Optional[str] = None,
        response_format: Optional[Union[str, Dict[str, Any]]] = None,
        timeout: int = 120,
    ):
        """
        Отправляет список сообщений в Ollama /api/chat.
        Поддерживает переопределение модели (например, vision-модели) и формата ответа.
        """
        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": False
        }

        if tools is not None:
            payload["tools"] = tools
        if response_format is not None:
            payload["format"] = response_format

        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=timeout
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

    def send_vision_query(
        self,
        prompt: str,
        images: Union[str, Path, bytes, bytearray, List[Any], tuple],
        model: Optional[str] = None,
        response_format: Optional[Union[str, Dict[str, Any]]] = None,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """
        Отправляет одиночный мультимодальный запрос к локальной Vision-модели Ollama.
        Не добавляет base64-изображения в диалоговую историю.
        """
        encoded = encode_images_base64(images)
        if not encoded:
            raise ValueError("Не переданы изображения для Vision-запроса.")

        eff_model = (model or DEFAULT_VISION_MODEL).strip() or DEFAULT_VISION_MODEL
        messages = [
            {
                "role": "user",
                "content": str(prompt or "").strip(),
                "images": encoded,
            }
        ]
        return self.send_chat(
            messages,
            tools=None,
            model=eff_model,
            response_format=response_format,
            timeout=timeout,
        )

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
        self._trim_history()

    def ask(self, user_message, add_to_history=True, tools=None, images=None, model: Optional[str] = None):
        request_messages = self.messages.copy()

        outgoing_msg: Dict[str, Any] = {
            "role": "user",
            "content": user_message
        }
        if images is not None:
            encoded = encode_images_base64(images)
            if encoded:
                outgoing_msg["images"] = encoded

        request_messages.append(outgoing_msg)

        if model is not None:
            result = self.send_chat(request_messages, tools=tools, model=model)
        else:
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
                self._trim_history()

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
            self._trim_history()

        return result