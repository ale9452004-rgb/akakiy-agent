"""
Пакет локального голосового интерфейса Акакия (STT, TTS, VoiceService).
"""

from voice.cleaner import clean_for_speech
from voice.normalizer import normalize_text_for_speech
from voice.service import VoiceService
from voice.stt import SpeechToTextEngine
from voice.tts import TextToSpeechEngine
from voice.hotkey import GlobalHotKeyManager
from voice.pipeline import (
    VoicePipeline,
    VoicePipelineResult,
    extract_speech_text,
    is_voice_exit_command,
    VOICE_EXIT_COMMANDS,
)

__all__ = [
    "VoiceService",
    "VoicePipeline",
    "VoicePipelineResult",
    "SpeechToTextEngine",
    "TextToSpeechEngine",
    "GlobalHotKeyManager",
    "clean_for_speech",
    "normalize_text_for_speech",
    "extract_speech_text",
    "is_voice_exit_command",
    "VOICE_EXIT_COMMANDS",
]
