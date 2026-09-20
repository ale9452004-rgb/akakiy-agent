"""
Автоматизированный набор тестов для системы памяти Акакия (Task 33).

Проверяет:
1. Long-term Memory: добавление, поиск, удаление по ID и тексту, очистку.
2. Дедупликацию и фильтрацию мусора (tracebacks, JSON, исключения, превышение длины).
3. Персистентность на диске и обработку сбоев/битых файлов.
4. Short-term Memory: скользящее окно (max_turns), добавление ходов, форматирование.
5. Реестр инструментов: remember, recall_memory, forget_memory через dispatch.
6. Интеграцию в Agent: команды 'запомни:', 'что ты помнишь', 'забудь:', 'найди в памяти:', 'очисти память'.
7. Синхронизацию системного промпта OllamaClient и скользящее окно истории сообщений.
"""

import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Обеспечиваем импорт из корня проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.memory import MemoryManager, is_valid_memory_text, normalize_for_comparison
from tools.dispatcher import dispatch
from tools.registry import TOOLS
from ollama_client import OllamaClient
from tools.agent import Agent


class TestMemoryValidationAndFiltering(unittest.TestCase):
    """Тестирование валидации и фильтрации мусора/шума."""

    def test_valid_human_texts(self):
        valid_examples = [
            "Мой любимый цвет синий",
            "Сервер базы данных работает на порту 5432",
            "Никогда не используй eval в коде",
            "Пользователь предпочитает короткие ответы",
            "Папка с логами: C:\\logs\\app",
        ]
        for text in valid_examples:
            is_valid, err = is_valid_memory_text(text)
            self.assertTrue(is_valid, f"Expected valid for '{text}', got error: {err}")

    def test_rejection_empty_and_short(self):
        invalid_examples = ["", "   ", ".,!?", "a", "ок", "  --  "]
        for text in invalid_examples:
            is_valid, err = is_valid_memory_text(text)
            self.assertFalse(is_valid, f"Expected invalid for '{text}'")

    def test_rejection_excessive_length(self):
        long_text = "слово " * 150  # > 500 символов
        is_valid, err = is_valid_memory_text(long_text)
        self.assertFalse(is_valid)
        self.assertIn("слишком длинный", err)

    def test_rejection_traceback(self):
        tb = (
            "Traceback (most recent call last):\n"
            '  File "main.py", line 12, in <module>\n'
            "ZeroDivisionError: division by zero"
        )
        is_valid, err = is_valid_memory_text(tb)
        self.assertFalse(is_valid)
        self.assertIn("трейсбек", err.lower())

    def test_rejection_exception_dumps(self):
        dumps = [
            "SyntaxError: invalid syntax in test.py at line 5",
            "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
            "ValueError: could not convert string to float: 'abc'",
            "FileNotFoundError: [Errno 2] No such file or directory: 'file.txt'",
        ]
        for dump in dumps:
            is_valid, err = is_valid_memory_text(dump)
            self.assertFalse(is_valid, f"Expected rejection for dump: '{dump}'")

    def test_rejection_raw_json_xml(self):
        raw_formats = [
            '{"error": 500, "status": "internal_failure", "retries": 3}',
            '[{"id": 1, "value": "test"}, {"id": 2}]',
            '<xml><status>failed</status><code count="2"/></xml>',
        ]
        for item in raw_formats:
            is_valid, err = is_valid_memory_text(item)
            self.assertFalse(is_valid, f"Expected rejection for raw payload: '{item}'")

    def test_normalization_comparison(self):
        t1 = "  Пользователь любит Python!  "
        t2 = "пользователь любит python"
        self.assertEqual(normalize_for_comparison(t1), normalize_for_comparison(t2))


