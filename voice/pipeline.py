"""
Модуль унифицированного голосового конвейера (Voice Pipeline) Акакия.

Обеспечивает сквозной поток:
STT (захват речи и распознавание Vosk) ->
Обработка Agent (CommandRouter -> SubAgents -> Tools -> LLM) ->
Очистка и нормализация текста ->
TTS (синтез и воспроизведение речи).

Поддерживает:
- как пошаговое исполнение (run_step), так и прямую обработку фраз (process_phrase);
- корректную обработку пустой речи, фонового шума и тишины;
- распознавание команд завершения сеанса и отмены ("стоп", "выключи голос");
- безопасную обработку ошибок STT, агента и аудиоустройств;
- извлечение естественного речевого ответа (extract_speech_text) из любых форматов (chat, subagents, tools, AgentResult);
- изоляцию потоков и потокобезопасные события для UI.
"""

from dataclasses import dataclass
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple, Union

from voice.cleaner import clean_for_speech
from voice.stt import SpeechToTextEngine, strip_wake_word, correct_recognized_text
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
    if not text or not isinstance(text, str):
        return False
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


def extract_speech_text(payload: Any) -> str:
    """
    Извлекает естественный лаконичный текст ответа для озвучивания (TTS)
    из любого формата ответа Agent, SubAgent или инструмента.
    """
    if payload is None:
        return ""

    if isinstance(payload, str):
        return payload

    # 1. Проверяем объекты AgentResult (из subagents, teamwork, executor)
    if hasattr(payload, "message") and hasattr(payload, "success"):
        if getattr(payload, "success", True):
            return str(payload.message or "")
        err_msg = getattr(payload, "error", None) or payload.message or "Произошла ошибка при выполнении задачи."
        return f"Ошибка: {err_msg}"

    # 2. Словарные контракты
    if isinstance(payload, dict):
        # 2.1. Чат или прямое текстовое сообщение
        p_type = payload.get("type")

        # Если в словаре есть явное поле answer
        if "answer" in payload and payload["answer"]:
            return str(payload["answer"])

        if p_type == "chat":
            return str(payload.get("answer", "") or payload.get("message", ""))

        # 2.2. Специализированные Sub-Agent'ы (image, presentation, document, research, coding, file, subagent)
        if p_type in ("image", "presentation", "document", "research", "coding", "file", "subagent"):
            if payload.get("answer"):
                return str(payload["answer"])
            if payload.get("message"):
                return str(payload["message"])
            sub_res = payload.get("result")
            if hasattr(sub_res, "message"):
                if getattr(sub_res, "success", True):
                    return str(sub_res.message)
                return f"Ошибка: {getattr(sub_res, 'error', None) or sub_res.message}"
            if not payload.get("success", True):
                return f"Ошибка: {payload.get('error') or payload.get('message') or 'Ошибка выполнения субагента.'}"

        # 2.3. Планы и их исполнение
        if p_type in ("plan", "plan_execution"):
            res = payload.get("result")
            if isinstance(res, dict):
                if res.get("success") is False or "error" in res:
                    return f"Ошибка выполнения плана: {res.get('error') or res.get('message') or 'Не удалось выполнить план.'}"
                return str(res.get("summary") or res.get("message") or "План успешно выполнен.")
            if hasattr(res, "message"):
                if getattr(res, "success", True):
                    return str(res.message)
                return f"Ошибка выполнения плана: {getattr(res, 'error', None) or res.message}"
            return str(payload.get("summary") or payload.get("message") or "План успешно выполнен.")

        # 2.4. Инструменты (tools)
        if p_type == "tool":
            tool_name = payload.get("tool", "")
            res = payload.get("result")
            if isinstance(res, dict):
                if res.get("success") is False or "error" in res:
                    return f"Ошибка: {res.get('error') or res.get('message') or 'Действие не выполнено.'}"
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
                        return str(inner["message"])
                if "message" in res:
                    return str(res["message"])
                return f"Инструмент {tool_name} выполнен успешно."
            elif hasattr(res, "message"):
                return str(res.message)
            return str(res or f"Инструмент {tool_name} выполнен.")

        # 2.5. Ошибки верхнего уровня
        if p_type == "error" or payload.get("success") is False:
            return f"Ошибка: {payload.get('error') or payload.get('message') or 'Произошла ошибка при обработке запроса.'}"

        # 2.6. Общие поля
        if "message" in payload and payload["message"]:
            return str(payload["message"])
        if "summary" in payload and payload["summary"]:
            return str(payload["summary"])

    return str(payload)


