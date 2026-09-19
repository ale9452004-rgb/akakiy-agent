import html
import logging
from pathlib import Path
import queue
import re
import threading
from typing import Callable, Optional

from voice.cleaner import clean_for_speech
from voice.normalizer import normalize_text_for_speech

logger = logging.getLogger(__name__)

# Путь к локальной модели Silero по умолчанию
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SILERO_MODEL_PATH = PROJECT_ROOT / "models" / "silero" / "v4_ru.pt"


def split_text_into_speech_chunks(
    text: str,
    target_chunk_chars: int = 350,
    max_chunk_chars: int = 500
) -> list[str]:
    """
    Разбивает длинный текст на безопасные и естественные для синтезатора Silero фрагменты:
    1. Сначала делит по границам предложений (. ! ? \n).
    2. Если отдельное предложение превышает max_chunk_chars, дробит его по пунктуации (, ; : —) или пробелам.
    3. Объединяет предложения в оптимальные порции размером ~250-400 символов.
    """
    text = text.strip()
    if not text:
        return []

    # 1. Разбиение по границам предложений
    raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    if not raw_sentences:
        raw_sentences = [text]

    # 2. Если предложение длиннее max_chunk_chars, делим по пунктуации внутри него
    refined_sentences = []
    for s in raw_sentences:
        if len(s) <= max_chunk_chars:
            refined_sentences.append(s)
        else:
            clauses = [c.strip() for c in re.split(r"(?<=[,;:—])\s+", s) if c.strip()]
            cur_clause = ""
            for c in clauses:
                if len(c) > max_chunk_chars:
                    words = c.split()
                    sub = ""
                    for w in words:
                        if len(sub) + len(w) + 1 <= max_chunk_chars:
                            sub = (sub + " " + w).strip()
                        else:
                            if sub:
                                refined_sentences.append(sub)
                            sub = w
                    if sub:
                        refined_sentences.append(sub)
                else:
                    if len(cur_clause) + len(c) + 1 <= target_chunk_chars:
                        cur_clause = (cur_clause + " " + c).strip()
                    else:
                        if cur_clause:
                            refined_sentences.append(cur_clause)
                        cur_clause = c
            if cur_clause:
                refined_sentences.append(cur_clause)

    # 3. Группировка предложений в сбалансированные блоки
    chunks = []
    current_chunk = ""
    for s in refined_sentences:
        if not current_chunk:
            current_chunk = s
        elif len(current_chunk) + len(s) + 1 <= target_chunk_chars:
            current_chunk += " " + s
        else:
            chunks.append(current_chunk)
            current_chunk = s
    if current_chunk:
        chunks.append(current_chunk)

    # 4. Проверка и нормализация граничной пунктуации каждого фрагмента
    final_chunks = []
    for i, ch in enumerate(chunks):
        ch = ch.strip()
        if not ch:
            continue
        if ch[-1] not in ".!?:;,-":
            ch += "." if i == len(chunks) - 1 else ","
        final_chunks.append(ch)

    return final_chunks


