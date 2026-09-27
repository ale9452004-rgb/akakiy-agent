"""
Модульные тесты для Voice Pipeline (Этап №17).

Проверяет:
1. Извлечение речевого ответа extract_speech_text (chat, subagents, tools, plans, errors, AgentResult).
2. Детекцию команд выхода и отмены is_voice_exit_command.
3. Модель результата VoicePipelineResult (статусы, свойства, dict-like доступ).
4. Обработку фраз через VoicePipeline.process_phrase (пустая речь, wake word, exit, агент, ошибки, отмена).
5. Пошаговое исполнение VoicePipeline.run_step (STT -> Agent -> TTS, Push-to-Talk, STT ошибки).
6. Интеграцию VoiceService с VoicePipeline (делегирование, speak_phrase, is_running, синхронизация).
"""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from voice.pipeline import (
    VoicePipeline,
    VoicePipelineResult,
    extract_speech_text,
    is_voice_exit_command,
    VOICE_EXIT_COMMANDS,
)
from voice.service import VoiceService
from tools.agents.result import AgentResult, Artifact, ArtifactType


class TestExtractSpeechText(unittest.TestCase):
    """Тестирование универсального извлечения речевого текста из ответов всех типов."""

    def test_plain_string(self):
        self.assertEqual(extract_speech_text("Привет, мир!"), "Привет, мир!")
        self.assertEqual(extract_speech_text(""), "")
        self.assertEqual(extract_speech_text(None), "")

    def test_agent_result_object(self):
        # Успешный результат субагента
        art = Artifact(type=ArtifactType.DOCUMENT, path="doc.docx", name="doc")
        res_ok = AgentResult(
            success=True,
            message="Документ успешно сгенерирован: doc.docx",
            artifacts=[art]
        )
        self.assertEqual(extract_speech_text(res_ok), "Документ успешно сгенерирован: doc.docx")

        # Ошибка субагента
        res_fail = AgentResult(
            success=False,
            message="Сбой генерации",
            error="Файл занят другим процессом"
        )
        self.assertEqual(extract_speech_text(res_fail), "Ошибка: Файл занят другим процессом")

    def test_chat_dict(self):
        payload = {"type": "chat", "answer": "Погода сегодня солнечная, +22 градуса."}
        self.assertEqual(extract_speech_text(payload), "Погода сегодня солнечная, +22 градуса.")

    def test_subagent_dict(self):
        # Презентация
        pres_payload = {
            "type": "presentation",
            "tool": "presentation",
            "answer": "Презентация по архитектуре успешно создана.",
            "success": True
        }
        self.assertEqual(extract_speech_text(pres_payload), "Презентация по архитектуре успешно создана.")

        # Картинка с ошибкой
        img_fail = {
            "type": "image",
            "tool": "image",
            "success": False,
            "error": "ComfyUI сервер недоступен"
        }
        self.assertEqual(extract_speech_text(img_fail), "Ошибка: ComfyUI сервер недоступен")

    def test_tool_dict(self):
        # Бытовой инструмент (создание задачи)
        tool_payload = {
            "type": "tool",
            "tool": "create_task",
            "result": {
                "success": True,
                "result": {"message": "Задача #5 'Купить молоко' успешно создана."}
            }
        }
        self.assertEqual(extract_speech_text(tool_payload), "Задача #5 'Купить молоко' успешно создана.")

        # Поиск файлов в проекте
        files_payload = {
            "type": "tool",
            "tool": "find_file",
            "result": {
                "success": True,
                "result": {"count": 12, "files": ["a.py", "b.py"]}
            }
        }
        self.assertEqual(extract_speech_text(files_payload), "В проекте найдено 12 файлов.")

        # Сбой инструмента
        tool_fail = {
            "type": "tool",
            "tool": "delete_task",
            "result": {
                "success": False,
                "error": "Задача #999 не найдена"
            }
        }
        self.assertEqual(extract_speech_text(tool_fail), "Ошибка: Задача #999 не найдена")

    def test_plan_dict(self):
        plan_ok = {
            "type": "plan_execution",
            "tool": "execute_plan",
            "result": {
                "success": True,
                "summary": "Все 4 шага плана успешно завершены."
            }
        }
        self.assertEqual(extract_speech_text(plan_ok), "Все 4 шага плана успешно завершены.")

        plan_fail = {
            "type": "plan_execution",
            "result": {
                "success": False,
                "error": "Шаг 2 прерван из-за синтаксической ошибки."
            }
        }
        self.assertEqual(extract_speech_text(plan_fail), "Ошибка выполнения плана: Шаг 2 прерван из-за синтаксической ошибки.")

    def test_error_dict(self):
        err_payload = {"type": "error", "error": "Модель Ollama перегружена."}
        self.assertEqual(extract_speech_text(err_payload), "Ошибка: Модель Ollama перегружена.")