class VoicePipelineResult:
    """
    Структурированный результат выполнения шага голосового конвейера (Voice Pipeline).
    """

    def __init__(
        self,
        status: str,  # "success", "empty", "exit", "error", "cancelled"
        recognized_text: str = "",
        cleaned_command: str = "",
        agent_result: Any = None,
        spoken_text: str = "",
        error: Optional[str] = None,
        duration_seconds: float = 0.0,
    ):
        self.status = str(status)
        self.recognized_text = str(recognized_text or "")
        self.cleaned_command = str(cleaned_command or "")
        self.agent_result = agent_result
        self.spoken_text = str(spoken_text or "")
        self.error = str(error) if error is not None else None
        self.duration_seconds = float(duration_seconds)

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    @property
    def is_exit(self) -> bool:
        return self.status == "exit"

    @property
    def is_empty(self) -> bool:
        return self.status == "empty"

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def is_error(self) -> bool:
        return self.status == "error"

    @property
    def created_files(self) -> list:
        if isinstance(self.agent_result, dict):
            return list(self.agent_result.get("created_files", []))
        if hasattr(self.agent_result, "created_files"):
            return list(self.agent_result.created_files)
        return []

    @property
    def artifacts(self) -> list:
        if isinstance(self.agent_result, dict):
            return list(self.agent_result.get("artifacts", []))
        if hasattr(self.agent_result, "artifacts"):
            return list(self.agent_result.artifacts)
        return []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "recognized_text": self.recognized_text,
            "cleaned_command": self.cleaned_command,
            "agent_result": self.agent_result,
            "spoken_text": self.spoken_text,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "created_files": self.created_files,
            "artifacts": self.artifacts,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __repr__(self) -> str:
        rec_preview = (self.recognized_text[:25] + "...") if len(self.recognized_text) > 25 else self.recognized_text
        spoken_preview = (self.spoken_text[:25] + "...") if len(self.spoken_text) > 25 else self.spoken_text
        return f"<VoicePipelineResult status='{self.status}' text='{rec_preview}' spoken='{spoken_preview}'>"


