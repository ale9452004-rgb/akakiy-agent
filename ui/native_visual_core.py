"""
Native GPU Visual Core (WGL + OpenGL 3.3+ + GLSL) for Akakiy.

Renders living organic plasma art directly into a native Windows Tkinter HWND
using the NVIDIA GPU (via ModernGL C-bindings and GDI DIBSection blitting)
without HTML, WebView2, Edge, or external child windows.
"""

import time
import math
import ctypes
import numpy as np
import tkinter as tk
from typing import Optional, Tuple, Dict, Any

from ui.akakiy_core import AkakiyCore

try:
    import moderngl
    HAS_MODERNGL = True
except ImportError:
    HAS_MODERNGL = False


# Win32 GDI DIB Header for Direct Blitting
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32)
    ]


VS_SOURCE = """
#version 330
in vec2 in_pos;
void main() {
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

FS_SOURCE = """
#version 330
out vec4 fragColor;

uniform vec2 u_resolution;
uniform float u_time;
uniform float u_audio_level;

uniform vec3 u_color_bg;
uniform vec3 u_color_nucleus;
uniform vec3 u_color_plasma;
uniform vec3 u_color_corona;

uniform float u_speed;
uniform float u_turbulence;
uniform float u_dissonance;
uniform float u_bloom_wave;

// Simplex 3D Noise (Ashima / Inigo Quilez)
vec4 permute(vec4 x) { return mod(((x * 34.0) + 1.0) * x, 289.0); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

float snoise(vec3 v) {
    const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);

    vec3 i  = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);

    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);

    vec3 x1 = x0 - i1 + 1.0 * C.xxx;
    vec3 x2 = x0 - i2 + 2.0 * C.xxx;
    vec3 x3 = x0 - 1.0 + 3.0 * C.xxx;

    i = mod(i, 289.0);
    vec4 p = permute(permute(permute(
                i.z + vec4(0.0, i1.z, i2.z, 1.0))
            + i.y + vec4(0.0, i1.y, i2.y, 1.0))
            + i.x + vec4(0.0, i1.x, i2.x, 1.0));

    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;

    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);

    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);

    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);

    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);

    vec4 s0 = floor(b0) * 2.0 + 1.0;
    vec4 s1 = floor(b1) * 2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));

    vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;

    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);

    vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
    p0 *= norm.x;
    p1 *= norm.y;
    p2 *= norm.z;
    p3 *= norm.w;

    vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}

float fbm(vec3 p) {
    float total = 0.0;
    float amp = 0.55;
    float freq = 1.0;
    for (int i = 0; i < 3; i++) {
        total += amp * snoise(p * freq);
        freq *= 2.15;
        amp *= 0.45;
    }
    return total;
}

