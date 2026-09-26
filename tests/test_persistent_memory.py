"""
Тесты для модуля Persistent Memory (Этап №16).

Проверяет:
1. Модель MemoryEntry (наследование dict, свойства, алиасы text/category, сериализация).
2. Валидацию и фильтрацию мусора (is_valid_memory_text, normalize_for_comparison).
3. CRUD операции PersistentMemory (create, get, update, delete, clear).
4. Дедупликацию записей при создании и обновлении.
5. Поиск и многокритериальную фильтрацию (query, type, tags, source).
6. Атомарную персистентность, восстановление после перезапуска и автомиграцию v1 -> v2.
7. Явную фиксацию результатов (remember_result).
8. Интеграцию с MemoryManager и изоляцию от краткосрочного контекста.
"""

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from tools.persistent_memory import (
    MemoryEntry,
    PersistentMemory,
    MemoryType,
    MemorySource,
    is_valid_memory_text,
    normalize_for_comparison,
)
from tools.memory import MemoryManager, get_memory_manager
from tools.agents.result import AgentResult, Artifact, ArtifactType


class TestMemoryEntryModel(unittest.TestCase):
    """Тестирование структуры и интерфейса модели MemoryEntry."""

    def test_init_and_dict_compatibility(self):
        entry = MemoryEntry(
            id=1,
            content="Любимый язык Python",
            type=MemoryType.PREFERENCE,
            source=MemorySource.USER,
            tags=["dev", "python"],
            metadata={"priority": "high"}
        )

        # Доступ как к dict
        self.assertEqual(entry["id"], 1)
        self.assertEqual(entry["content"], "Любимый язык Python")
        self.assertEqual(entry["text"], "Любимый язык Python")
        self.assertEqual(entry["type"], "preference")
        self.assertEqual(entry["category"], "preference")
        self.assertEqual(entry["source"], "user")
        self.assertEqual(entry["tags"], ["dev", "python"])
        self.assertEqual(entry["metadata"]["priority"], "high")

        # Доступ через атрибуты
        self.assertEqual(entry.id, 1)
        self.assertEqual(entry.content, "Любимый язык Python")
        self.assertEqual(entry.text, "Любимый язык Python")
        self.assertEqual(entry.type, "preference")
        self.assertEqual(entry.category, "preference")
        self.assertEqual(entry.source, "user")
        self.assertEqual(entry.tags, ["dev", "python"])
        self.assertEqual(entry.metadata, {"priority": "high"})

    def test_attribute_mutations_sync_with_dict(self):
        entry = MemoryEntry(id=2, content="Старый текст")
        entry.content = "Новый текст"
        self.assertEqual(entry["content"], "Новый текст")
        self.assertEqual(entry["text"], "Новый текст")

        entry.type = MemoryType.NOTE
        self.assertEqual(entry["type"], "note")
        self.assertEqual(entry["category"], "note")

        entry.tags = ["tag1", "tag2"]
        self.assertEqual(entry["tags"], ["tag1", "tag2"])

    def test_native_json_serialization(self):
        entry = MemoryEntry(
            id=3,
            content="Сервер на порту 8000",
            type=MemoryType.FACT,
            source=MemorySource.SYSTEM
        )
        # Проверяем, что стандартный json.dumps работает без custom encoder
        serialized = json.dumps(entry, ensure_ascii=False)
        self.assertIn("Сервер на порту 8000", serialized)
        parsed = json.loads(serialized)
        self.assertEqual(parsed["id"], 3)
        self.assertEqual(parsed["content"], "Сервер на порту 8000")
        self.assertEqual(parsed["text"], "Сервер на порту 8000")

    def test_from_dict_v1_and_v2(self):
        # v1 формат (из старого memory.json)
        v1_dict = {
            "id": 10,
            "text": "Пользователь живёт в Москве",
            "category": "general",
            "created_at": "2026-01-01 12:00:00"
        }
        e1 = MemoryEntry.from_dict(v1_dict)
        self.assertEqual(e1.id, 10)
        self.assertEqual(e1.content, "Пользователь живёт в Москве")
        self.assertEqual(e1.type, "general")
        self.assertEqual(e1.source, MemorySource.USER)
        self.assertEqual(e1.created_at, "2026-01-01 12:00:00")

        # v2 формат
        v2_dict = {
            "id": 11,
            "content": "Использовать ComfyUI для генерации картинок",
            "type": "fact",
            "source": "agent",
            "tags": ["image", "comfyui"],
            "metadata": {"model": "sdxl"},
            "created_at": "2026-02-01 10:00:00",
            "updated_at": "2026-02-01 11:00:00"
        }
        e2 = MemoryEntry.from_dict(v2_dict)
        self.assertEqual(e2.id, 11)
        self.assertEqual(e2.content, "Использовать ComfyUI для генерации картинок")
        self.assertEqual(e2.tags, ["image", "comfyui"])
        self.assertEqual(e2.metadata["model"], "sdxl")


