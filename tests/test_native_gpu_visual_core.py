"""
Targeted tests for Native GPU Visual Core (WGL + OpenGL + GLSL on Tkinter HWND).
"""

import unittest
import tkinter as tk
import win32gui
from ui.native_visual_core import NativeGPUVisualCore, HAS_MODERNGL


class TestNativeGPUVisualCore(unittest.TestCase):
    """Тестирование нативного аппаратного GPU-ядра на базе ModernGL + Win32 GDI."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_native_gpu_core_creation_and_no_child_windows(self):
        """Проверка инициализации нативного ядра и отсутствия сторонних/браузерных окон."""
        core = NativeGPUVisualCore(self.root, width=520, height=210)
        core.pack()
        self.root.update()

        self.assertEqual(core.winfo_class(), "Canvas")
        self.assertEqual(core.state, "idle")

        # Проверка отсутствия дочерних окон браузера
        children = []
        win32gui.EnumChildWindows(core.winfo_id(), lambda h, extra: children.append(h), None)
        self.assertEqual(len(children), 0, "Нативное ядро не должно содержать дочерних браузерных окон")

        # Проверка GPU контекста
        if HAS_MODERNGL:
            self.assertIsNotNone(core.ctx, "ModernGL контекст должен быть успешно инициализирован")
            self.assertIsNotNone(core.fbo, "GPU Framebuffer должен быть создан")

        core.stop()

    def test_native_gpu_core_state_transitions(self):
        """Проверка переключения состояний в нативном GPU ядре."""
        core = NativeGPUVisualCore(self.root, width=400, height=180)
        core.pack()
        self.root.update()

        for st in ("listening", "thinking", "working", "speaking", "success", "error", "idle"):
            core.set_state(st)
            self.assertEqual(core.state, st)

        core.stop()

    def test_native_gpu_core_audio_level(self):
        """Проверка реакции на уровень аудио."""
        core = NativeGPUVisualCore(self.root)
        core.pack()

        core.set_audio_level(0.65)
        self.assertAlmostEqual(core.target_audio_level, 0.65)

        core.set_audio_level(1.5)
        self.assertEqual(core.target_audio_level, 1.0)

        core.set_audio_level(-0.5)
        self.assertEqual(core.target_audio_level, 0.0)

        core.stop()

    def test_native_gpu_core_resize(self):
        """Проверка обработки изменения размера (resize)."""
        core = NativeGPUVisualCore(self.root, width=300, height=150)
        core.pack()
        self.root.update()

        class MockEvent:
            width = 600
            height = 300

        core._on_configure(MockEvent())
        self.assertEqual(core.w, 600)
        self.assertEqual(core.h, 300)

        if HAS_MODERNGL and core.fbo:
            self.assertEqual(core.fbo.size, (600, 300))

        core.stop()

    def test_native_gpu_core_clean_destroy(self):
        """Проверка освобождения всех аппаратных GPU ресурсов при закрытии."""
        core = NativeGPUVisualCore(self.root)
        core.pack()
        self.root.update()

        core.destroy()

        self.assertFalse(core._is_active)
        self.assertIsNone(core.ctx)
        self.assertIsNone(core.fbo)
        self.assertIsNone(core.tex)
        self.assertEqual(core.hdc, 0)


class TestHomeViewNativeGPUIntegration(unittest.TestCase):
    """
    Интеграционные тесты подключения NativeGPUVisualCore в production HomeView:
    - HomeView содержит NativeGPUVisualCore;
    - Визуал находится внутри HomeView;
    - Отсутствие дочерних browser/WebView HWND;
    - Передача состояний в Native GPU Core;
    - Корректный destroy без сбоев.
    """

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_home_view_contains_native_gpu_visual_core(self):
        """Проверяет, что production HomeView содержит именно NativeGPUVisualCore."""
        from ui.views.home import HomeView
        view = HomeView(self.root)
        view.pack()
        self.root.update()

        self.assertIsNotNone(view.neural_core)
        self.assertIsInstance(view.neural_core, NativeGPUVisualCore)
        self.assertEqual(view.neural_core.winfo_class(), "Canvas")
        self.assertEqual(view.neural_core.state, "idle")

        view.destroy()

    def test_visual_core_inside_home_view_hierarchy(self):
        """Проверяет, что Native GPU Core физически размещен внутри дерева HomeView."""
        from ui.views.home import HomeView
        view = HomeView(self.root)
        view.pack()
        self.root.update()

        core_parent = view.neural_core.master
        self.assertIn(core_parent, view.winfo_children())

        view.destroy()

    def test_no_child_browser_or_webview_hwnd(self):
        """Проверяет полное отсутствие сторонних браузерных процессов и дочерних HWND."""
        from ui.views.home import HomeView
        view = HomeView(self.root)
        view.pack()
        self.root.update()

        core_hwnd = view.neural_core.winfo_id()
        self.assertGreater(core_hwnd, 0)

        child_hwnds = []
        win32gui.EnumChildWindows(core_hwnd, lambda h, extra: child_hwnds.append(h), None)
        self.assertEqual(len(child_hwnds), 0, "Native GPU Core не должен иметь дочерних HWND")

        view.destroy()

    def test_state_transitions_reach_native_gpu_core(self):
        """Проверяет, что смена состояний корректно доходит до Native GPU Core."""
        from ui.views.home import HomeView
        view = HomeView(self.root)
        view.pack()
        self.root.update()

        states = ("listening", "thinking", "working", "speaking", "success", "error", "idle")
        for st in states:
            view.neural_core.set_state(st)
            view.update_state_display(st)
            self.assertEqual(view.neural_core.state, st)

            badge_text = view.lbl_status_badge.cget("text")
            self.assertTrue(len(badge_text) > 0)

        view.destroy()

    def test_audio_level_and_resize_lifecycle(self):
        """Проверяет обработку уровня звука и динамический ресайз в HomeView."""
        from ui.views.home import HomeView
        view = HomeView(self.root)
        view.pack()
        self.root.update()

        view.neural_core.set_audio_level(0.75)
        self.assertAlmostEqual(view.neural_core.target_audio_level, 0.75)

        # Ресайз
        self.root.geometry("1400x900")
        self.root.update()
        self.assertGreater(view.neural_core.w, 0)
        self.assertGreater(view.neural_core.h, 0)

        view.destroy()

    def test_clean_home_view_destroy_without_errors(self):
        """Проверяет чистое закрытие HomeView с освобождением GPU-памяти и контекста."""
        from ui.views.home import HomeView
        view = HomeView(self.root)
        view.pack()
        self.root.update()

        core = view.neural_core
        self.assertTrue(core._is_active)

        # Уничтожаем HomeView
        view.destroy()

        self.assertFalse(core._is_active)
        self.assertIsNone(core.ctx)
        self.assertIsNone(core.fbo)

    def test_home_view_framebuffer_has_nonzero_rendered_pixels(self):
        """Диагностический smoke test: проверяет наличие ненулевых пикселей в FBO и HDC."""
        import ctypes
        import numpy as np
        from ui.views.home import HomeView

        # Отображаем окно для проверки физических пикселей на Windows DC
        self.root.deiconify()
        self.root.update()

        view = HomeView(self.root)
        view.pack()
        self.root.update()

        core = view.neural_core
        self.assertIsNotNone(core.fbo)
        self.assertIsNotNone(core.ctx)

        # Выполняем рендер кадра
        core._render_frame()

        # 1. Чтение FBO
        data = core.fbo.read(components=4)
        self.assertEqual(len(data), core.w * core.h * 4)

        arr = np.frombuffer(data, dtype=np.uint8)
        self.assertGreater(arr.max(), 0, "Буфер кадра не должен быть пустым")
        self.assertEqual(arr.max(), 255, "Центральная сингулярность должна достигать максимальной яркости 255")

        # 2. Проверка блиттинга в Canvas HDC
        center_px = ctypes.windll.gdi32.GetPixel(core.hdc, core.w // 2, core.h // 2)
        self.assertEqual(center_px, 0xffffff, "Центр холста должен содержать яркую точку сингулярности (0xffffff)")

        view.destroy()
        self.root.withdraw()


if __name__ == "__main__":
    unittest.main()

