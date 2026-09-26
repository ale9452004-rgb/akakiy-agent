"""
Тесты расширенного контракта AgentContext v2 (Этап №5 — AgentContext v2).

Проверяет:
1. Структурированные поля задачи: task_id, root_task_id, task_type, instruction, status, mark_completed, mark_failed.
2. Работу с файлами и их метаданными: add_file, get_file_metadata, set_file_metadata, remove_file, has_file.
3. Передачу и поиск результатов предыдущих агентов: add_result, get_last_result, get_results_from.
4. Метаданные параметров и протокол сопоставления: get, set, update_metadata, has_metadata, __getitem__, __setitem__, __contains__.
5. Иерархическую связь parent/child: create_child_context, наследование root_task_id, изоляцию метаданных, copy.
6. Сериализацию и десериализацию: to_dict, from_dict, to_json, from_json, 100% обратную совместимость со словарями v1.
7. Совместимость с SubAgent (EchoAgent, ImageAgent).
"""

import json
import sys
import unittest
import uuid
from pathlib import Path

# Обеспечиваем импорт из корня проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.agents.context import AgentContext
from tools.agents.result import AgentResult
from tools.agents.echo import EchoAgent
from tools.agents.image import ImageAgent


class TestAgentContextV2TaskAndStatus(unittest.TestCase):
    """1. Проверка структурированных атрибутов задачи и управления статусом."""

    def test_task_id_and_root_task_id_default(self):
        ctx = AgentContext(task="Тестовая задача")
        self.assertIsNotNone(ctx.task_id)
        # По умолчанию root_task_id совпадает с task_id
        self.assertEqual(ctx.root_task_id, ctx.task_id)
        self.assertEqual(ctx.status, "pending")
        self.assertIsNone(ctx.task_type)
        self.assertIsNone(ctx.instruction)

    def test_custom_task_attributes(self):
        custom_id = "task-custom-123"
        root_id = "task-root-000"
        ctx = AgentContext(
            task="Сгенерировать диаграмму",
            task_id=custom_id,
            root_task_id=root_id,
            task_type="diagram",
            instruction="Использовать PlantUML",
            status="running"
        )
        self.assertEqual(ctx.task_id, custom_id)
        self.assertEqual(ctx.root_task_id, root_id)
        self.assertEqual(ctx.task_type, "diagram")
        self.assertEqual(ctx.instruction, "Использовать PlantUML")
        self.assertEqual(ctx.status, "running")

    def test_mark_completed_and_failed(self):
        ctx = AgentContext(task="Тест статуса")
        self.assertEqual(ctx.status, "pending")

        ctx.mark_completed()
        self.assertEqual(ctx.status, "completed")

        ctx.mark_failed("error_timeout")
        self.assertEqual(ctx.status, "error_timeout")


class TestAgentContextV2FilesAndMetadata(unittest.TestCase):
    """2. Проверка работы с файлами и их метаданными."""

    def test_add_file_with_metadata(self):
        ctx = AgentContext(task="Работа с файлами")
        ctx.add_file("output/chart.png", mime_type="image/png", role="output", size=1024)

        self.assertIn("output/chart.png", ctx.files)
        self.assertTrue(ctx.has_file("output/chart.png"))

        meta = ctx.get_file_metadata("output/chart.png")
        self.assertEqual(meta.get("mime_type"), "image/png")
        self.assertEqual(meta.get("role"), "output")
        self.assertEqual(meta.get("size"), 1024)

    def test_add_file_deduplication_updates_metadata(self):
        ctx = AgentContext(task="Тест дедупликации", files=["data.csv"])
        self.assertEqual(ctx.get_file_metadata("data.csv"), {})

        # Повторное добавление обновляет метаданные, не дублируя путь в files
        ctx.add_file("data.csv", delimiter=",", rows=100)
        self.assertEqual(ctx.files.count("data.csv"), 1)
        self.assertEqual(ctx.get_file_metadata("data.csv")["rows"], 100)

    def test_set_file_metadata(self):
        ctx = AgentContext(task="Установка метаданных")
        ctx.set_file_metadata("doc.md", {"author": "Akakiy", "version": 2})

        self.assertTrue(ctx.has_file("doc.md"))
        self.assertEqual(ctx.get_file_metadata("doc.md")["author"], "Akakiy")

    def test_remove_file(self):
        ctx = AgentContext(task="Удаление файла")
        ctx.add_file("temp.log", level="debug")
        self.assertTrue(ctx.has_file("temp.log"))

        removed = ctx.remove_file("temp.log")
        self.assertTrue(removed)
        self.assertFalse(ctx.has_file("temp.log"))
        self.assertEqual(ctx.get_file_metadata("temp.log"), {})

        # Повторное удаление возвращает False
        self.assertFalse(ctx.remove_file("temp.log"))


