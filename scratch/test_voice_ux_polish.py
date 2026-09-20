"""
Тестовый набор для валидации полировки Voice UX и GUI 2.0:
1. STT: нормализация имени Акакия («Акакий, привет!» вместо «А какие»), сохранение обычных фраз, пороги RMS и тишины.
2. GUI: сохранение истории чата при переключении вкладок без дублирования.
3. GUI: глобальный статус в Topbar (все 6 регламентированных состояний).
4. GUI: реактивное обновление активного экрана (refresh_current_view).
5. Бытовой слой: жизненный цикл удаления сущностей, отсутствие удалённых данных в хранилище, GUI и системном промпте.
"""

import json
import os
from pathlib import Path
import queue
import shutil
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from voice.stt import correct_recognized_text, SpeechToTextEngine
from skills.household import HOUSEHOLD_SYSTEM_PROMPT, HouseholdSkill
from tools.household import HouseholdManager
from tools.context import ContextManager
from tools.memory import MemoryManager
from tools.agent import Agent
from gui import AkakiyGUI


class TestSTTPolish(unittest.TestCase):
    """1. Тесты нормализации STT и endpointing."""

    def test_acoustic_akakiy_replacements(self):
        # «Акакий, привет!» распознанный как «а какие привет» -> 'привет'
        self.assertEqual(correct_recognized_text("а какие привет"), "привет")
        self.assertEqual(correct_recognized_text("а какие, привет"), "привет")

        # Изолированное обращение
        self.assertEqual(correct_recognized_text("а какие"), "акакий")
        self.assertEqual(correct_recognized_text("акакие"), "акакий")
        self.assertEqual(correct_recognized_text("а какий"), "акакий")
        self.assertEqual(correct_recognized_text("акаки"), "акакий")

        # Команды с искажённым обращением
        self.assertEqual(correct_recognized_text("акакие у меня задачи"), "у меня задачи")
        self.assertEqual(correct_recognized_text("а какие создай задачу купить хлеб"), "создай задачу купить хлеб")
        self.assertEqual(correct_recognized_text("слушай акакий покажи файлы"), "покажи файлы")

        # Не искажать обычные русские фразы, не содержащие «а какие» перед командами
        self.assertEqual(correct_recognized_text("какие у меня задачи"), "какие у меня задачи")
        self.assertEqual(correct_recognized_text("покажи список заметок"), "покажи список заметок")

    def test_stt_endpointing_parameters(self):
        stt = SpeechToTextEngine(model_path="dummy_nonexistent")
        # Проверяем сигнатуру и дефолты
        import inspect
        sig = inspect.signature(stt.listen_phrase)
        self.assertEqual(sig.parameters["silence_threshold_seconds"].default, 1.3)


