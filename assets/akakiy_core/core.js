/**
 * ============================================================================
 * Akakiy Visual Core 2.0 — WebGL2 Living Digital Art Engine
 * Custom GLSL Shader, Volumetric Plasma Density, Organic Turbulences & Bridge
 * ============================================================================
 */

(function () {
    "use strict";

    // ------------------------------------------------------------------------
    // GLSL Shaders (Vertex & Fragment)
    // ------------------------------------------------------------------------

    const VS_SOURCE = `#version 300 es
    in vec2 a_position;
    out vec2 v_uv;
    void main() {
        v_uv = a_position * 0.5 + 0.5;
        gl_Position = vec4(a_position, 0.0, 1.0);
    }`;

    const FS_SOURCE = `#version 300 es
    precision highp float;

    in vec2 v_uv;
    out vec4 fragColor;

    uniform vec2 u_resolution;
    uniform float u_time;
    uniform float u_audio_level;

    uniform vec3 u_color_nucleus;
    uniform vec3 u_color_plasma;
    uniform vec3 u_color_corona;

    uniform float u_speed;
    uniform float u_turbulence;
    uniform float u_flux;
    uniform float u_dissonance;
    uniform float u_bloom_wave;

    // --- Simplex 3D Noise (Ashima / Inigo Quilez) ---
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

    // Fractal Brownian Motion (FBM)
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
        // Центрированные координаты с сохранением пропорций
        vec2 uv = (gl_FragCoord.xy - 0.5 * u_resolution) / min(u_resolution.x, u_resolution.y);
        float r = length(uv);
        float theta = atan(uv.y, uv.x);

        // 1. Потоковая циркуляция и направленный флюс
        float swirl = 1.35 * sin(r * 4.2 - u_time * u_speed * 1.6);
        float cos_s = cos(swirl);
        float sin_s = sin(swirl);
        vec2 rot_uv = vec2(
            uv.x * cos_s - uv.y * sin_s,
            uv.x * sin_s + uv.y * cos_s
        );

        // Направленный энергетический дрейф (Working flux)
        rot_uv.x += u_flux * sin(u_time * 3.5 + uv.y * 6.0) * 0.08;

        // Фазовый диссонанс при ошибке
        float diss = u_dissonance * sin(theta * 6.0 + u_time * 8.0) * 0.09;

        // 2. Двойной Domain Warping для органической плазмы
        vec3 p1 = vec3(rot_uv * 2.8, u_time * u_speed * 0.45);
        float n1 = fbm(p1);

        vec3 p2 = vec3(rot_uv * 3.4 + vec2(n1 * 0.65), u_time * u_speed * 0.7);
        float n2 = fbm(p2);

        // Искривлённый радиус плотности
        float warp_r = r + (n1 * 0.16 + n2 * 0.1) * u_turbulence + diss;

        // 3. Органическое дыхание и реакция на звук
        float breath = sin(u_time * u_speed * 1.8) * 0.025 + u_audio_level * 0.16;
        float plasma_radius = 0.34 + breath;

        // СЛОЙ 1: Центральная светящаяся сингулярность (Nucleus)
        float nucleus_r = length(uv + vec2(n1 * 0.04));
        float nucleus_glow = exp(-nucleus_r * nucleus_r * 42.0) * 1.8;
        vec3 nucleus_col = mix(u_color_nucleus, vec3(1.0, 1.0, 1.0), smoothstep(0.12, 0.02, nucleus_r));

        // СЛОЙ 2: Текучее плазменное тело (Volumetric Plasma Field)
        float plasma_density = smoothstep(plasma_radius + 0.12, plasma_radius - 0.16, warp_r);
        float plasma_ribbons = 0.5 + 0.5 * sin(n2 * 9.0 + u_time * u_speed * 2.4);
        vec3 plasma_col = u_color_plasma * plasma_density * (0.6 + 0.5 * plasma_ribbons);

        // СЛОЙ 3: Диффузная эфирная корона (Ambient Radial Bloom)
        float corona_decay = 0.18 / (r + 0.15);
        float corona_glow = corona_decay * exp(-r * 2.4);
        vec3 corona_col = u_color_corona * corona_glow;

        // СЛОЙ 4: Акустические концентрические волны (Listening ripples)
        float sound_ripple = 0.0;
        if (u_audio_level > 0.02) {
            float wave_phase = r * 32.0 - u_time * 9.0;
            sound_ripple = sin(wave_phase) * u_audio_level * smoothstep(0.65, 0.15, r) * 0.35;
        }

        // СЛОЙ 5: Световая волна завершения (Success Bloom Shockwave)
        float success_bloom = 0.0;
        if (u_bloom_wave > 0.01) {
            float ring_r = u_bloom_wave * 0.75;
            float dist_to_ring = abs(r - ring_r);
            success_bloom = exp(-dist_to_ring * dist_to_ring * 90.0) * (1.0 - u_bloom_wave) * 1.5;
        }

        // СЛОЙ 6: Тонкие квантовые фотоны (Sparks / Micro-Particles)
        vec3 spark_p = vec3(rot_uv * 14.0, u_time * 0.6);
        float raw_spark = snoise(spark_p);
        float sparks = pow(max(0.0, raw_spark), 12.0) * 12.0 * smoothstep(0.48, 0.08, r);

        // Итоговое аддитивное оптическое сложение (Additive/Screen Blend)
        vec3 final_rgb = nucleus_col * nucleus_glow
                       + plasma_col
                       + corona_col
                       + u_color_nucleus * sound_ripple
                       + vec3(1.0, 0.92, 0.6) * success_bloom
                       + u_color_nucleus * sparks;

        // Мягкое виньетирование по краям кадра
        float vignette = smoothstep(1.2, 0.4, r);
        final_rgb *= vignette;

        fragColor = vec4(final_rgb, 1.0);
    }`;

    // ------------------------------------------------------------------------
    // Цветовые и физические параметры для 7 состояний
    // ------------------------------------------------------------------------

    const STATE_CONFIGS = {
        idle: {
            nucleus: [0.22, 0.85, 1.0],     // Электрик-циан
            plasma:  [0.08, 0.45, 0.85],    // Глубокий лазурный
            corona:  [0.02, 0.25, 0.60],    // Эфирный синий
            speed: 0.65,
            turbulence: 0.75,
            flux: 0.0,
            dissonance: 0.0,
        },
        listening: {
            nucleus: [0.45, 0.98, 1.0],     // Яркий аквамарин
            plasma:  [0.12, 0.68, 0.82],    // Бирюзовый
            corona:  [0.04, 0.38, 0.55],    // Мягкий циан
            speed: 0.95,
            turbulence: 1.1,
            flux: 0.0,
            dissonance: 0.0,
        },
        thinking: {
            nucleus: [0.85, 0.60, 1.0],     // Розово-лавандовый
            plasma:  [0.55, 0.22, 0.92],    // Ультрафиолет
            corona:  [0.32, 0.08, 0.62],    // Глубокий индиго
            speed: 1.75,
            turbulence: 1.6,
            flux: 0.3,
            dissonance: 0.0,
        },
        working: {
            nucleus: [0.35, 1.0, 0.82],     // Неоновый мятный
            plasma:  [0.06, 0.75, 0.52],    // Изумрудный
            corona:  [0.02, 0.42, 0.32],    // Глубокий малахит
            speed: 1.5,
            turbulence: 1.35,
            flux: 1.0,                      // Направленный энергетический поток
            dissonance: 0.0,
        },
        speaking: {
            nucleus: [0.32, 0.95, 0.88],    // Морской бриз
            plasma:  [0.10, 0.65, 0.62],    // Мягкий тил
            corona:  [0.04, 0.35, 0.38],    // Диффузная бирюза
            speed: 1.1,
            turbulence: 0.95,
            flux: 0.2,
            dissonance: 0.0,
        },
        success: {
            nucleus: [1.0, 0.92, 0.55],     // Тёплое золото
            plasma:  [0.95, 0.68, 0.15],    // Янтарный расцвет
            corona:  [0.45, 0.55, 0.18],    // Золотисто-зелёный
            speed: 1.1,
            turbulence: 0.85,
            flux: 0.0,
            dissonance: 0.0,
        },
        error: {
            nucleus: [1.0, 0.55, 0.65],     // Тёплый коралл
            plasma:  [0.85, 0.25, 0.40],    // Розовый кварц
            corona:  [0.55, 0.10, 0.25],    // Винный
            speed: 0.85,
            turbulence: 1.5,
            flux: 0.0,
            dissonance: 0.85,               // Органический фазовый диссонанс
        }
    };

    // ------------------------------------------------------------------------
    // Движок WebGL2
    // ------------------------------------------------------------------------

    class AkakiyVisualCore {
        constructor(canvas) {
            this.canvas = canvas;
            this.gl = canvas.getContext("webgl2", {
                alpha: false,
                antialias: true,
                depth: false,
                stencil: false,
                powerPreference: "high-performance"
            });

            if (!this.gl) {
                console.error("WebGL2 is not supported on this device/browser.");
                return;
            }

            this.currentState = "idle";
            this.targetState = "idle";
            this.audioLevel = 0.0;
            this.targetAudioLevel = 0.0;
            this.bloomWave = 0.0;

            // Текущие интерполируемые параметры шейдера
            this.cur = {
                nucleus: [...STATE_CONFIGS.idle.nucleus],
                plasma:  [...STATE_CONFIGS.idle.plasma],
                corona:  [...STATE_CONFIGS.idle.corona],
                speed: STATE_CONFIGS.idle.speed,
                turbulence: STATE_CONFIGS.idle.turbulence,
                flux: STATE_CONFIGS.idle.flux,
                dissonance: STATE_CONFIGS.idle.dissonance,
            };

            this.initShaders();
            this.initGeometry();
            this.setupResize();

            // FPS трекер
            this.frameCount = 0;
            this.lastFpsUpdate = performance.now();
            this.fps = 60;

            this.startTime = performance.now();
            this.rafId = requestAnimationFrame((t) => this.render(t));
        }

        compileShader(source, type) {
            const gl = this.gl;
            const shader = gl.createShader(type);
            gl.shaderSource(shader, source);
            gl.compileShader(shader);
            if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
                const info = gl.getShaderInfoLog(shader);
                gl.deleteShader(shader);
                throw new Error("Shader compile error: " + info);
            }
            return shader;
        }

        initShaders() {
            const gl = this.gl;
            const vs = this.compileShader(VS_SOURCE, gl.VERTEX_SHADER);
            const fs = this.compileShader(FS_SOURCE, gl.FRAGMENT_SHADER);

            const program = gl.createProgram();
            gl.attachShader(program, vs);
            gl.attachShader(program, fs);
            gl.linkProgram(program);

            if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
                throw new Error("Program link error: " + gl.getProgramInfoLog(program));
            }

            this.program = program;
            gl.useProgram(program);

            // Кэширование расположения uniforms
            this.uniforms = {
                resolution:    gl.getUniformLocation(program, "u_resolution"),
                time:          gl.getUniformLocation(program, "u_time"),
                audio_level:   gl.getUniformLocation(program, "u_audio_level"),
                color_nucleus: gl.getUniformLocation(program, "u_color_nucleus"),
                color_plasma:  gl.getUniformLocation(program, "u_color_plasma"),
                color_corona:  gl.getUniformLocation(program, "u_color_corona"),
                speed:         gl.getUniformLocation(program, "u_speed"),
                turbulence:    gl.getUniformLocation(program, "u_turbulence"),
                flux:          gl.getUniformLocation(program, "u_flux"),
                dissonance:    gl.getUniformLocation(program, "u_dissonance"),
                bloom_wave:    gl.getUniformLocation(program, "u_bloom_wave"),
            };
        }

        initGeometry() {
            const gl = this.gl;
            // Полноэкранный квад (два треугольника)
            const positions = new Float32Array([
                -1, -1,
                 1, -1,
                -1,  1,
                -1,  1,
                 1, -1,
                 1,  1,
            ]);

            const vao = gl.createVertexArray();
            gl.bindVertexArray(vao);

            const vbo = gl.createBuffer();
            gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
            gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);

            const posLoc = gl.getAttribLocation(this.program, "a_position");
            gl.enableVertexAttribArray(posLoc);
            gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

            this.vao = vao;
        }

        setupResize() {
            const resize = () => {
                const dpr = Math.min(window.devicePixelRatio || 1, 2);
                const w = Math.floor(this.canvas.clientWidth * dpr);
                const h = Math.floor(this.canvas.clientHeight * dpr);
                if (this.canvas.width !== w || this.canvas.height !== h) {
                    this.canvas.width = w;
                    this.canvas.height = h;
                    this.gl.viewport(0, 0, w, h);
                }
            };
            window.addEventListener("resize", resize);
            resize();
        }

        setState(newState) {
            if (STATE_CONFIGS[newState]) {
                this.targetState = newState;
                if (newState === "success") {
                    this.bloomWave = 0.01;
                }
            }
        }

        setAudioLevel(level) {
            this.targetAudioLevel = Math.max(0.0, Math.min(1.0, level));
        }

        render(timestamp) {
            const gl = this.gl;
            const t = (timestamp - this.startTime) * 0.001;

            // 1. Плавная интерполяция состояний (Lerp 0.08)
            const tgt = STATE_CONFIGS[this.targetState] || STATE_CONFIGS.idle;
            const factor = 0.08;

            for (let i = 0; i < 3; i++) {
                this.cur.nucleus[i] += (tgt.nucleus[i] - this.cur.nucleus[i]) * factor;
                this.cur.plasma[i]  += (tgt.plasma[i]  - this.cur.plasma[i])  * factor;
                this.cur.corona[i]  += (tgt.corona[i]  - this.cur.corona[i])  * factor;
            }

            this.cur.speed      += (tgt.speed      - this.cur.speed)      * factor;
            this.cur.turbulence += (tgt.turbulence - this.cur.turbulence) * factor;
            this.cur.flux       += (tgt.flux       - this.cur.flux)       * factor;
            this.cur.dissonance += (tgt.dissonance - this.cur.dissonance) * factor;

            this.audioLevel += (this.targetAudioLevel - this.audioLevel) * 0.2;

            // Развитие волны успеха и авто-возврат в idle
            if (this.bloomWave > 0.0) {
                this.bloomWave += 0.018;
                if (this.bloomWave >= 1.0) {
                    this.bloomWave = 0.0;
                    if (this.targetState === "success") {
                        this.setState("idle");
                    }
                }
            }

            // 2. Передача uniforms в шейдер
            gl.useProgram(this.program);
            gl.uniform2f(this.uniforms.resolution, this.canvas.width, this.canvas.height);
            gl.uniform1f(this.uniforms.time, t);
            gl.uniform1f(this.uniforms.audio_level, this.audioLevel);

            gl.uniform3fv(this.uniforms.color_nucleus, this.cur.nucleus);
            gl.uniform3fv(this.uniforms.color_plasma,  this.cur.plasma);
            gl.uniform3fv(this.uniforms.color_corona,  this.cur.corona);

            gl.uniform1f(this.uniforms.speed,      this.cur.speed);
            gl.uniform1f(this.uniforms.turbulence, this.cur.turbulence);
            gl.uniform1f(this.uniforms.flux,       this.cur.flux);
            gl.uniform1f(this.uniforms.dissonance, this.cur.dissonance);
            gl.uniform1f(this.uniforms.bloom_wave, this.bloomWave);

            // 3. Отрисовка
            gl.bindVertexArray(this.vao);
            gl.drawArrays(gl.TRIANGLES, 0, 6);

            // 4. Подсчёт FPS
            this.frameCount++;
            if (timestamp - this.lastFpsUpdate >= 500) {
                this.fps = Math.round((this.frameCount * 1000) / (timestamp - this.lastFpsUpdate));
                this.frameCount = 0;
                this.lastFpsUpdate = timestamp;
                if (window.onCoreTelemetry) {
                    window.onCoreTelemetry(this.fps, this.targetState, this.audioLevel);
                }
            }

            this.rafId = requestAnimationFrame((nextT) => this.render(nextT));
        }

        destroy() {
            if (this.rafId) {
                cancelAnimationFrame(this.rafId);
            }
        }
    }

    // ------------------------------------------------------------------------
    // Инициализация при загрузке страницы и экспорт API
    // ------------------------------------------------------------------------

    window.addEventListener("DOMContentLoaded", () => {
        const canvas = document.getElementById("gl-canvas");
        if (!canvas) return;

        const core = new AkakiyVisualCore(canvas);

        // Экспорт глобального API для внешнего вызова (Python / WebView2 bridge)
        window.akakiyCore = {
            setState: (st) => {
                core.setState(st);
                updateHudState(st);
            },
            setAudioLevel: (lvl) => {
                core.setAudioLevel(lvl);
                updateHudAudio(lvl);
            },
            getState: () => core.targetState,
            getFps: () => core.fps,
            instance: core
        };

        // Подключение интерактивного калибровочного HUD
        setupCalibrationHUD(core);

        // Подключение WebSocket клиента к локальному серверу Python (если активен)
        initPythonBridge();
    });

    function setupCalibrationHUD(core) {
        const hud = document.getElementById("calibration-hud");
        const fpsEl = document.getElementById("hud-fps");
        const slider = document.getElementById("audio-slider");
        const audioVal = document.getElementById("audio-val");
        const stateBtns = document.querySelectorAll(".btn-state");

        const urlParams = new URLSearchParams(window.location.search);
        const isEmbedded = urlParams.get("embedded") === "1";
        if (isEmbedded && hud) {
            hud.style.display = "none";
            return;
        }

        // Обработка кликов по кнопкам состояний
        stateBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                const st = btn.getAttribute("data-state");
                window.akakiyCore.setState(st);
            });
        });

        // Обработка слайдера звука
        if (slider) {
            slider.addEventListener("input", (e) => {
                const val = parseFloat(e.target.value);
                window.akakiyCore.setAudioLevel(val);
                if (audioVal) audioVal.textContent = val.toFixed(2);
            });
        }

        // Телеметрия
        window.onCoreTelemetry = (fps, state, audio) => {
            if (fpsEl) fpsEl.textContent = `${fps} FPS`;
        };

        // Hotkey 'H' для скрытия/показа калибровочного HUD
        window.addEventListener("keydown", (e) => {
            if (e.key === "h" || e.key === "H" || e.key === "р" || e.key === "Р") {
                if (hud) hud.classList.toggle("hidden");
            }
        });
    }

    function updateHudState(activeState) {
        const stateBtns = document.querySelectorAll(".btn-state");
        stateBtns.forEach(btn => {
            if (btn.getAttribute("data-state") === activeState) {
                btn.classList.add("active");
            } else {
                btn.classList.remove("active");
            }
        });
    }

    function updateHudAudio(level) {
        const slider = document.getElementById("audio-slider");
        const audioVal = document.getElementById("audio-val");
        if (slider) slider.value = level;
        if (audioVal) audioVal.textContent = Number(level).toFixed(2);
    }

    // ------------------------------------------------------------------------
    // Python WebSocket Bridge (автоматическое подключение к Python серверу)
    // ------------------------------------------------------------------------
    function initPythonBridge() {
        const urlParams = new URLSearchParams(window.location.search);
        const wsPort = urlParams.get("ws") || "8765";
        const wsUrl = `ws://127.0.0.1:${wsPort}`;

        let ws = null;
        let retryTimeout = null;

        function connect() {
            try {
                ws = new WebSocket(wsUrl);
                ws.onopen = () => {
                    console.log("[AkakiyBridge] Connected to Python Core Server:", wsUrl);
                };
                ws.onmessage = (event) => {
                    try {
                        const msg = JSON.parse(event.data);
                        if (msg.action === "setState" && msg.state) {
                            window.akakiyCore.setState(msg.state);
                        } else if (msg.action === "setAudioLevel" && msg.level !== undefined) {
                            window.akakiyCore.setAudioLevel(msg.level);
                        }
                    } catch (err) {
                        console.error("[AkakiyBridge] Invalid message:", err);
                    }
                };
                ws.onclose = () => {
                    retryTimeout = setTimeout(connect, 2000);
                };
                ws.onerror = () => {
                    ws.close();
                };
            } catch (e) {
                retryTimeout = setTimeout(connect, 3000);
            }
        }

        connect();
    }
})();
