"""
Модуль тестирования AgentResult v2 и модели Artifact (Этап 6).

Проверяет:
1. Создание, свойства, фабричные методы и сериализацию Artifact;
2. Классификацию и автоопределение типов артефактов ArtifactType;
3. Синхронизацию между created_files и artifacts;
4. Поддержку нескольких артефактов разных типов в одном AgentResult;
5. Выборку по типу, свойство images, поиск по имени и индексу;
6. Полную обратную совместимость с v1 (dict-like интерфейс, from_dict со старыми словарями).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from tools.agents.result import AgentResult, Artifact, ArtifactType


class TestArtifactModel(unittest.TestCase):
    """1. Тестирование модели Artifact и фабричных методов."""

    def test_artifact_defaults(self):
        """Проверка инициализации по умолчанию."""
        art = Artifact(name="test_item")
        self.assertEqual(art.name, "test_item")
        self.assertEqual(art.type, ArtifactType.FILE)
        self.assertIsNone(art.path)
        self.assertIsNone(art.content)
        self.assertEqual(art.metadata, {})
        self.assertFalse(art.is_image)
        self.assertFalse(art.is_document)
        self.assertFalse(art.is_file)
        self.assertFalse(art.exists())

    def test_artifact_properties_and_helpers(self):
        """Проверка свойств is_image, is_document, is_file."""
        img_art = Artifact(name="pic.png", type=ArtifactType.IMAGE, path="some/path/pic.png")
        self.assertTrue(img_art.is_image)
        self.assertFalse(img_art.is_document)
        self.assertTrue(img_art.is_file)

        doc_art = Artifact(name="report.pdf", type=ArtifactType.DOCUMENT, path="some/path/report.pdf")
        self.assertTrue(doc_art.is_document)
        self.assertFalse(doc_art.is_image)

    def test_artifact_from_file_with_real_file(self):
        """Создание артефакта из существующего локального файла с проверкой размера и MIME."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"dummy_content")
            temp_path = f.name

        try:
            art = Artifact.from_file(temp_path)
            self.assertEqual(art.type, ArtifactType.IMAGE)
            self.assertEqual(art.name, Path(temp_path).name)
            self.assertEqual(art.path, temp_path)
            self.assertTrue(art.exists())
            self.assertGreater(art.size_bytes, 0)
            self.assertEqual(art.mime_type, "image/png")
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_artifact_from_image_factory(self):
        """Проверка фабрики Artifact.from_image."""
        art = Artifact.from_image(
            path="data/test.png",
            name="custom_name.png",
            width=1024,
            height=768,
            seed=42
        )
        self.assertEqual(art.type, ArtifactType.IMAGE)
        self.assertEqual(art.name, "custom_name.png")
        self.assertEqual(art.path, "data/test.png")
        self.assertEqual(art.metadata.get("width"), 1024)
        self.assertEqual(art.metadata.get("height"), 768)
        self.assertEqual(art.metadata.get("seed"), 42)

    def test_artifact_from_text_factory(self):
        """Проверка фабрики Artifact.from_text."""
        content = "# Заголовок\nТестовый документ"
        art = Artifact.from_text(content=content, name="notes.md", type=ArtifactType.TEXT)
        self.assertEqual(art.type, ArtifactType.TEXT)
        self.assertEqual(art.content, content)
        self.assertEqual(art.size_bytes, len(content))
        self.assertFalse(art.is_file)

    def test_artifact_dict_like_access(self):
        """Проверка словарного доступа к атрибутам и метаданным Artifact."""
        art = Artifact(
            name="file.txt",
            type="text",
            metadata={"author": "Akakiy", "version": 2}
        )
        # Основные поля
        self.assertEqual(art["name"], "file.txt")
        self.assertEqual(art["type"], "text")
        # Поля из metadata
        self.assertEqual(art["author"], "Akakiy")
        self.assertEqual(art.get("version"), 2)
        self.assertEqual(art.get("non_existent", "default"), "default")
        self.assertIn("author", art)
        self.assertIn("name", art)
        self.assertNotIn("unknown_key", art)

    def test_artifact_serialization_roundtrip(self):
        """Проверка to_dict/from_dict и to_json/from_json."""
        original = Artifact(
            name="doc.pdf",
            type=ArtifactType.DOCUMENT,
            path="/tmp/doc.pdf",
            content="summary",
            metadata={"pages": 12, "author": "User"}
        )
        d = original.to_dict()
        restored = Artifact.from_dict(d)

        self.assertEqual(restored.name, original.name)
        self.assertEqual(restored.type, original.type)
        self.assertEqual(restored.path, original.path)
        self.assertEqual(restored.content, original.content)
        self.assertEqual(restored.metadata, original.metadata)

        # JSON roundtrip
        j = original.to_json()
        from_j = Artifact.from_json(j)
        self.assertEqual(from_j.name, original.name)
        self.assertEqual(from_j.metadata, original.metadata)

    def test_artifact_from_dict_invalid_type_raises(self):
        """from_dict с некорректным типом вызывает TypeError."""
        with self.assertRaises(TypeError):
            Artifact.from_dict("invalid")


