"""
Переиспользуемый компонент Neural Core (Нейронное ядро Акакия) на базе Tkinter Canvas.

Реализует чистую процедурную 3D-проекцию вращающейся сферы нейросети:
- Распределение узлов по сфере (алгоритм Фибоначчи);
- 3D-вращение вокруг осей X и Y с перспективной проекцией глубины Z;
- Синаптические связи между соседними узлами с глубинной градацией яркости;
- Бегущие потенциалы действия (световые искры);
- Внутреннее светящееся энергетическое ядро;
- Реактивность к уровню аудио (микрофон/речь);
- 6 состояний: idle, thinking, working, listening, speaking, error.
"""

import math
import tkinter as tk
from typing import List, Tuple, Dict, Any


def fibonacci_sphere(num_points: int = 40, radius: float = 65.0) -> List[Tuple[float, float, float]]:
    """Генерирует равномерно распределённые точки на сфере радиуса radius."""
    points = []
    phi = math.pi * (math.sqrt(5.0) - 1.0)  # Золотой угол в радианах

    for i in range(num_points):
        y = 1.0 - (i / float(num_points - 1)) * 2.0  # от 1 до -1
        r_at_y = math.sqrt(max(0.0, 1.0 - y * y))
        theta = phi * i

        x = math.cos(theta) * r_at_y
        z = math.sin(theta) * r_at_y

        points.append((x * radius, y * radius, z * radius))

    return points


