"""
Automated test suite verifying Voice Integration in Akakiy GUI 2.0:
1. Voice session start/stop via UI button.
2. Audio level reactive modulation on NeuralCore.
3. Voice speech recognition pipeline (STT -> GUI Chat).
4. Voice Agent result dispatch to GUI Chat and NeuralCore.
5. Exit command ('стоп' / voice_mode_toggle) triggering automatic shutdown.
6. Full end-to-end loop with real VoiceService pipeline (mocking audio I/O).
"""

import os
import sys
import time
import unittest
import tkinter as tk
from unittest.mock import MagicMock, patch

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from gui import AkakiyGUI
from voice.service import VoiceService
from tools.household import HouseholdManager
from tools.memory import MemoryManager


class TestGUIVoiceIntegration(unittest.TestCase):

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.mock_agent = MagicMock()
        self.mock_agent.process.return_value = {
            "type": "chat",
            "answer": "Конечно, задача создана!"
        }

        self.mock_voice = MagicMock()
        self.mock_voice.is_busy.return_value = False
        self.mock_voice.start_session.return_value = True

        self.gui = AkakiyGUI(
            self.root,
            agent=self.mock_agent,
            household=MagicMock(),
            memory=MagicMock(),
            voice=self.mock_voice
        )
        self.root.update_idletasks()

    def tearDown(self):
        try:
            self.gui.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_button_starts_voice_session(self):
        self.assertFalse(self.gui.voice_enabled)
        self.assertEqual(self.gui.btn_mic.cget("text"), "🎙 Голос")

        # Click mic button
        self.gui._on_toggle_voice()
        self.mock_voice.start_session.assert_called_once_with(continuous=True)
        self.assertTrue(self.gui.voice_enabled)
        self.assertEqual(self.gui.btn_mic.cget("text"), "⏹ Стоп")
        self.assertEqual(self.gui.chip_voice.cget("text"), "ГОЛОС: ВКЛ")
        self.assertEqual(self.gui.neural_core.state, "listening")

    def test_button_stops_voice_session(self):
        # Start first
        self.gui._on_toggle_voice()
        self.assertTrue(self.gui.voice_enabled)

        # Click again to stop
        self.gui._on_toggle_voice()
        self.mock_voice.stop_session.assert_called_once()
        self.assertFalse(self.gui.voice_enabled)
        self.assertEqual(self.gui.btn_mic.cget("text"), "🎙 Голос")
        self.assertEqual(self.gui.chip_voice.cget("text"), "ГОЛОС: ВЫКЛ")
        self.assertEqual(self.gui.neural_core.state, "idle")

    def test_audio_level_event_updates_neural_core(self):
        self.gui._on_toggle_voice()
        # VoiceService emits voice_audio_level
        self.gui._on_voice_event("voice_audio_level", {"level": 0.88})
        self.gui._poll_queue()
        self.assertAlmostEqual(self.gui.neural_core.audio_level, 0.88, places=2)

    def test_voice_recognized_event_appends_chat(self):
        self.gui.switch_view("chat")
        self.gui._on_voice_event("voice_recognized", {"text": "привет акакий"})
        self.gui._poll_queue()
        chat_content = self.gui.chat_text.get("1.0", tk.END)
        self.assertIn("привет акакий", chat_content)
        self.assertIn("ВЫ (ГОЛОС)", chat_content.upper())

    def test_voice_agent_result_appends_chat(self):
        self.gui.switch_view("chat")
        payload = {
            "payload": {"answer": "Здравствуйте! Рад слышать вас."},
            "query": "привет"
        }
        self.gui._on_voice_event("voice_agent_result", payload)
        self.gui._poll_queue()
        chat_content = self.gui.chat_text.get("1.0", tk.END)
        self.assertIn("Здравствуйте! Рад слышать вас.", chat_content)
        self.assertIn("АКАКИЙ (ГОЛОС)", chat_content.upper())

    def test_voice_state_event_updates_ui_state(self):
        self.gui._on_voice_event("voice_state", {"state": "thinking"})
        self.gui._poll_queue()
        self.assertEqual(self.gui.neural_core.state, "thinking")
        self.assertIn("ДУМАЕТ", self.gui.status_badge.cget("text"))

        self.gui._on_voice_event("voice_state", {"state": "speaking"})
        self.gui._poll_queue()
        self.assertEqual(self.gui.neural_core.state, "speaking")
        self.assertIn("ОТВЕТ", self.gui.status_badge.cget("text"))

    def test_voice_mode_toggle_exits_mode(self):
        # Start voice mode
        self.gui._on_toggle_voice()
        self.assertTrue(self.gui.voice_enabled)

        # VoiceService sends exit command event (user said "стоп" / "выключи голос")
        self.gui._on_voice_event("voice_mode_toggle", {"enabled": False})
        self.gui._poll_queue()

        self.assertFalse(self.gui.voice_enabled)
        self.assertEqual(self.gui.btn_mic.cget("text"), "🎙 Голос")
        self.assertEqual(self.gui.chip_voice.cget("text"), "ГОЛОС: ВЫКЛ")
        self.assertEqual(self.gui.neural_core.state, "idle")

    def test_voice_error_event_shows_error_state(self):
        self.gui._on_voice_event("voice_error", {"message": "Микрофон не найден"})
        self.gui._poll_queue()
        self.assertEqual(self.gui.neural_core.state, "error")
        self.assertIn("ОШИБКА", self.gui.status_badge.cget("text"))


