"""
Модуль тестирования специализированного Sub-Agent'а CodingAgent (Этап 10).

Проверяет:
1. Инициализацию, свойства и метаданные CodingAgent;
2. Разбор задачи, целевых файлов и инструкций (parse_task);
3. Статический анализ файлов и выявление проблем (analyze_files);
4. Защиту периметра безопасности (safety boundary: запрет изменения файлов вне allowed_files);
5. Безопасное применение точечных правок (apply_edits);
6. Targeted verification изменённых файлов (проверка синтаксиса и тестов);
7. Полный жизненный цикл run(AgentContext) -> AgentResult с Artifact типа code;
8. Обработку ошибок (невалидный контекст, отключенный агент, пустая задача, сбой верификации);
9. Регистрацию CodingAgent в AgentRegistry по умолчанию;
10. Маршрутизацию естественных и явных запросов кодинга в CommandRouter;
11. Интеграцию с Agent.process().
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.agents import (
    AgentContext,
    AgentResult,
    AgentRegistry,
    Artifact,
    ArtifactType,
    CodingAgent,
    get_agent_registry,
    reset_agent_registry,
)
from tools.router import CommandRouter


class TestCodingAgent(unittest.TestCase):
    """1. Модульное тестирование функционала CodingAgent."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name).resolve()
        self.agent = CodingAgent(project_path=self.temp_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_and_capabilities(self):
        """Проверка инициализации и заявленных возможностей."""
        self.assertEqual(self.agent.name, "coding")
        self.assertTrue(self.agent.enabled)
        self.assertIn("coding", self.agent.capabilities)
        self.assertIn("code", self.agent.capabilities)
        self.assertIn("edit", self.agent.capabilities)
        self.assertIn("verify", self.agent.capabilities)
        self.assertEqual(self.agent.project_path, self.temp_path)

    def test_parse_task_from_prompt_and_metadata(self):
        """Разбор задачи, файлов и белого списка allowed_files."""
        task_str = "измени код в файле utils.py замени 'foo' на 'bar'"
        meta = {
            "allowed_files": ["utils.py"],
            "verify": True
        }
        parsed = self.agent.parse_task(task_str, metadata=meta)

        self.assertIn("utils.py", parsed["target_files"])
        self.assertIn("utils.py", parsed["allowed_files"])
        self.assertEqual(parsed["mode"], "edit")
        self.assertEqual(len(parsed["edits"]), 1)
        self.assertEqual(parsed["edits"][0]["old_text"], "foo")
        self.assertEqual(parsed["edits"][0]["new_text"], "bar")
        self.assertTrue(parsed["verify"])

    def test_parse_task_analyze_mode(self):
        """Режим анализа при отсутствии инструкций по замене."""
        task_str = "проанализируй код в файле tools/agent.py"
        parsed = self.agent.parse_task(task_str)
        self.assertEqual(parsed["mode"], "analyze")
        self.assertIn("tools/agent.py", parsed["target_files"])

    def test_analyze_files_detects_syntax_errors(self):
        """Анализ файлов выявляет синтаксические ошибки в Python-файлах."""
        valid_py = self.temp_path / "valid.py"
        valid_py.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

        broken_py = self.temp_path / "broken.py"
        broken_py.write_text("def broken(\n", encoding="utf-8")

        with patch("tools.agents.coding.PROJECT_PATH", self.temp_path), \
             patch("tools.files.PROJECT_PATH", self.temp_path):
            problems, plan = self.agent.analyze_files([str(valid_py), str(broken_py)])

            self.assertEqual(len(problems), 1)
            self.assertEqual(problems[0]["file"], str(broken_py))
            self.assertEqual(problems[0]["type"], "syntax_error")
            self.assertGreaterEqual(len(plan), 2)

    def test_apply_edits_safety_boundary(self):
        """Запрещено вносить изменения в файлы, не входящие в allowed_files."""
        target_file = self.temp_path / "forbidden.py"
        target_file.write_text("x = 1\n", encoding="utf-8")

        edits = [{
            "file": str(target_file),
            "old_text": "x = 1",
            "new_text": "x = 2"
        }]
        allowed_files = {"safe.py"}  # forbidden.py отсутствует в белом списке

        success, modified, results, err = self.agent.apply_edits(
            edits=edits,
            allowed_files=allowed_files
        )

        self.assertFalse(success)
        self.assertIn("не входит в список разрешённых", err)
        self.assertEqual(len(modified), 0)
        # Убеждаемся, что файл на диске остался нетронутым
        self.assertEqual(target_file.read_text(encoding="utf-8"), "x = 1\n")

    def test_apply_edits_success(self):
        """Успешное применение точечной правки в разрешённом файле."""
        target_file = self.temp_path / "target.py"
        target_file.write_text("def calculate():\n    return 42\n", encoding="utf-8")

        with patch("tools.agents.coding.PROJECT_PATH", self.temp_path), \
             patch("tools.files.PROJECT_PATH", self.temp_path):
            norm_name = self.agent._normalize_path_str(target_file)
            edits = [{
                "file": str(target_file),
                "old_text": "return 42",
                "new_text": "return 100"
            }]

            success, modified, results, err = self.agent.apply_edits(
                edits=edits,
                allowed_files={norm_name}
            )

            self.assertTrue(success)
            self.assertIsNone(err)
            self.assertEqual(len(modified), 1)
            self.assertIn("return 100", target_file.read_text(encoding="utf-8"))

    def test_verify_changes_detects_broken_syntax(self):
        """Верификация выявляет синтаксические ошибки после применения правок."""
        broken_file = self.temp_path / "mod.py"
        broken_file.write_text("def error(\n", encoding="utf-8")

        with patch("tools.agents.coding.PROJECT_PATH", self.temp_path), \
             patch("tools.files.PROJECT_PATH", self.temp_path):
            v_ok, v_report = self.agent.verify_changes([str(broken_file)])
            self.assertFalse(v_ok)
            self.assertFalse(v_report["syntax_ok"])
            self.assertEqual(len(v_report["syntax_errors"]), 1)

    def test_run_success_creates_artifacts_and_result(self):
        """Полный успешный прогон run() возвращает AgentResult с Artifact типа code."""
        code_file = self.temp_path / "service.py"
        code_file.write_text("VERSION = '1.0'\n", encoding="utf-8")

        with patch("tools.agents.coding.PROJECT_PATH", self.temp_path), \
             patch("tools.files.PROJECT_PATH", self.temp_path):
            ctx = AgentContext(
                task=f"замени '1.0' на '2.0' в файле {code_file.name}",
                files=[str(code_file)]
            )
            res = self.agent.run(ctx)

            self.assertIsInstance(res, AgentResult)
            self.assertTrue(res.success)
            self.assertIn("Успешно применены изменения", res.message)
            self.assertEqual(len(res.created_files), 1)

            # Проверка артефактов
            self.assertEqual(len(res.artifacts), 1)
            art = res.artifacts[0]
            self.assertIsInstance(art, Artifact)
            self.assertEqual(art.type, ArtifactType.CODE)
            self.assertTrue(art.is_code)
            self.assertEqual(len(res.code_artifacts), 1)

            # Проверка изменения на диске
            self.assertIn("VERSION = '2.0'", code_file.read_text(encoding="utf-8"))

    def test_run_verification_failure_returns_fail(self):
        """Если правка нарушает синтаксис, run() завершается ошибкой верификации."""
        code_file = self.temp_path / "syntax_test.py"
        code_file.write_text("def test():\n    pass\n", encoding="utf-8")

        with patch("tools.agents.coding.PROJECT_PATH", self.temp_path), \
             patch("tools.files.PROJECT_PATH", self.temp_path):
            ctx = AgentContext(
                task=f"сломай синтаксис",
                metadata={
                    "edits": [{
                        "file": str(code_file),
                        "old_text": "def test():\n    pass\n",
                        "new_text": "def broken(\n"
                    }],
                    "allowed_files": [str(code_file)],
                    "verify": True
                }
            )
            res = self.agent.run(ctx)

            self.assertFalse(res.success)
            self.assertIn("Верификация после правок не пройдена", res.error)

    def test_run_with_invalid_context_returns_fail(self):
        """Невалидный контекст возвращает AgentResult.fail."""
        res = self.agent.run("не AgentContext")
        self.assertFalse(res.success)
        self.assertIn("Некорректный контекст", res.error)

    def test_run_when_disabled_returns_fail(self):
        """Отключенный агент возвращает AgentResult.fail."""
        self.agent.enabled = False
        ctx = AgentContext(task="кодинг")
        res = self.agent.run(ctx)
        self.assertFalse(res.success)
        self.assertIn("отключен", res.error)

    def test_run_with_empty_task_returns_fail(self):
        """Пустая задача без файлов возвращает AgentResult.fail."""
        ctx = AgentContext(task="")
        res = self.agent.run(ctx)
        self.assertFalse(res.success)
        self.assertIn("Не указана задача или файлы", res.error)


class TestCodingRegistryAndRouting(unittest.TestCase):
    """2. Тестирование регистрации и маршрутизации CodingAgent."""

    def setUp(self):
        reset_agent_registry()
        self.router = CommandRouter()

    def tearDown(self):
        reset_agent_registry()

    def test_registry_contains_coding_agent(self):
        """CodingAgent автоматически зарегистрирован в AgentRegistry."""
        reg = get_agent_registry()
        self.assertTrue(reg.has("coding"))
        agent = reg.get("coding")
        self.assertIsInstance(agent, CodingAgent)

    def test_router_match_coding_patterns(self):
        """Проверка распознавания естественных и явных команд кодинга."""
        patterns = [
            ("кодинг: обнови функцию test в utils.py", "обнови функцию test в utils.py"),
            ("код: исправь опечатку в config.py", "исправь опечатку в config.py"),
            ("coding: refactor module test.py", "refactor module test.py"),
            ("измени код в файле tools/agent.py", "tools/agent.py"),
            ("исправь код в файле main.py", "main.py"),
            ("отредактируй файл settings.py", "settings.py"),
            ("проанализируй код в файле helper.py", "helper.py"),
            ("примени патч к файлу data.py", "data.py"),
            ("Акакий, пожалуйста, исправь код в файле logic.py", "logic.py"),
        ]
        for user_cmd, expected_fragment in patterns:
            res = self.router.match_coding(user_cmd)
            self.assertIsNotNone(res, f"Команда '{user_cmd}' не распознана match_coding")
            self.assertEqual(res["action"], "coding")
            self.assertIn(expected_fragment, res["prompt"])

    def test_router_route_integration(self):
        """CommandRouter.route() возвращает type: 'coding'."""
        route = self.router.route("кодинг: оптимизируй функцию calculate в math.py")
        self.assertEqual(route.get("type"), "coding")
        self.assertEqual(route.get("action"), "coding")
        self.assertIn("calculate в math.py", route.get("prompt"))

    def test_explicit_subagent_route(self):
        """Явный вызов субагента 'субагент coding: ...' маршрутизируется в coding."""
        route1 = self.router.route("субагент coding: обнови config.py")
        self.assertEqual(route1.get("type"), "coding")
        self.assertEqual(route1.get("prompt"), "обнови config.py")

        route2 = self.router.route("субагент code: проверь main.py")
        self.assertEqual(route2.get("type"), "coding")
        self.assertEqual(route2.get("prompt"), "проверь main.py")

    def test_non_image_target_protection(self):
        """Запросы кодинга не перехватываются ImageAgent."""
        img_res = self.router.match_image("отредактируй код с красивыми картинками")
        self.assertIsNone(img_res, "Запрос кодинга не должен перехватываться match_image")

    def test_agent_process_coding_routing(self):
        """Интеграционная проверка вызова CodingAgent через Agent.process()."""
        from tools.agent import Agent

        mock_ai = MagicMock()
        mock_mem = MagicMock()
        main_agent = Agent(ai_client=mock_ai, memory_manager=mock_mem)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir).resolve()
            test_py = tmp_path / "demo.py"
            test_py.write_text("VAL = 10\n", encoding="utf-8")

            coding_agent = CodingAgent(project_path=tmp_path)
            main_agent.agent_registry.register(coding_agent)

            with patch("tools.agents.coding.PROJECT_PATH", tmp_path), \
                 patch("tools.files.PROJECT_PATH", tmp_path):
                result = main_agent.process(f"проанализируй код в файле {test_py.name}")
                self.assertEqual(result["type"], "coding")
                self.assertTrue(result["success"])
                self.assertIn("Анализ кода завершён", result["answer"])


if __name__ == "__main__":
    unittest.main()