class TestPersistentMemoryCRUD(unittest.TestCase):
    """Тестирование операций CRUD в изолированном PersistentMemory."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_persistent_memory.json"
        self.pm = PersistentMemory(storage_path=self.storage_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_get(self):
        ok, msg, entry = self.pm.create(
            content="Пользователь предпочитает темную тему",
            type=MemoryType.PREFERENCE,
            tags=["ui", "theme"]
        )
        self.assertTrue(ok)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.id, 1)
        self.assertEqual(entry.type, "preference")
        self.assertIn("темную тему", msg)

        # Чтение по ID
        found = self.pm.get(1)
        self.assertIsNotNone(found)
        self.assertEqual(found.content, "Пользователь предпочитает темную тему")

        # Чтение по строковому ID со знаками
        self.assertEqual(self.pm.get("#1"), found)
        self.assertEqual(self.pm.get("№1"), found)

    def test_create_validation_rejection(self):
        # Пустой текст
        ok, msg, _ = self.pm.create("")
        self.assertFalse(ok)
        self.assertIn("пустым", msg)

        # Слишком короткий текст
        ok, msg, _ = self.pm.create("ок")
        self.assertFalse(ok)
        self.assertIn("короткий", msg)

        # Трейсбек
        tb = "Traceback (most recent call last):\n  File 'test.py', line 1\nZeroDivisionError: division by zero"
        ok, msg, _ = self.pm.create(tb)
        self.assertFalse(ok)
        self.assertIn("трейсбек", msg.lower())

        # Сырой JSON
        ok, msg, _ = self.pm.create('{"status": "error", "code": 500}')
        self.assertFalse(ok)
        self.assertIn("JSON-дамп", msg)

    def test_deduplication_on_create(self):
        ok1, _, e1 = self.pm.create("Имя кота Барсик")
        self.assertTrue(ok1)

        # Повторное создание с тем же смыслом (разный регистр/пробелы)
        ok2, msg2, e2 = self.pm.create("  имя кота барсик!  ")
        self.assertFalse(ok2)
        self.assertIn("уже есть в памяти", msg2)
        self.assertEqual(e2.id, e1.id)

    def test_update_entry(self):
        ok, _, entry = self.pm.create("Рабочая станция на Linux")
        self.assertTrue(ok)

        # Успешное обновление
        upd_ok, upd_msg, updated = self.pm.update(
            entry.id,
            content="Рабочая станция на Ubuntu 24.04",
            type=MemoryType.FACT,
            tags=["os", "linux"]
        )
        self.assertTrue(upd_ok)
        self.assertEqual(updated.content, "Рабочая станция на Ubuntu 24.04")
        self.assertEqual(updated.tags, ["os", "linux"])

        # Проверка диска: изменения должны быть сохранены
        reloaded = PersistentMemory(storage_path=self.storage_path)
        self.assertEqual(reloaded.get(entry.id).content, "Рабочая станция на Ubuntu 24.04")

    def test_update_duplicate_rejection(self):
        self.pm.create("Первая запись факта")
        _, _, e2 = self.pm.create("Вторая запись факта")

        # Попытка обновить e2 текстом, который уже есть в первой записи
        ok, msg, _ = self.pm.update(e2.id, content="первая запись факта")
        self.assertFalse(ok)
        self.assertIn("уже есть в записи #1", msg)

    def test_delete_by_id_and_text(self):
        self.pm.create("Удалить этот факт навсегда")
        _, _, e2 = self.pm.create("Оставить этот факт")

        # Удаление по ID
        del_ok, del_msg = self.pm.delete(1)
        self.assertTrue(del_ok)
        self.assertIn("Удалил запись #1", del_msg)
        self.assertIsNone(self.pm.get(1))
        self.assertEqual(len(self.pm), 1)

        # Удаление по фрагменту текста
        del_ok2, del_msg2 = self.pm.delete("Оставить этот факт")
        self.assertTrue(del_ok2)
        self.assertEqual(len(self.pm), 0)

    def test_delete_ambiguous_text_requires_id(self):
        self.pm.create("Сервер баз данных в облаке")
        self.pm.create("Сервер приложений на локальной машине")

        # Поиск по общему слову "сервер" даёт 2 совпадения
        del_ok, del_msg = self.pm.delete("сервер")
        self.assertFalse(del_ok)
        self.assertIn("Найдено несколько записей", del_msg)
        self.assertEqual(len(self.pm), 2)

    def test_clear(self):
        self.pm.create("Запись 1")
        self.pm.create("Запись 2")
        self.assertEqual(len(self.pm), 2)

        ok, msg = self.pm.clear()
        self.assertTrue(ok)
        self.assertEqual(len(self.pm), 0)
        self.assertIn("удалено записей: 2", msg)


class TestPersistentMemorySearchAndFiltering(unittest.TestCase):
    """Тестирование поиска и фильтрации по типу, тегам и источнику."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_search_memory.json"
        self.pm = PersistentMemory(storage_path=self.storage_path)

        self.pm.create("Кофе без сахара", type=MemoryType.PREFERENCE, source=MemorySource.USER, tags=["food", "drink"])
        self.pm.create("Порт SSH сервера 2222", type=MemoryType.FACT, source=MemorySource.USER, tags=["network", "ssh"])
        self.pm.create("Успешно построен график продаж", type=MemoryType.RESULT, source=MemorySource.AGENT, tags=["sales", "report"])
        self.pm.create("Памятка: купить кабель HDMI", type=MemoryType.NOTE, source=MemorySource.USER, tags=["shopping"])

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_search_by_query(self):
        res = self.pm.search(query="порт")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].content, "Порт SSH сервера 2222")

    def test_filter_by_type(self):
        res = self.pm.search(type=MemoryType.PREFERENCE)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].content, "Кофе без сахара")

    def test_filter_by_tags(self):
        res = self.pm.search(tags=["network"])
        self.assertEqual(len(res), 1)
        self.assertIn("SSH", res[0].content)

    def test_filter_by_source(self):
        agent_res = self.pm.search(source=MemorySource.AGENT)
        self.assertEqual(len(agent_res), 1)
        self.assertEqual(agent_res[0].type, MemoryType.RESULT)

    def test_combined_search_and_filter(self):
        res = self.pm.search(query="кабель", type=MemoryType.NOTE, tags=["shopping"])
        self.assertEqual(len(res), 1)
        self.assertIn("HDMI", res[0].content)


