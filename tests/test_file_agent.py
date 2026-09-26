"""
Unit и интеграционные тесты для FileAgent v1.

Проверяют:
- инициализацию и объявленные capabilities FileAgent;
- разбор задач (parse_task) для различных операций (search, read, create, copy, move, metadata);
- поиск файлов и поиск текста;
- чтение файлов и формирование модели Artifact;
- создание файлов с сохранением содержимого и артефакта;
- безопасное копирование и перемещение файлов;
- получение структурированных метаданных файла;
- строгую защиту от path traversal за пределы рабочей директории;
- категорический запрет на операции удаления файлов;
- свойство AgentResult.file_artifacts;
- регистрацию FileAgent в AgentRegistry;
- детерминированную маршрутизацию в CommandRouter (match_file);
- сквозную обработку в Agent.process.
"""

from pathlib import Path
import shutil
import tempfile
import unittest

from tools.agents.context import AgentContext
from tools.agents.file import FileAgent
from tools.agents.registry import AgentRegistry, get_agent_registry, reset_agent_registry
from tools.agents.result import AgentResult, Artifact, ArtifactType
from tools.router import CommandRouter


class TestFileAgent(unittest.TestCase):
    """Набор тестов для специализированного FileAgent v1."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="fileagent_test_")
        self.tmp_path = Path(self.tmp_dir).resolve()
        self.agent = FileAgent(project_path=self.tmp_path)
        self.router = CommandRouter()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_file_agent_init_and_capabilities(self):
        """Проверка имени, описания и возможностей FileAgent."""
        self.assertEqual(self.agent.name, "file")
        self.assertTrue(self.agent.enabled)
        for cap in ["file", "files", "search", "read", "create", "write", "copy", "move", "metadata", "stat"]:
            self.assertIn(cap, self.agent.capabilities)

    def test_parse_task_metadata_actions(self):
        """Проверка разбора явных действий из metadata."""
        p_read = self.agent.parse_task("задача", metadata={"action": "read", "file": "test.txt"})
        self.assertEqual(p_read["action"], "read")
        self.assertEqual(p_read["file"], "test.txt")

        p_create = self.agent.parse_task("задача", metadata={"action": "write", "file": "out.txt", "content": "hello"})
        self.assertEqual(p_create["action"], "create")
        self.assertEqual(p_create["file"], "out.txt")
        self.assertEqual(p_create["content"], "hello")

        p_copy = self.agent.parse_task("задача", metadata={"action": "copy", "source": "a.txt", "destination": "b.txt"})
        self.assertEqual(p_copy["action"], "copy")
        self.assertEqual(p_copy["source"], "a.txt")
        self.assertEqual(p_copy["destination"], "b.txt")

        p_move = self.agent.parse_task("задача", metadata={"action": "rename", "source": "a.txt", "destination": "b.txt"})
        self.assertEqual(p_move["action"], "move")

        p_meta = self.agent.parse_task("задача", metadata={"action": "stat", "file": "data.json"})
        self.assertEqual(p_meta["action"], "metadata")

        p_del = self.agent.parse_task("задача", metadata={"action": "delete", "file": "bad.txt"})
        self.assertEqual(p_del["action"], "delete")

    def test_parse_task_natural_language(self):
        """Проверка разбора естественных русскоязычных команд."""
        p_cp = self.agent.parse_task("скопируй файл data.json в backup.json")
        self.assertEqual(p_cp["action"], "copy")
        self.assertEqual(p_cp["source"], "data.json")
        self.assertEqual(p_cp["destination"], "backup.json")

        p_mv = self.agent.parse_task("перемести old.txt в archive/old.txt")
        self.assertEqual(p_mv["action"], "move")
        self.assertEqual(p_mv["source"], "old.txt")
        self.assertEqual(p_mv["destination"], "archive/old.txt")

        p_meta = self.agent.parse_task("метаданные файла README.md")
        self.assertEqual(p_meta["action"], "metadata")
        self.assertEqual(p_meta["file"], "README.md")

        p_rd = self.agent.parse_task("прочитай файл config.py")
        self.assertEqual(p_rd["action"], "read")
        self.assertEqual(p_rd["file"], "config.py")

        p_cr = self.agent.parse_task("создай файл hello.txt с содержимым Привет мир")
        self.assertEqual(p_cr["action"], "create")
        self.assertEqual(p_cr["file"], "hello.txt")
        self.assertEqual(p_cr["content"], "Привет мир")

        p_del = self.agent.parse_task("удали файл secret.key")
        self.assertEqual(p_del["action"], "delete")

    def test_create_and_read_file(self):
        """Создание файла и последующее его чтение с валидацией артефактов."""
        # 1. Создание
        ctx_create = AgentContext(
            instruction="создай файл notes/hello.txt с содержимым Тестовая запись"
        )
        res_create = self.agent.run(ctx_create)
        self.assertTrue(res_create.success, f"Create failed: {res_create.error}")
        self.assertTrue((self.tmp_path / "notes" / "hello.txt").exists())
        self.assertEqual(len(res_create.created_files), 1)
        self.assertEqual(len(res_create.artifacts), 1)
        self.assertEqual(res_create.primary_artifact.type, ArtifactType.TEXT)

        # 2. Чтение
        ctx_read = AgentContext(
            instruction="прочитай файл notes/hello.txt"
        )
        res_read = self.agent.run(ctx_read)
        self.assertTrue(res_read.success, f"Read failed: {res_read.error}")
        self.assertEqual(res_read.data["content"], "Тестовая запись")
        self.assertEqual(len(res_read.artifacts), 1)
        self.assertEqual(res_read.primary_artifact.content, "Тестовая запись")

    def test_read_nonexistent_file(self):
        """Чтение несуществующего файла возвращает ошибку."""
        ctx = AgentContext(instruction="прочитай файл non_existent_file.txt")
        res = self.agent.run(ctx)
        self.assertFalse(res.success)
        self.assertIn("не найден", res.error)

    def test_copy_file(self):
        """Безопасное копирование существующего файла."""
        src_file = self.tmp_path / "source.txt"
        src_file.write_text("Контент для копирования", encoding="utf-8")

        ctx = AgentContext(
            instruction="скопируй файл source.txt в sub/target.txt"
        )
        res = self.agent.run(ctx)
        self.assertTrue(res.success, f"Copy failed: {res_create.error if 'res_create' in locals() else res.error}")
        self.assertTrue((self.tmp_path / "sub" / "target.txt").exists())
        self.assertEqual((self.tmp_path / "sub" / "target.txt").read_text(encoding="utf-8"), "Контент для копирования")
        self.assertEqual(len(res.created_files), 1)
        self.assertEqual(len(res.artifacts), 1)

    def test_copy_nonexistent_source(self):
        """Копирование с несуществующим источником."""
        ctx = AgentContext(
            instruction="скопируй файл no_such_file.txt в dest.txt"
        )
        res = self.agent.run(ctx)
        self.assertFalse(res.success)
        self.assertIn("не найден", res.error)

    def test_move_file(self):
        """Безопасное перемещение существующего файла."""
        src_file = self.tmp_path / "to_move.txt"
        src_file.write_text("Контент для перемещения", encoding="utf-8")

        ctx = AgentContext(
            instruction="перемести файл to_move.txt в moved.txt"
        )
        res = self.agent.run(ctx)
        self.assertTrue(res.success, f"Move failed: {res.error}")
        self.assertFalse(src_file.exists())
        self.assertTrue((self.tmp_path / "moved.txt").exists())
        self.assertEqual((self.tmp_path / "moved.txt").read_text(encoding="utf-8"), "Контент для перемещения")
        self.assertEqual(len(res.created_files), 1)

    def test_move_nonexistent_source(self):
        """Перемещение несуществующего файла."""
        ctx = AgentContext(
            instruction="перемести файл missing.txt в dest.txt"
        )
        res = self.agent.run(ctx)
        self.assertFalse(res.success)
        self.assertIn("не найден", res.error)

    def test_get_metadata(self):
        """Получение метаданных файла."""
        test_file = self.tmp_path / "info.json"
        test_file.write_text('{"key": "value"}', encoding="utf-8")

        ctx = AgentContext(
            instruction="метаданные файла info.json"
        )
        res = self.agent.run(ctx)
        self.assertTrue(res.success, f"Metadata failed: {res.error}")
        self.assertEqual(res.data["name"], "info.json")
        self.assertEqual(res.data["size_bytes"], len('{"key": "value"}'.encode("utf-8")))
        self.assertEqual(res.data["extension"], ".json")
        self.assertTrue(res.data["is_file"])
        self.assertIn("created_at", res.data)
        self.assertIn("modified_at", res.data)
        self.assertEqual(len(res.artifacts), 1)

    def test_get_metadata_nonexistent(self):
        """Получение метаданных несуществующего файла."""
        ctx = AgentContext(instruction="информация о файле nonexistent.txt")
        res = self.agent.run(ctx)
        self.assertFalse(res.success)
        self.assertIn("не найден", res.error)

    def test_search_files(self):
        """Поиск файлов по имени."""
        (self.tmp_path / "alpha.py").write_text("# alpha", encoding="utf-8")
        (self.tmp_path / "beta.txt").write_text("beta text", encoding="utf-8")
        (self.tmp_path / "sub").mkdir()
        (self.tmp_path / "sub" / "alpha_sub.py").write_text("# sub", encoding="utf-8")

        ctx = AgentContext(instruction="найди файл alpha")
        res = self.agent.run(ctx)
        self.assertTrue(res.success, f"Search failed: {res.error}")
        self.assertEqual(res.data["count"], 2)
        matched_names = [m["name"] for m in res.data["matches"]]
        self.assertIn("alpha.py", matched_names)
        self.assertIn("alpha_sub.py", matched_names)

    def test_path_traversal_protection(self):
        """Защита от выхода за пределы рабочей директории."""
        traversal_paths = [
            "../../outside.txt",
            "..\\..\\windows\\system32\\cmd.exe",
            "/etc/passwd",
            "C:\\Windows\\win.ini"
        ]
        for bad_path in traversal_paths:
            # Чтение
            res_rd = self.agent.read(bad_path)
            self.assertFalse(res_rd.success)
            self.assertTrue("запрещён" in res_rd.error or "Некорректный" in res_rd.error or "не найден" in res_rd.error)

            # Создание
            res_cr = self.agent.create(bad_path, "hacked")
            self.assertFalse(res_cr.success)
            self.assertTrue("запрещён" in res_cr.error or "Некорректный" in res_cr.error)

            # Копирование
            res_cp = self.agent.copy(bad_path, "local.txt")
            self.assertFalse(res_cp.success)
            self.assertTrue("запрещён" in res_cp.error or "Некорректный" in res_cp.error or "не найден" in res_cp.error)

            # Метаданные
            res_st = self.agent.get_metadata(bad_path)
            self.assertFalse(res_st.success)
            self.assertTrue("запрещён" in res_st.error or "Некорректный" in res_st.error or "не найден" in res_st.error)

    def test_delete_operation_forbidden(self):
        """Категорический запрет на удаление файлов."""
        ctx1 = AgentContext(instruction="удали файл my_data.txt")
        res1 = self.agent.run(ctx1)
        self.assertFalse(res1.success)
        self.assertIn("запрещено", res1.error)

        ctx2 = AgentContext(instruction="remove file test.txt", metadata={"action": "delete"})
        res2 = self.agent.run(ctx2)
        self.assertFalse(res2.success)
        self.assertIn("запрещено", res2.error)

    def test_agent_result_file_artifacts_property(self):
        """Проверка свойства file_artifacts у AgentResult."""
        art_file = Artifact.from_file(self.tmp_path / "doc.txt", type=ArtifactType.FILE)
        art_code = Artifact.from_code(self.tmp_path / "script.py")
        art_img = Artifact.from_file(self.tmp_path / "img.png", type=ArtifactType.IMAGE)

        res = AgentResult.ok(artifacts=[art_file, art_code, art_img])
        self.assertEqual(len(res.file_artifacts), 1)
        self.assertEqual(res.file_artifacts[0].name, "doc.txt")
        self.assertEqual(len(res.code_artifacts), 1)
        self.assertEqual(len(res.images), 1)

    def test_registry_integration(self):
        """Проверка регистрации FileAgent в AgentRegistry."""
        reg = get_agent_registry()
        agent = reg.get("file")
        self.assertIsNotNone(agent)
        self.assertEqual(agent.name, "file")

        # Проверка по capabilities
        self.assertIn("copy", agent.capabilities)
        self.assertIn("move", agent.capabilities)
        self.assertIn("read", agent.capabilities)
        self.assertIn("create", agent.capabilities)
        self.assertIn("metadata", agent.capabilities)

    def test_router_match_file_patterns(self):
        """Проверка шаблонов распознавания команд для FileAgent."""
        test_commands = [
            "файл: скопируй a.txt в b.txt",
            "файлы: прочитай config.json",
            "файловый агент: создай report.txt",
            "скопируй файл data.json в data_backup.json",
            "перемести файл log.txt в logs/log.txt",
            "метаданные файла ARCHITECTURE.md",
            "прочитай файл README.md",
            "создай файл greeting.txt с содержимым Привет мир"
        ]
        for cmd in test_commands:
            match = self.router.match_file(cmd)
            self.assertIsNotNone(match, f"Команда не распознана match_file: '{cmd}'")

        # Запросы файлов не должны распознаваться как генерация изображений
        img_res = self.router.match_image("создай файл picture.png с красивыми картинками")
        self.assertIsNone(img_res, "Запрос создания файла не должен перехватываться match_image")

    def test_router_dispatch_file_fastpath(self):
        """Проверка диспетчеризации в CommandRouter.route."""
        r1 = self.router.route("субагент file: покажи файл test.txt")
        self.assertEqual(r1["type"], "file")

        r2 = self.router.route("скопируй файл old.txt в new.txt")
        self.assertEqual(r2["type"], "file")
        self.assertEqual(r2["action"], "copy")

        r3 = self.router.route("метаданные файла config.py")
        self.assertEqual(r3["type"], "file")
        self.assertEqual(r3["action"], "metadata")

    def test_agent_process_file_routing(self):
        """Сквозная интеграция вызова FileAgent через Agent.process."""
        from tools.agent import Agent
        agent = Agent()

        # Чтение файла проекта через явную команду субагента
        resp = agent.process("субагент file: прочитай файл ARCHITECTURE.md")
        self.assertEqual(resp.get("type"), "file")
        self.assertTrue(resp.get("success"), f"Agent.process failed: {resp.get('error')}")
        self.assertIn("успешно прочитан", resp.get("answer", ""))
        self.assertEqual(len(resp.get("artifacts", [])), 1)


if __name__ == "__main__":
    unittest.main()
