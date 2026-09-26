"""
Unit и интеграционные тесты для Agent Teamwork v1 (Sub-Agent Pipeline).

Проверяют:
- нормализацию шагов (PipelineStep, tuple, dict, валидация);
- обработку пустого pipeline и неизвестных субагентов;
- последовательный конвейер из 2 шагов (EchoAgent -> EchoAgent);
- последовательный конвейер из 2 шагов с файлами (FileAgent create -> FileAgent read);
- последовательный конвейер из 3 шагов (ResearchAgent -> DocumentAgent -> FileAgent);
- последовательный конвейер из 3 шагов с кодом (FileAgent -> CodingAgent -> FileAgent);
- досрочную остановку при сбое на промежуточном шаге с сохранением артефактов предыдущих шагов;
- работу пользовательского input_transform;
- функцию run_agent_pipeline (публичный функциональный API);
- интеграцию TeamworkCoordinator.run_pipeline с объектом Agent.
"""

from pathlib import Path
import shutil
import tempfile
import unittest

from tools.agents.context import AgentContext
from tools.agents.registry import get_agent_registry
from tools.agents.result import AgentResult, Artifact, ArtifactType
from tools.teamwork import (
    PipelineStep,
    TeamworkPipeline,
    normalize_step,
    run_agent_pipeline,
)