class TestPersistenceAndMigration(unittest.TestCase):
    """Тестирование надёжности хранения и автомиграции v1 -> v2."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_migration.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_migration_from_v1_format(self):
        # Записываем старый формат v1 на диск
        v1_payload = {
            "version": 1,
            "updated_at": "2026-01-01T10:00:00",
            "memories": [
                {"id": 1, "text": "Любимый цвет зелёный", "category": "preference", "created_at": "2026-01-01 10:00:00"},
                {"id": 2, "text": "Рабочая директория /home/user", "category": "fact", "created_at": "2026-01-01 10:05:00"}
            ]
        }
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(v1_payload, f, ensure_ascii=False)

        # Загружаем через PersistentMemory
        pm = PersistentMemory(storage_path=self.storage_path)
        self.assertEqual(len(pm), 2)

        entry1 = pm.get(1)
        self.assertEqual(entry1.content, "Любимый цвет зелёный")
        self.assertEqual(entry1.type, "preference")
        self.assertEqual(entry1.source, MemorySource.USER)

        # Проверяем сохранение нового формата v2
        pm.create("Новый факт v2")
        with open(self.storage_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("version"), 2)
        self.assertEqual(len(data.get("memories")), 3)

    def test_corrupted_file_handling(self):
        # Записываем битый JSON
        with open(self.storage_path, "w", encoding="utf-8") as f:
            f.write("{ invalid json corrupted ...")

        # Приложение не должно падать при повреждении файла
        pm = PersistentMemory(storage_path=self.storage_path)
        self.assertEqual(len(pm), 0)

        # Новые записи должны корректно сохраняться
        ok, _, _ = pm.create("Восстановленная запись")
        self.assertTrue(ok)
        self.assertEqual(len(pm), 1)


class TestRememberResult(unittest.TestCase):
    """Тестирование явного сохранения результатов задач (remember_result)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_results_memory.json"
        self.pm = PersistentMemory(storage_path=self.storage_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_remember_agent_result(self):
        artifact = Artifact(type=ArtifactType.DOCUMENT, path="docs/report.docx", name="Отчет")
        res = AgentResult(
            success=True,
            message="Документ успешно сгенерирован в формате docx",
            artifacts=[artifact],
            created_files=["docs/report.docx"],
            data={"agent_name": "document_agent"}
        )

        ok, msg, entry = self.pm.remember_result(
            result=res,
            title="Годовой отчет 2026",
            tags=["doc", "annual"]
        )
        self.assertTrue(ok)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.type, MemoryType.RESULT)
        self.assertEqual(entry.source, MemorySource.AGENT)
        self.assertIn("Годовой отчет 2026", entry.content)
        self.assertIn("result", entry.tags)
        self.assertIn("doc", entry.tags)
        self.assertEqual(entry.metadata.get("created_files"), ["docs/report.docx"])
        self.assertEqual(entry.metadata.get("artifacts_count"), 1)


