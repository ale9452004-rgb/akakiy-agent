"""
Тесты для быстрых команд CLI REPL и интеграции commands.py с main.py.
"""

import io
import sys
import unittest
from unittest.mock import MagicMock, patch

from commands import (
    show_help,
    show_status,
    show_files,
    read_file,
    handle_cli_command,
)
import main


class TestCLICommands(unittest.TestCase):
    """Тестирование функций модуля commands.py."""

    @patch("commands.requests.get")
    def test_show_status_online_with_model(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "qwen3:8b:latest"}]}
        mock_get.return_value = mock_resp

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            show_status()

        output = buf.getvalue()
        self.assertIn("--- Статус Акакия ---", output)
        self.assertIn("Ollama: подключён", output)
        self.assertIn("Статус: работает", output)

    @patch("commands.requests.get")
    def test_show_status_offline(self, mock_get):
        import requests
        mock_get.side_effect = requests.RequestException("Connection refused")

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            show_status()

        output = buf.getvalue()
        self.assertIn("--- Статус Акакия ---", output)
        self.assertIn("недоступен (сервер не запущен)", output)
        self.assertIn("ошибка (нет связи с Ollama)", output)

    def test_show_help_contains_fast_commands(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            show_help()

        output = buf.getvalue()
        self.assertIn("Быстрые команды CLI:", output)
        self.assertIn(":status", output)
        self.assertIn(":files", output)
        self.assertIn(":read", output)
        self.assertIn(":help", output)
        self.assertIn(":exit", output)

    def test_show_files_prints_real_files(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            show_files()

        output = buf.getvalue()
        self.assertIn("--- Файлы проекта ---", output)
        self.assertIn("config.py", output)
        self.assertIn("main.py", output)
        # Проверяем, что не выводятся ключи словаря-обёртки
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        self.assertNotIn("count", lines)
        self.assertNotIn("success", lines)

    def test_read_file_existing(self):
        content = read_file("config.py")
        self.assertIsNotNone(content)
        self.assertIn("PROJECT_PATH", content)

    def test_read_file_nonexistent(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            content = read_file("nonexistent_file_xyz_123.txt")

        self.assertIsNone(content)
        output = buf.getvalue()
        self.assertIn("Файл не найден", output)


class TestCLICommandHandler(unittest.TestCase):
    """Тестирование роутера быстрых команд handle_cli_command."""

    @patch("commands.show_status")
    def test_status_aliases(self, mock_status):
        for cmd in [":status", ":STATUS", "  :status  ", ":статус", ":s", "статус", "status", "show_status"]:
            with self.subTest(cmd=cmd):
                mock_status.reset_mock()
                handled = handle_cli_command(cmd)
                self.assertTrue(handled, f"Команда {cmd} должна быть обработана")
                mock_status.assert_called_once()

    @patch("commands.show_help")
    def test_help_aliases(self, mock_help):
        for cmd in [":help", ":HELP", ":помощь", ":h", ":?", "?", "помощь", "help", "show_help"]:
            with self.subTest(cmd=cmd):
                mock_help.reset_mock()
                handled = handle_cli_command(cmd)
                self.assertTrue(handled, f"Команда {cmd} должна быть обработана")
                mock_help.assert_called_once()

    @patch("commands.show_files")
    def test_files_aliases(self, mock_files):
        for cmd in [":files", ":FILES", ":файлы", ":ls", ":dir", ":f", "files", "show_files"]:
            with self.subTest(cmd=cmd):
                mock_files.reset_mock()
                handled = handle_cli_command(cmd)
                self.assertTrue(handled, f"Команда {cmd} должна быть обработана")
                mock_files.assert_called_once()

    def test_read_file_valid_aliases(self):
        for cmd in [":read config.py", ":cat config.py", ":read_file config.py", "cat config.py", "read_file config.py"]:
            with self.subTest(cmd=cmd):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    handled = handle_cli_command(cmd)
                self.assertTrue(handled)
                output = buf.getvalue()
                self.assertIn("--- config.py ---", output)
                self.assertIn("PROJECT_PATH", output)

    def test_read_file_quoted_argument(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            handled = handle_cli_command(':read "config.py"')
        self.assertTrue(handled)
        output = buf.getvalue()
        self.assertIn("--- config.py ---", output)
        self.assertIn("PROJECT_PATH", output)

    def test_read_file_missing_argument(self):
        for cmd in [":read", ":cat", ":read_file", "read_file", ':read ""']:
            with self.subTest(cmd=cmd):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    handled = handle_cli_command(cmd)
                self.assertTrue(handled)
                output = buf.getvalue()
                self.assertIn("Использование: :read", output)

    def test_read_file_nonexistent(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            handled = handle_cli_command(":read nonexistent_file_xyz_123.txt")
        self.assertTrue(handled)
        output = buf.getvalue()
        self.assertIn("Файл не найден", output)

    def test_non_cli_queries_pass_through(self):
        # Обычные команды Акакия не должны перехватываться
        queries = [
            "покажи список файлов",
            "покажи файлы",
            "найди файл config.py",
            "найди функцию main",
            "поиск по проекту test",
            "создай задачу купить хлеб",
            "покажи задачи",
            "создай заметку мысли: текст",
            "напомни позвонить маме в 19:00",
            "запомни: я люблю кофе",
            "что ты помнишь",
            "план: отрефакторить код",
            "Привет, Акакий!",
            "",
            None,
        ]
        for query in queries:
            with self.subTest(query=query):
                handled = handle_cli_command(query)
                self.assertFalse(handled, f"Запрос '{query}' не должен обрабатываться как CLI-команда")


class TestMainREPLIntegration(unittest.TestCase):
    """Интеграционные тесты интерактивного REPL цикла в main.py."""

    @patch("main.Agent")
    @patch("main.input")
    def test_main_exit_aliases(self, mock_input, mock_agent_cls):
        for exit_cmd in ["выход", "exit", "quit", ":exit", ":quit", ":q", "EXIT", "QUIT"]:
            with self.subTest(exit_cmd=exit_cmd):
                mock_input.side_effect = [exit_cmd]
                buf = io.StringIO()
                with patch("sys.stdout", buf), patch("sys.argv", ["main.py"]):
                    main.main()

                output = buf.getvalue()
                self.assertIn("Акакий запущен.", output)
                self.assertIn("Акакий завершает работу.", output)

    @patch("main.Agent")
    @patch("main.input")
    @patch("main.handle_cli_command")
    def test_main_executes_cli_command_without_agent(self, mock_handle, mock_input, mock_agent_cls):
        mock_agent = MagicMock()
        mock_agent_cls.return_value = mock_agent

        mock_input.side_effect = [":files", ":status", "выход"]
        mock_handle.return_value = True

        buf = io.StringIO()
        with patch("sys.stdout", buf), patch("sys.argv", ["main.py"]):
            main.main()

        self.assertEqual(mock_handle.call_count, 2)
        mock_agent.process.assert_not_called()

    @patch("main.Agent")
    @patch("main.input")
    def test_main_passes_regular_query_to_agent(self, mock_input, mock_agent_cls):
        mock_agent = MagicMock()
        mock_agent.process.return_value = {
            "type": "chat",
            "answer": "Здравствуй, создатель!",
        }
        mock_agent_cls.return_value = mock_agent

        mock_input.side_effect = ["Привет!", "выход"]

        buf = io.StringIO()
        with patch("sys.stdout", buf), patch("sys.argv", ["main.py"]):
            main.main()

        mock_agent.process.assert_called_once_with("Привет!")
        output = buf.getvalue()
        self.assertIn("Здравствуй, создатель!", output)


if __name__ == "__main__":
    unittest.main()
