"""
Targeted tests for ImageArtifactCard, FileArtifactCard, and GUI artifact integration.
"""

import os
import sys
import tempfile
import unittest
import tkinter as tk
from unittest.mock import MagicMock
from pathlib import Path

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from PIL import Image
from tools.agents.result import Artifact, ArtifactType
from ui.artifact_card import (
    ImageArtifactCard,
    FileArtifactCard,
    create_artifact_card,
    _resolve_artifact_path,
)
from ui.views.chat import ChatView
from ui.views.home import HomeView
from tools.household import HouseholdManager


class TestArtifactCard(unittest.TestCase):
    """Тестирование карточек артефактов и рендереров."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.temp_dir = tempfile.TemporaryDirectory()

        # Создаём реальное тестовое изображение PNG (800x600)
        self.test_img_path = os.path.join(self.temp_dir.name, "sample_ai_art.png")
        img = Image.new("RGB", (800, 600), color=(56, 189, 248))
        img.save(self.test_img_path, format="PNG")

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass
        self.temp_dir.cleanup()

    def test_image_artifact_detection(self):
        """Проверяет корректное определение IMAGE Artifact различными способами."""
        # 1. Через объект Artifact(type=ArtifactType.IMAGE)
        art1 = Artifact(name="art1.png", type=ArtifactType.IMAGE, path=self.test_img_path)
        card1 = create_artifact_card(self.root, art1)
        self.assertIsInstance(card1, ImageArtifactCard)

        # 2. Через словарь с type: image
        art2 = {"type": "image", "name": "art2.jpg", "path": self.test_img_path}
        card2 = create_artifact_card(self.root, art2)
        self.assertIsInstance(card2, ImageArtifactCard)

        # 3. Через путь с расширением изображения (.png, .webp)
        card3 = create_artifact_card(self.root, self.test_img_path)
        self.assertIsInstance(card3, ImageArtifactCard)

    def test_image_artifact_card_with_real_image(self):
        """Проверяет создание карточки с реальным изображением, thumbnail и метаданными."""
        art = Artifact.from_image(
            path=self.test_img_path,
            name="sample_ai_art.png",
            width=800,
            height=600,
            prompt="Futuristic neural city at night"
        )

        card = ImageArtifactCard(self.root, art, compact=False)
        self.root.update()

        # Проверяем, что thumbnail загружен и ссылка сохранена
        self.assertIsNotNone(card._photo_ref)
        self.assertFalse(card._is_error)
        self.assertEqual(card.orig_width, 800)
        self.assertEqual(card.orig_height, 600)

        # Проверяем компактный режим (для HomeView)
        compact_card = ImageArtifactCard(self.root, art, compact=True)
        self.root.update()
        self.assertIsNotNone(compact_card._photo_ref)
        self.assertFalse(compact_card._is_error)

    def test_missing_image_handled_gracefully(self):
        """Проверяет аккуратную обработку отсутствующего файла без падения GUI."""
        fake_path = os.path.join(self.temp_dir.name, "non_existent_file.png")
        art = Artifact(name="missing.png", type=ArtifactType.IMAGE, path=fake_path)

        card = ImageArtifactCard(self.root, art)
        self.root.update()

        # Должен активироваться флаг ошибки, но исключений быть не должно
        self.assertTrue(card._is_error)
        self.assertIsNone(card._photo_ref)

    def test_non_image_artifact_fallback(self):
        """Проверяет, что неграфические артефакты создают FileArtifactCard и не ломаются."""
        # Документ PDF
        doc_art = Artifact(name="report.pdf", type=ArtifactType.DOCUMENT, path="data/report.pdf")
        doc_card = create_artifact_card(self.root, doc_art)
        self.assertIsInstance(doc_card, FileArtifactCard)
        self.assertEqual(doc_card.art_type, ArtifactType.DOCUMENT)

        # Презентация PPTX
        pres_art = Artifact(name="deck.pptx", type=ArtifactType.PRESENTATION, path="data/deck.pptx")
        pres_card = create_artifact_card(self.root, pres_art)
        self.assertIsInstance(pres_card, FileArtifactCard)
        self.assertEqual(pres_card.art_type, ArtifactType.PRESENTATION)

        # Исходный код
        code_art = Artifact(name="script.py", type=ArtifactType.CODE, path="data/script.py")
        code_card = create_artifact_card(self.root, code_art)
        self.assertIsInstance(code_card, FileArtifactCard)

    def test_chat_view_renders_image_artifact(self):
        """Проверяет встраивание карточки IMAGE Artifact непосредственно в ChatView."""
        chat_view = ChatView(self.root, shell=MagicMock())
        self.root.update()

        art = Artifact.from_image(path=self.test_img_path, prompt="Cyberpunk avatar")
        chat_view.insert_chat_ui(
            author="Акакий",
            message="Изображение успешно сгенерировано:",
            t_str="12:00:00",
            artifacts=[art]
        )
        self.root.update()

        # Проверяем, что в Text виджете появилось встроенное окно
        embedded_windows = chat_view.chat_text.window_names()
        self.assertGreaterEqual(len(embedded_windows), 1)

    def test_home_view_renders_recent_work_image_artifact(self):
        """Проверяет отображение IMAGE Artifact в Recent Work Results на HomeView."""
        mock_shell = MagicMock()
        mock_shell.recent_work_results = [
            {
                "type": "image",
                "title": "Генерация изображения",
                "message": "Изображение успешно сгенерировано: sample_ai_art.png",
                "time": "12:00:00",
                "success": True,
                "created_files": [self.test_img_path],
                "artifacts": [
                    {
                        "name": "sample_ai_art.png",
                        "type": "image",
                        "path": self.test_img_path,
                        "metadata": {"prompt": "Sunset over digital ocean"}
                    }
                ]
            }
        ]
        storage_path = os.path.join(self.temp_dir.name, "h.json")
        mock_shell.household = HouseholdManager(storage_path=storage_path)

        home_view = HomeView(self.root, shell=mock_shell)
        self.root.update()

        # Ищем виджет ImageArtifactCard среди дочерних элементов HomeView
        def find_image_cards(widget):
            cards = []
            if isinstance(widget, ImageArtifactCard):
                cards.append(widget)
            for child in widget.winfo_children():
                cards.extend(find_image_cards(child))
            return cards

        cards = find_image_cards(home_view)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].artifact_name, "sample_ai_art.png")
        self.assertTrue(cards[0].compact)


if __name__ == "__main__":
    unittest.main(verbosity=2)
