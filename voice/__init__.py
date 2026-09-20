"""
Пакет локального голосового интерфейса Акакия (STT, TTS, VoiceService).
"""

from voice.cleaner import clean_for_speech
from voice.normalizer import normalize_text_for_speech
from voice.service import VoiceService
from voice.stt import SpeechToTextEngine
from voice.tts import TextToSpeechEngine
from voice.hotkey import GlobalHotKeyManager

__all__ = [
    "VoiceService",
    "SpeechToTextEngine",
    "TextToSpeechEngine",
    "GlobalHotKeyManager",
    "clean_for_speech",
    "normalize_text_for_speech",
]