class TestArtifactType(unittest.TestCase):
    """2. Тестирование классификатора ArtifactType."""

    def test_guess_type(self):
        """Проверка автоопределения типа по расширению файла."""
        # Изображения
        self.assertEqual(ArtifactType.guess_type("image.png"), ArtifactType.IMAGE)
        self.assertEqual(ArtifactType.guess_type("photo.JPEG"), ArtifactType.IMAGE)
        self.assertEqual(ArtifactType.guess_type("banner.webp"), ArtifactType.IMAGE)
        # Документы
        self.assertEqual(ArtifactType.guess_type("doc.pdf"), ArtifactType.DOCUMENT)
        self.assertEqual(ArtifactType.guess_type("sheet.xlsx"), ArtifactType.DOCUMENT)
        self.assertEqual(ArtifactType.guess_type("table.csv"), ArtifactType.DOCUMENT)
        # Текст
        self.assertEqual(ArtifactType.guess_type("notes.txt"), ArtifactType.TEXT)
        self.assertEqual(ArtifactType.guess_type("README.md"), ArtifactType.TEXT)
        # Код
        self.assertEqual(ArtifactType.guess_type("script.py"), ArtifactType.CODE)
        self.assertEqual(ArtifactType.guess_type("config.json"), ArtifactType.CODE)
        self.assertEqual(ArtifactType.guess_type("app.ts"), ArtifactType.CODE)
        # Аудио
        self.assertEqual(ArtifactType.guess_type("track.mp3"), ArtifactType.AUDIO)
        self.assertEqual(ArtifactType.guess_type("voice.wav"), ArtifactType.AUDIO)
        # Fallback
        self.assertEqual(ArtifactType.guess_type("archive.zip"), ArtifactType.FILE)
        self.assertEqual(ArtifactType.guess_type("binary.bin"), ArtifactType.FILE)
        self.assertEqual(ArtifactType.guess_type(""), ArtifactType.FILE)