class TestAgentContextV2Results(unittest.TestCase):
    """3. Проверка передачи и поиска результатов предыдущих агентов."""

    def test_add_and_get_last_result(self):
        ctx = AgentContext(task="Конвейер шагов")
        self.assertIsNone(ctx.get_last_result())

        res1 = AgentResult.ok(message="Шаг 1 выполнен", data={"step": 1})
        ctx.add_result(res1, agent_name="planner")

        res2 = AgentResult.ok(message="Шаг 2 выполнен", data={"step": 2})
        ctx.add_result(res2, agent_name="coder")

        # Последний общий результат
        self.assertEqual(ctx.get_last_result(), res2)
        # Последний результат конкретного агента
        self.assertEqual(ctx.get_last_result("planner"), res1)
        self.assertEqual(ctx.get_last_result("coder"), res2)
        self.assertIsNone(ctx.get_last_result("unknown_agent"))

    def test_get_results_from(self):
        ctx = AgentContext(task="Сбор результатов")
        res1 = {"agent": "reviewer", "score": 90}
        res2 = {"agent": "reviewer", "score": 95}
        res3 = {"agent": "linter", "warnings": 0}

        ctx.add_result(res1)
        ctx.add_result(res2)
        ctx.add_result(res3)

        reviewer_results = ctx.get_results_from("reviewer")
        self.assertEqual(len(reviewer_results), 2)
        self.assertEqual(reviewer_results[0]["score"], 90)
        self.assertEqual(reviewer_results[1]["score"], 95)


class TestAgentContextV2MetadataProtocol(unittest.TestCase):
    """4. Проверка протокола доступа к метаданным."""

    def test_dict_like_access(self):
        ctx = AgentContext(task="Тест метаданных", metadata={"key1": "val1"})
        # Чтение
        self.assertEqual(ctx["key1"], "val1")
        self.assertEqual(ctx.get("key1"), "val1")
        self.assertEqual(ctx.get("missing", 42), 42)

        # Проверка наличия
        self.assertIn("key1", ctx)
        self.assertTrue(ctx.has_metadata("key1"))
        self.assertNotIn("key2", ctx)

        # Запись
        ctx["key2"] = "val2"
        self.assertEqual(ctx.get("key2"), "val2")
        ctx.set("key3", "val3")
        self.assertEqual(ctx["key3"], "val3")

    def test_update_metadata(self):
        ctx = AgentContext(task="Пакетное обновление", metadata={"a": 1})
        ctx.update_metadata({"b": 2, "c": 3})
        self.assertEqual(ctx["a"], 1)
        self.assertEqual(ctx["b"], 2)
        self.assertEqual(ctx["c"], 3)


class TestAgentContextV2Hierarchy(unittest.TestCase):
    """5. Проверка создания дочерних контекстов (parent/child) и изоляции."""

    def test_create_child_context_inheritance_and_isolation(self):
        parent_agent_mock = object()
        parent = AgentContext(
            task="Основная задача",
            files=["main.py"],
            previous_results=["init_res"],
            metadata={"shared_cfg": True, "parent_only": 100},
            parent_agent=parent_agent_mock,
            task_type="orchestration"
        )
        parent.set_file_metadata("main.py", {"type": "code"})

        child = parent.create_child_context(
            task="Подзадача анализа",
            files=["extra.py"],
            inherit_files=True,
            inherit_metadata=True,
            inherit_results=True,
            metadata={"child_specific": 200}
        )

        # Проверка связей
        self.assertEqual(child.parent_context, parent)
        self.assertEqual(child.parent_agent, parent_agent_mock)
        self.assertEqual(child.root_task_id, parent.task_id)
        self.assertNotEqual(child.task_id, parent.task_id)

        # Проверка наследования файлов
        self.assertTrue(child.has_file("main.py"))
        self.assertTrue(child.has_file("extra.py"))
        self.assertEqual(child.get_file_metadata("main.py")["type"], "code")

        # Проверка наследования и изоляции метаданных
        self.assertTrue(child["shared_cfg"])
        self.assertEqual(child["child_specific"], 200)

        # Модификация child не должна затронуть parent
        child["shared_cfg"] = False
        self.assertTrue(parent["shared_cfg"])
        self.assertNotIn("child_specific", parent)

        # Модификация файлов child не затрагивает parent
        child.add_file("child_temp.txt")
        self.assertFalse(parent.has_file("child_temp.txt"))

    def test_create_child_context_no_inheritance(self):
        parent = AgentContext(
            task="Родитель",
            files=["p.txt"],
            previous_results=["p_res"],
            metadata={"secret": 123}
        )
        child = parent.create_child_context(
            task="Чистый ребенок",
            inherit_files=False,
            inherit_metadata=False,
            inherit_results=False
        )
        self.assertEqual(child.files, [])
        self.assertEqual(child.previous_results, [])
        self.assertNotIn("secret", child)
        self.assertEqual(child.root_task_id, parent.task_id)

    def test_context_copy(self):
        ctx = AgentContext(task="Оригинал", metadata={"param": 10})
        cloned = ctx.copy()
        self.assertEqual(cloned.task, ctx.task)
        self.assertEqual(cloned.metadata, ctx.metadata)
        cloned["param"] = 20
        self.assertEqual(ctx["param"], 10)