void main() {
    vec2 uv = (gl_FragCoord.xy - 0.5 * u_resolution) / min(u_resolution.x, u_resolution.y);
    float r = length(uv);
    float theta = atan(uv.y, uv.x);

    // 1. Потоковая циркуляция и вихревое движение
    float swirl = 1.35 * sin(r * 4.2 - u_time * u_speed * 1.6);
    float cos_s = cos(swirl);
    float sin_s = sin(swirl);
    vec2 rot_uv = vec2(
        uv.x * cos_s - uv.y * sin_s,
        uv.x * sin_s + uv.y * cos_s
    );

    // Фазовый диссонанс при ошибке
    float diss = u_dissonance * sin(theta * 6.0 + u_time * 8.0) * 0.09;

    // 2. Двойной Domain Warping
    vec3 p1 = vec3(rot_uv * 2.8, u_time * u_speed * 0.45);
    float n1 = fbm(p1);

    vec3 p2 = vec3(rot_uv * 3.4 + vec2(n1 * 0.65), u_time * u_speed * 0.7);
    float n2 = fbm(p2);

    float warp_r = r + (n1 * 0.16 + n2 * 0.1) * u_turbulence + diss;

    // 3. Органическое дыхание и реакция на звук
    float breath = sin(u_time * u_speed * 1.8) * 0.025 + u_audio_level * 0.16;
    float plasma_radius = 0.34 + breath;

    // СЛОЙ 1: Центральная светящаяся сингулярность (Nucleus)
    float nucleus_r = length(uv + vec2(n1 * 0.04));
    float nucleus_glow = exp(-nucleus_r * nucleus_r * 42.0) * 1.8;
    vec3 nucleus_col = mix(u_color_nucleus, vec3(1.0, 1.0, 1.0), smoothstep(0.12, 0.02, nucleus_r));

    // СЛОЙ 2: Текучее плазменное тело (Volumetric Plasma Body)
    float plasma_density = smoothstep(plasma_radius + 0.12, plasma_radius - 0.16, warp_r);
    float plasma_ribbons = 0.5 + 0.5 * sin(n2 * 9.0 + u_time * u_speed * 2.4);
    vec3 plasma_col = u_color_plasma * plasma_density * (0.6 + 0.5 * plasma_ribbons);

    // СЛОЙ 3: Диффузная эфирная корона (Ambient Bloom)
    float corona_decay = 0.18 / (r + 0.15);
    float corona_glow = corona_decay * exp(-r * 2.4);
    vec3 corona_col = u_color_corona * corona_glow;

    // СЛОЙ 4: Квантовые фотонные искры (Quantum Sparks)
    vec3 spark_p = vec3(rot_uv * 14.0, u_time * 0.6);
    float sparks = pow(max(0.0, snoise(spark_p)), 12.0) * 12.0 * smoothstep(0.48, 0.08, r);

    // СЛОЙ 5: Световая гармоническая волна (Bloom Wave)
    float wave_dist = abs(r - u_bloom_wave);
    float wave_pulse = exp(-wave_dist * wave_dist * 80.0) * smoothstep(0.0, 0.15, u_bloom_wave);
    vec3 wave_col = u_color_nucleus * wave_pulse * 1.6;

    // Итоговое аддитивное оптическое сложение
    vec3 final_rgb = nucleus_col * nucleus_glow
                   + plasma_col
                   + corona_col
                   + u_color_nucleus * sparks
                   + wave_col;

    // Мягкое виньетирование по краям кадра
    float vignette = smoothstep(1.2, 0.4, r);
    final_rgb *= vignette;

    // Плавное бесшовное смешивание с фоном карточки Hero
    vec3 result_rgb = u_color_bg + final_rgb;

    // Вывод в формате Windows GDI BGRA
    fragColor = vec4(result_rgb.b, result_rgb.g, result_rgb.r, 1.0);
}
"""


STATE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "idle": {
        "status": "СИСТЕМА В РАВНОВЕСИИ",
        "badge": "● ГОТОВ",
        "text": "#38bdf8",
        "description": "Акакий активен • Квантовая плазма в спокойном равновесии",
        "nucleus": (0.22, 0.85, 1.0),     # Электрик-циан
        "plasma":  (0.08, 0.45, 0.85),    # Глубокий лазурный
        "corona":  (0.02, 0.25, 0.60),    # Эфирный синий
        "speed": 0.65,
        "turbulence": 0.75,
        "dissonance": 0.0,
    },
    "listening": {
        "status": "СЛУШАЕТ...",
        "badge": "🎙 СЛУШАЕТ",
        "text": "#00f3ff",
        "description": "Мягкое раскрытие навстречу входящему голосу",
        "nucleus": (0.45, 0.98, 1.0),     # Аквамарин
        "plasma":  (0.12, 0.68, 0.82),    # Бирюза
        "corona":  (0.04, 0.38, 0.55),    # Мягкий циан
        "speed": 0.95,
        "turbulence": 1.1,
        "dissonance": 0.0,
    },
    "thinking": {
        "status": "АНАЛИЗ...",
        "badge": "◌ АНАЛИЗ",
        "text": "#c084fc",
        "description": "Циркуляция внутренней энергии и синтез плана решений",
        "nucleus": (0.85, 0.60, 1.0),     # Розово-лавандовый
        "plasma":  (0.55, 0.22, 0.92),    # Ультрафиолет
        "corona":  (0.32, 0.08, 0.62),    # Глубокий индиго
        "speed": 1.75,
        "turbulence": 1.6,
        "dissonance": 0.0,
    },
    "working": {
        "status": "ВЫПОЛНЕНИЕ...",
        "badge": "⚙ ДЕЙСТВИЕ",
        "text": "#34d399",
        "description": "Исполнение инструментов и системных вызовов",
        "nucleus": (0.35, 1.0, 0.82),     # Неоновый мятный
        "plasma":  (0.06, 0.75, 0.52),    # Изумрудный
        "corona":  (0.02, 0.42, 0.32),    # Малахит
        "speed": 1.5,
        "turbulence": 1.35,
        "dissonance": 0.0,
    },
    "speaking": {
        "status": "ОТВЕЧАЕТ...",
        "badge": "🔊 ОТВЕТ",
        "text": "#2dd4bf",
        "description": "Синтез и воспроизведение голосового ответа",
        "nucleus": (0.32, 0.95, 0.88),    # Морской бриз
        "plasma":  (0.10, 0.65, 0.62),    # Мягкий тил
        "corona":  (0.04, 0.35, 0.38),    # Диффузная бирюза
        "speed": 1.1,
        "turbulence": 0.95,
        "dissonance": 0.0,
    },
    "success": {
        "status": "УСПЕШНО",
        "badge": "✦ УСПЕШНО",
        "text": "#fbbf24",
        "description": "Гармонический волновой всплеск энергии",
        "nucleus": (1.0, 0.92, 0.55),     # Тёплое золото
        "plasma":  (0.95, 0.68, 0.15),    # Янтарный расцвет
        "corona":  (0.45, 0.55, 0.18),    # Золотисто-зелёный
        "speed": 1.1,
        "turbulence": 0.85,
        "dissonance": 0.0,
    },
    "error": {
        "status": "ВНИМАНИЕ",
        "badge": "✖ СБОЙ",
        "text": "#f87171",
        "description": "Органическое фазовое возмущение и затухание гармоник",
        "nucleus": (1.0, 0.55, 0.65),     # Тёплый коралл
        "plasma":  (0.85, 0.25, 0.40),    # Розовый кварц
        "corona":  (0.55, 0.10, 0.25),    # Винный
        "speed": 0.85,
        "turbulence": 1.5,
        "dissonance": 0.85,               # Органический диссонанс
    }
}

COLOR_PALETTES = STATE_CONFIGS


class NativeGPUVisualCore(AkakiyCore):
    """
    Нативное аппаратное визуальное ядро Akakiy Core на базе WGL + OpenGL + GLSL.
    Рендерится на GPU (NVIDIA RTX) и блитится в HWND через Win32 GDI SetDIBitsToDevice
    со скоростью 60 FPS без создания дочерних окон или внешних браузерных процессов.
    """

    COLOR_PALETTES: Dict[str, Dict[str, Any]] = COLOR_PALETTES

    def __init__(
        self,
        parent,
        width: int = 520,
        height: int = 210,
        bg: str = "#0a0e17",
        target_fps: int = 60,
        num_nodes: int = 34,
        show_status_text: bool = False,
        **kwargs
    ):
        tk.Canvas.__init__(
            self,
            parent,
            width=width,
            height=height,
            bg=bg,
            highlightthickness=0,
            **kwargs
        )
        self.w = max(64, int(width))
        self.h = max(64, int(height))
        self.bg_hex = bg
        self.target_fps = target_fps
        self.frame_delay_ms = max(10, int(1000 / target_fps))
        self.num_nodes = num_nodes
        self.show_status_text = show_status_text
        self.nodes = []
        self.edges = []
        self.sparks = []
        self.center_x = self.w / 2.0
        self.center_y = self.h / 2.0

        self.state = "idle"
        self.target_state = "idle"
        self.audio_level = 0.0
        self.target_audio_level = 0.0
        self.bloom_wave = 0.0
        self._is_destroyed = False

        # Преобразование hex-цвета фона в RGB [0.0 .. 1.0]
        try:
            h = bg.lstrip("#")
            self.cur_bg = [int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
        except Exception:
            self.cur_bg = [0.047, 0.063, 0.090]  # #0c1017

        # Интерполируемые параметры
        cfg = STATE_CONFIGS["idle"]
        self.cur_nucleus = list(cfg["nucleus"])
        self.cur_plasma = list(cfg["plasma"])
        self.cur_corona = list(cfg["corona"])
        self.cur_speed = cfg["speed"]
        self.cur_turbulence = cfg["turbulence"]
        self.cur_dissonance = cfg["dissonance"]

        self._is_active = True
        self._timer_id: Optional[str] = None
        self.start_time = time.perf_counter()
        self.frame_count = 0
        self.last_fps_calc = time.perf_counter()
        self.current_fps = 60.0

        # Win32 GDI и ModernGL ресурсы
        self.hwnd = 0
        self.hdc = 0
        self.ctx = None
        self.prog = None
        self.vbo = None
        self.vao = None
        self.fbo = None
        self.tex = None
        self.bmi = None

        # Инициализация аппаратного пайплайна
        self._init_gpu_pipeline()
        self.bind("<Configure>", self._on_configure)
        self.bind("<Expose>", self._on_expose)

        # Запуск цикла рендеринга
        self._schedule_next_frame()

    def _init_gpu_pipeline(self) -> None:
        """Инициализация контекста ModernGL и Win32 GDI дескрипторов."""
        if not HAS_MODERNGL:
            return

        self.hwnd = self.winfo_id()
        self.hdc = ctypes.windll.user32.GetDC(self.hwnd)

        # Подготовка структуры BITMAPINFO для прямого блиттинга
        self.bmi = BITMAPINFOHEADER()
        self.bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        self.bmi.biWidth = self.w
        self.bmi.biHeight = self.h  # положительная высота для OpenGL bottom-up
        self.bmi.biPlanes = 1
        self.bmi.biBitCount = 32
        self.bmi.biCompression = 0
        self.bmi.biSizeImage = self.w * self.h * 4

        try:
            self.ctx = moderngl.create_context(standalone=True)
            self.prog = self.ctx.program(vertex_shader=VS_SOURCE, fragment_shader=FS_SOURCE)

            # Полноэкранный квад (два треугольника)
            quad_data = np.array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1], dtype="f4")
            self.vbo = self.ctx.buffer(quad_data)
            self.vao = self.ctx.vertex_array(self.prog, [(self.vbo, "2f", "in_pos")])

            # Текстура и FBO для внеэкранного рендеринга
            self.tex = self.ctx.texture((self.w, self.h), 4)
            self.fbo = self.ctx.framebuffer(color_attachments=[self.tex])
        except Exception:
            self._cleanup_gpu()

    def _on_configure(self, event) -> None:
        """Динамическое обновление размера FBO при ресайзе окна."""
        if hasattr(event, "widget") and event.widget != self:
            return
        new_w = max(64, event.width)
        new_h = max(64, event.height)
        if event.width <= 64 or event.height <= 64:
            return
        if new_w == self.w and new_h == self.h:
            return

        self.w = new_w
        self.h = new_h
        if self.bmi:
            self.bmi.biWidth = self.w
            self.bmi.biHeight = self.h
            self.bmi.biSizeImage = self.w * self.h * 4

        if self.ctx:
            try:
                if self.fbo:
                    self.fbo.release()
                if self.tex:
                    self.tex.release()
                self.tex = self.ctx.texture((self.w, self.h), 4)
                self.fbo = self.ctx.framebuffer(color_attachments=[self.tex])
            except Exception:
                pass

    def _on_expose(self, event=None) -> None:
        """Немедленный блиттинг при открытии или перерисовке окна."""
        if self._is_active:
            self._render_frame()

    def _set_uniform(self, name: str, value: Any) -> None:
        """Безопасная установка uniform шейдера без риска KeyError."""
        if self.prog and name in self.prog:
            try:
                self.prog[name].value = value
            except Exception:
                pass

    @property
    def color_scheme(self) -> Dict[str, Any]:
        """Возвращает палитру и метаданные текущего состояния ядра."""
        return self.COLOR_PALETTES.get(self.state, self.COLOR_PALETTES["idle"])

    @property
    def state_description(self) -> str:
        """Возвращает текстовое описание текущего состояния ядра."""
        return self.color_scheme.get("description", "")

    @property
    def state_badge_text(self) -> str:
        """Возвращает форматированный текст бейджа текущего состояния."""
        return self.color_scheme.get("badge", f"● {self.state.upper()}")

    def set_state(self, state_name: str) -> None:
        """Переключает целевое состояние ядра."""
        if state_name in STATE_CONFIGS:
            self.target_state = state_name
            self.state = state_name
        else:
            self.target_state = "idle"
            self.state = "idle"

        if self.state == "success":
            self.bloom_wave = 0.1
            try:
                self.after(1600, lambda: self.set_state("idle") if self.state == "success" else None)
            except Exception:
                pass

    def trigger_pulse(self, intensity: float = 1.0) -> None:
        """Создает кратковременный импульс энергии."""
        self.target_audio_level = min(1.0, max(0.3, float(intensity)))
        self.bloom_wave = 0.1

    def set_audio_level(self, level: float) -> None:
        """Передаёт уровень громкости для динамической модуляции."""
        self.target_audio_level = max(0.0, min(1.0, float(level)))

    def _schedule_next_frame(self) -> None:
        if not self._is_active or self._is_destroyed:
            return
        if self._timer_id:
            try:
                self.after_cancel(self._timer_id)
            except Exception:
                pass
        self._timer_id = self.after(self.frame_delay_ms, self._render_frame)

    def _render_frame(self) -> None:
        """Отрисовка одного кадра на GPU и блиттинг в Tkinter DC."""
        if not self._is_active:
            return

        t = time.perf_counter() - self.start_time

        # 1. Плавная интерполяция состояний (Lerp 0.08)
        tgt = STATE_CONFIGS.get(self.target_state, STATE_CONFIGS["idle"])
        factor = 0.08

        for i in range(3):
            self.cur_nucleus[i] += (tgt["nucleus"][i] - self.cur_nucleus[i]) * factor
            self.cur_plasma[i]  += (tgt["plasma"][i]  - self.cur_plasma[i])  * factor
            self.cur_corona[i]  += (tgt["corona"][i]  - self.cur_corona[i])  * factor

        self.cur_speed      += (tgt["speed"]      - self.cur_speed)      * factor
        self.cur_turbulence += (tgt["turbulence"] - self.cur_turbulence) * factor
        self.cur_dissonance += (tgt["dissonance"] - self.cur_dissonance) * factor

        self.audio_level += (self.target_audio_level - self.audio_level) * 0.2

        if self.bloom_wave > 0.0:
            self.bloom_wave += 0.03
            if self.bloom_wave > 1.2:
                self.bloom_wave = 0.0

        # 2. Рендеринг на GPU через ModernGL
        if self.ctx and self.fbo and self.prog:
            try:
                if not self.hdc and self.hwnd:
                    self.hdc = ctypes.windll.user32.GetDC(self.hwnd)

                self._set_uniform("u_resolution", (float(self.w), float(self.h)))
                self._set_uniform("u_time", float(t))
                self._set_uniform("u_audio_level", float(self.audio_level))
                self._set_uniform("u_color_bg", tuple(self.cur_bg))
                self._set_uniform("u_color_nucleus", tuple(self.cur_nucleus))
                self._set_uniform("u_color_plasma", tuple(self.cur_plasma))
                self._set_uniform("u_color_corona", tuple(self.cur_corona))
                self._set_uniform("u_speed", float(self.cur_speed))
                self._set_uniform("u_turbulence", float(self.cur_turbulence))
                self._set_uniform("u_dissonance", float(self.cur_dissonance))
                self._set_uniform("u_bloom_wave", float(self.bloom_wave))

                self.fbo.use()
                self.vao.render()
                data = self.fbo.read(components=4)

                # 3. Мгновенный блиттинг в DC окна Tkinter (0.15 мс)
                if self.hdc:
                    ctypes.windll.gdi32.SetDIBitsToDevice(
                        self.hdc, 0, 0, self.w, self.h, 0, 0, 0, self.h,
                        data, ctypes.byref(self.bmi), 0
                    )
            except Exception:
                pass

        # 4. Подсчёт FPS
        self.frame_count += 1
        now = time.perf_counter()
        if now - self.last_fps_calc >= 1.0:
            self.current_fps = self.frame_count / (now - self.last_fps_calc)
            self.frame_count = 0
            self.last_fps_calc = now

        self._schedule_next_frame()

    def _cleanup_gpu(self) -> None:
        """Освобождение GPU-ресурсов."""
        if self.fbo:
            try: self.fbo.release()
            except Exception: pass
            self.fbo = None
        if self.tex:
            try: self.tex.release()
            except Exception: pass
            self.tex = None
        if self.vao:
            try: self.vao.release()
            except Exception: pass
            self.vao = None
        if self.vbo:
            try: self.vbo.release()
            except Exception: pass
            self.vbo = None
        if self.prog:
            try: self.prog.release()
            except Exception: pass
            self.prog = None
        if self.ctx:
            try: self.ctx.release()
            except Exception: pass
            self.ctx = None
        if self.hdc and self.hwnd:
            try: ctypes.windll.user32.ReleaseDC(self.hwnd, self.hdc)
            except Exception: pass
            self.hdc = 0

    def stop(self) -> None:
        """Останавливает цикл анимации без удаления виджета."""
        self._is_active = False
        if self._timer_id:
            try: self.after_cancel(self._timer_id)
            except Exception: pass
            self._timer_id = None

    def start(self) -> None:
        """Запускает или возобновляет цикл анимации."""
        if not self._is_active and not self._is_destroyed:
            self._is_active = True
            self._schedule_next_frame()

    def destroy(self) -> None:
        """Освобождает GPU-ресурсы и корректно уничтожает виджет."""
        self.stop()
        self._is_destroyed = True
        self._cleanup_gpu()
        super().destroy()


def launch_native_preview() -> None:
    """Запуск отдельного окна демонстрации и калибровки Native GPU Visual Core."""
    root = tk.Tk()
    root.title("Akakiy Native GPU Visual Core 2.0 (WGL / ModernGL / GLSL)")
    root.geometry("620x700")
    root.minsize(440, 520)
    root.configure(bg="#0c1017")

    header = tk.Frame(root, bg="#0c1017", padx=16, pady=12)
    header.pack(fill="x")
    title_lbl = tk.Label(
        header,
        text="AKAKIY NATIVE GPU CORE (OpenGL / GLSL)",
        font=("Segoe UI", 11, "bold"),
        fg="#00f3ff",
        bg="#0c1017",
    )
    title_lbl.pack(side="left")

    fps_lbl = tk.Label(
        header,
        text="FPS: --",
        font=("Consolas", 10),
        fg="#7982a9",
        bg="#0c1017",
    )
    fps_lbl.pack(side="right")

    core_container = tk.Frame(root, bg="#0c1017")
    core_container.pack(fill="both", expand=True, padx=16, pady=8)

    core = NativeGPUVisualCore(core_container, width=500, height=500, bg="#0c1017")
    core.pack(fill="both", expand=True)

    ctrl_frame = tk.Frame(root, bg="#121824", padx=12, pady=12)
    ctrl_frame.pack(fill="x", side="bottom")

    state_lbl = tk.Label(
        ctrl_frame,
        text="Состояния ядра (GPU State Transition):",
        font=("Segoe UI", 9, "bold"),
        fg="#9ba3b8",
        bg="#121824",
    )
    state_lbl.pack(anchor="w", pady=(0, 6))

    btn_row = tk.Frame(ctrl_frame, bg="#121824")
    btn_row.pack(fill="x")

    states = [
        ("Idle", "idle", "#38bdf8"),
        ("Listening", "listening", "#00f3ff"),
        ("Thinking", "thinking", "#c084fc"),
        ("Working", "working", "#34d399"),
        ("Speaking", "speaking", "#2dd4bf"),
        ("Success", "success", "#fbbf24"),
        ("Error", "error", "#f87171"),
    ]

    for label, state_key, col in states:
        b = tk.Button(
            btn_row,
            text=label,
            font=("Segoe UI", 8),
            bg="#1a2336",
            fg=col,
            activebackground=col,
            activeforeground="#0c1017",
            relief="flat",
            padx=8,
            pady=4,
            cursor="hand2",
            command=lambda s=state_key: core.set_state(s),
        )
        b.pack(side="left", padx=2, expand=True, fill="x")

    def update_stats():
        if root.winfo_exists():
            fps_lbl.config(text=f"FPS: {core.current_fps:4.1f} | RTX 4070")
            root.after(500, update_stats)

    root.after(500, update_stats)

    def on_closing():
        core.destroy()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    launch_native_preview()

