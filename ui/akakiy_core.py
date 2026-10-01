"""
Модуль визуального ядра Акакия (Akakiy Core) — Visual Direction 2.0.

Реализует живой абстрактный арт-объект:
- Мягкая центральная световая масса (luminous singularity);
- Несколько органических текучих слоёв (digital matter / plasma / fluid);
- Плавные волновые деформации без геометрических сеток и жестких каркасов;
- Тонкие внутренние световые нити и скользящие фотонные импульсы;
- Мягкое диффузное свечение и ощущение глубины;
- В состоянии idle объект медленно «дышит» и слегка меняет форму;
- 7 органических состояний:
    • idle: спокойное медленное дыхание, глубокая лазурно-циановая аура;
    • listening: мягкое раскрытие навстречу голосу, концентрические волны, реакция на audio_level;
    • thinking: циркуляция внутренней энергии, ускоренные потоки, аметистовый спектр;
    • working: направленный поток энергии через объект, изумрудно-мятный импульс;
    • success: короткая красивая гармоническая световая волна (bloom) с возвратом в idle;
    • speaking: мягкая пульсация в ритме речи, бирюзовый спектр;
    • error: органическое фазовое возмущение формы в тёплый кораллово-розовый спектр без резких алертов.
"""

import math
import tkinter as tk
from typing import List, Tuple, Dict, Any, Optional


def hex_to_rgb(hex_str: str) -> Tuple[float, float, float]:
    """Преобразует строку цвета '#RRGGBB' в кортеж чисел (r, g, b)."""
    h = hex_str.lstrip("#")
    if len(h) == 6:
        try:
            return (float(int(h[0:2], 16)), float(int(h[2:4], 16)), float(int(h[4:6], 16)))
        except ValueError:
            pass
    return (56.0, 189.0, 248.0)


def rgb_to_hex(rgb: Tuple[float, float, float]) -> str:
    """Преобразует кортеж чисел (r, g, b) в hex-строку '#RRGGBB'."""
    r = max(0, min(255, int(round(rgb[0]))))
    g = max(0, min(255, int(round(rgb[1]))))
    b = max(0, min(255, int(round(rgb[2]))))
    return f"#{r:02x}{g:02x}{b:02x}"


def interpolate_rgb(
    c1: Tuple[float, float, float],
    c2: Tuple[float, float, float],
    factor: float = 0.12
) -> Tuple[float, float, float]:
    """Плавная линейная интерполяция между двумя RGB-цветами."""
    return (
        c1[0] + (c2[0] - c1[0]) * factor,
        c1[1] + (c2[1] - c1[1]) * factor,
        c1[2] + (c2[2] - c1[2]) * factor,
    )


def fibonacci_sphere(num_points: int = 34, radius: float = 70.0) -> List[Tuple[float, float, float]]:
    """Генератор геометрических узлов для обратной совместимости."""
    points = []
    phi = math.pi * (math.sqrt(5.0) - 1.0)
    for i in range(num_points):
        y = 1.0 - (i / float(max(1, num_points - 1))) * 2.0
        r_at_y = math.sqrt(max(0.0, 1.0 - y * y))
        theta = phi * i
        x = math.cos(theta) * r_at_y
        z = math.sin(theta) * r_at_y
        points.append((x * radius, y * radius, z * radius))
    return points