class TextToSpeechEngine:
    """
    Потокобезопасный локальный движок озвучивания речи.
    Обрабатывает фразы через внутреннюю очередь в выделенном рабочем потоке.

    Основной движок:
      - Silero TTS v4_ru, голос 'eugene' (нейросетевой зрелый мужской тембр, инференс строго на CPU).
    Резервный движок (автоматический fallback):
      - Windows OneCore Microsoft Pavel (SAPI/COM).
    """

    def __init__(
        self,
        voice_name_hint: str = "eugene",
        rate: int = -1,
        pitch: int = -2,
        model_path: Optional[Path] = None
    ):
        self.voice_name_hint = (voice_name_hint or "eugene").lower()
        # Если передан масштаб WPM (> 10), нормализуем под SAPI (-10..+10)
        self.rate = -1 if rate > 10 else rate
        self.pitch = pitch
        self.model_path = Path(model_path) if model_path else DEFAULT_SILERO_MODEL_PATH

        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._current_stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        self._backend = "none"  # "silero" или "sapi"
        self._silero_model = None
        self._speaker = None
        self._engine = None  # Алиас для обратной совместимости с тестами/моками
        self._current_stream = None

        self.voice_name: str = "Инициализация..."
        self._is_speaking = False

        # 1. Загрузка Silero TTS (один раз при создании, инференс строго на CPU)
        if not self._init_silero():
            self._init_sapi_sync()

        # 2. Запуск рабочего потока обработки очереди
        self._start_worker()

    def _start_worker(self):
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._run_tts_loop,
            daemon=True,
            name="Akakiy-TTS-Worker"
        )
        self._worker_thread.start()

    def _init_silero(self) -> bool:
        """Загружает модель Silero TTS на CPU и настраивает голос."""
        if not self.model_path.exists():
            logger.info(f"Файл модели Silero не найден ({self.model_path}), активируется SAPI fallback.")
            return False
        try:
            import torch
            device = torch.device("cpu")
            self._silero_model = torch.package.PackageImporter(str(self.model_path)).load_pickle("tts_models", "model")
            self._silero_model.to(device)
            speaker = self.voice_name_hint if hasattr(self._silero_model, "speakers") and self.voice_name_hint in self._silero_model.speakers else "eugene"
            self.voice_name = f"Silero {speaker.capitalize()} (Neural CPU)"
            self._backend = "silero"
            logger.info(f"Инициализирован основной TTS: {self.voice_name}")
            return True
        except Exception as e:
            logger.warning(f"Не удалось загрузить Silero TTS: {e}. Переключение на SAPI fallback.")
            self._silero_model = None
            return False

    def _init_sapi_sync(self):
        """Определяет имя голоса для SAPI при создании, если Silero недоступен."""
        self._backend = "sapi"
        self.voice_name = "Microsoft Pavel (SAPI Fallback)"

    def _setup_sapi(self) -> bool:
        """Инициализирует или восстанавливает COM SpVoice в текущем рабочем потоке."""
        if self._speaker is not None:
            return True
        try:
            import win32com.client
            self._speaker = win32com.client.Dispatch("SAPI.SpVoice")
            if self._engine is None:
                self._engine = self._speaker

            selected_token = None
            # 1. Поиск в каталоге Windows OneCore (где расположен Microsoft Pavel)
            try:
                cat_onecore = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
                cat_onecore.SetId(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices", False)
                tokens = cat_onecore.EnumerateTokens()
                for i in range(tokens.Count):
                    tok = tokens.Item(i)
                    desc = tok.GetDescription().lower()
                    if "pavel" in desc:
                        selected_token = tok
                        break

                if not selected_token:
                    for i in range(tokens.Count):
                        tok = tokens.Item(i)
                        desc = tok.GetDescription().lower()
                        if "russian" in desc or "ru-" in desc:
                            selected_token = tok
                            break
            except Exception as e:
                logger.debug(f"Каталог OneCore недоступен: {e}")

            # 2. Если в OneCore не найден, поиск в стандартном SAPI5 (fallback)
            if not selected_token:
                try:
                    for v in self._speaker.GetVoices():
                        desc = v.GetDescription().lower()
                        if "pavel" in desc or "russian" in desc or "irina" in desc:
                            selected_token = v
                            break
                except Exception as e:
                    logger.debug(f"Поиск в SAPI5 завершился с ошибкой: {e}")

            if selected_token:
                self._speaker.Voice = selected_token
                desc = selected_token.GetDescription()
                if self._backend == "sapi":
                    self.voice_name = f"{desc} (SAPI Fallback)"
            elif hasattr(self._speaker, "Voice"):
                desc = self._speaker.Voice.GetDescription()
                if self._backend == "sapi":
                    self.voice_name = f"{desc} (SAPI Fallback)"

            # Установка базовой скорости (-10..+10)
            try:
                self._speaker.Rate = self.rate
            except Exception:
                pass

            logger.info(f"SAPI SpVoice инициализирован: {self.voice_name} (rate={self.rate}, pitch={self.pitch})")
            return True

        except Exception as e:
            logger.warning(f"Не удалось инициализировать SAPI.SpVoice: {e}")
            self._speaker = None
            return False

    def _speak_silero(self, text: str, on_start: Optional[Callable[[], None]] = None):
        """
        Синтезирует речь через Silero на CPU с безопасным разбиением на фрагменты
        и непрерывным потоковым выводом в sounddevice.OutputStream.
        """
        import sounddevice as sd
        sample_rate = 24000
        speaker = self.voice_name_hint if hasattr(self._silero_model, "speakers") and self.voice_name_hint in self._silero_model.speakers else "eugene"

        # Нормализация чисел, латиницы и технических символов перед синтезом Silero
        text = normalize_text_for_speech(text)
        chunks = split_text_into_speech_chunks(text)
        if not chunks:
            return

        stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32")
        self._current_stream = stream
        chunk_size = 1200  # 50 мс порции при частоте 24 кГц
        first_chunk = True

        try:
            stream.start()
            total_chunks = len(chunks)
            for idx, chunk in enumerate(chunks):
                if self._current_stop_event.is_set() or self._stop_event.is_set():
                    break

                audio_tensor = self._silero_model.apply_tts(
                    text=chunk,
                    speaker=speaker,
                    sample_rate=sample_rate,
                    put_accent=True,
                    put_yo=True
                )

                if self._current_stop_event.is_set() or self._stop_event.is_set():
                    break

                if first_chunk:
                    first_chunk = False
                    if on_start and callable(on_start):
                        try:
                            on_start()
                        except Exception:
                            pass

                audio_np = audio_tensor.numpy()

                # К последнему фрагменту добавляем хвост тишины (~150 мс),
                # чтобы акустический спад последнего слога не срезался драйвером звуковой карты
                is_last_chunk = (idx == total_chunks - 1)
                if is_last_chunk:
                    import numpy as np
                    tail_silence = np.zeros(int(sample_rate * 0.15), dtype="float32")
                    audio_np = np.concatenate([audio_np, tail_silence])

                for i in range(0, len(audio_np), chunk_size):
                    if self._current_stop_event.is_set() or self._stop_event.is_set():
                        break
                    stream.write(audio_np[i : i + chunk_size])

                # Небольшая естественная пауза между чанками (~50 мс)
                if not is_last_chunk and not self._current_stop_event.is_set() and not self._stop_event.is_set():
                    import numpy as np
                    inter_chunk = np.zeros(int(sample_rate * 0.05), dtype="float32")
                    stream.write(inter_chunk)

            # Дожидаемся полного завершения воспроизведения всех буферов в динамики
            if not self._current_stop_event.is_set() and not self._stop_event.is_set():
                stream.stop()

        except Exception:
            if not self._current_stop_event.is_set() and not self._stop_event.is_set():
                raise
        finally:
            self._current_stream = None
            try:
                if self._current_stop_event.is_set() or self._stop_event.is_set():
                    stream.abort()
                stream.close()
            except Exception:
                pass

    def _speak_sapi(self, text: str, on_start: Optional[Callable[[], None]] = None):
        """Озвучивает текст через SAPI с модуляцией pitch и rate."""
        if not self._speaker or self._current_stop_event.is_set() or self._stop_event.is_set():
            return
        escaped = html.escape(text)
        xml_text = f'<pitch absmiddle="{self.pitch}"><rate speed="{self.rate}">{escaped}</rate></pitch>'
        if on_start and callable(on_start):
            try:
                on_start()
            except Exception:
                pass
        self._speaker.Speak(xml_text, 1 | 8)  # SVSFlagsAsync | SVSFIsXML

        while not self._current_stop_event.is_set() and not self._stop_event.is_set():
            if self._speaker.WaitUntilDone(50):
                break

    def _run_tts_loop(self):
        """Выполняется в выделенном потоке."""
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

        if self._backend == "sapi":
            self._setup_sapi()

        while not self._stop_event.is_set():
            try:
                task = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if task is None:
                break

            text, on_start, on_finish = task
            clean_text = clean_for_speech(text) if text else ""

            # Если текста нет или в нём нет ни одной буквы/цифры
            if not clean_text or not any(c.isalnum() for c in clean_text):
                self._queue.task_done()
                if on_finish and callable(on_finish):
                    try:
                        on_finish()
                    except Exception:
                        pass
                continue

            self._is_speaking = True
            self._current_stop_event.clear()

            try:
                # Если _engine был замокан в тестах с интерфейсом .say()
                if self._engine and hasattr(self._engine, "say"):
                    if on_start and callable(on_start):
                        try:
                            on_start()
                        except Exception:
                            pass
                    self._engine.say(clean_text)
                    if hasattr(self._engine, "runAndWait"):
                        self._engine.runAndWait()
                elif self._backend == "silero" and self._silero_model:
                    # Нормализуем текст (числа в слова, латиницу и технические токены в русскую фонетику)
                    norm_text = normalize_text_for_speech(clean_text)
                    has_cyrillic = any("\u0400" <= c <= "\u04ff" for c in norm_text)
                    if has_cyrillic:
                        try:
                            self._speak_silero(norm_text, on_start=on_start)
                        except Exception as ex:
                            if not self._current_stop_event.is_set() and not self._stop_event.is_set():
                                logger.warning(f"Ошибка Silero ({ex}), fallback на SAPI для: {clean_text[:40]}")
                                if self._setup_sapi():
                                    self._speak_sapi(clean_text, on_start=on_start)
                    else:
                        if not self._current_stop_event.is_set() and not self._stop_event.is_set():
                            if self._setup_sapi():
                                self._speak_sapi(clean_text, on_start=on_start)
                else:
                    if not self._current_stop_event.is_set() and not self._stop_event.is_set():
                        if self._setup_sapi():
                            self._speak_sapi(clean_text, on_start=on_start)

            except Exception as ex:
                logger.error(f"Ошибка воспроизведения речи: {ex}")
            finally:
                self._is_speaking = False
                self._queue.task_done()
                if on_finish and callable(on_finish):
                    try:
                        on_finish()
                    except Exception:
                        pass

        # Cleanup при завершении рабочего потока
        self._speaker = None
        self._engine = None
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except Exception:
            pass

    def speak(
        self,
        text: str,
        on_start: Optional[Callable[[], None]] = None,
        on_finish: Optional[Callable[[], None]] = None
    ):
        """
        Ставит текст в очередь на озвучивание.
        Не блокирует вызывающий поток.
        """
        if not text or not text.strip():
            if on_finish and callable(on_finish):
                on_finish()
            return

        self._queue.put((text, on_start, on_finish))

    def stop(self):
        """Прерывает текущее воспроизведение и очищает очередь."""
        while not self._queue.empty():
            try:
                task = self._queue.get_nowait()
                self._queue.task_done()
                if task and len(task) == 3:
                    _, _, pending_finish = task
                    if pending_finish and callable(pending_finish):
                        try:
                            pending_finish()
                        except Exception:
                            pass
            except queue.Empty:
                break

        self._current_stop_event.set()

        # Если воспроизводит sounddevice
        if hasattr(self, "_current_stream") and self._current_stream is not None:
            try:
                self._current_stream.abort()
            except Exception:
                pass

        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

        # Если воспроизводит SAPI
        if self._speaker and self._is_speaking:
            try:
                # SVSFPurgeBeforeSpeak = 2, SVSFlagsAsync = 1
                self._speaker.Speak("", 2 | 1)
            except Exception:
                pass

        if self._engine and hasattr(self._engine, "stop"):
            try:
                self._engine.stop()
            except Exception:
                pass

        self._is_speaking = False

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    def shutdown(self):
        """Корректно останавливает фоновый поток TTS."""
        self.stop()
        self._stop_event.set()
        self._queue.put(None)
