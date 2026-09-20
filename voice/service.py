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

logger = logging.getLogger(__name__)


VOICE_EXIT_COMMANDS = {
    "стоп",
    "хватит",
    "отмена",
    "выключи голос",
    "отключи голос",
    "выключить голос",
    "отключить голос",
    "выруби голос",
    "отключись",
    "пока",
    "до свидания",
    "заверши сеанс",
    "завершить сеанс",
    "заверши работу",
    "завершить работу",
    "отмена голоса",
    "выключить голосовой режим",
    "отключить голосовой режим",
}


def is_voice_exit_command(text: str) -> bool:
    """Определяет, является ли фраза командой отключения голосового режима."""
    import re
    cleaned = re.sub(r"[^\w\s]", "", text.lower()).strip()
    if cleaned in VOICE_EXIT_COMMANDS:
        return True
    exit_triggers = [
        "выключи голос",
        "отключи голос",
        "выключить голос",
        "отключить голос",
        "выруби голос",
        "заверши сеанс",
        "завершить сеанс",
        "выключить голосовой режим",
        "отключить голосовой режим",
    ]
    for trig in exit_triggers:
        if trig in cleaned:
            return True
    return False


class VoiceService:
    """
    Высокоуровневый сервис голосового управления Акакием.
    Изолирует аудио-потоки от GUI и логики Agent.
    Поддерживает непрерывный hands-free диалог (Continuous Conversation).
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
        self._finish_event = threading.Event()
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

        self._stop_event.clear()
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

    def _run_voice_pipeline(self, continuous: bool = True):
        """
        Основной рабочий цикл голосового взаимодействия:
        listening -> thinking -> speaking -> listening ... (при continuous=True)
        Завершается по stop_event, голосовой команде выхода или ошибке аудиоустройства.
        """
        logger.info(f"Запущен рабочий цикл голосового диалога (continuous={continuous}).")

        try:
            while not self._stop_event.is_set():
                # 1. Захват речи (listening)
                self._set_state("listening")
                self._finish_event.clear()
                recognized_text, err = self.stt.listen_phrase(
                    timeout=None,
                    phrase_time_limit=25.0,
                    silence_threshold_seconds=1.0,
                    on_level_callback=lambda lvl: self.emit("voice_audio_level", {"level": lvl}),
                    stop_event=self._stop_event,
                    finish_event=self._finish_event
                )

                if self._stop_event.is_set():
                    break

                if err:
                    logger.error(f"Ошибка распознавания: {err}")
                    self.emit("voice_error", {"message": err})
                    self._set_state("error")
                    self.emit("voice_mode_toggle", {"enabled": False})
                    time.sleep(1.0)
                    break

                recognized_text = recognized_text.strip()
                if not recognized_text:
                    # Фоновый шум, тишина или кашель без распознанных слов — продолжаем слушать
                    continue

                # 2. Проверка голосовых команд завершения
                if is_voice_exit_command(recognized_text):
                    logger.info(f"Получена команда завершения голосового режима: '{recognized_text}'")
                    self.emit("voice_recognized", {"text": recognized_text})
                    self._set_state("speaking")
                    self.emit("voice_mode_toggle", {"enabled": False})

                    speech_done = threading.Event()
                    self.tts.speak("Голосовой режим отключён.", on_finish=speech_done.set)
                    while not speech_done.is_set() and not self._stop_event.is_set():
                        time.sleep(0.05)
                    break

                # 3. Передача распознанного текста в GUI
                self.emit("voice_recognized", {"text": recognized_text})

                # 4. Интеллектуальная обработка (thinking)
                self._set_state("thinking")

                # Отсекаем обращение 'акакий' перед передачей агенту
                clean_cmd = strip_wake_word(recognized_text)
                if not clean_cmd and re.match(r"^(?:слушай[,\s]+)?акакий[,\s]*$", recognized_text, flags=re.IGNORECASE):
                    # Пользователь просто позвал по имени
                    result_payload = {
                        "type": "chat",
                        "answer": "Да, я здесь! Чем могу помочь?"
                    }
                elif self.agent:
                    cmd_for_agent = clean_cmd if clean_cmd else recognized_text
                    try:
                        result_payload = self.agent.process(cmd_for_agent)
                    except Exception as ag_ex:
                        logger.error(f"Ошибка агента при обработке голосового запроса: {ag_ex}", exc_info=True)
                        result_payload = {"type": "error", "error": f"Ошибка агента: {ag_ex}"}
                else:
                    result_payload = {
                        "type": "chat",
                        "answer": f"Распознано: {recognized_text}"
                    }

                if self._stop_event.is_set():
                    break

                # Передаем итоговый результат в GUI для отображения
                self.emit("voice_agent_result", {"payload": result_payload, "query": recognized_text})

                # 5. Извлечение текста для озвучки
                raw_answer = self._extract_speech_text(result_payload)
                clean_speech = clean_for_speech(raw_answer)

                # 6. Озвучивание (speaking)
                if clean_speech and not self._stop_event.is_set():
                    self._set_state("speaking")
                    speech_done = threading.Event()

                    self.tts.speak(clean_speech, on_finish=speech_done.set)

                    # Ожидаем завершения речи или сигнала прерывания
                    while not speech_done.is_set() and not self._stop_event.is_set():
                        time.sleep(0.05)

                if self._stop_event.is_set():
                    break

                # 7. Небольшая акустическая пауза (0.35 с) для затухания реверберации колонок в комнате
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
        if not isinstance(payload, dict):
            return str(payload)

        p_type = payload.get("type")
        if p_type == "chat":
            return payload.get("answer", "")

        elif p_type in ("plan", "plan_execution"):
            # Для планов возвращаем summary или message, либо ошибку
            res = payload.get("result")
            if isinstance(res, dict):
                if res.get("success") is False or "error" in res:
                    return f"Ошибка выполнения плана: {res.get('error') or res.get('message') or 'Не удалось выполнить план.'}"
                return res.get("summary") or res.get("message") or "План успешно выполнен."
            return payload.get("summary") or payload.get("message") or "План успешно выполнен."

        elif p_type == "tool":
            tool_name = payload.get("tool", "")
            res = payload.get("result")
            if isinstance(res, dict):
                # 1. Проверяем статус ошибки верхнего уровня
                if res.get("success") is False or "error" in res:
                    return f"Ошибка: {res.get('error') or res.get('message') or 'Действие не выполнено.'}"

                # 2. Проверяем вложенный результат (inner result)
                inner = res.get("result", res)
                if isinstance(inner, dict):
                    if inner.get("success") is False or "error" in inner:
                        return f"Ошибка: {inner.get('error') or inner.get('message') or 'Действие не выполнено.'}"
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
            return f"Ошибка: {payload.get('error') or 'Произошла ошибка при обработке запроса.'}"

        return payload.get("message") or payload.get("answer") or "Запрос обработан."

    def shutdown(self):
        """Останавливает все потоки сервиса."""
        self.stop_session()
        self.tts.shutdown()