class AkakiyCore(tk.Canvas):
    """
    Живой органический арт-объект Akakiy Core для Desktop Hub.
    """

    COLOR_PALETTES: Dict[str, Dict[str, Any]] = {
        "idle": {
            "core": "#38bdf8",
            "halo": "#0284c7",
            "glow": "#091726",
            "plasma_outer": "#0d2238",
            "plasma_mid": "#10385c",
            "synapse": "#0369a1",
            "spark": "#bae6fd",
            "text": "#7dd3fc",
            "status": "СИСТЕМА В РАВНОВЕСИИ",
            "badge": "● ГОТОВ",
            "description": "Акакий активен • Органическое ядро в спокойном равновесии",
            "rot_speed": 0.012,
            "pulse_speed": 1.0,
        },
        "listening": {
            "core": "#22d3ee",
            "halo": "#0891b2",
            "glow": "#0b2030",
            "plasma_outer": "#103147",
            "plasma_mid": "#154d6e",
            "synapse": "#0e7490",
            "spark": "#cffafe",
            "text": "#67e8f9",
            "status": "СЛУШАЕТ...",
            "badge": "🎙 СЛУШАЕТ",
            "description": "Мягкое раскрытие навстречу голосу",
            "rot_speed": 0.018,
            "pulse_speed": 1.8,
        },
        "thinking": {
            "core": "#c084fc",
            "halo": "#9333ea",
            "glow": "#1d0e2e",
            "plasma_outer": "#291445",
            "plasma_mid": "#451e73",
            "synapse": "#7e22ce",
            "spark": "#f3e8ff",
            "text": "#d8b4fe",
            "status": "АНАЛИЗ...",
            "badge": "◌ АНАЛИЗ",
            "description": "Циркуляция внутренней энергии и синтез решений",
            "rot_speed": 0.028,
            "pulse_speed": 2.4,
        },
        "working": {
            "core": "#34d399",
            "halo": "#10b981",
            "glow": "#072016",
            "plasma_outer": "#0b3323",
            "plasma_mid": "#135239",
            "synapse": "#059669",
            "spark": "#d1fae5",
            "text": "#6ee7b7",
            "status": "ВЫПОЛНЕНИЕ...",
            "badge": "⚙ РАБОТА",
            "description": "Направленный поток энергии через ядро",
            "rot_speed": 0.024,
            "pulse_speed": 2.0,
        },
        "success": {
            "core": "#38bdf8",
            "halo": "#fbbf24",
            "glow": "#241804",
            "plasma_outer": "#3b2b0a",
            "plasma_mid": "#5e4512",
            "synapse": "#f59e0b",
            "spark": "#fef3c7",
            "text": "#fde68a",
            "status": "УСПЕШНО",
            "badge": "✦ УСПЕШНО",
            "description": "Гармоническая световая волна завершения",
            "rot_speed": 0.018,
            "pulse_speed": 1.6,
        },
        "speaking": {
            "core": "#2dd4bf",
            "halo": "#14b8a6",
            "glow": "#091e1c",
            "plasma_outer": "#0f3632",
            "plasma_mid": "#175750",
            "synapse": "#0d9488",
            "spark": "#ccfbf1",
            "text": "#5eead4",
            "status": "ОТВЕТ...",
            "badge": "🔊 ОТВЕТ",
            "description": "Пульсация в ритме речи",
            "rot_speed": 0.020,
            "pulse_speed": 1.8,
        },
        "error": {
            "core": "#fb7185",
            "halo": "#e11d48",
            "glow": "#260a12",
            "plasma_outer": "#3d131f",
            "plasma_mid": "#5c1e30",
            "synapse": "#be123c",
            "spark": "#ffe4e6",
            "text": "#fca5a5",
            "status": "ВНИМАНИЕ",
            "badge": "✖ ВНИМАНИЕ",
            "description": "Состояние: внимание • Органическое возмущение формы",
            "rot_speed": 0.022,
            "pulse_speed": 2.6,
        },
    }

    def __init__(
        self,
        parent: tk.Widget,
        size: int = 240,
        bg: str = "#070a0f",
        width: Optional[int] = None,
        height: Optional[int] = None,
        num_nodes: int = 34,
        show_status_text: bool = False,
        **kwargs
    ):
        effective_w = width if width is not None else kwargs.pop("width", size)
        effective_h = height if height is not None else kwargs.pop("height", size)
        size = min(effective_w, effective_h)

        super().__init__(
            parent,
            width=effective_w,
            height=effective_h,
            bg=bg,
            highlightthickness=0,
            **kwargs
        )

        self.size = size
        self.w = float(effective_w)
        self.h = float(effective_h)
        self.cx = self.w / 2.0
        self.cy = self.h / 2.0
        self.state = "idle"
        self.audio_level = 0.0
        self.tick = 0
        self.show_status_text = show_status_text
        self._is_destroyed = False
        self._after_id: Optional[str] = None
        self._success_frames = 0
        self._dynamic_pulse = 0.0

        # Цветовые состояния с плавной интерполяцией
        init_palette = self.COLOR_PALETTES["idle"]
        self.cur_colors = {
            k: hex_to_rgb(init_palette[k])
            for k in ("core", "halo", "glow", "plasma_outer", "plasma_mid", "synapse", "spark", "text")
        }
        self.cur_rot_speed = float(init_palette["rot_speed"])
        self.cur_pulse_speed = float(init_palette["pulse_speed"])

        # Базовая геометрия для обратной совместимости
        self.sphere_radius = size * 0.35
        self.nodes = fibonacci_sphere(num_points=num_nodes, radius=self.sphere_radius)
        self.edges = [(i, (i + 1) % len(self.nodes)) for i in range(len(self.nodes))]
        self.sparks = [{"edge_idx": i, "progress": i / 8.0, "speed": 0.02} for i in range(8)]

        # Внутренние световые нити (плазменные струи)
        self.filaments = []
        for i in range(5):
            self.filaments.append({
                "phase": i * (math.pi / 2.5),
                "speed": 0.016 + i * 0.005,
                "span": (self.size * 0.28) + i * 6.0,
                "y_bias": (i - 2) * 8.0
            })

        # Запуск анимационного цикла
        self._animate()

    # -------------------------------------------------------------------------
    # Публичный API компонента
    # -------------------------------------------------------------------------

    @property
    def color_scheme(self) -> Dict[str, Any]:
        """Возвращает текущую цветовую палитру ядра."""
        return self.COLOR_PALETTES.get(self.state, self.COLOR_PALETTES["idle"])

    @property
    def state_description(self) -> str:
        """Понятное описание текущего состояния ядра для интерфейса."""
        palette = self.COLOR_PALETTES.get(self.state, self.COLOR_PALETTES["idle"])
        return palette.get("description", "")

    @property
    def state_badge_text(self) -> str:
        """Текст компактного бейджа текущего состояния."""
        palette = self.COLOR_PALETTES.get(self.state, self.COLOR_PALETTES["idle"])
        return palette.get("badge", f"● {self.state.upper()}")

    def set_state(self, state: str) -> None:
        """Устанавливает визуальное состояние ядра."""
        if state in self.COLOR_PALETTES:
            self.state = state
            if state == "success":
                self._success_frames = 54  # ~1.9 сек на световой импульс
        else:
            self.state = "idle"

    def set_audio_level(self, level: float) -> None:
        """Устанавливает уровень звука / реактивности (0.0 - 1.0)."""
        self.audio_level = max(0.0, min(1.0, float(level)))

    def pulse(self, intensity: float = 0.6) -> None:
        """Эмулирует мгновенный энергетический импульс."""
        self.set_audio_level(intensity)
        self._dynamic_pulse = max(self._dynamic_pulse, float(intensity) * 8.0)

    def trigger_pulse(self, intensity: float = 0.6) -> None:
        """Создает динамический световой импульс."""
        self.pulse(intensity)

    def stop(self) -> None:
        """Останавливает цикл анимации и отменяет запланированные вызовы."""
        self._is_destroyed = True
        if getattr(self, "_after_id", None):
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def start(self) -> None:
        """Перезапускает цикл анимации."""
        if self._is_destroyed:
            self._is_destroyed = False
            self._animate()

    def destroy(self) -> None:
        """Корректное освобождение ресурсов Canvas."""
        self.stop()
        super().destroy()

    # -------------------------------------------------------------------------
    # Процедурный рендеринг органического ядра (Fluid Canvas Loop)
    # -------------------------------------------------------------------------

    def _animate(self) -> None:
        if self._is_destroyed:
            return

        self.tick += 1
        self.delete("all")

        # 1. Плавная интерполяция цветов и динамики
        target_palette = self.COLOR_PALETTES.get(self.state, self.COLOR_PALETTES["idle"])
        factor = 0.12
        for k in self.cur_colors:
            if k in target_palette:
                target_rgb = hex_to_rgb(target_palette[k])
                self.cur_colors[k] = interpolate_rgb(self.cur_colors[k], target_rgb, factor)

        c_core = rgb_to_hex(self.cur_colors["core"])
        c_halo = rgb_to_hex(self.cur_colors["halo"])
        c_glow = rgb_to_hex(self.cur_colors["glow"])
        c_plasma_out = rgb_to_hex(self.cur_colors["plasma_outer"])
        c_plasma_mid = rgb_to_hex(self.cur_colors["plasma_mid"])
        c_synapse = rgb_to_hex(self.cur_colors["synapse"])
        c_spark = rgb_to_hex(self.cur_colors["spark"])
        c_text = rgb_to_hex(self.cur_colors["text"])

        self.cur_rot_speed += (target_palette["rot_speed"] - self.cur_rot_speed) * factor
        self.cur_pulse_speed += (target_palette["pulse_speed"] - self.cur_pulse_speed) * factor

        # Автоматический возврат из состояния success обратно в idle
        if self.state == "success":
            if self._success_frames > 0:
                self._success_frames -= 1
            if self._success_frames <= 0:
                self.set_state("idle")

        # Затухание динамического импульса
        if self._dynamic_pulse > 0.05:
            self._dynamic_pulse *= 0.88
        else:
            self._dynamic_pulse = 0.0

        # Временная шкала органического дыхания
        t = self.tick * 0.03
        pulse = (
            math.sin(t * self.cur_pulse_speed * 0.6) * 3.8
            + math.sin(t * self.cur_pulse_speed * 1.3) * 1.6
            + self._dynamic_pulse
        )

        if self.state in ("listening", "speaking"):
            pulse += self.audio_level * 16.0

        # =====================================================================
        # СЛОЙ 1: Глубокое диффузное свечение фона (Ambient Light Pools)
        # =====================================================================
        for r_ratio, col in [(0.46, c_glow), (0.34, c_plasma_out), (0.24, c_plasma_mid)]:
            rad_x = (self.w * r_ratio) * (1.0 + 0.03 * math.sin(t * 0.5))
            rad_y = (self.h * r_ratio) * (1.0 + 0.03 * math.cos(t * 0.7))
            self.create_oval(
                self.cx - rad_x, self.cy - rad_y,
                self.cx + rad_x, self.cy + rad_y,
                fill=col, outline=""
            )

        # Концентрические мягкие волны прослушивания (Listening Wave Ripples)
        if self.state == "listening" and self.audio_level > 0.04:
            for w_idx in range(2):
                wave_t = (self.tick + w_idx * 16) % 32
                wave_r = (self.size * 0.22) + wave_t * (self.size * 0.007) * (1.0 + self.audio_level * 1.5)
                self.create_oval(
                    self.cx - wave_r * 1.25, self.cy - wave_r * 0.9,
                    self.cx + wave_r * 1.25, self.cy + wave_r * 0.9,
                    fill="", outline=c_core, width=1
                )

        # Световой импульс успеха (Success Bloom)
        if self.state == "success":
            bloom_ratio = (54 - self._success_frames) / 54.0
            bloom_rx = (self.size * 0.16) + bloom_ratio * (self.size * 0.38)
            bloom_ry = (self.size * 0.12) + bloom_ratio * (self.size * 0.28)
            self.create_oval(
                self.cx - bloom_rx, self.cy - bloom_ry,
                self.cx + bloom_rx, self.cy + bloom_ry,
                fill="", outline=c_halo, width=2
            )

        # =====================================================================
        # СЛОЙ 2: Внешняя органическая мембрана (Outer Fluid Layer)
        # =====================================================================
        num_pts = 24
        outer_pts: List[float] = []
        base_outer_r = (self.size * 0.34) + pulse * 1.1

        # Фазовое возмущение для состояния error
        error_jitter = 0.08 * math.sin(t * 4.0) if self.state == "error" else 0.0

        for i in range(num_pts):
            theta = (i / float(num_pts)) * 2.0 * math.pi
            w1 = 0.07 * math.sin(2.0 * theta + t * 0.7)
            w2 = 0.04 * math.cos(3.0 * theta - t * 0.5)
            w3 = 0.02 * math.sin(5.0 * theta + t * 1.1)
            r = base_outer_r * (1.0 + w1 + w2 + w3 + error_jitter)
            px = self.cx + r * math.cos(theta) * 1.24
            py = self.cy + r * math.sin(theta) * 0.88
            outer_pts.extend([px, py])

        self.create_polygon(
            outer_pts,
            fill=c_plasma_out,
            outline=c_plasma_mid,
            width=1,
            smooth=True,
            splinesteps=18
        )

        # =====================================================================
        # СЛОЙ 3: Промежуточная плазменная масса (Mid Plasma Layer)
        # =====================================================================
        mid_pts: List[float] = []
        base_mid_r = (self.size * 0.24) + pulse * 0.9

        for i in range(num_pts):
            theta = (i / float(num_pts)) * 2.0 * math.pi
            w1 = 0.08 * math.cos(2.0 * theta - t * 0.6 + 1.2)
            w2 = 0.05 * math.sin(3.0 * theta + t * 0.8 + 0.6)
            r = base_mid_r * (1.0 + w1 + w2)
            px = self.cx + r * math.cos(theta) * 1.22
            py = self.cy + r * math.sin(theta) * 0.90
            mid_pts.extend([px, py])

        self.create_polygon(
            mid_pts,
            fill=c_plasma_mid,
            outline=c_halo,
            width=1,
            smooth=True,
            splinesteps=18
        )

        # =====================================================================
        # СЛОЙ 4: Внутреннее светящееся тело (Inner Vibrant Fluid Mass)
        # =====================================================================
        inner_pts: List[float] = []
        base_inner_r = (self.size * 0.16) + pulse * 0.7

        for i in range(num_pts):
            theta = (i / float(num_pts)) * 2.0 * math.pi
            w1 = 0.09 * math.sin(3.0 * theta + t * 1.1)
            w2 = 0.04 * math.cos(4.0 * theta - t * 1.3)
            r = base_inner_r * (1.0 + w1 + w2)
            px = self.cx + r * math.cos(theta) * 1.20
            py = self.cy + r * math.sin(theta) * 0.92
            inner_pts.extend([px, py])

        self.create_polygon(
            inner_pts,
            fill=c_halo,
            outline=c_core,
            width=1,
            smooth=True,
            splinesteps=18
        )

        # =====================================================================
        # СЛОЙ 5: Внутренние световые нити и скользящие фотоны (Filaments)
        # =====================================================================
        speed_multiplier = 2.2 if self.state == "thinking" else (1.6 if self.state == "working" else 1.0)
        direction_shift = (t * 12.0) if self.state == "working" else 0.0

        for fil in self.filaments:
            p = fil["phase"] + t * fil["speed"] * speed_multiplier * 8.0
            span = fil["span"]
            y_b = fil["y_bias"] + math.sin(p * 0.7) * 5.0

            # 5-точечный сплайн органической световой линии
            f_pts: List[float] = []
            for s in range(5):
                u = (s / 4.0) - 0.5  # от -0.5 до +0.5
                fx = self.cx + (u * span * 2.0) + (direction_shift % 30.0 - 15.0)
                fy = self.cy + y_b + math.sin(p + u * 3.4) * 8.0
                f_pts.extend([fx, fy])

            line_w = 2 if self.state == "working" else 1
            self.create_line(
                f_pts,
                fill=c_spark if self.state in ("working", "success") else c_core,
                width=line_w,
                smooth=True,
                splinesteps=14
            )

            # Скользящий световой импульс (photon pulse) вдоль нити
            u_pulse = math.sin(p) * 0.5
            dot_x = self.cx + (u_pulse * span * 1.8)
            dot_y = self.cy + y_b + math.sin(p + u_pulse * 3.4) * 8.0
            dot_r = 2.0 if self.state == "thinking" else 1.6
            self.create_oval(
                dot_x - dot_r, dot_y - dot_r,
                dot_x + dot_r, dot_y + dot_r,
                fill="#ffffff",
                outline=""
            )

        # =====================================================================
        # СЛОЙ 6: Центральная световая сингулярность (Luminous Core Singularity)
        # =====================================================================
        core_r = (self.size * 0.08) + pulse * 0.5
        self.create_oval(
            self.cx - core_r * 1.35, self.cy - core_r * 0.95,
            self.cx + core_r * 1.35, self.cy + core_r * 0.95,
            fill=c_core, outline=""
        )

        hot_r = max(2.0, core_r * 0.55)
        self.create_oval(
            self.cx - hot_r * 1.25, self.cy - hot_r * 0.88,
            self.cx + hot_r * 1.25, self.cy + hot_r * 0.88,
            fill=c_spark, outline=""
        )

        spec_r = max(1.8, hot_r * 0.35)
        self.create_oval(
            self.cx - spec_r, self.cy - spec_r,
            self.cx + spec_r, self.cy + spec_r,
            fill="#ffffff", outline=""
        )

        # =====================================================================
        # СЛОЙ 7: Опциональная встроенная строка статуса (если включена)
        # =====================================================================
        if self.show_status_text:
            badge_text = target_palette.get("badge", f"● {self.state.upper()}")
            self.create_text(
                self.cx, self.size - 12,
                text=badge_text,
                fill=c_text,
                font=("Segoe UI Variable Text Semibold", 9)
            )

        # Следующий кадр через 35 мс (~28 FPS)
        if not self._is_destroyed:
            try:
                self._after_id = self.after(35, self._animate)
            except Exception:
                pass