class NeuralCore(tk.Canvas):
    """
    Интерактивный графический компонент 3D нейронной сферы Акакия.
    """

    COLOR_PALETTES = {
        "idle": {
            "core": "#58a6ff",
            "halo": "#1f6feb",
            "glow": "#0d419d",
            "synapse": "#388bfd",
            "spark": "#ffffff",
            "text": "#79c0ff",
            "status": "АКТИВЕН",
            "rot_speed": 0.015,
            "pulse_speed": 1.5,
        },
        "thinking": {
            "core": "#d2a8ff",
            "halo": "#bc8cff",
            "glow": "#5a32a3",
            "synapse": "#a371f7",
            "spark": "#f0e6ff",
            "text": "#d2a8ff",
            "status": "АНАЛИЗ",
            "rot_speed": 0.045,
            "pulse_speed": 3.2,
        },
        "working": {
            "core": "#39d353",
            "halo": "#2ea043",
            "glow": "#196c2e",
            "synapse": "#238636",
            "spark": "#aff5b4",
            "text": "#56d364",
            "status": "РАБОТА",
            "rot_speed": 0.035,
            "pulse_speed": 2.8,
        },
        "listening": {
            "core": "#79c0ff",
            "halo": "#388bfd",
            "glow": "#1f6feb",
            "synapse": "#58a6ff",
            "spark": "#ffffff",
            "text": "#79c0ff",
            "status": "СЛУШАЕТ",
            "rot_speed": 0.020,
            "pulse_speed": 2.0,
        },
        "speaking": {
            "core": "#56d364",
            "halo": "#3fb950",
            "glow": "#238636",
            "synapse": "#2ea043",
            "spark": "#e6ffed",
            "text": "#7ee787",
            "status": "ОТВЕТ",
            "rot_speed": 0.028,
            "pulse_speed": 2.4,
        },
        "error": {
            "core": "#ff7b72",
            "halo": "#da3633",
            "glow": "#8e1519",
            "synapse": "#f85149",
            "spark": "#ffdcd7",
            "text": "#ffa198",
            "status": "ОШИБКА",
            "rot_speed": 0.030,
            "pulse_speed": 4.5,
        },
    }

    def __init__(self, parent, size: int = 180, bg: str = "#161b22", width: int = None, height: int = None, num_nodes: int = 36, **kwargs):
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
        self.cx = effective_w / 2.0
        self.cy = effective_h / 2.0
        self.state = "idle"
        self.audio_level = 0.0
        self.tick = 0
        self._is_destroyed = False

        # Геометрия 3D сферы
        sphere_radius = (size * 0.36)
        self.nodes = fibonacci_sphere(num_points=num_nodes, radius=sphere_radius)

        # Вычисляем синаптические рёбра (пары узлов на расстоянии взаимодействия)
        self.edges = []
        max_dist_sq = (sphere_radius * 0.72) ** 2
        for i in range(len(self.nodes)):
            for j in range(i + 1, len(self.nodes)):
                p1 = self.nodes[i]
                p2 = self.nodes[j]
                d2 = (p1[0]-p2[0])**2 + (p1[1]-p2[1])**2 + (p1[2]-p2[2])**2
                if d2 < max_dist_sq:
                    self.edges.append((i, j))

        # Световые импульсы (action potentials)
        self.sparks = []
        for i in range(7):
            edge_idx = (i * 5) % max(1, len(self.edges))
            self.sparks.append({
                "edge_idx": edge_idx,
                "progress": (i / 7.0),
                "speed": 0.025 + (i % 3) * 0.015
            })

        self.angle_y = 0.0
        self.angle_x = 0.25

        self._animate()

    @property
    def color_scheme(self) -> dict:
        """Возвращает текущую активную палитру стилей ядра."""
        return self.COLOR_PALETTES.get(self.state, self.COLOR_PALETTES["idle"])

    def set_state(self, state: str):
        """Устанавливает визуальное состояние ядра."""
        if state in self.COLOR_PALETTES:
            self.state = state
        else:
            self.state = "idle"

    def set_audio_level(self, level: float):
        """Устанавливает уровень звука для реактивности (0.0 - 1.0)."""
        self.audio_level = max(0.0, min(1.0, float(level)))

    def pulse(self, intensity: float = 0.5):
        """Эмулирует одиночный звуковой импульс."""
        self.set_audio_level(intensity)

    def stop(self):
        """Останавливает цикл анимации."""
        self._is_destroyed = True

    def start(self):
        """Перезапускает цикл анимации."""
        if self._is_destroyed:
            self._is_destroyed = False
            self._animate()

    def destroy(self):
        self.stop()
        super().destroy()

    def _animate(self):
        if self._is_destroyed:
            return

        self.tick += 1
        self.delete("all")

        palette = self.COLOR_PALETTES.get(self.state, self.COLOR_PALETTES["idle"])

        # Обновление углов вращения
        rot_spd = palette["rot_speed"]
        self.angle_y += rot_spd
        self.angle_x += rot_spd * 0.35

        sin_y, cos_y = math.sin(self.angle_y), math.cos(self.angle_y)
        sin_x, cos_x = math.sin(self.angle_x), math.cos(self.angle_x)

        # Пульсация
        t = self.tick * 0.05
        pulse = math.sin(t * palette["pulse_speed"]) * 3.0
        if self.state in ("listening", "speaking"):
            pulse += self.audio_level * 10.0

        # Перспективная проекция 3D точек
        view_dist = 220.0
        projected: List[Tuple[float, float, float, float]] = []

        for x, y, z in self.nodes:
            # Масштабирование пульсацией
            rad_mult = 1.0 + (pulse * 0.005)
            x_m, y_m, z_m = x * rad_mult, y * rad_mult, z * rad_mult

            # Вращение вокруг оси Y
            x1 = x_m * cos_y + z_m * sin_y
            z1 = -x_m * sin_y + z_m * cos_y

            # Вращение вокруг оси X
            y2 = y_m * cos_x - z1 * sin_x
            z2 = y_m * sin_x + z1 * cos_x

            # Проекция на 2D экран
            scale = view_dist / (view_dist + z2 + 80.0)
            px = self.cx + x1 * scale
            py = self.cy + y2 * scale
            depth_factor = (z2 + 100.0) / 200.0  # 0.0 (сзади) .. 1.0 (впереди)

            projected.append((px, py, z2, depth_factor))

        # 1. Фоновое мягкое свечение ядра (Ambient Glow)
        glow_r = (self.size * 0.28) + pulse * 1.5
        self.create_oval(
            self.cx - glow_r, self.cy - glow_r,
            self.cx + glow_r, self.cy + glow_r,
            fill="", outline=palette["glow"], width=2
        )

        # 2. Отрисовка синаптических рёбер
        for idx1, idx2 in self.edges:
            p1 = projected[idx1]
            p2 = projected[idx2]

            # Средняя глубина ребра для определения яркости
            avg_depth = (p1[3] + p2[3]) * 0.5
            if avg_depth < 0.25:
                line_color = palette["glow"]
                line_w = 1
            elif avg_depth < 0.65:
                line_color = palette["synapse"]
                line_w = 1
            else:
                line_color = palette["halo"]
                line_w = 1

            self.create_line(p1[0], p1[1], p2[0], p2[1], fill=line_color, width=line_w)

        # 3. Бегущие потенциалы действия (искры)
        for s in self.sparks:
            s["progress"] = (s["progress"] + s["speed"]) % 1.0
            if s["edge_idx"] < len(self.edges):
                i1, i2 = self.edges[s["edge_idx"]]
                p1, p2 = projected[i1], projected[i2]
                prog = s["progress"]
                sx = p1[0] + (p2[0] - p1[0]) * prog
                sy = p1[1] + (p2[1] - p1[1]) * prog
                s_r = 1.5
                self.create_oval(
                    sx - s_r, sy - s_r, sx + s_r, sy + s_r,
                    fill=palette["spark"], outline=""
                )

        # 4. Центральное энергетическое ядро (Inner Core)
        core_r = (self.size * 0.14) + pulse * 0.8
        self.create_oval(
            self.cx - core_r, self.cy - core_r,
            self.cx + core_r, self.cy + core_r,
            fill=palette["halo"], outline=""
        )
        hot_r = core_r * 0.58
        self.create_oval(
            self.cx - hot_r, self.cy - hot_r,
            self.cx + hot_r, self.cy + hot_r,
            fill=palette["core"], outline=""
        )

        # 5. Отрисовка узлов нейросети (сортировка по Z для корректного перекрытия)
        sorted_nodes = sorted(enumerate(projected), key=lambda item: item[1][2])

        for orig_idx, (px, py, z2, depth) in sorted_nodes:
            # Радиус узла зависит от глубины
            node_r = 2.0 + depth * 2.4
            if depth > 0.6:
                node_fill = palette["core"]
                node_outline = palette["spark"]
            elif depth > 0.3:
                node_fill = palette["halo"]
                node_outline = ""
            else:
                node_fill = palette["glow"]
                node_outline = ""

            self.create_oval(
                px - node_r, py - node_r,
                px + node_r, py + node_r,
                fill=node_fill, outline=node_outline
            )

        # 6. Статусная строка состояния под сферой
        self.create_text(
            self.cx, self.size - 12,
            text=f"● {palette['status']}",
            fill=palette["text"],
            font=("Consolas", 8, "bold")
        )

        self.after(33, self._animate)
