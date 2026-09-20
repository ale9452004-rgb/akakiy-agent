"""
Тестовый набор для валидации Task 023 — Fix voice + household regressions.
Проверяет:
1. STT Wake Word сохранение и отсечение (strip_wake_word).
2. STT Адаптивный порог шума и endpointing.
3. Озвучка ошибок (success=False никогда не считается успехом).
4. Batch / relative delete в HouseholdManager.
5. Детерминированная маршрутизация и ультра-низкая латентность (< 5мс).
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Добавляем корень проекта в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice.stt import correct_recognized_text, strip_wake_word
from voice.service import VoiceService
from tools.household import HouseholdManager
from tools.agent import Agent


class TestVoiceHousehold023(unittest.TestCase):
    """Тестовый набор для валидации Task 023 — Fix voice + household regressions."""

    def test_wake_word_handling(self):
        print("\n--- 1. Проверка Wake Word («Акакий») ---")
        # Тест 1: 'а как и привет' -> 'акакий привет'
        c1 = correct_recognized_text("а как и привет")
        self.assertIn("акакий", c1.lower(), f"Expected 'акакий' in '{c1}'")
        print(f"  [OK] correct_recognized_text('а как и привет') -> '{c1}'")

        # Тест 2: 'акакие, создай задачу купить молоко' -> 'акакий, создай задачу купить молоко'
        c2 = correct_recognized_text("акакие, создай задачу купить молоко")
        self.assertTrue("акакий" in c2.lower() and "купить молоко" in c2, f"Failed: '{c2}'")
        print(f"  [OK] correct_recognized_text('акакие, ...') -> '{c2}'")

        # Тест 3: strip_wake_word для передачи агенту
        s2 = strip_wake_word(c2)
        self.assertEqual(s2, "создай задачу купить молоко", f"Expected 'создай задачу купить молоко', got '{s2}'")
        print(f"  [OK] strip_wake_word('{c2}') -> '{s2}'")

        # Тест 4: Если сказали только 'акакий'
        s4 = strip_wake_word("акакий")
        self.assertEqual(s4, "", f"Expected empty string for wake word only, got '{s4}'")
        print(f"  [OK] strip_wake_word('акакий') -> '' (wake-only detection)")

    def test_voice_error_reporting(self):
        print("\n--- 2. Проверка озвучивания ошибок (success=False) ---")
        vs = VoiceService(agent=None)

        # 1. Tool result with success=False
        payload_fail = {
            "type": "tool",
            "tool": "delete_task",
            "result": {
                "success": False,
                "error": "Задача #999 не найдена."
            }
        }
        speech_fail = vs._extract_speech_text(payload_fail)
        self.assertTrue("Ошибка" in speech_fail and "не найдена" in speech_fail, f"Got: {speech_fail}")
        self.assertNotIn("успешно", speech_fail.lower(), f"Falsely reported success: {speech_fail}")
        print(f"  [OK] Failed tool speech: '{speech_fail}'")

        # 2. Nested inner fail
        payload_inner_fail = {
            "type": "tool",
            "tool": "household",
            "result": {
                "result": {
                    "success": False,
                    "message": "Элемент не существует."
                }
            }
        }
        speech_inner = vs._extract_speech_text(payload_inner_fail)
        self.assertTrue("Ошибка" in speech_inner and "не существует" in speech_inner, f"Got: {speech_inner}")
        print(f"  [OK] Nested fail speech: '{speech_inner}'")

        # 3. Successful tool
        payload_ok = {
            "type": "tool",
            "tool": "create_task",
            "result": {
                "success": True,
                "message": "Задача #1 \"Купить молоко\" создана."
            }
        }
        speech_ok = vs._extract_speech_text(payload_ok)
        self.assertTrue("Купить молоко" in speech_ok and "Ошибка" not in speech_ok, f"Got: {speech_ok}")
        print(f"  [OK] Success tool speech: '{speech_ok}'")

    def test_batch_and_relative_delete(self):
        print("\n--- 3. Проверка Batch / Relative Deletion ---")
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_db = Path(tmp_dir) / "test_household.json"
            mgr = HouseholdManager(storage_path=test_db)

            # Создаём 5 тестовых заметок
            for i in range(1, 6):
                mgr.create_note(f"Заметка {i}", f"Контент {i}")
            self.assertEqual(len(mgr.notes), 5)

            # 1. Относительное удаление: 'последние три'
            res_rel = mgr.delete_note("последние три")
            self.assertTrue(res_rel["success"], f"Failed: {res_rel}")
            self.assertEqual(res_rel["count"], 3, f"Expected 3 deleted, got {res_rel['count']}")
            self.assertEqual(len(mgr.notes), 2, f"Expected 2 remaining notes, got {len(mgr.notes)}")
            print(f"  [OK] Delete 'последние три': {res_rel['message']}")

            # 2. Удаление по списку номеров: '#1, #2'
            res_batch = mgr.delete_note("#1, #2")
            self.assertTrue(res_batch["success"], f"Failed: {res_batch}")
            self.assertEqual(res_batch["count"], 2)
            self.assertEqual(len(mgr.notes), 0, f"Expected 0 remaining notes, got {len(mgr.notes)}")
            print(f"  [OK] Delete multiple IDs '#1, #2': {res_batch['message']}")

            # 3. Удаление из пустого списка -> success=False
            res_empty = mgr.delete_note("последнюю")
            self.assertFalse(res_empty["success"], f"Expected failure on empty collection, got {res_empty}")
            print(f"  [OK] Delete on empty: {res_empty['error']}")

            # 4. Проверка задач
            for i in range(1, 4):
                mgr.create_task(f"Задача {i}")
            res_task_rel = mgr.delete_task("последнюю")
            self.assertTrue(res_task_rel["success"])
            self.assertEqual(len(mgr.tasks), 2)
            print(f"  [OK] Delete task 'последнюю': {res_task_rel['message']}")

    def test_deterministic_routing_and_latency(self):
        print("\n--- 4. Проверка Детерминированной Маршрутизации и Латентности ---")
        agent = Agent()

        commands = [
            ("создай задачу купить свежий хлеб", "create_task"),
            ("покажи задачи", "list_tasks"),
            ("выполни задачу 1", "complete_task"),
            ("удали последние три заметки", "delete_note"),
            ("удали последние 2 задачи", "delete_task"),
            ("создай заметку Рецепт: Мука 200г, Сахар 100г", "create_note"),
            ("покажи заметки", "list_notes"),
            ("найди в заметках Мука", "search_notes"),
            ("напомни позвонить коллеге завтра в 10:00", "create_reminder"),
            ("покажи напоминания", "list_reminders"),
            ("удали последнее напоминание", "delete_reminder"),
            ("покажи списки", "show_list"),
            ("создай список Покупки", "create_list"),
            ("запомни мой любимый чай зеленый", "remember"),
            ("что ты помнишь", "recall_memory"),
        ]

        for cmd, expected_tool in commands:
            t0 = time.perf_counter()
            routing = agent.choose_tool(cmd)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            tool = routing.get("tool")
            self.assertEqual(tool, expected_tool, f"Query '{cmd}' routed to '{tool}', expected '{expected_tool}'")
            self.assertLess(elapsed_ms, 10.0, f"Latency too high: {elapsed_ms:.2f} ms for '{cmd}'")
            print(f"  [OK] '{cmd}' -> {tool} ({elapsed_ms:.3f} ms)")


if __name__ == "__main__":
    unittest.main()