class TestVoiceExitCommands(unittest.TestCase):
    """Тестирование детектора команд выхода из голосового режима."""

    def test_exit_phrases(self):
        self.assertTrue(is_voice_exit_command("стоп"))
        self.assertTrue(is_voice_exit_command("хватит"))
        self.assertTrue(is_voice_exit_command("отмена"))
        self.assertTrue(is_voice_exit_command("выключи голос"))
        self.assertTrue(is_voice_exit_command("отключи голос!"))
        self.assertTrue(is_voice_exit_command("выруби голос"))
        self.assertTrue(is_voice_exit_command("отключись"))
        self.assertTrue(is_voice_exit_command("пока"))
        self.assertTrue(is_voice_exit_command("заверши сеанс"))

    def test_non_exit_phrases(self):
        self.assertFalse(is_voice_exit_command("создай задачу купить хлеб"))
        self.assertFalse(is_voice_exit_command("какая сегодня погода"))
        self.assertFalse(is_voice_exit_command("покажи список задач"))
        self.assertFalse(is_voice_exit_command(""))
        self.assertFalse(is_voice_exit_command(None))


class TestVoicePipelineResult(unittest.TestCase):
    """Тестирование модели результата VoicePipelineResult."""

    def test_properties_and_dict_access(self):
        res = VoicePipelineResult(
            status="success",
            recognized_text="акакий создай заметку",
            cleaned_command="создай заметку",
            spoken_text="Заметка создана.",
            duration_seconds=0.45
        )
        self.assertTrue(res.is_success)
        self.assertFalse(res.is_exit)
        self.assertFalse(res.is_empty)
        self.assertFalse(res.is_cancelled)
        self.assertFalse(res.is_error)

        # Dict-like доступ
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["recognized_text"], "акакий создай заметку")
        self.assertEqual(res.get("spoken_text"), "Заметка создана.")
        self.assertAlmostEqual(res.duration_seconds, 0.45)

        # Repr
        self.assertIn("status='success'", repr(res))


class TestVoicePipelineProcessPhrase(unittest.TestCase):
    """Тестирование метода VoicePipeline.process_phrase."""

    def setUp(self):
        self.mock_agent = MagicMock()
        self.mock_stt = MagicMock()
        self.mock_tts = MagicMock()
        self.events = []

        def event_sink(evt, data):
            self.events.append((evt, data))

        self.pipeline = VoicePipeline(
            agent=self.mock_agent,
            stt=self.mock_stt,
            tts=self.mock_tts,
            event_sink=event_sink
        )

        def sync_speak(text, on_finish=None):
            if on_finish and callable(on_finish):
                on_finish()

        self.mock_tts.speak.side_effect = sync_speak

    def test_empty_phrase_handling(self):
        res = self.pipeline.process_phrase("   ")
        self.assertTrue(res.is_empty)
        self.assertEqual(res.status, "empty")
        self.mock_agent.process.assert_not_called()
        self.mock_tts.speak.assert_not_called()
        self.assertEqual(self.pipeline.state, "idle")

    def test_exit_command_triggers_mode_toggle_and_speech(self):
        res = self.pipeline.process_phrase("выключи голос")
        self.assertTrue(res.is_exit)
        self.assertEqual(res.spoken_text, "Голосовой режим отключён.")
        self.mock_agent.process.assert_not_called()
        self.mock_tts.speak.assert_called_once()
        self.assertIn("Голосовой режим отключён.", self.mock_tts.speak.call_args[0][0])

        # Проверяем события
        event_types = [e[0] for e in self.events]
        self.assertIn("voice_recognized", event_types)
        self.assertIn("voice_mode_toggle", event_types)
        # Toggle передал enabled=False
        toggle_data = [e[1] for e in self.events if e[0] == "voice_mode_toggle"][0]
        self.assertFalse(toggle_data["enabled"])

    def test_wake_word_only_greeting(self):
        res = self.pipeline.process_phrase("слушай акакий")
        self.assertTrue(res.is_success)
        self.assertEqual(res.spoken_text, "Да, я здесь! Чем могу помочь?")
        self.mock_agent.process.assert_not_called()
        self.mock_tts.speak.assert_called_once()
        self.assertIn("Да, я здесь! Чем могу помочь?", self.mock_tts.speak.call_args[0][0])

    def test_normal_command_processed_and_spoken(self):
        self.mock_agent.process.return_value = {
            "type": "chat",
            "answer": "Конечно, файл сохранён!"
        }

        res = self.pipeline.process_phrase("акакий, сохрани файл main.py")
        self.assertTrue(res.is_success)
        self.assertEqual(res.cleaned_command, "сохрани файл main.py")
        self.mock_agent.process.assert_called_once_with("сохрани файл main.py")
        self.mock_tts.speak.assert_called_once()
        self.assertIn("Конечно, файл сохранён!", self.mock_tts.speak.call_args[0][0])

        event_types = [e[0] for e in self.events]
        self.assertIn("voice_recognized", event_types)
        self.assertIn("voice_agent_result", event_types)

    def test_agent_exception_handled_gracefully(self):
        self.mock_agent.process.side_effect = RuntimeError("Сбой базы данных")

        res = self.pipeline.process_phrase("покажи заметки")
        self.assertTrue(res.is_error)
        self.assertIn("Сбой базы данных", res.error)
        self.assertIn("Ошибка", res.spoken_text)
        self.mock_tts.speak.assert_called_once()

    def test_cancellation_via_stop_event(self):
        stop_event = threading.Event()
        stop_event.set()

        res = self.pipeline.process_phrase("создай задачу", stop_event=stop_event)
        self.assertTrue(res.is_cancelled)
        self.mock_agent.process.assert_not_called()
        self.mock_tts.speak.assert_not_called()