class TestMemoryManagerIntegration(unittest.TestCase):
    """Тестирование интеграции MemoryManager с PersistentMemory и изоляции short-term памяти."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_mm_integration.json"
        self.mgr = MemoryManager(storage_path=self.storage_path, max_turns=3)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_backward_compatible_methods(self):
        # remember
        ok, msg, entry = self.mgr.remember("Имя разработчика Александр", category="fact")
        self.assertTrue(ok)
        self.assertEqual(entry["id"], 1)
        self.assertEqual(entry["text"], "Имя разработчика Александр")

        # recall / search
        all_items = self.mgr.get_all()
        self.assertEqual(len(all_items), 1)
        found = self.mgr.search("Александр")
        self.assertEqual(len(found), 1)

        # format_memories_summary
        summary = self.mgr.format_memories_summary()
        self.assertIn("1. Имя разработчика Александр", summary)

        # format_for_system_prompt
        prompt_txt = self.mgr.format_for_system_prompt()
        self.assertIn("- Имя разработчика Александр", prompt_txt)

        # forget
        del_ok, _ = self.mgr.forget(1)
        self.assertTrue(del_ok)
        self.assertEqual(len(self.mgr.get_all()), 0)

    def test_new_crud_convenience_methods(self):
        ok, _, e = self.mgr.remember("Сервер баз данных PostgreSQL 16")
        self.assertTrue(ok)

        # get_entry
        entry = self.mgr.get_entry(e["id"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry.content, "Сервер баз данных PostgreSQL 16")

        # update_entry
        upd_ok, _, updated = self.mgr.update_entry(
            e["id"],
            content="Сервер баз данных PostgreSQL 17",
            tags=["db", "sql"]
        )
        self.assertTrue(upd_ok)
        self.assertEqual(updated.content, "Сервер баз данных PostgreSQL 17")
        self.assertEqual(updated.tags, ["db", "sql"])

        # delete_entry
        del_ok, _ = self.mgr.delete_entry(e["id"])
        self.assertTrue(del_ok)
        self.assertIsNone(self.mgr.get_entry(e["id"]))

    def test_short_term_dialogue_isolation(self):
        # Проверяем, что краткосрочные реплики НЕ попадают в PersistentMemory
        self.mgr.add_turn("Привет, Акакий", "Привет! Чем могу помочь?")
        self.mgr.add_turn("Какая погода?", "Погода отличная.")

        self.assertEqual(len(self.mgr.get_recent_history()), 4)
        # Persistent memory должна оставаться пустой
        self.assertEqual(len(self.mgr.get_all()), 0)

        # Очистка short_term не затрагивает persistent
        self.mgr.remember("Важный факт для памяти")
        self.assertEqual(len(self.mgr.get_all()), 1)

        self.mgr.clear_short_term()
        self.assertEqual(len(self.mgr.get_recent_history()), 0)
        self.assertEqual(len(self.mgr.get_all()), 1)


if __name__ == "__main__":
    unittest.main()
