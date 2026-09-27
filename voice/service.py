"""
Координатор голосового сеанса (VoiceService).
Оркестрирует полный конвейер:
Микрофон -> STT (Vosk) -> Agent.process() -> Cleaner -> TTS (pyttsx3 / SAPI).
Передает события состояний и громкости в GUI через потокобезопасный event_sink.
"""

import logging
import re
import threading
import time
from typing import Any, Callable, Dict, Optional

from voice.cleaner import clean_for_speech
from voice.stt import SpeechToTextEngine, strip_wake_word
from voice.tts import TextToSpeechEngine
from voice.pipeline import (
    VoicePipeline,
    VoicePipelineResult,
    extract_speech_text,
    is_voice_exit_command,
    VOICE_EXIT_COMMANDS,
)

logger = logging.getLogger(__name__)


class VoiceService:
    """
    Высокоуровневый сервис голосового управления Акакием.
    Изолирует аудио-потоки от GUI и логики Agent.
    Оркестрирует сеанс непрерывного hands-free диалога (Continuous Conversation)
    через модульный голосовой конвейер VoicePipeline.
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
        self.pipeline = VoicePipeline(
            agent=self.agent,
            stt=self.stt,
            tts=self.tts,
            event_sink=self.emit
        )
        self._state = "idle"
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._finish_event = threading.Event()
        self._session_thread: Optional[threading.Thread] = None

    def _sync_pipeline(self):
        """Синхронизирует компоненты и коллбэки с VoicePipeline."""
        if hasattr(self, "pipeline") and self.pipeline:
            self.pipeline.agent = self.agent
            self.pipeline.stt = self.stt
            self.pipeline.tts = self.tts
            self.pipeline.event_sink = self.emit

    def emit(self, event_type: str, data: Optional[Dict[str, Any]] = None):
        """Отправляет событие в интерфейс (GUI event queue)."""
        if self.event_sink and callable(self.event_sink):
            try:
                self.event_sink(event_type, data or {})
            except Exception as e:
                logger.warning(f"Ошибка отправки события {event_type}: {e}")

    @property
    def state(self) -> str:
        if hasattr(self, "pipeline") and self.pipeline:
            return self.pipeline.state
        return self._state

    def _set_state(self, new_state: str):
        with self._lock:
            self._state = new_state
            if hasattr(self, "pipeline") and self.pipeline:
                self.pipeline._state = new_state
        self.emit("voice_state", {"state": new_state})

    @property
    def is_running(self) -> bool:
        """Проверяет, активен ли рабочий поток голосового сеанса."""
        return self._session_thread is not None and self._session_thread.is_alive()

    def is_busy(self) -> bool:
        with self._lock:
            if self._session_thread and self._session_thread.is_alive():
                return True
            curr_state = self.state
            return curr_state in ("listening", "thinking", "speaking")

    def start_session(self, continuous: bool = True) -> bool:
        """
        Запускает голосовой диалог:
        continuous=True: непрерывный hands-free диалог (listening -> thinking -> speaking -> listening).
        continuous=False: один шаг диалога (однократный запуск).
        """
        if self.is_busy():
            logger.info("Голосовой сеанс уже активен, повторный запуск пропущен.")
            return False

        if self._session_thread and self._session_thread.is_alive():
            self._session_thread.join(timeout=1.0)

        self._set_state("listening")
        self._stop_event.clear()
        self._finish_event.clear()
        self._session_thread = threading.Thread(
            target=self._run_voice_pipeline,
            args=(continuous,),
            daemon=True,
            name="Akakiy-VoiceSession-Thread"
        )
        self._session_thread.start()
        return True

    def stop_session(self):
        """Останавливает текущую запись или воспроизведение и завершает сеанс."""
        self._stop_event.set()
        self._finish_event.set()
        self.tts.stop()
        if self._session_thread and self._session_thread.is_alive():
            if threading.current_thread() != self._session_thread:
                self._session_thread.join(timeout=1.5)
        self._set_state("idle")

    def finish_listening(self):
        """Досрочно завершает текущую фазу записи фразы (Push-to-Talk release), передавая её на обработку."""
        self._finish_event.set()

    def speak_text(self, text: str, on_finish: Optional[Callable[[], None]] = None):
        """Прямой вызов озвучивания произвольного текста."""
        self._sync_pipeline()
        self.pipeline.speak(text, on_finish=on_finish)

    speak_phrase = speak_text

    def process_phrase(
        self,
        phrase: str,
        speak: bool = True,
        on_finish: Optional[Callable[[], None]] = None
    ) -> VoicePipelineResult:
        """Прямая обработка фразы через конвейер VoicePipeline."""
        self._sync_pipeline()
        return self.pipeline.process_phrase(
            phrase=phrase,
            speak=speak,
            stop_event=self._stop_event,
            on_finish=on_finish
        )

    def _run_voice_pipeline(self, continuous: bool = True):
        """
        Основной рабочий цикл голосового взаимодействия:
        listening -> thinking -> speaking -> listening ... (при continuous=True)
        Завершается по stop_event, голосовой команде выхода или ошибке аудиоустройства.
        """
        logger.info(f"Запущен рабочий цикл голосового диалога (continuous={continuous}).")
        self._sync_pipeline()

        try:
            while not self._stop_event.is_set():
                self._finish_event.clear()
                step_res = self.pipeline.run_step(
                    stop_event=self._stop_event,
                    finish_event=self._finish_event,
                    silence_threshold_seconds=1.0,
                    phrase_time_limit=25.0
                )

                if self._stop_event.is_set() or step_res.is_cancelled:
                    break

                if step_res.is_exit:
                    break

                if step_res.is_error and step_res.error:
                    err_lower = step_res.error.lower()
                    if any(e in err_lower for e in ("микрофон", "sounddevice", "input device", "device error", "no default")):
                        self.emit("voice_mode_toggle", {"enabled": False})
                        time.sleep(1.0)
                        break

                if step_res.is_empty:
                    continue

                if self._stop_event.is_set():
                    break

                # Акустическая пауза (0.35 с) для затухания реверберации колонок в комнате
                time.sleep(0.35)

                if not continuous:
                    break

        except Exception as ex:
            logger.error(f"Непредвиденная ошибка в голосовом конвейере: {ex}", exc_info=True)
            self.emit("voice_error", {"message": f"Ошибка голосового модуля: {ex}"})
            self._set_state("error")
            time.sleep(1.0)
        finally:
            self._set_state("idle")
            logger.info("Рабочий цикл непрерывного голосового диалога завершён.")

    def _extract_speech_text(self, payload: Any) -> str:
        """Извлекает ключевой голосовой ответ из контракта Agent."""
        return extract_speech_text(payload)

    def shutdown(self):
        """Останавливает все потоки сервиса."""
        self.stop_session()
        self.tts.shutdown()
