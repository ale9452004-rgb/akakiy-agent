"""
Пакет локального голосового интерфейса Акакия (STT, TTS, VoiceService).
"""

from voice.cleaner import clean_for_speech
from voice.service import VoiceService
from voice.stt import SpeechToTextEngine
from voice.tts import TextToSpeechEngine

__all__ = [
    "VoiceService",
    "SpeechToTextEngine",
    "TextToSpeechEngine",
    "clean_for_speech",
]