class TestAgentTeamwork(unittest.TestCase):
    """Тестовый набор для конвейера взаимодействия субагентов (Agent Teamwork v1)."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="teamwork_test_")
        self.tmp_path = Path(self.tmp_dir).resolve()

        from tools.agents.echo import EchoAgent
        from tools.agents.file import FileAgent
        from tools.agents.coding import CodingAgent
        from tools.agents.research import ResearchAgent
        from tools.agents.document import DocumentAgent
        from tools.agents.registry import AgentRegistry

        self.registry = AgentRegistry()
        self.registry.register(EchoAgent())
        self.registry.register(FileAgent(project_path=self.tmp_path))
        self.registry.register(CodingAgent(project_path=self.tmp_path))
        self.registry.register(ResearchAgent(output_dir=self.tmp_path / "research", project_path=self.tmp_path))
        self.registry.register(DocumentAgent(output_dir=self.tmp_path / "documents"))

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_normalize_step_formats(self):
        """Проверка нормализации шагов из разных форматов (объект, кортеж, словарь)."""
        # 1. Из PipelineStep
        s1 = PipelineStep(agent="echo", task="test task")
        self.assertEqual(normalize_step(s1), s1)

        # 2. Из кортежа (agent, task)
        s2 = normalize_step(("echo", "hello world"))
        self.assertEqual(s2.agent_name, "echo")
        self.assertEqual(s2.task, "hello world")

        # 3. Из кортежа (agent, task, metadata)
        s3 = normalize_step(("file", "read file", {"param": 123}))
        self.assertEqual(s3.agent_name, "file")
        self.assertEqual(s3.metadata.get("param"), 123)

        # 4. Из словаря
        s4 = normalize_step({
            "agent": "research",
            "task": "исследуй тему",
            "name": "custom_research",
            "metadata": {"depth": 2}
        })
        self.assertEqual(s4.agent_name, "research")
        self.assertEqual(s4.name, "custom_research")
        self.assertEqual(s4.metadata.get("depth"), 2)

        # 5. Ошибка при некорректном формате
        with self.assertRaises(ValueError):
            normalize_step(12345)

        with self.assertRaises(ValueError):
            normalize_step({"task": "no agent"})

    def test_empty_pipeline_fails(self):
        """Пустой pipeline возвращает ошибку."""
        pipeline = TeamworkPipeline(registry=self.registry)
        res = pipeline.run()
        self.assertFalse(res.success)
        self.assertIn("не содержит шагов", res.error)

    def test_unknown_agent_fails(self):
        """Попытка вызвать несуществующего агента прерывает pipeline."""
        pipeline = TeamworkPipeline(registry=self.registry)
        pipeline.add_step(("unregistered_agent_xyz", "some task"))
        res = pipeline.run()
        self.assertFalse(res.success)
        self.assertIn("не найден в реестре", res.error)
        self.assertEqual(res.data.get("failed_step"), 1)

    def test_two_step_echo_pipeline(self):
        """Базовый конвейер из 2 шагов EchoAgent с передачей контекста."""
        pipeline = TeamworkPipeline(registry=self.registry)
        pipeline.add_step(("echo", "Сообщение 1"))
        pipeline.add_step(("echo", "Сообщение 2"))

        res = pipeline.run(initial_task="Старт")
        self.assertTrue(res.success, f"Pipeline failed: {res.error}")
        self.assertEqual(res.data.get("total_steps"), 2)
        self.assertEqual(res.data.get("completed_steps"), 2)
        self.assertEqual(len(res.data.get("history")), 2)
        self.assertEqual(res.data["pipeline"], ["echo", "echo"])

    def test_two_step_file_pipeline(self):
        """Последовательное взаимодействие: создание файла -> чтение файла."""
        test_file = self.tmp_path / "teamwork_note.txt"
        pipeline = TeamworkPipeline(registry=self.registry)

        # Шаг 1: FileAgent создаёт файл
        pipeline.add_step({
            "agent": "file",
            "task": f"создай файл {test_file} с содержимым Данные конвейера",
            "name": "create_note"
        })

        # Шаг 2: FileAgent читает файл
        pipeline.add_step({
            "agent": "file",
            "task": f"прочитай файл {test_file}",
            "name": "read_note"
        })

        res = pipeline.run()
        self.assertTrue(res.success, f"Pipeline failed: {res.error}")
        self.assertTrue(test_file.exists())
        self.assertEqual(test_file.read_text(encoding="utf-8"), "Данные конвейера")
        self.assertEqual(len(res.created_files), 1)
        self.assertEqual(len(res.artifacts), 2)  # 1 артефакт создания + 1 артефакт чтения
        self.assertEqual(res.data.get("completed_steps"), 2)

    def test_three_step_research_document_file_pipeline(self):
        """
        Конвейер из 3 разнородных субагентов:
        1. ResearchAgent собирает информацию по теме;
        2. DocumentAgent генерирует .docx документ на основе исследования;
        3. FileAgent получает структурированные метаданные созданного документа.
        """
        pipeline = TeamworkPipeline(registry=self.registry)

        # Шаг 1: Исследование
        pipeline.add_step(
            PipelineStep(
                agent="research",
                task="исследуй тему Архитектура Акакия",
                name="step_research"
            )
        )

        # Шаг 2: Создание документа (получает topic и findings из предыдущего шага)
        pipeline.add_step(
            PipelineStep(
                agent="document",
                task="создай документ Архитектура Акакия",
                name="step_document"
            )
        )

        # Шаг 3: Получение метаданных созданного .docx через FileAgent
        def transform_to_meta(ctx: AgentContext, last_res: AgentResult) -> AgentContext:
            if last_res and last_res.created_files:
                doc_path = last_res.created_files[0]
                ctx.instruction = f"метаданные файла {doc_path}"
            return ctx

        pipeline.add_step(
            PipelineStep(
                agent="file",
                name="step_stat",
                input_transform=transform_to_meta
            )
        )

        res = pipeline.run(initial_task="Комплексный анализ архитектуры")
        self.assertTrue(res.success, f"Three-step pipeline failed: {res.error}")
        self.assertEqual(res.data.get("completed_steps"), 3)
        self.assertEqual(res.data["pipeline"], ["research", "document", "file"])

        # Проверяем накопленные артефакты:
        # Research (Markdown) + Document (.docx) + File (metadata)
        self.assertGreaterEqual(len(res.artifacts), 3)
        self.assertTrue(any(a.is_research for a in res.artifacts))
        self.assertTrue(any(a.is_document for a in res.artifacts))

        # Созданные файлы содержат и отчет md, и документ docx
        created = res.created_files
        self.assertTrue(any(f.endswith(".md") for f in created))
        self.assertTrue(any(f.endswith(".docx") for f in created))

    def test_three_step_file_coding_file_pipeline(self):
        """
        Конвейер безопасного изменения кода:
        1. FileAgent создаёт python-файл;
        2. CodingAgent применяет точечные правки и верифицирует синтаксис;
        3. FileAgent копирует файл в бэкап.
        """
        target_py = self.tmp_path / "calc_service.py"
        backup_py = self.tmp_path / "calc_service_backup.py"

        pipeline = TeamworkPipeline(registry=self.registry)

        # Шаг 1: Создание
        pipeline.add_step({
            "agent": "file",
            "task": f"создай файл {target_py} с содержимым def compute():\n    return 10\n"
        })

        # Шаг 2: Точечная модификация кода через CodingAgent
        pipeline.add_step({
            "agent": "coding",
            "task": f"измени код в файле {target_py}",
            "metadata": {
                "target_files": [str(target_py)],
                "allowed_files": [str(target_py)],
                "edits": [
                    {"file": str(target_py), "old_str": "return 10", "new_str": "return 42"}
                ],
                "mode": "edit",
                "verify": True
            }
        })

        # Шаг 3: Создание копии через FileAgent
        pipeline.add_step({
            "agent": "file",
            "task": f"скопируй файл {target_py} в {backup_py}"
        })

        res = pipeline.run()
        self.assertTrue(res.success, f"Code pipeline failed: {res.error}")
        self.assertEqual(res.data.get("completed_steps"), 3)

        # Проверяем итоговый код на диске
        self.assertIn("return 42", target_py.read_text(encoding="utf-8"))
        self.assertTrue(backup_py.exists())
        self.assertIn("return 42", backup_py.read_text(encoding="utf-8"))

        # Артефакты содержат код
        self.assertTrue(any(a.is_code for a in res.artifacts))

    def test_step_error_stops_pipeline(self):
        """Сбой на промежуточном шаге останавливает конвейер и сохраняет накопленные артефакты."""
        created_file = self.tmp_path / "step1_out.txt"
        pipeline = TeamworkPipeline(registry=self.registry, stop_on_error=True)

        # Шаг 1: Успешное создание файла
        pipeline.add_step({
            "agent": "file",
            "task": f"создай файл {created_file} с содержимым Успех шага 1"
        })

        # Шаг 2: Заведомо ошибочный шаг (чтение несуществующего файла)
        pipeline.add_step({
            "agent": "file",
            "task": "прочитай файл absolutely_missing_file_404.txt"
        })

        # Шаг 3: Не должен выполниться
        pipeline.add_step({
            "agent": "echo",
            "task": "этот шаг не должен выполниться"
        })

        res = pipeline.run()
        self.assertFalse(res.success)
        self.assertIn("Pipeline прерван", res.message)
        self.assertEqual(res.data.get("failed_step"), 2)
        self.assertEqual(res.data.get("completed_steps"), 1)
        self.assertEqual(len(res.data.get("history")), 2)

        # Артефакт шага 1 сохранён в итоговом AgentResult.fail!
        self.assertEqual(len(res.artifacts), 1)
        self.assertEqual(len(res.created_files), 1)
        self.assertTrue(created_file.exists())

    def test_custom_input_transform(self):
        """Проверка модификации контекста через input_transform."""
        def custom_hook(ctx: AgentContext, prev_res: AgentResult) -> AgentContext:
            ctx.set("injected_var", "custom_value_42")
            ctx.instruction = f"эхо: {prev_res.message} -> трансформировано"
            return ctx

        pipeline = TeamworkPipeline(registry=self.registry)
        pipeline.add_step(("echo", "Исходный шаг 1"))
        pipeline.add_step(PipelineStep(agent="echo", input_transform=custom_hook))

        res = pipeline.run()
        self.assertTrue(res.success)
        self.assertEqual(res.data.get("completed_steps"), 2)
        step2_hist = res.data["history"][1]
        self.assertIn("трансформировано", step2_hist["task"])

    def test_run_agent_pipeline_convenience_api(self):
        """Проверка функционального API run_agent_pipeline."""
        res = run_agent_pipeline(
            steps=[
                ("echo", "Шаг 1"),
                ("echo", "Шаг 2"),
                ("echo", "Шаг 3")
            ],
            registry=self.registry
        )
        self.assertTrue(res.success)
        self.assertEqual(res.data.get("total_steps"), 3)
        self.assertEqual(res.data.get("completed_steps"), 3)

    def test_teamwork_coordinator_run_pipeline(self):
        """Проверка метода run_pipeline у TeamworkCoordinator."""
        from tools.agent import Agent
        agent = Agent()

        res = agent.teamwork.run_pipeline([
            ("echo", "координатор шаг 1"),
            ("echo", "координатор шаг 2")
        ])
        self.assertTrue(res.success)
        self.assertEqual(res.data.get("completed_steps"), 2)
        self.assertEqual(res.data["pipeline"], ["echo", "echo"])


if __name__ == "__main__":
    unittest.main()
