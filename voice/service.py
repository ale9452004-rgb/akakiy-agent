"""
Координатор голосового сеанса (VoiceService).
Оркестрирует полный конвейер:
Микрофон -> STT (Vosk) -> Agent.process() -> Cleaner -> TTS (pyttsx3 / SAPI).
Передает события состояний и громкости в GUI через потокобезопасный event_sink.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from voice.cleaner import clean_for_speech
from voice.stt import SpeechToTextEngine
from voice.tts import TextToSpeechEngine

logger = logging.getLogger(__name__)


class VoiceService:
    """
    Высокоуровневый сервис голосового управления Акакием.
    Изолирует аудио-потоки от GUI и логики Agent.
    """

    def __init__(
        self,
        agent: Optional[Any] = None,
        event_sink: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        model_path: Optional[str] = None
    ):
        self.agent = agent
        self.event_sink = event_sink
        self.stt = SpeechToTextEngine(model_path=model_path)
        self.tts = TextToSpeechEngine()
        self._state = "idle"
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._session_thread: Optional[threading.Thread] = None

    def emit(self, event_type: str, data: Optional[Dict[str, Any]] = None):
        """Отправляет событие в интерфейс (GUI event queue)."""
        if self.event_sink and callable(self.event_sink):
            try:
                self.event_sink(event_type, data or {})
            except Exception as e:
                logger.warning(f"Ошибка отправки события {event_type}: {e}")

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, new_state: str):
        with self._lock:
            self._state = new_state
        self.emit("voice_state", {"state": new_state})

    def is_busy(self) -> bool:
        with self._lock:
            return self._state in ("listening", "thinking", "speaking")

    def start_session(self) -> bool:
        """
        Запускает один цикл голосового диалога:
        Слушает фразу -> распознаёт -> передаёт Агенту -> озвучивает ответ.
        """
        if self.is_busy():
            logger.info("Голосовой сеанс уже активен, повторный запуск пропущен.")
            return False

        self._stop_event.clear()
        self._session_thread = threading.Thread(
            target=self._run_voice_pipeline,
            daemon=True,
            name="Akakiy-VoiceSession-Thread"
        )
        self._session_thread.start()
        return True

    def stop_session(self):
        """Останавливает текущую запись или воспроизведение."""
        self._stop_event.set()
        self.tts.stop()
        self._set_state("idle")

    def speak_text(self, text: str, on_finish: Optional[Callable[[], None]] = None):
        """Прямой вызов озвучивания произвольного текста."""
        clean = clean_for_speech(text)
        if not clean:
            if on_finish:
                on_finish()
            return

        self._set_state("speaking")

        def _done():
            self._set_state("idle")
            if on_finish and callable(on_finish):
                on_finish()

        self.tts.speak(clean, on_finish=_done)

    def _run_voice_pipeline(self):
        """Основной рабочий цикл голосового взаимодействия."""
        try:
            # 1. Захват речи (listening)
            self._set_state("listening")
            recognized_text, err = self.stt.listen_phrase(
                timeout=8.0,
                phrase_time_limit=14.0,
                on_level_callback=lambda lvl: self.emit("voice_audio_level", {"level": lvl}),
                stop_event=self._stop_event
            )

            if self._stop_event.is_set():
                self._set_state("idle")
                return

            if err:
                logger.error(f"Ошибка распознавания: {err}")
                self.emit("voice_error", {"message": err})
                self._set_state("error")
                time.sleep(1.0)
                self._set_state("idle")
                return

            recognized_text = recognized_text.strip()
            if not recognized_text:
                logger.info("Речь не обнаружена (тишина или таймаут).")
                self._set_state("idle")
                return

            # 2. Передача распознанного текста в GUI и Agent
            self.emit("voice_recognized", {"text": recognized_text})

            # 3. Интеллектуальная обработка (thinking)
            self._set_state("thinking")

            if self.agent:
                result_payload = self.agent.process(recognized_text)
            else:
                result_payload = {
                    "type": "chat",
                    "answer": f"Распознано: {recognized_text}"
                }

            if self._stop_event.is_set():
                self._set_state("idle")
                return

            # Передаем итоговый результат в GUI для отображения
            self.emit("voice_agent_result", {"payload": result_payload, "query": recognized_text})

            # 4. Извлечение текста для озвучки
            raw_answer = self._extract_speech_text(result_payload)
            clean_speech = clean_for_speech(raw_answer)

            # 5. Озвучивание (speaking)
            if clean_speech and not self._stop_event.is_set():
                self._set_state("speaking")
                speech_done = threading.Event()

                def _finish_tts():
                    speech_done.set()

                self.tts.speak(clean_speech, on_finish=_finish_tts)

                # Ожидаем завершения речи или сигнала прерывания
                while not speech_done.is_set() and not self._stop_event.is_set():
                    time.sleep(0.05)

        except Exception as ex:
            logger.error(f"Непредвиденная ошибка в голосовом конвейере: {ex}", exc_info=True)
            self.emit("voice_error", {"message": f"Ошибка голосового модуля: {ex}"})
            self._set_state("error")
            time.sleep(1.0)

        finally:
            self._set_state("idle")

    def _extract_speech_text(self, payload: Any) -> str:
        """Извлекает ключевой голосовой ответ из контракта Agent."""
        if not isinstance(payload, dict):
            return str(payload)

        p_type = payload.get("type")
        if p_type == "chat":
            return payload.get("answer", "")

        elif p_type == "plan":
            # Для планов возвращаем summary или message
            return payload.get("summary") or payload.get("message") or "План успешно выполнен."

        elif p_type == "tool":
            tool_name = payload.get("tool", "")
            res = payload.get("result")
            if isinstance(res, dict):
                inner = res.get("result", res)
                if isinstance(inner, dict):
                    if "files" in inner and "count" in inner:
                        return f"В проекте найдено {inner['count']} файлов."
                    if "path" in inner and "exists" in inner:
                        status = "найден" if inner["exists"] else "не найден"
                        return f"Файл {inner.get('path', '')} {status}."
                    if "message" in inner:
                        return inner["message"]
                if "message" in res:
                    return res["message"]
                return f"Инструмент {tool_name} выполнен успешно."
            return str(res or f"Инструмент {tool_name} выполнен.")

        elif p_type == "error":
            return payload.get("error") or "Произошла ошибка при обработке запроса."

        return payload.get("message") or payload.get("answer") or "Запрос обработан."

    def shutdown(self):
        """Останавливает все потоки сервиса."""
        self.stop_session()
        self.tts.shutdown()
