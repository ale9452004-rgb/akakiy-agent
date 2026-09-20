"""
Модуль локального распознавания речи (STT) для Акакия.
Использует Vosk с компактной русской моделью и sounddevice для захвата аудиопотока.
"""

import json
import logging
import math
import os
from pathlib import Path
import queue
import re
import struct
import threading
import time
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

COMMON_ACOUSTIC_REPLACEMENTS = [
    # Исправление акустических искажений имени «Акакий»
    (r"\b(а\s+какие|акакие)\b(?=(?:[\s,]+(?:привет|здравствуй|добр|слушай|помоги|создай|добавь|удали|покажи|открой|напиши|сделай|напомни|запиши|найди|выполни|проверь|очисти|забудь|вспомни|что|где|кто|у\s+меня|скажи|как|сколько)|$))", "акакий"),
    (r"^а\s*какие$", "акакий"),
    (r"^(?:слушай\s+)?(а\s+какие|акакие|а\s+какий|акаки|а\s+как\s+и|а\s+как\s+ей)\b", "акакий"),
    (r"\b(а\s+какий|акаки|а\s+как\s+и|а\s+как\s+ей)\b", "акакий"),
    (r"\b(дик|гид|гит)\s+статус\b", "git status"),
    (r"\b(гид|гип|гит)\s+(пуш|уж)\b", "git push"),
    (r"\b(гид|гит)\s+(дифф|диф)\b", "git diff"),
    (r"\b(гид|гит)\s+коммит\b", "git commit"),
    (r"\b(гид|гит)\s+лог\b", "git log"),
    (r"\bтест\s+свит\b", "test suite"),
    (r"\bпулл\s+реквест\b", "pull request"),
    (r"\bмейн\s+(пай|пу)\b", "main.py"),
    (r"\bмейн\s+точка\s+пай\b", "main.py"),
    (r"\b([a-zA-Zа-яА-Я0-9_]+)\s+пай\b", r"\1.py"),
    (r"\b(очисть|очистить)\b", "очисти"),
]



def correct_recognized_text(text: str) -> str:
    """
    Пост-обработка распознанного текста Vosk:
    - исправляет частые фонетические искажения модели на технических терминах и имени;
    - сохраняет имя 'акакий' в тексте для точного отображения в UI и логах.
    """
    if not text or not isinstance(text, str):
        return ""
    res = text.strip()
    for pat, repl in COMMON_ACOUSTIC_REPLACEMENTS:
        res = re.sub(pat, repl, res, flags=re.IGNORECASE)
    return res


def strip_wake_word(text: str) -> str:
    """
    Отсекает обращение 'акакий' / 'слушай акакий' в начале команды для передачи в Agent.
    Если команда состояла только из обращения, возвращает пустую строку.
    """
    if not text or not isinstance(text, str):
        return ""
    res = text.strip()
    wake_match = re.match(r"^(?:слушай[,\s]+)?(?:акакий[,\s]*)+(.+)$", res, flags=re.IGNORECASE)
    if wake_match:
        return wake_match.group(1).strip()
    if re.match(r"^(?:слушай[,\s]+)?акакий[,\s]*$", res, flags=re.IGNORECASE):
        return ""
    return res