class TestVoicePipelineRunStep(unittest.TestCase):
    """Тестирование пошагового выполнения VoicePipeline.run_step."""

    def setUp(self):
        self.mock_agent = MagicMock()
        self.mock_stt = MagicMock()
        self.mock_tts = MagicMock()
        self.events = []

        def event_sink(evt, data):
            self.events.append((evt, data))

        self.pipeline = VoicePipeline(
            agent=self.mock_agent,
            stt=self.mock_stt,
            tts=self.mock_tts,
            event_sink=event_sink
        )

        def sync_speak(text, on_finish=None):
            if on_finish and callable(on_finish):
                on_finish()

        self.mock_tts.speak.side_effect = sync_speak

    def test_successful_step(self):
        self.mock_stt.listen_phrase.return_value = ("создай задачу помыть посуду", None)
        self.mock_agent.process.return_value = {
            "type": "tool",
            "result": {"message": "Задача создана."}
        }

        res = self.pipeline.run_step()
        self.assertTrue(res.is_success)
        self.assertEqual(res.recognized_text, "создай задачу помыть посуду")
        self.assertEqual(res.spoken_text, "Задача создана.")
        self.mock_agent.process.assert_called_once_with("создай задачу помыть посуду")
        self.mock_tts.speak.assert_called_once()

    def test_stt_returns_empty_silence(self):
        self.mock_stt.listen_phrase.return_value = ("", None)
        res = self.pipeline.run_step()
        self.assertTrue(res.is_empty)
        self.mock_agent.process.assert_not_called()

    def test_stt_returns_hardware_error(self):
        self.mock_stt.listen_phrase.return_value = ("", "Микрофон отключен или недоступен.")
        res = self.pipeline.run_step()
        self.assertTrue(res.is_error)
        self.assertEqual(res.error, "Микрофон отключен или недоступен.")
        self.assertEqual(self.pipeline.state, "error")

        event_types = [e[0] for e in self.events]
        self.assertIn("voice_error", event_types)

    def test_stop_event_during_step(self):
        stop_event = threading.Event()
        stop_event.set()

        self.mock_stt.listen_phrase.return_value = ("", None)
        res = self.pipeline.run_step(stop_event=stop_event)
        self.assertTrue(res.is_cancelled)


class TestVoiceServicePipelineIntegration(unittest.TestCase):
    """Тестирование интеграции VoiceService с VoicePipeline и обратной совместимости."""

    def setUp(self):
        self.mock_agent = MagicMock()
        self.mock_agent.process.return_value = {"type": "chat", "answer": "Готово!"}

        self.vs = VoiceService(agent=self.mock_agent, event_sink=None)
        self.vs.stt = MagicMock()
        self.vs.tts = MagicMock()

        def sync_speak(text, on_finish=None):
            if on_finish and callable(on_finish):
                on_finish()

        self.vs.tts.speak.side_effect = sync_speak

    def tearDown(self):
        self.vs.stop_session()

    def test_process_phrase_direct(self):
        res = self.vs.process_phrase("акакий, проведи тест")
        self.assertTrue(res.is_success)
        self.assertEqual(res.cleaned_command, "проведи тест")
        self.mock_agent.process.assert_called_once_with("проведи тест")
        self.vs.tts.speak.assert_called_once()

    def test_speak_phrase_alias(self):
        # speak_phrase должно быть алиасом к speak_text
        self.vs.speak_phrase("Тестовая реплика")
        self.vs.tts.speak.assert_called_once()
        self.assertIn("Тестовая реплика", self.vs.tts.speak.call_args[0][0])

    def test_is_running_property(self):
        self.assertFalse(self.vs.is_running)

    def test_sync_pipeline_when_mocks_reassigned(self):
        # Проверяем, что замена stt/tts на экземпляре VoiceService прозрачно обновляет pipeline
        new_stt = MagicMock()
        new_tts = MagicMock()
        self.vs.stt = new_stt
        self.vs.tts = new_tts

        self.vs._sync_pipeline()
        self.assertIs(self.vs.pipeline.stt, new_stt)
        self.assertIs(self.vs.pipeline.tts, new_tts)


if __name__ == "__main__":
    unittest.main()