class TestMemoryManagerLongTerm(unittest.TestCase):
    """Тестирование CRUD и персистентности долговременной памяти."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_memory.json"
        self.mem = MemoryManager(storage_path=self.storage_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_remember_and_recall(self):
        success, msg, *_ = self.mem.remember("Порт веб-сервера 8080")
        self.assertTrue(success)
        self.assertIn("Запомнил", msg)

        # Проверяем recall всех
        all_mem = self.mem.recall()
        self.assertEqual(len(all_mem), 1)
        self.assertEqual(all_mem[0]["id"], 1)
        self.assertEqual(all_mem[0]["text"], "Порт веб-сервера 8080")

    def test_deduplication(self):
        s1, *_ = self.mem.remember("Использовать PostgreSQL для БД")
        self.assertTrue(s1)

        # Повторное добавление того же факта
        s2, msg2, *_ = self.mem.remember("использовать postgresql для бд!")
        self.assertFalse(s2)
        self.assertIn("уже есть", msg2)
        self.assertEqual(len(self.mem.recall()), 1)

    def test_search(self):
        self.mem.remember("Фронтенд написан на React")
        self.mem.remember("Бэкенд использует FastAPI и Python")
        self.mem.remember("База данных PostgreSQL")

        found_py = self.mem.search("python")
        self.assertEqual(len(found_py), 1)
        self.assertEqual(found_py[0]["id"], 2)

        found_db = self.mem.search("база")
        self.assertEqual(len(found_db), 1)
        self.assertEqual(found_db[0]["id"], 3)

        found_none = self.mem.search("несуществующий")
        self.assertEqual(len(found_none), 0)

    def test_forget_by_id(self):
        self.mem.remember("Факт номер один")
        self.mem.remember("Факт номер два")

        # Удаление по строковому ID
        s1, m1 = self.mem.forget("1")
        self.assertTrue(s1)
        self.assertIn("Удалил", m1)
        self.assertEqual(len(self.mem.recall()), 1)
        self.assertEqual(self.mem.recall()[0]["id"], 2)

        # Удаление несуществующего ID
        s2, m2 = self.mem.forget("99")
        self.assertFalse(s2)

    def test_forget_by_text(self):
        self.mem.remember("Тестовый сервер на порту 3000")
        self.mem.remember("Продакшн на порту 80")

        s, m = self.mem.forget("порту 3000")
        self.assertTrue(s)
        self.assertEqual(len(self.mem.recall()), 1)
        self.assertIn("Продакшн", self.mem.recall()[0]["text"])

    def test_clear_long_term(self):
        self.mem.remember("Запись 1")
        self.mem.remember("Запись 2")
        self.assertEqual(len(self.mem.recall()), 2)

        s, m = self.mem.clear_long_term()
        self.assertTrue(s)
        self.assertEqual(len(self.mem.recall()), 0)

    def test_disk_persistence(self):
        self.mem.remember("Постоянный факт проекта")
        self.assertTrue(self.storage_path.exists())

        # Создаем второй экземпляр, указывающий на тот же файл
        mem2 = MemoryManager(storage_path=self.storage_path)
        all_mem = mem2.recall()
        self.assertEqual(len(all_mem), 1)
        self.assertEqual(all_mem[0]["text"], "Постоянный факт проекта")

    def test_graceful_recovery_on_corrupt_file(self):
        # Записываем мусор в файл
        self.storage_path.write_text("{невалидный json: 123", encoding="utf-8")
        # Не должно выбрасывать исключение при инициализации
        mem_corrupt = MemoryManager(storage_path=self.storage_path)
        self.assertEqual(len(mem_corrupt.recall()), 0)
        # Должно успешно работать и перетереть битый файл
        s, *_ = mem_corrupt.remember("Новый факт после сбоя")
        self.assertTrue(s)
        self.assertEqual(len(mem_corrupt.recall()), 1)


class TestShortTermMemory(unittest.TestCase):
    """Тестирование скользящего окна краткосрочной памяти диалога."""

    def test_sliding_window_limit(self):
        mem = MemoryManager(max_turns=3)
        for i in range(5):
            mem.add_turn(f"Вопрос {i}", f"Ответ {i}")

        turns = mem.get_recent_turns()
        self.assertEqual(len(turns), 3)
        self.assertEqual(turns[0]["user"], "Вопрос 2")
        self.assertEqual(turns[1]["user"], "Вопрос 3")
        self.assertEqual(turns[2]["user"], "Вопрос 4")

    def test_formatting_turns(self):
        mem = MemoryManager(max_turns=3)
        mem.add_turn("Привет", "Здравствуй!")
        formatted = mem.format_short_term_context()
        self.assertIn("Пользователь: Привет", formatted)
        self.assertIn("Акакий: Здравствуй!", formatted)


class TestDispatcherMemoryTools(unittest.TestCase):
    """Тестирование вызова инструментов памяти через диспетчер."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "disp_mem.json"
        self.mem = MemoryManager(storage_path=self.storage_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_registry_registration(self):
        self.assertIn("remember", TOOLS)
        self.assertIn("recall_memory", TOOLS)
        self.assertIn("forget_memory", TOOLS)

    def test_dispatch_remember_recall_forget(self):
        with patch("tools.memory._global_memory_manager", self.mem), \
             patch("tools.memory.get_memory_manager", return_value=self.mem):
            # remember
            r1 = dispatch("remember", text="Флаг дебага включён")
            self.assertTrue(r1.get("success"), r1)
            self.assertIn("Запомнил", r1.get("result", {}).get("message", ""))

            # recall
            r2 = dispatch("recall_memory", query="дебаг")
            self.assertTrue(r2.get("success"), r2)
            results = r2.get("result", {}).get("memories", [])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["text"], "Флаг дебага включён")

            # forget
            r3 = dispatch("forget_memory", target="дебаг")
            self.assertTrue(r3.get("success"), r3)
            self.assertIn("Удалил", r3.get("result", {}).get("message", ""))

            # recall again
            r4 = dispatch("recall_memory", query="")
            self.assertEqual(len(r4.get("result", {}).get("memories", [])), 0)