class TestVoiceServiceLivePipeline(unittest.TestCase):
    """Verifies end-to-end integration with the real VoiceService coordinator."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.mock_agent = MagicMock()
        self.mock_agent.process.return_value = {
            "type": "chat",
            "answer": "Сделано!"
        }

        self.voice_service = VoiceService(agent=self.mock_agent, event_sink=None)
        self.voice_service.stt = MagicMock()
        self.voice_service.tts = MagicMock()

        def mock_speak(text, on_finish=None):
            if on_finish and callable(on_finish):
                on_finish()

        self.voice_service.tts.speak.side_effect = mock_speak

        self.gui = AkakiyGUI(
            self.root,
            agent=self.mock_agent,
            household=MagicMock(),
            memory=MagicMock(),
            voice=self.voice_service
        )
        # Connect real event_sink to GUI
        self.voice_service.event_sink = self.gui._on_voice_event
        self.root.update_idletasks()

    def tearDown(self):
        try:
            self.voice_service.stop_session()
        except Exception:
            pass
        try:
            self.gui.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_end_to_end_dialogue_then_voice_exit(self):
        """
        Step 1: User says 'создай заметку' -> Agent processes -> TTS speaks answer.
        Step 2: User says 'стоп' -> Exit triggered -> Voice mode disabled automatically.
        """
        dialogue_phrases = [
            ("создай заметку купить хлеб", None),
            ("стоп", None),
        ]
        phrase_iter = iter(dialogue_phrases)

        def mock_listen_phrase(*args, **kwargs):
            try:
                text, err = next(phrase_iter)
                # trigger level callback
                lvl_cb = kwargs.get("on_level_callback")
                if lvl_cb:
                    lvl_cb(0.7)
                return text, err
            except StopIteration:
                return "", None

        self.voice_service.stt.listen_phrase.side_effect = mock_listen_phrase

        # 1. Click button to start
        self.gui._on_toggle_voice()
        self.assertTrue(self.gui.voice_enabled)

        # Wait briefly for thread to process dialogue and exit on "стоп"
        for _ in range(25):
            self.root.update()
            self.gui._poll_queue()
            if not self.voice_service.is_busy():
                break
            time.sleep(0.08)

        # Poll any remaining events
        self.gui._poll_queue()

        # Verify agent was called with the user phrase
        self.mock_agent.process.assert_called_once_with("создай заметку купить хлеб")

        # Verify TTS was invoked
        self.assertTrue(self.voice_service.tts.speak.called)

        # Verify voice mode was automatically switched off by 'стоп'
        self.assertFalse(self.gui.voice_enabled)
        self.assertEqual(self.gui.btn_mic.cget("text"), "🎙 Голос")
        self.assertEqual(self.gui.chip_voice.cget("text"), "ГОЛОС: ВЫКЛ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
