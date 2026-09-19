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
import struct
import threading
import time
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)


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
        timeout: float = 8.0,
        phrase_time_limit: float = 14.0,
        silence_threshold_seconds: float = 1.6,
        on_level_callback: Optional[Callable[[float], None]] = None,
        stop_event: Optional[threading.Event] = None
    ) -> Tuple[str, Optional[str]]:
        """
        Слушает микрофон до завершения произнесения фразы или таймаута.

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
        recognized_text = ""

        try:
            # Захват моно, 16кГц, int16, блоками по ~250 мс (4000 сэмплов)
            with sd.RawInputStream(
                samplerate=self.samplerate,
                blocksize=4000,
                dtype="int16",
                channels=1,
                callback=audio_callback
            ):
                while True:
                    if stop_event and stop_event.is_set():
                        break

                    now = time.time()

                    # Проверка общего таймаута ожидания речи
                    if speech_started_time is None and (now - start_time) > timeout:
                        break

                    # Проверка максимальной длины фразы
                    if (now - start_time) > phrase_time_limit:
                        break

                    try:
                        data = audio_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    # Вычисление уровня громкости (RMS)
                    count = len(data) // 2
                    if count > 0:
                        shorts = struct.unpack(f"<{count}h", data)
                        sum_sq = sum(s * s for s in shorts)
                        rms = math.sqrt(sum_sq / count) / 32768.0
                        # Масштабируем до 0.0-1.0
                        norm_level = min(1.0, rms * 5.0)

                        if on_level_callback:
                            try:
                                on_level_callback(norm_level)
                            except Exception:
                                pass

                        # Детекция активности голоса
                        if norm_level > 0.05:
                            if speech_started_time is None:
                                speech_started_time = now
                            last_speech_time = now

                    # Передача чанка в KaldiRecognizer
                    if recognizer.AcceptWaveform(data):
                        res = json.loads(recognizer.Result())
                        text = res.get("text", "").strip()
                        if text:
                            recognized_text = text
                            break
                    else:
                        partial_res = json.loads(recognizer.PartialResult())
                        partial_text = partial_res.get("partial", "").strip()
                        if partial_text:
                            if speech_started_time is None:
                                speech_started_time = now
                            last_speech_time = now

                    # Детекция паузы после начала речи
                    if speech_started_time and last_speech_time:
                        if (now - last_speech_time) > silence_threshold_seconds:
                            # Долгая пауза после речи -> завершаем фразу
                            break

            # Финализируем распознавание
            if not recognized_text:
                final_res = json.loads(recognizer.FinalResult())
                recognized_text = final_res.get("text", "").strip()

            # Сбрасываем уровень аудио
            if on_level_callback:
                try:
                    on_level_callback(0.0)
                except Exception:
                    pass

            return recognized_text, None

        except Exception as e:
            logger.error(f"Ошибка при захвате микрофона или распознавании: {e}")
            if on_level_callback:
                try:
                    on_level_callback(0.0)
                except Exception:
                    pass
            return "", f"Ошибка аудиоустройства: {e}"