class VoicePipeline:
    """
    Полноценный конвейер голосового взаимодействия (Voice Pipeline).

    Связывает компоненты в единый детерминированный поток:
    STT (Vosk) -> Обработка Agent -> Извлечение/очистка текста -> TTS (pyttsx3 / Silero).

    Изолирует потоки и предоставляет безопасный API для вызова как из
    фонового сеанса VoiceService, так и автономно в скриптах и тестах.
    """

    def __init__(
        self,
        agent: Optional[Any] = None,
        stt: Optional[SpeechToTextEngine] = None,
        tts: Optional[TextToSpeechEngine] = None,
        event_sink: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        model_path: Optional[str] = None
    ):
        self.agent = agent
        self.stt = stt or SpeechToTextEngine(model_path=model_path)
        self.tts = tts or TextToSpeechEngine()
        self.event_sink = event_sink
        self._state = "idle"
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        return self._state

    def set_state(self, new_state: str):
        with self._lock:
            self._state = new_state
        self.emit("voice_state", {"state": new_state})

    def emit(self, event_type: str, data: Optional[Dict[str, Any]] = None):
        """Передаёт событие конвейера внешним подписчикам (GUI queue / логгеры)."""
        if self.event_sink and callable(self.event_sink):
            try:
                self.event_sink(event_type, data or {})
            except Exception as e:
                logger.warning(f"Ошибка отправки события {event_type}: {e}")

    # =========================================================================
    # Фаза 1: STT (Захват речи и распознавание)
    # =========================================================================

    def listen(
        self,
        timeout: Optional[float] = None,
        phrase_time_limit: float = 25.0,
        silence_threshold_seconds: float = 1.0,
        on_level_callback: Optional[Callable[[float], None]] = None,
        stop_event: Optional[threading.Event] = None,
        finish_event: Optional[threading.Event] = None
    ) -> Tuple[str, Optional[str]]:
        """
        Захватывает аудио с микрофона через STT и возвращает распознанный текст.
        Возвращает: (recognized_text, error_message).
        """
        self.set_state("listening")
        level_cb = on_level_callback or (lambda lvl: self.emit("voice_audio_level", {"level": lvl}))

        text, err = self.stt.listen_phrase(
            timeout=timeout,
            phrase_time_limit=phrase_time_limit,
            silence_threshold_seconds=silence_threshold_seconds,
            on_level_callback=level_cb,
            stop_event=stop_event,
            finish_event=finish_event
        )

        clean_text = (text or "").strip()
        return clean_text, err

    # =========================================================================
    # Фаза 2: Обработка команды через Agent Pipeline
    # =========================================================================

    def process_command(
        self,
        recognized_text: str,
        stop_event: Optional[threading.Event] = None
    ) -> Tuple[str, Any]:
        """
        Передает очищенную команду в Agent Pipeline и возвращает сырой ответ.
        Возвращает: (cleaned_command, result_payload).
        """
        self.set_state("thinking")
        clean_cmd = strip_wake_word(recognized_text)

        # 1. Проверка случая, когда пользователь просто позвал по имени
        if not clean_cmd and re.match(r"^(?:слушай[,\s]+)?акакий[,\s]*$", recognized_text, flags=re.IGNORECASE):
            return clean_cmd, {
                "type": "chat",
                "answer": "Да, я здесь! Чем могу помочь?"
            }

        # 2. Передача команды в Agent
        if self.agent:
            cmd_for_agent = clean_cmd if clean_cmd else recognized_text
            try:
                result_payload = self.agent.process(cmd_for_agent)
            except Exception as ag_ex:
                logger.error(f"Ошибка агента при обработке голосового запроса '{cmd_for_agent}': {ag_ex}", exc_info=True)
                result_payload = {
                    "type": "error",
                    "error": f"Ошибка агента: {ag_ex}"
                }
        else:
            result_payload = {
                "type": "chat",
                "answer": f"Распознано: {recognized_text}"
            }

        return clean_cmd, result_payload

    # =========================================================================
    # Фаза 3: Озвучивание через TTS
    # =========================================================================

    def speak(
        self,
        text: str,
        stop_event: Optional[threading.Event] = None,
        on_finish: Optional[Callable[[], None]] = None
    ) -> str:
        """
        Очищает текст от разметки/кода и озвучивает его через TTS.
        Ожидает окончания синтеза или сигнала остановки stop_event.
        Возвращает фактически очищенный текст, отправленный в TTS.
        """
        clean_speech = clean_for_speech(text)
        if not clean_speech or (stop_event and stop_event.is_set()):
            if on_finish and callable(on_finish):
                on_finish()
            return clean_speech or ""

        self.set_state("speaking")
        speech_done = threading.Event()

        def _done():
            speech_done.set()
            if on_finish and callable(on_finish):
                on_finish()

        self.tts.speak(clean_speech, on_finish=_done)

        # Ожидаем завершения воспроизведения или сигнала прерывания
        while not speech_done.is_set():
            if stop_event and stop_event.is_set():
                self.tts.stop()
                break
            time.sleep(0.04)

        return clean_speech

    # =========================================================================
    # Сквозной конвейер (End-to-End Execution)
    # =========================================================================

    def process_phrase(
        self,
        phrase: str,
        speak: bool = True,
        stop_event: Optional[threading.Event] = None,
        on_finish: Optional[Callable[[], None]] = None
    ) -> VoicePipelineResult:
        """
        Сквозная обработка готовой текстовой фразы через Agent -> TTS.
        Позволяет запускать конвейер без микрофона (для тестов, симуляций и шорткатов).
        """
        start_time = time.time()
        text = str(phrase or "").strip()

        # 1. Пустая речь
        if not text:
            self.set_state("idle")
            if on_finish and callable(on_finish):
                on_finish()
            return VoicePipelineResult(
                status="empty",
                recognized_text="",
                duration_seconds=time.time() - start_time
            )

        # 2. Проверка команды выхода
        if is_voice_exit_command(text):
            logger.info(f"Получена голосовая команда завершения сеанса: '{text}'")
            self.emit("voice_recognized", {"text": text})
            self.emit("voice_mode_toggle", {"enabled": False})
            spoken = ""
            if speak and (not stop_event or not stop_event.is_set()):
                spoken = self.speak("Голосовой режим отключён.", stop_event=stop_event, on_finish=on_finish)
            else:
                self.set_state("idle")
                if on_finish and callable(on_finish):
                    on_finish()
            return VoicePipelineResult(
                status="exit",
                recognized_text=text,
                cleaned_command=text,
                spoken_text=spoken or "Голосовой режим отключён.",
                duration_seconds=time.time() - start_time
            )

        # 3. Передача распознанного текста в GUI
        self.emit("voice_recognized", {"text": text})

        if stop_event and stop_event.is_set():
            self.set_state("idle")
            if on_finish and callable(on_finish):
                on_finish()
            return VoicePipelineResult(
                status="cancelled",
                recognized_text=text,
                duration_seconds=time.time() - start_time
            )

        # 4. Обработка через Agent
        clean_cmd, result_payload = self.process_command(text, stop_event=stop_event)

        if stop_event and stop_event.is_set():
            self.set_state("idle")
            if on_finish and callable(on_finish):
                on_finish()
            return VoicePipelineResult(
                status="cancelled",
                recognized_text=text,
                cleaned_command=clean_cmd,
                agent_result=result_payload,
                duration_seconds=time.time() - start_time
            )

        # Передаем результат агента в GUI
        self.emit("voice_agent_result", {"payload": result_payload, "query": text})

        # 5. Извлечение текста для озвучки
        raw_answer = extract_speech_text(result_payload)
        spoken_text = ""

        # 6. Озвучивание
        if speak and raw_answer and (not stop_event or not stop_event.is_set()):
            spoken_text = self.speak(raw_answer, stop_event=stop_event, on_finish=on_finish)
        else:
            self.set_state("idle")
            if on_finish and callable(on_finish):
                on_finish()

        # Классификация статуса выполнения
        is_err = False
        err_msg = None
        if isinstance(result_payload, dict):
            if result_payload.get("type") == "error" or result_payload.get("success") is False:
                is_err = True
                err_msg = str(result_payload.get("error") or result_payload.get("message") or "Ошибка агента")
        elif hasattr(result_payload, "success") and not result_payload.success:
            is_err = True
            err_msg = str(getattr(result_payload, "error", None) or result_payload.message)

        status = "error" if is_err else "success"

        return VoicePipelineResult(
            status=status,
            recognized_text=text,
            cleaned_command=clean_cmd,
            agent_result=result_payload,
            spoken_text=spoken_text or clean_for_speech(raw_answer),
            error=err_msg,
            duration_seconds=time.time() - start_time
        )

    def run_step(
        self,
        stop_event: Optional[threading.Event] = None,
        finish_event: Optional[threading.Event] = None,
        silence_threshold_seconds: float = 1.0,
        phrase_time_limit: float = 25.0
    ) -> VoicePipelineResult:
        """
        Выполняет один полный цикл конвейера от микрофона до динамиков:
        STT (listen) -> Agent (process) -> TTS (speak).
        """
        start_time = time.time()

        # 1. Захват аудио и распознавание
        recognized_text, err = self.listen(
            phrase_time_limit=phrase_time_limit,
            silence_threshold_seconds=silence_threshold_seconds,
            stop_event=stop_event,
            finish_event=finish_event
        )

        # Проверка сигнала отмены во время записи
        if stop_event and stop_event.is_set():
            self.set_state("idle")
            return VoicePipelineResult(
                status="cancelled",
                error="Сеанс остановлен пользователем.",
                duration_seconds=time.time() - start_time
            )

        # Ошибка STT / аудиоустройства
        if err:
            logger.error(f"Ошибка распознавания речи в конвейере: {err}")
            self.emit("voice_error", {"message": err})
            self.set_state("error")
            return VoicePipelineResult(
                status="error",
                error=err,
                duration_seconds=time.time() - start_time
            )

        # Тишина / отсутствие речи
        if not recognized_text:
            self.set_state("idle")
            return VoicePipelineResult(
                status="empty",
                duration_seconds=time.time() - start_time
            )

        # 2. Обработка распознанной команды и озвучивание
        return self.process_phrase(recognized_text, speak=True, stop_event=stop_event)
