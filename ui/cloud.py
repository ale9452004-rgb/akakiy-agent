import math
import time
import tkinter as tk


class AkakiyCloud(tk.Canvas):
    """
    Футуристичное анимированное ядро / облако Акакия (Cybernetic AI Core).
    Поддерживает состояния:
    - 'idle': глубокая спокойная голубая пульсация (ядро дышит);
    - 'thinking': ускоренное вращение фиолетового вихря и квантовых связей;
    - 'working': расширяющиеся неоновые изумрудные импульсы;
    - 'waiting': янтарно-золотистое мерцание (ожидание подтверждения);
    - 'error': красная тревожная пульсация;
    - 'listening': колебания волны (архитектурный задел под голос);
    - 'speaking': модуляция амплитуды (архитектурный задел под голос).
    """

    def __init__(self, parent, size=130, width=None, height=None, **kwargs):
        effective_w = width if width is not None else kwargs.pop("width", size)
        effective_h = height if height is not None else kwargs.pop("height", size)
        size = min(effective_w, effective_h)
        super().__init__(
            parent,
            width=effective_w,
            height=effective_h,
            bg="#161b22",
            highlightthickness=0,
            **kwargs
        )
        self.size = size
        self.cx = size / 2
        self.cy = size / 2
        self.state = "idle"
        self.tick = 0
        self.audio_level = 0.0  # 0.0 - 1.0 (задел под голосовой модуль)
        self.particles = []
        for i in range(12):
            self.particles.append({
                "angle": (i / 12) * 2 * math.pi,
                "speed": 0.025 + (i % 3) * 0.012,
                "radius": 28 + (i % 4) * 6
            })
        self._animate()

    def set_state(self, state):
        if state in ("idle", "thinking", "working", "waiting", "error", "listening", "speaking"):
            self.state = state

    def set_audio_level(self, level):
        """Интерфейс для будущего подключения микрофона / голосового вывода."""
        self.audio_level = max(0.0, min(1.0, float(level)))

    def _animate(self):
        self.tick += 1
        self.delete("all")

        t = self.tick * 0.05
        # Органическое двойное дыхание
        pulse = math.sin(t) * 4 + math.sin(t * 2.3) * 1.5

        # Выбор цветовой схемы и параметров динамики
        if self.state == "idle":
            base_r = 32 + pulse
            core_color = "#58a6ff"
            halo_color = "#1f6feb"
            glow_color = "#0d419d"
            sub_text = "АКТИВЕН"
            status_color = "#58a6ff"
            wave_speed = 1.2

        elif self.state == "thinking":
            base_r = 34 + math.sin(t * 2) * 6
            core_color = "#bc8cff"
            halo_color = "#8957e5"
            glow_color = "#5a32a3"
            sub_text = "АНАЛИЗ"
            status_color = "#d2a8ff"
            wave_speed = 2.2

        elif self.state == "working":
            base_r = 36 + math.sin(t * 2.5) * 7
            core_color = "#39d353"
            halo_color = "#2ea043"
            glow_color = "#196c2e"
            sub_text = "РАБОТА"
            status_color = "#56d364"
            wave_speed = 2.5

        elif self.state == "waiting":
            base_r = 34 + math.sin(t * 3) * 8
            core_color = "#e3b341"
            halo_color = "#bb8009"
            glow_color = "#7d4e00"
            sub_text = "ОДОБРЕНИЕ"
            status_color = "#f2cc60"
            wave_speed = 1.8

        elif self.state == "error":
            base_r = 34 + math.sin(t * 4.5) * 8
            core_color = "#ff7b72"
            halo_color = "#da3633"
            glow_color = "#8e1519"
            sub_text = "ОШИБКА"
            status_color = "#ffa198"
            wave_speed = 3.0

        elif self.state == "listening":
            base_r = 32 + self.audio_level * 16 + pulse
            core_color = "#58a6ff"
            halo_color = "#1f6feb"
            glow_color = "#388bfd"
            sub_text = "СЛУШАЕТ"
            status_color = "#79c0ff"
            wave_speed = 1.5

        elif self.state == "speaking":
            base_r = 32 + self.audio_level * 20 + math.sin(t * 3) * 5
            core_color = "#3fb950"
            halo_color = "#238636"
            glow_color = "#2ea043"
            sub_text = "ОТВЕТ"
            status_color = "#7ee787"
            wave_speed = 2.0

        # 1. Угловые технологические маркеры (Cyberpunk HUD Brackets)
        b_color = "#21262d"
        b_len = 6
        pad = 6
        # Top-Left
        self.create_line(pad, pad, pad + b_len, pad, fill=b_color, width=1)
        self.create_line(pad, pad, pad, pad + b_len, fill=b_color, width=1)
        # Top-Right
        self.create_line(self.size - pad, pad, self.size - pad - b_len, pad, fill=b_color, width=1)
        self.create_line(self.size - pad, pad, self.size - pad, pad + b_len, fill=b_color, width=1)
        # Bottom-Left
        self.create_line(pad, self.size - pad, pad + b_len, self.size - pad, fill=b_color, width=1)
        self.create_line(pad, self.size - pad, pad, self.size - pad - b_len, fill=b_color, width=1)
        # Bottom-Right
        self.create_line(self.size - pad, self.size - pad, self.size - pad - b_len, self.size - pad, fill=b_color, width=1)
        self.create_line(self.size - pad, self.size - pad, self.size - pad, self.size - pad - b_len, fill=b_color, width=1)

        # 2. Внешнее свечение (Ambient Aura)
        aura_r = base_r + 14
        self.create_oval(
            self.cx - aura_r, self.cy - aura_r,
            self.cx + aura_r, self.cy + aura_r,
            fill="", outline=glow_color, width=2
        )

        # 3. Расширяющиеся импульсные волновые кольца
        if self.state in ("working", "waiting", "thinking", "error"):
            wave_r = (base_r + (self.tick * wave_speed) % 26)
            self.create_oval(
                self.cx - wave_r, self.cy - wave_r,
                self.cx + wave_r, self.cy + wave_r,
                fill="", outline=halo_color, width=1
            )

        # 4. Средний ореол ядра
        self.create_oval(
            self.cx - base_r, self.cy - base_r,
            self.cx + base_r, self.cy + base_r,
            fill=halo_color, outline=""
        )

        # 5. Внутреннее горячее ядро
        inner_r = base_r * 0.62
        self.create_oval(
            self.cx - inner_r, self.cy - inner_r,
            self.cx + inner_r, self.cy + inner_r,
            fill=core_color, outline=""
        )

        # Центральная световая точка (Glance)
        glance_r = inner_r * 0.35
        self.create_oval(
            self.cx - glance_r, self.cy - glance_r - 2,
            self.cx + glance_r, self.cy + glance_r - 2,
            fill="#ffffff", outline=""
        )

        # 6. Квантовая решётка / орбитальные частицы (Neural Network Lattice)
        coords = []
        for p in self.particles:
            p["angle"] += p["speed"]
            px = self.cx + math.cos(p["angle"]) * (p["radius"] + pulse * 0.35)
            py = self.cy + math.sin(p["angle"]) * (p["radius"] + pulse * 0.35)
            coords.append((px, py))

        # Соединительные линии между близкими частицами
        num_particles = len(coords)
        for i in range(num_particles):
            for j in range(i + 1, num_particles):
                dx = coords[i][0] - coords[j][0]
                dy = coords[i][1] - coords[j][1]
                dist_sq = dx * dx + dy * dy
                if dist_sq < 34 * 34:  # расстояние меньше 34px
                    self.create_line(
                        coords[i][0], coords[i][1],
                        coords[j][0], coords[j][1],
                        fill=glow_color, width=1
                    )

        # Отрисовка самих орбитальных точек
        for px, py in coords:
            self.create_oval(px - 2, py - 2, px + 2, py + 2, fill=core_color, outline="")

        # 7. Текстовая подпись состояния ядра
        self.create_text(
            self.cx, self.size - 14,
            text=f"● {sub_text}",
            fill=status_color,
            font=("Consolas", 8, "bold")
        )

        self.after(33, self._animate)
