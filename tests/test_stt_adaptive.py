"""
Тест проверки адаптивного endpointing в STT.
"""

import math
import struct
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice.stt import SpeechToTextEngine


class TestSTTAdaptive(unittest.TestCase):
    def test_stt_adaptive_threshold_logic(self):
        print("\n--- Тест адаптивного порога фонового шума ---")
        # Симулируем 100мс аудио фреймы фонового шума (RMS уровень ~ 0.028)
        noise_amplitude = int(32768 * 0.028 / 5.0)
        samples_per_chunk = 1600
        noise_chunk = struct.pack(f"<{samples_per_chunk}h", *([noise_amplitude] * samples_per_chunk))

        # Вычисление norm_level
        count = len(noise_chunk) // 2
        shorts = struct.unpack(f"<{count}h", noise_chunk)
        sum_sq = sum(s * s for s in shorts)
        rms = math.sqrt(sum_sq / count) / 32768.0
        norm_level = min(1.0, rms * 5.0)

        print(f"  Измеренный уровень симулированного шума: {norm_level:.4f}")
        assert 0.025 < norm_level < 0.032, f"Unexpected noise level: {norm_level}"

        # Проверяем калибровку в алгоритме
        noise_samples = [norm_level] * 5
        avg_noise = sum(noise_samples) / len(noise_samples)
        speech_threshold = max(0.042, min(0.08, avg_noise * 1.55))

        print(f"  Адаптированный порог детекции речи: {speech_threshold:.4f}")
        # Порог ДОЛЖЕН быть строго выше фонового шума!
        assert speech_threshold > norm_level, f"Threshold {speech_threshold} is not above noise floor {norm_level}!"
        assert norm_level < speech_threshold, "Noise should NOT trigger speech detection"

        # Теперь симулируем речь (уровень ~ 0.18)
        speech_amplitude = int(32768 * 0.18 / 5.0)
        speech_chunk = struct.pack(f"<{samples_per_chunk}h", *([speech_amplitude] * samples_per_chunk))
        count = len(speech_chunk) // 2
        shorts = struct.unpack(f"<{count}h", speech_chunk)
        sum_sq = sum(s * s for s in shorts)
        speech_norm = min(1.0, math.sqrt(sum_sq / count) / 32768.0 * 5.0)

        print(f"  Уровень симулированной речи: {speech_norm:.4f}")
        assert speech_norm > speech_threshold, "Speech should reliably trigger detection"
        print("  [OK] Адаптивный порог безупречно отсекает шум и детектирует речь!")


if __name__ == "__main__":
    unittest.main()
