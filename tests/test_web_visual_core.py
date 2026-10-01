"""
Targeted tests for Akakiy Visual Core 2.0 (WebGL2 + WebView2 / Edge Architecture) and Typography.
"""

import os
import unittest
import urllib.request
from pathlib import Path

from ui.web_visual_core import (
    AkakiyVisualBridge,
    find_edge_binary,
    get_free_port
)
from ui.typography import TypographySystem, load_local_fonts


class TestAkakiyWebVisualCore(unittest.TestCase):
    """Тестирование изолированного модуля аппаратного WebGL2 визуализатора."""

    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent
        cls.assets_core_dir = cls.root_dir / "assets" / "akakiy_core"
        cls.assets_fonts_dir = cls.root_dir / "assets" / "fonts"

    def test_core_assets_exist(self):
        """Проверка наличия всех ключевых файлов WebGL2 ядра."""
        index_html = self.assets_core_dir / "index.html"
        core_js = self.assets_core_dir / "core.js"
        core_css = self.assets_core_dir / "core.css"

        self.assertTrue(index_html.exists(), "index.html должен существовать")
        self.assertTrue(core_js.exists(), "core.js должен существовать")
        self.assertTrue(core_css.exists(), "core.css должен существовать")

        self.assertGreater(index_html.stat().st_size, 200)
        self.assertGreater(core_js.stat().st_size, 2000)
        self.assertGreater(core_css.stat().st_size, 500)

    def test_html_calibration_controls(self):
        """Проверка разметки калибровочного HUD в index.html."""
        html_content = (self.assets_core_dir / "index.html").read_text(encoding="utf-8")

        self.assertIn("gl-canvas", html_content)
        self.assertIn("calibration-hud", html_content)
        self.assertIn("audio-slider", html_content)

        # Все 7 состояний
        for st in ("idle", "listening", "thinking", "working", "speaking", "success", "error"):
            self.assertIn(f'data-state="{st}"', html_content)

    def test_glsl_shaders_and_states_in_js(self):
        """Проверка наличия шейдеров, шума, состояний и bridge в core.js."""
        js_content = (self.assets_core_dir / "core.js").read_text(encoding="utf-8")

        self.assertIn("#version 300 es", js_content, "Шейдер должен использовать WebGL2 (#version 300 es)")
        self.assertIn("snoise", js_content, "Должен присутствовать процедурный шум Simplex/Perlin")
        self.assertIn("fbm", js_content, "Должен присутствовать фрактальный броуновский шум (FBM)")
        self.assertIn("u_audio_level", js_content, "Шейдер должен принимать аудио-уровень")
        self.assertIn("window.akakiyCore", js_content, "Должен экспортироваться глобальный bridge API")

        for st in ("idle", "listening", "thinking", "working", "speaking", "success", "error"):
            self.assertIn(f"{st}:", js_content)

    def test_bridge_state_and_audio_clamping(self):
        """Проверка логики состояний и фильтрации аудиоуровня в Python bridge."""
        bridge = AkakiyVisualBridge()
        self.assertEqual(bridge.state, "idle")

        bridge.set_state("thinking")
        self.assertEqual(bridge.state, "thinking")

        # Невалидное состояние не должно устанавливаться
        bridge.set_state("invalid_alien_state")
        self.assertEqual(bridge.state, "thinking")

        # Проверка ограничения громкости (clamping 0.0 .. 1.0)
        bridge.set_audio_level(0.75)
        self.assertAlmostEqual(bridge.audio_level, 0.75)

        bridge.set_audio_level(2.5)
        self.assertEqual(bridge.audio_level, 1.0)

        bridge.set_audio_level(-0.5)
        self.assertEqual(bridge.audio_level, 0.0)

    def test_bridge_http_server_lifecycle(self):
        """Проверка запуска и отдачи статики через локальный HTTP сервер моста."""
        bridge = AkakiyVisualBridge()
        try:
            bridge.start_servers()
            url = f"http://127.0.0.1:{bridge.http_port}/index.html"
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                self.assertEqual(resp.status, 200)
                body = resp.read().decode("utf-8")
                self.assertIn("AKAKIY VISUAL CORE 2.0", body)
        finally:
            bridge.stop()

    def test_edge_binary_discovery(self):
        """Проверка обнаружения Edge / WebView2 в ОС Windows."""
        edge_path = find_edge_binary()
        if os.name == "nt":
            self.assertIsNotNone(edge_path, "На Windows должен быть найден msedge.exe или msedgewebview2.exe")
            self.assertTrue(os.path.exists(edge_path), f"Файл {edge_path} должен существовать на диске")

    def test_typography_system_scale(self):
        """Проверка иерархической шкалы типографики."""
        typo = TypographySystem(use_system_fallbacks=True)

        self.assertIsInstance(typo.FONT_DISPLAY, tuple)
        self.assertIsInstance(typo.FONT_TITLE, tuple)
        self.assertIsInstance(typo.FONT_HEADING, tuple)
        self.assertIsInstance(typo.FONT_BODY, tuple)
        self.assertIsInstance(typo.FONT_CAPTION, tuple)
        self.assertIsInstance(typo.FONT_MONO, tuple)

        # Проверка кеглей
        self.assertGreaterEqual(typo.FONT_DISPLAY[1], 16)
        self.assertGreaterEqual(typo.FONT_TITLE[1], 12)
        self.assertGreaterEqual(typo.FONT_HEADING[1], 10)
        self.assertEqual(typo.FONT_BODY[1], 9)
        self.assertEqual(typo.FONT_CAPTION[1], 8)
        self.assertEqual(typo.FONT_MONO[1], 8)

    def test_home_view_uses_native_akakiy_core(self):
        """Проверка того, что HomeView использует нативный AkakiyCore без Edge/WebView2."""
        import tkinter as tk
        from ui.views.home import HomeView
        from ui.akakiy_core import AkakiyCore

        class MockShell:
            def __init__(self):
                self.current_state = "idle"
                self.neural_core = None
                self.household = None
                self.memory = None
                self.voice = None
                self.agent = None

        root = tk.Tk()
        root.withdraw()
        try:
            shell = MockShell()
            home = HomeView(root, shell=shell)
            home.pack()
            root.update()

            # 1. Проверяем, что ядро — нативный экземпляр AkakiyCore (Canvas)
            self.assertIsInstance(home.neural_core, AkakiyCore)
            self.assertIs(shell.neural_core, home.neural_core)

            # 2. Проверяем реактивное обновление статусов
            home.update_state_display("listening")
            self.assertIn("СЛУШАЕТ", home.lbl_status_badge.cget("text"))

            home.update_state_display("working")
            self.assertIn("ВЫПОЛНЕНИЕ", home.lbl_status_badge.cget("text"))

            home.neural_core.stop()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()