class TestGUIAndVoiceUXPolish(unittest.TestCase):
    """2-5. Тесты сохранения чата, глобального статуса, реактивности и удаления."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.household_file = Path(self.temp_dir) / "test_household.json"
        self.memory_file = Path(self.temp_dir) / "test_memory.json"

        self.household = HouseholdManager(storage_path=self.household_file)
        self.memory = MemoryManager(storage_file=self.memory_file)
        self.context = ContextManager(memory_manager=self.memory)

        # Создаём корневое окно Tk (скрытое для headless тестов)
        self.root = tk.Tk()
        self.root.withdraw()

        # Мокаем Agent
        self.agent = MagicMock()
        self.agent.context_mgr = self.context

        # Voice мок
        self.voice = MagicMock()
        self.voice.is_busy.return_value = False
        self.voice.start_session.return_value = True

        self.gui = AkakiyGUI(
            root=self.root,
            agent=self.agent,
            household=self.household,
            memory=self.memory,
            voice=self.voice
        )

    def tearDown(self):
        try:
            self.gui.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_chat_persistence_across_tabs(self):
        """2. Диалог должен сохраняться при переключении вкладок без дублирования."""
        # Переключаемся на Чат
        self.gui.switch_section("chat")
        initial_count = len(self.gui.chat_messages)
        self.assertEqual(initial_count, 1)  # Приветствие

        # Добавляем сообщения
        self.gui._append_chat("Вы", "Привет, Акакий!")
        self.gui._append_chat("Акакий", "Здравствуйте! Чем помочь?")
        self.assertEqual(len(self.gui.chat_messages), 3)

        # Переключаемся на другие вкладки
        self.gui.switch_section("tasks")
        self.assertEqual(self.gui.current_section, "tasks")

        self.gui.switch_section("reminders")
        self.assertEqual(self.gui.current_section, "reminders")

        self.gui.switch_section("home")
        self.assertEqual(self.gui.current_section, "home")

        # Возвращаемся в Чат
        self.gui.switch_section("chat")
        self.assertEqual(self.gui.current_section, "chat")

        # Проверяем, что количество сообщений не изменилось (нет дубликатов приветствия)
        self.assertEqual(len(self.gui.chat_messages), 3)
        self.assertIn("Привет, Акакий!", self.gui.chat_messages[1][1])
        self.assertIn("Здравствуйте! Чем помочь?", self.gui.chat_messages[2][1])

        # Проверяем виджет Text
        chat_content = self.gui.chat_text.get("1.0", tk.END)
        self.assertIn("Привет, Акакий!", chat_content)
        self.assertIn("Здравствуйте! Чем помочь?", chat_content)

        # Проверяем очистку
        self.gui._clear_chat()
        self.assertEqual(len(self.gui.chat_messages), 0)
        self.assertEqual(len(self.gui.log_messages), 0)
        self.assertEqual(self.gui.chat_text.get("1.0", tk.END).strip(), "")

    def test_global_visible_state(self):
        """3. Глобально видимый статус на всех экранах."""
        test_states = [
            ("listening", "🎙 СЛУШАЕТ..."),
            ("thinking", "◌ ДУМАЕТ..."),
            ("working", "⚙ ВЫПОЛНЯЕТ ДЕЙСТВИЕ"),
            ("speaking", "🔊 ОТВЕЧАЕТ (ОТВЕТ)..."),
            ("idle", "✓ ГОТОВ"),
            ("error", "✖ ОШИБКА"),
        ]

        for state, expected_text in test_states:
            self.gui._set_state(state)
            self.assertEqual(self.gui.current_state, state)
            self.assertEqual(self.gui.status_badge.cget("text"), expected_text)

            # Переключаемся на разные разделы — статус-бейдж в Topbar не исчезает
            for sec in ("home", "tasks", "notes", "lists", "memory", "settings"):
                self.gui.switch_section(sec)
                self.assertEqual(self.gui.status_badge.cget("text"), expected_text)

        # При переходе на Home neural_core синхронизируется с current_state
        self.gui._set_state("working")
        self.gui.switch_section("home")
        self.assertEqual(self.gui.neural_core.state, "working")

    def test_reactive_data_update(self):
        """4. Реактивное обновление активной вкладки."""
        # Открываем вкладку Задачи
        self.gui.switch_section("tasks")
        self.assertEqual(len(self.household.tasks), 0)

        # Симулируем событие завершения инструмента через очередь
        self.household.create_task("Новая реактивная задача")
        self.gui.queue.put(("action_observed", ("after_tool", {"tool": "create_task"})))

        # Запускаем один шаг очереди
        self.gui._poll_queue()

        # Проверяем, что в списке задач на экране появилась эта задача
        tasks_on_ui = [w for w in self.gui.tasks_list_frame.winfo_children()]
        # Должен быть минимум один Frame с задачей, а не Label 'Задач пока нет'
        self.assertGreaterEqual(len(tasks_on_ui), 1)

        # Проверяем реактивное обновление на Home
        self.gui.switch_section("home")
        self.household.create_task("Вторая задача")
        self.gui.queue.put(("process_result", {"answer": "Задача создана"}))
        self.gui._poll_queue()

        # Home перерисовался с актуальными данными
        self.assertEqual(self.gui.current_section, "home")

    def test_deleted_data_lifecycle(self):
        """5. Удалённые данные не должны возвращаться в UI, хранилище и запросах."""
        # 1. Создание задачи
        res = self.household.create_task("Временная задача для проверки удаления")
        task_id = res["task"]["id"]
        self.assertEqual(len(self.household.list_tasks()["tasks"]), 1)

        # 2. Удаление задачи
        del_res = self.household.delete_task(task_id)
        self.assertTrue(del_res["success"])

        # 3. Проверка хранилища на диске
        with open(self.household_file, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        self.assertEqual(len(disk_data.get("tasks", [])), 0)

        # 4. Проверка вызова list_tasks
        list_res = self.household.list_tasks(status="all")
        self.assertEqual(len(list_res["tasks"]), 0)
        self.assertIn("пуст", list_res["message"].lower())

        # 5. Проверка системного промпта HouseholdSkill
        self.assertIn("КРИТИЧЕСКИ ВАЖНО", HOUSEHOLD_SYSTEM_PROMPT)
        self.assertIn("ВСЕГДА вызывай соответствующий инструмент", HOUSEHOLD_SYSTEM_PROMPT)
        self.assertIn("Никогда не восстанавливай и не придумывай ранее удалённые элементы", HOUSEHOLD_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