class TestOllamaClientHistorySliding(unittest.TestCase):
    """Тестирование скользящего окна сообщений в OllamaClient."""

    def test_history_trimming_preserves_system_prompt(self):
        client = OllamaClient(max_history=6)
        system_content = client.messages[0]["content"]

        # Добавляем 10 взаимодействий (20 сообщений)
        for i in range(10):
            client.add_interaction(f"Вопрос {i}", f"Ответ {i}")

        # Проверяем, что первое сообщение осталось системным
        self.assertEqual(client.messages[0]["role"], "system")
        self.assertEqual(client.messages[0]["content"], system_content)

        # Всего сообщений не больше max_history (6)
        self.assertLessEqual(len(client.messages), 6)

        # Последнее сообщение - это последний ответ
        self.assertEqual(client.messages[-1]["content"], "Ответ 9")


class TestAgentMemoryIntegration(unittest.TestCase):
    """Тестирование работы команд памяти и сохранения контекста в Agent."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "agent_mem.json"
        self.mem = MemoryManager(storage_path=self.storage_path)

        # Мокаем OllamaClient, чтобы тесты не требовали запущенного Ollama
        self.mock_ai = MagicMock(spec=OllamaClient)
        self.mock_ai.messages = [{"role": "system", "content": "Базовый промпт"}]
        self.mock_ai.get_system_prompt.return_value = "Базовый промпт"

        with patch("tools.agent.get_memory_manager", return_value=self.mem), \
             patch("tools.agent.OllamaClient", return_value=self.mock_ai):
            self.agent = Agent()
            self.agent.memory = self.mem

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_command_remember(self):
        res = self.agent.process("запомни: Рабочий порт 9090")
        self.assertEqual(res["type"], "chat")
        self.assertIn("Запомнил", res["answer"])
        self.assertEqual(len(self.mem.recall()), 1)

        # Проверяем, что системный промпт обновился
        self.mock_ai.set_system_prompt.assert_called()
        last_prompt = self.mock_ai.set_system_prompt.call_args[0][0]
        self.assertIn("Рабочий порт 9090", last_prompt)

    def test_command_what_do_you_remember(self):
        self.mem.remember("Имя кота Барсик")
        res = self.agent.process("что ты помнишь")
        self.assertEqual(res["type"], "chat")
        self.assertIn("Барсик", res["answer"])

    def test_command_search_memory(self):
        self.mem.remember("Имя собаки Шарик")
        self.mem.remember("Имя попугая Кеша")

        res = self.agent.process("найди в памяти: Шарик")
        self.assertEqual(res["type"], "chat")
        self.assertIn("Шарик", res["answer"])
        self.assertNotIn("Кеша", res["answer"])

    def test_command_forget(self):
        self.mem.remember("Устаревший токен 12345")
        res1 = self.agent.process("забудь: 12345")
        self.assertEqual(res1["type"], "chat")
        self.assertIn("Удалил", res1["answer"])
        self.assertEqual(len(self.mem.recall()), 0)

    def test_command_clear_memory(self):
        self.mem.remember("Факт А")
        self.mem.remember("Факт Б")
        res = self.agent.process("очисти память")
        self.assertEqual(res["type"], "chat")
        self.assertIn("очищена", res["answer"])
        self.assertEqual(len(self.mem.recall()), 0)

    def test_short_term_interaction_recording(self):
        self.agent.process("запомни: Тестовый факт")
        turns = self.agent.memory.get_recent_turns()
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["user"], "запомни: Тестовый факт")
        self.assertIn("Запомнил", turns[0]["assistant"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