class SpeechToTextEngine:
    """
    Локальный движок распознавания речи на базе Vosk.
    Выполняет захват аудио с микрофона, вычисляет уровень сигнала (RMS)
    и возвращает распознанный русский текст.
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = self._resolve_model_path(model_path)
        self.model = None
        self.samplerate = 16000
        self._init_model()

    def _resolve_model_path(self, custom_path: Optional[str]) -> Path:
        if custom_path and Path(custom_path).exists():
            return Path(custom_path)

        project_root = Path(__file__).resolve().parent.parent
        candidates = [
            project_root / "models" / "vosk-model-small-ru-0.22",
            Path(r"c:\Akakiy agent\models\vosk-model-small-ru-0.22"),
        ]

        # Также проверяем любые подпапки в models/
        models_dir = project_root / "models"
        if models_dir.exists():
            for sub in models_dir.iterdir():
                if sub.is_dir() and "vosk" in sub.name.lower():
                    candidates.append(sub)

        for c in candidates:
            if c.exists() and (c / "am").exists():
                return c

        return candidates[0]

    def _init_model(self):
        try:
            import vosk
            if not self.model_path.exists():
                logger.warning(f"Директория модели Vosk не найдена: {self.model_path}")
                return

            # Отключаем избыточный вывод Kaldi в консоль
            vosk.SetLogLevel(-1)
            self.model = vosk.Model(str(self.model_path))
            logger.info(f"Vosk модель успешно загружена из {self.model_path}")
        except Exception as e:
            logger.error(f"Не удалось инициализировать Vosk: {e}")
            self.model = None

    def is_ready(self) -> bool:
        return self.model is not None

    def listen_phrase(
        self,
        timeout: Optional[float] = 8.0,
        phrase_time_limit: float = 16.0,
        silence_threshold_seconds: float = 1.3,
        on_level_callback: Optional[Callable[[float], None]] = None,
        stop_event: Optional[threading.Event] = None
    ) -> Tuple[str, Optional[str]]:
        """
        Слушает микрофон до завершения произнесения фразы или таймаута.
        Накапливает все фрагменты фразы без преждевременного обрыва на AcceptWaveform.

        Возвращает:
            (recognized_text, error_message)
        """
        if not self.is_ready():
            return "", f"Модель Vosk не загружена (путь: {self.model_path})"

        try:
            import sounddevice as sd
            import vosk
        except ImportError as e:
            return "", f"Не установлена библиотека для STT: {e}"

        audio_queue = queue.Queue()

        def audio_callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"Аудио статус: {status}")
            audio_queue.put(bytes(indata))

        recognizer = vosk.KaldiRecognizer(self.model, self.samplerate)
        recognizer.SetWords(False)

        start_time = time.time()
        speech_started_time = None
        last_speech_time = None
        accumulated_parts = []
        effective_silence = max(1.0, float(silence_threshold_seconds if silence_threshold_seconds is not None else 1.1))

        # Адаптивная калибровка порога тишины под аппаратный шум микрофона
        noise_samples = []
        speech_threshold = 0.042

        try:
            # Захват моно, 16кГц, int16, блоками по 100 мс (1600 сэмплов)
            with sd.RawInputStream(
                samplerate=self.samplerate,
                blocksize=1600,
                dtype="int16",
                channels=1,
                callback=audio_callback
            ):
                while True:
                    if stop_event and stop_event.is_set():
                        break

                    now = time.time()

                    # Проверка таймаута ожидания первого слова (если задан)
                    if timeout is not None and speech_started_time is None and (now - start_time) > timeout:
                        break

                    # Проверка максимальной длины фразы
                    if (now - start_time) > phrase_time_limit:
                        break

                    try:
                        data = audio_queue.get(timeout=0.08)
                    except queue.Empty:
                        continue

                    # Вычисление уровня громкости (RMS)
                    count = len(data) // 2
                    if count > 0:
                        shorts = struct.unpack(f"<{count}h", data)
                        sum_sq = sum(s * s for s in shorts)
                        rms = math.sqrt(sum_sq / count) / 32768.0
                        norm_level = min(1.0, rms * 5.0)

                        if on_level_callback:
                            try:
                                on_level_callback(norm_level)
                            except Exception:
                                pass

                        # Адаптивная оценка фонового шума в первые несколько фреймов до начала речи
                        if speech_started_time is None and len(noise_samples) < 5:
                            noise_samples.append(norm_level)
                            avg_noise = sum(noise_samples) / len(noise_samples)
                            speech_threshold = max(0.042, min(0.08, avg_noise * 1.55))

                        # Детекция активности голоса по энергии (выше адаптивного порога шума)
                        if norm_level > speech_threshold:
                            if speech_started_time is None:
                                speech_started_time = now
                            last_speech_time = now

                    # Передача чанка в KaldiRecognizer
                    if recognizer.AcceptWaveform(data):
                        res = json.loads(recognizer.Result())
                        text = res.get("text", "").strip()
                        if text:
                            accumulated_parts.append(text)
                            if speech_started_time is None:
                                speech_started_time = now
                            last_speech_time = now
                    else:
                        partial_res = json.loads(recognizer.PartialResult())
                        partial_text = partial_res.get("partial", "").strip()
                        if partial_text:
                            if speech_started_time is None:
                                speech_started_time = now
                            last_speech_time = now

                    # Детекция паузы после начала речи: завершаем фразу, если тишина > effective_silence
                    if speech_started_time and last_speech_time:
                        if (now - last_speech_time) > effective_silence:
                            break

            # 1. Извлекаем все оставшиеся аудио-чанки из очереди
            while not audio_queue.empty():
                try:
                    rem_data = audio_queue.get_nowait()
                    if recognizer.AcceptWaveform(rem_data):
                        res = json.loads(recognizer.Result())
                        text = res.get("text", "").strip()
                        if text:
                            accumulated_parts.append(text)
                except queue.Empty:
                    break

            # 2. Подаём акустическую тишину (silence padding) в KaldiRecognizer,
            # чтобы декодер успел выгрузить согласные и мягкие окончания слова
            silence_pad = b"\x00" * 3200
            for _ in range(3):
                if recognizer.AcceptWaveform(silence_pad):
                    res = json.loads(recognizer.Result())
                    text = res.get("text", "").strip()
                    if text:
                        accumulated_parts.append(text)

            # 3. Финализируем распознавание через FinalResult
            final_res = json.loads(recognizer.FinalResult())
            final_text = final_res.get("text", "").strip()
            if final_text:
                accumulated_parts.append(final_text)

            # Сбрасываем уровень аудио
            if on_level_callback:
                try:
                    on_level_callback(0.0)
                except Exception:
                    pass

            raw_recognized = " ".join(accumulated_parts).strip()
            recognized_text = correct_recognized_text(raw_recognized)

            return recognized_text, None

        except Exception as e:
            logger.error(f"Ошибка при захвате микрофона или распознавании: {e}")
            if on_level_callback:
                try:
                    on_level_callback(0.0)
                except Exception:
                    pass
            return "", f"Ошибка аудиоустройства: {e}"
