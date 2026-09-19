import html
import logging
from pathlib import Path
import queue
import threading
from typing import Callable, Optional

from voice.cleaner import clean_for_speech

logger = logging.getLogger(__name__)

# Путь к локальной модели Silero по умолчанию
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SILERO_MODEL_PATH = PROJECT_ROOT / "models" / "silero" / "v4_ru.pt"


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
        """Синтезирует речь через Silero на CPU и выводит PCM аудио порциями через sounddevice."""
        import sounddevice as sd
        sample_rate = 24000
        speaker = self.voice_name_hint if hasattr(self._silero_model, "speakers") and self.voice_name_hint in self._silero_model.speakers else "eugene"

        audio_tensor = self._silero_model.apply_tts(
            text=text,
            speaker=speaker,
            sample_rate=sample_rate,
            put_accent=True,
            put_yo=True
        )

        if self._current_stop_event.is_set() or self._stop_event.is_set():
            return

        audio_np = audio_tensor.numpy()
        chunk_size = 1200  # 50 мс порции при частоте 24 кГц

        stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32")
        self._current_stream = stream
        try:
            stream.start()
            if on_start and callable(on_start):
                try:
                    on_start()
                except Exception:
                    pass
            for i in range(0, len(audio_np), chunk_size):
                if self._current_stop_event.is_set() or self._stop_event.is_set():
                    break
                stream.write(audio_np[i : i + chunk_size])
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
                    has_cyrillic = any("\u0400" <= c <= "\u04ff" for c in clean_text)
                    if has_cyrillic:
                        try:
                            self._speak_silero(clean_text, on_start=on_start)
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