class TestAgentContextV2Serialization(unittest.TestCase):
    """6. Проверка сериализации, десериализации и обратной совместимости."""

    def test_to_dict_and_from_dict_v2_full(self):
        res = AgentResult.ok(message="OK", data={"x": 1})
        ctx = AgentContext(
            task="Полная сериализация",
            task_type="code_review",
            instruction="Проверить типы",
            status="completed",
            files=["app.py"],
            previous_results=[res],
            metadata={"lang": "ru"}
        )
        ctx.set_file_metadata("app.py", {"lines": 50})

        d = ctx.to_dict()
        self.assertEqual(d["task"], "Полная сериализация")
        self.assertEqual(d["task_type"], "code_review")
        self.assertEqual(d["instruction"], "Проверить типы")
        self.assertEqual(d["status"], "completed")
        self.assertEqual(d["file_metadata"]["app.py"]["lines"], 50)
        # Регулярный результат AgentResult сериализован в dict
        self.assertEqual(d["previous_results"][0]["message"], "OK")

        restored = AgentContext.from_dict(d)
        self.assertEqual(restored.task_id, ctx.task_id)
        self.assertEqual(restored.root_task_id, ctx.root_task_id)
        self.assertEqual(restored.task, ctx.task)
        self.assertEqual(restored.task_type, ctx.task_type)
        self.assertEqual(restored.instruction, ctx.instruction)
        self.assertEqual(restored.status, ctx.status)
        self.assertEqual(restored.files, ctx.files)
        self.assertEqual(restored.get_file_metadata("app.py")["lines"], 50)
        self.assertEqual(restored.metadata, ctx.metadata)

    def test_from_dict_v1_backward_compatibility(self):
        """Проверка восстановления из словаря v1, где нет новых полей."""
        v1_dict = {
            "task": "Старая задача v1",
            "files": ["old.txt"],
            "previous_results": ["step1"],
            "metadata": {"legacy": True}
        }
        restored = AgentContext.from_dict(v1_dict)
        self.assertEqual(restored.task, "Старая задача v1")
        self.assertEqual(restored.files, ["old.txt"])
        self.assertEqual(restored.previous_results, ["step1"])
        self.assertEqual(restored["legacy"], True)
        # Новые поля получают безопасные дефолты
        self.assertIsNotNone(restored.task_id)
        self.assertEqual(restored.root_task_id, restored.task_id)
        self.assertEqual(restored.status, "pending")
        self.assertIsNone(restored.task_type)
        self.assertIsNone(restored.instruction)

    def test_to_and_from_json(self):
        ctx = AgentContext(task="JSON тест", files=["f1.txt"], metadata={"val": 99})
        json_str = ctx.to_json(indent=2)
        self.assertIsInstance(json_str, str)
        # Проверяем корректный JSON
        parsed = json.loads(json_str)
        self.assertEqual(parsed["task"], "JSON тест")

        restored = AgentContext.from_json(json_str)
        self.assertEqual(restored.task, ctx.task)
        self.assertEqual(restored["val"], 99)

    def test_from_json_invalid_type_raises(self):
        with self.assertRaises(TypeError):
            AgentContext.from_json(12345)  # не строка


class TestAgentContextV2SubAgentCompatibility(unittest.TestCase):
    """7. Проверка совместимости с существующими SubAgent (EchoAgent, ImageAgent)."""

    def test_echo_agent_with_v2_context(self):
        agent = EchoAgent()
        ctx = AgentContext(
            task="Эхо v2",
            task_type="test",
            metadata={"test_key": 777}
        )
        ctx.add_file("output.txt", role="mock")
        res = agent.run(ctx)

        self.assertTrue(res.success)
        self.assertIn("Эхо v2", res.message)
        self.assertEqual(res.data["echo_metadata"]["test_key"], 777)

    def test_image_agent_validate_context(self):
        agent = ImageAgent()
        ctx = AgentContext(task="Кот на Луне", metadata={"width": 1024, "height": 1024})
        self.assertTrue(agent.validate_context(ctx))


if __name__ == "__main__":
    unittest.main()
