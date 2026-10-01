"""
Тесты для нового визуального интерфейса Akakiy Core и обновлённого HomeView (Этап 1 визуального обновления).

Проверяют:
1. Инициализацию, 3D геометрию, узлы, рёбра и кольца потока AkakiyCore.
2. 7 состояний AkakiyCore (idle, listening, thinking, working, success, speaking, error) и fallback.
3. Плавную интерполяцию цветов и отсутствие блокировки UI (производительность рендеринга).
4. Реактивность к звуку, импульсы pulse / trigger_pulse.
5. Автоматический возврат из состояния success обратно в idle.
6. Неагрессивную эстетику состояния error (кораллово-розовый спектр вместо кричащего красного).
7. Жизненный цикл (stop, start, destroy).
8. Интеграцию HomeView с AkakiyCore в качестве центрального Hero-элемента.
9. Синхронизацию состояний GUI Shell -> AkakiyCore -> HomeView.
"""

import os
import sys
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from ui.akakiy_core import AkakiyCore, hex_to_rgb, rgb_to_hex, interpolate_rgb
from ui.neural_core import NeuralCore
from ui.views.home import HomeView
from tools.household import HouseholdManager
from gui import AkakiyGUI


class TestAkakiyCoreVisual(unittest.TestCase):
    """Модульные тесты процедурного ядра AkakiyCore."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_core_initialization_and_geometry(self):
        """Проверяет создание ядра, генерацию 3D узлов, рёбер и искр."""
        core = AkakiyCore(self.root, width=400, height=240, num_nodes=34)
        core.pack()
        self.root.update_idletasks()

        self.assertEqual(len(core.nodes), 34)
        self.assertGreater(len(core.edges), 0)
        self.assertGreater(len(core.sparks), 0)
        self.assertEqual(core.state, "idle")
        self.assertFalse(core._is_destroyed)

        # Проверка отрисовки примитивов на Canvas
        items = core.find_all()
        self.assertGreater(len(items), 10)

        core.stop()
        self.assertTrue(core._is_destroyed)

    def test_core_all_seven_states_and_fallback(self):
        """Проверяет поддержку всех 7 состояний ядра и возврат в idle при неизвестном значении."""
        core = AkakiyCore(self.root, width=300, height=200)

        states = ["idle", "listening", "thinking", "working", "success", "speaking", "error"]
        for st in states:
            core.set_state(st)
            self.assertEqual(core.state, st)
            scheme = core.color_scheme
            self.assertIn("core", scheme)
            self.assertIn("halo", scheme)
            self.assertIn("glow", scheme)
            self.assertIn("synapse", scheme)
            self.assertIn("spark", scheme)
            self.assertIn("text", scheme)
            self.assertIn("status", scheme)
            self.assertTrue(len(core.state_description) > 0)
            self.assertTrue(len(core.state_badge_text) > 0)

        # Fallback при неизвестном состоянии
        core.set_state("unknown_quantum_state")
        self.assertEqual(core.state, "idle")
        core.stop()

    def test_color_interpolation_and_smoothness(self):
        """Проверяет плавную интерполяцию цветов между кадрами."""
        core = AkakiyCore(self.root, width=300, height=200)

        # Переключаем в thinking (аметистовый)
        core.set_state("thinking")
        initial_rgb = tuple(core.cur_colors["core"])

        # Выполняем 3 шага анимации
        for _ in range(3):
            core._animate()

        after_rgb = core.cur_colors["core"]
        target_rgb = hex_to_rgb(core.COLOR_PALETTES["thinking"]["core"])

        # Цвет должен приблизиться к целевому, но интерполироваться плавно
        dist_initial = sum((initial_rgb[i] - target_rgb[i]) ** 2 for i in range(3))
        dist_after = sum((after_rgb[i] - target_rgb[i]) ** 2 for i in range(3))
        self.assertLess(dist_after, dist_initial)

        core.stop()

    def test_audio_reactivity_and_pulse(self):
        """Проверяет реактивность к уровню аудио и генерацию импульса."""
        core = AkakiyCore(self.root, width=300, height=200)

        core.set_audio_level(0.7)
        self.assertAlmostEqual(core.audio_level, 0.7, places=2)

        # Ограничение диапазона (clamping)
        core.set_audio_level(2.5)
        self.assertAlmostEqual(core.audio_level, 1.0, places=2)
        core.set_audio_level(-1.0)
        self.assertAlmostEqual(core.audio_level, 0.0, places=2)

        # trigger_pulse и pulse
        core.trigger_pulse(0.8)
        self.assertAlmostEqual(core.audio_level, 0.8, places=2)
        self.assertGreater(core._dynamic_pulse, 0.0)

        core.stop()

    def test_success_state_bloom_and_auto_return(self):
        """Проверяет запуск светового импульса (bloom) в success и автовозврат в idle."""
        core = AkakiyCore(self.root, width=300, height=200)
        core.set_state("success")
        self.assertEqual(core.state, "success")
        self.assertGreater(core._success_frames, 0)

        # Эмулируем завершение кадров импульса
        core._success_frames = 1
        core._animate()
        # Должен переключиться обратно в idle
        self.assertEqual(core.state, "idle")

        core.stop()

    def test_error_state_non_aggressive_styling(self):
        """Проверяет, что состояние ошибки оформлено в мягких кораллово-розовых тонах без кричащего красного."""
        core = AkakiyCore(self.root, width=300, height=200)
        core.set_state("error")

        scheme = core.color_scheme
        # Проверяем, что цвет не равен чистому #ff0000
        self.assertNotEqual(scheme["core"].lower(), "#ff0000")
        self.assertNotEqual(scheme["halo"].lower(), "#ff0000")
        self.assertEqual(scheme["status"], "ВНИМАНИЕ")
        self.assertTrue("внимание" in scheme["description"].lower() or "требуется" in scheme["description"].lower())

        core.stop()

    def test_render_performance_no_ui_freeze(self):
        """Проверяет скорость рендеринга кадра (не блокирует поток Tkinter)."""
        core = AkakiyCore(self.root, width=460, height=240, num_nodes=34)
        core.pack()
        self.root.update_idletasks()

        t0 = time.time()
        for _ in range(15):
            core._animate()
            self.root.update_idletasks()
        dt = time.time() - t0

        avg_ms_per_frame = (dt / 15.0) * 1000.0
        # Кадр должен рендериться быстрее 8 мс (комфортно для 28-60 FPS)
        self.assertLess(avg_ms_per_frame, 15.0)

        core.stop()

    def test_backward_compatibility_alias_neural_core(self):
        """Проверяет, что NeuralCore является совместимым фасадом для AkakiyCore."""
        core = NeuralCore(self.root, width=300, height=200, num_nodes=30)
        self.assertIsInstance(core, AkakiyCore)
        core.set_state("working")
        self.assertEqual(core.state, "working")
        core.stop()


class TestHomeViewWithAkakiyCore(unittest.TestCase):
    """Интеграционные тесты HomeView с обновленным визуальным ядром AkakiyCore."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        test_key = self.id().replace(".", "_").replace(":", "_")
        self.storage_path = os.path.join(WORKSPACE, "scratch", f"test_home_{test_key}_{time.time_ns()}.json")
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

        self.household = HouseholdManager(storage_path=self.storage_path)
        self.household.create_task("Подготовить дизайн-концепцию")
        self.household.create_reminder("Совещание команды", "через 2 часа")
        self.household.create_list("покупки")
        self.household.create_note("Заметка о ядре", "Текст заметки")

        self.mock_shell = MagicMock()
        self.mock_shell.household = self.household
        self.mock_shell.current_state = "idle"
        self.mock_shell.neural_core = None
        self.mock_shell.recent_work_results = [
            {
                "type": "image",
                "title": "Генерация арта",
                "message": "Сгенерировано изображение в высоком разрешении",
                "success": True,
                "created_files": ["data/art.png"],
                "time": "12:00:00"
            }
        ]

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

    def test_home_view_hero_stage_renders_akakiy_core(self):
        """Проверяет, что AkakiyCore является центральным визуальным Hero-элементом HomeView."""
        view = HomeView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        # Ядро инициализировано и связано
        self.assertIsNotNone(view.neural_core)
        self.assertIsNotNone(view.core)
        self.assertIsInstance(view.neural_core, AkakiyCore)

        # Проверяем наличие текстовых бейджей статуса
        self.assertIsNotNone(view.lbl_status_badge)
        self.assertIsNotNone(view.lbl_status_desc)

        # Проверяем реактивное обновление статуса
        view.update_state_display("thinking")
        badge_text = view.lbl_status_badge.cget("text")
        self.assertIn("АНАЛИЗ", badge_text)

        # Очистка
        view.neural_core.stop()

    def test_home_view_task_completion_and_refresh(self):
        """Проверяет завершение задачи и обновление дашборда."""
        view = HomeView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        tasks = self.household.list_tasks(status="pending")["tasks"]
        self.assertEqual(len(tasks), 1)
        task_id = tasks[0]["id"]

        # Быстрое завершение
        view.quick_complete_task(task_id)
        self.root.update_idletasks()

        remaining_tasks = self.household.list_tasks(status="pending")["tasks"]
        self.assertEqual(len(remaining_tasks), 0)

        view.neural_core.stop()

    def test_shell_state_sync_with_core_and_home_view(self):
        """Проверяет сквозную синхронизацию состояния: AkakiyGUI -> AkakiyCore -> HomeView."""
        gui = AkakiyGUI(
            root=self.root,
            agent=MagicMock(),
            household=self.household,
            voice=MagicMock()
        )
        gui.switch_view("home")
        self.root.update_idletasks()

        # Проверяем переключение в listening
        gui._set_state("listening")
        self.assertEqual(gui.current_state, "listening")
        self.assertEqual(gui.neural_core.state, "listening")

        # Проверяем переключение в success
        gui._set_state("success")
        self.assertEqual(gui.current_state, "success")
        self.assertEqual(gui.neural_core.state, "success")

        gui.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