class TestAgentResultV2(unittest.TestCase):
    """3. Тестирование AgentResult v2 с поддержкой Artifacts."""

    def test_created_files_sync_to_artifacts(self):
        """Передача created_files автоматически создает соответствующие Artifacts."""
        res = AgentResult.ok(
            message="Файлы созданы",
            created_files=["output/img_1.png", "output/report.pdf"]
        )
        self.assertEqual(len(res.artifacts), 2)
        self.assertEqual(res.created_files, ["output/img_1.png", "output/report.pdf"])

        art1 = res.artifacts[0]
        self.assertEqual(art1.name, "img_1.png")
        self.assertEqual(art1.type, ArtifactType.IMAGE)
        self.assertEqual(art1.path, "output/img_1.png")

        art2 = res.artifacts[1]
        self.assertEqual(art2.name, "report.pdf")
        self.assertEqual(art2.type, ArtifactType.DOCUMENT)

    def test_image_metadata_sync_from_data(self):
        """При создании артефакта из created_files данные width/height/seed переносятся в метаданные."""
        res = AgentResult.ok(
            message="Изображение создано",
            created_files=["data/generated/images/img_test.png"],
            data={"width": 1024, "height": 768, "seed": 12345}
        )
        self.assertEqual(len(res.artifacts), 1)
        art = res.artifacts[0]
        self.assertTrue(art.is_image)
        self.assertEqual(art.metadata.get("width"), 1024)
        self.assertEqual(art.metadata.get("height"), 768)
        self.assertEqual(art.metadata.get("seed"), 12345)

    def test_artifacts_sync_to_created_files(self):
        """Передача явного списка artifacts автоматически синхронизирует created_files."""
        art1 = Artifact(name="pic.png", type=ArtifactType.IMAGE, path="/images/pic.png")
        art2 = Artifact(name="snippet.py", type=ArtifactType.CODE, path="/code/snippet.py")
        art3 = Artifact(name="inline_note", type=ArtifactType.TEXT, content="inline text", path=None)

        res = AgentResult.ok(artifacts=[art1, art2, art3])
        # Только артефакты с реальным path попадают в created_files
        self.assertEqual(res.created_files, ["/images/pic.png", "/code/snippet.py"])
        self.assertEqual(len(res.artifacts), 3)

    def test_add_artifact_and_add_file(self):
        """Добавление артефактов через add_artifact и add_file."""
        res = AgentResult.ok("Пустой результат")
        self.assertFalse(res.has_artifacts)

        # Добавление объекта Artifact
        art1 = res.add_artifact(Artifact(name="manual.png", type=ArtifactType.IMAGE, path="manual.png"))
        self.assertEqual(len(res.artifacts), 1)
        self.assertEqual(res.created_files, ["manual.png"])
        self.assertIs(res.primary_artifact, art1)

        # Добавление через add_file
        art2 = res.add_file("data/doc.pdf", author="Akakiy")
        self.assertEqual(len(res.artifacts), 2)
        self.assertEqual(art2.type, ArtifactType.DOCUMENT)
        self.assertEqual(art2.metadata.get("author"), "Akakiy")
        self.assertEqual(res.created_files, ["manual.png", "data/doc.pdf"])

        # Добавление через словарь
        art3 = res.add_artifact({"name": "inline.txt", "type": "text", "content": "hello"})
        self.assertEqual(len(res.artifacts), 3)
        self.assertEqual(art3.name, "inline.txt")

    def test_filtering_artifacts_by_type_and_images_property(self):
        """Фильтрация артефактов по типу и свойство images."""
        res = AgentResult.ok(
            created_files=["img1.png", "doc.pdf", "img2.jpg", "script.py"]
        )
        self.assertEqual(len(res.images), 2)
        self.assertEqual([a.name for a in res.images], ["img1.png", "img2.jpg"])

        docs = res.get_artifacts_by_type("document")
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].name, "doc.pdf")

        codes = res.get_artifacts_by_type("code")
        self.assertEqual(len(codes), 1)
        self.assertEqual(codes[0].name, "script.py")

    def test_get_artifact_by_name_and_index(self):
        """Поиск артефакта по имени, пути или числовому индексу."""
        res = AgentResult.ok(
            created_files=["folder/a.png", "folder/b.pdf"]
        )
        # По индексу
        self.assertEqual(res.get_artifact(0).name, "a.png")
        self.assertEqual(res.get_artifact(1).name, "b.pdf")
        self.assertIsNone(res.get_artifact(5))

        # По имени
        self.assertEqual(res.get_artifact("a.png").path, "folder/a.png")
        self.assertEqual(res.get_artifact("folder/b.pdf").name, "b.pdf")
        self.assertIsNone(res.get_artifact("non_existent.txt"))

    def test_serialization_roundtrip_dict_and_json(self):
        """Проверка to_dict/from_dict и to_json/from_json для AgentResult."""
        original = AgentResult.ok(
            message="Операция выполнена",
            created_files=["image.png"],
            data={"key": "val"},
            artifacts=[
                Artifact(name="image.png", type=ArtifactType.IMAGE, path="image.png", metadata={"w": 100})
            ]
        )
        d = original.to_dict()
        self.assertIn("artifacts", d)
        self.assertEqual(len(d["artifacts"]), 1)
        self.assertEqual(d["artifacts"][0]["name"], "image.png")

        restored = AgentResult.from_dict(d)
        self.assertTrue(restored.success)
        self.assertEqual(restored.message, original.message)
        self.assertEqual(restored.created_files, original.created_files)
        self.assertEqual(restored.data, original.data)
        self.assertEqual(len(restored.artifacts), 1)
        self.assertEqual(restored.artifacts[0].name, "image.png")
        self.assertEqual(restored.artifacts[0].metadata.get("w"), 100)

        # JSON roundtrip
        j = original.to_json()
        from_j = AgentResult.from_json(j)
        self.assertTrue(from_j.success)
        self.assertEqual(len(from_j.artifacts), 1)

    def test_backward_compatibility_with_v1_dict(self):
        """from_dict корректно парсит старый формат v1 (без ключа 'artifacts')."""
        v1_dict = {
            "success": True,
            "message": "Старый результат",
            "created_files": ["old_output.png"],
            "data": {"version": 1}
        }
        res = AgentResult.from_dict(v1_dict)
        self.assertTrue(res.success)
        self.assertEqual(res.message, "Старый результат")
        self.assertEqual(res.created_files, ["old_output.png"])
        # Автоматически восстановился артефакт
        self.assertEqual(len(res.artifacts), 1)
        self.assertEqual(res.artifacts[0].name, "old_output.png")
        self.assertEqual(res.artifacts[0].type, ArtifactType.IMAGE)

    def test_dict_like_access_compatibility(self):
        """Проверка обратной совместимости с dict-like интерфейсом."""
        res = AgentResult.ok(
            message="Тестовый результат",
            created_files=["file.txt"]
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["message"], "Тестовый результат")
        self.assertEqual(res["created_files"], ["file.txt"])
        self.assertEqual(len(res["artifacts"]), 1)
        self.assertIn("artifacts", res)
        self.assertIn("created_files", res)
        self.assertIn("success", res.keys())

    def test_fail_factory_with_error(self):
        """Проверка создания ошибочного результата."""
        res = AgentResult.fail(
            error="Сбой в обработке",
            message="Ошибка выполнения",
            data={"code": 500}
        )
        self.assertFalse(res.success)
        self.assertEqual(res.error, "Сбой в обработке")
        self.assertEqual(res.message, "Ошибка выполнения")
        self.assertEqual(res.created_files, [])
        self.assertEqual(res.artifacts, [])
        self.assertIn("FAIL", repr(res))


if __name__ == "__main__":
    unittest.main()
