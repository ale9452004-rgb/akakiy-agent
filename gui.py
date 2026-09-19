import sys
import os
import math
import time
import queue
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext
from pathlib import Path

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(r"c:\Akakiy agent")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.agent import Agent
from tools.dispatcher import (
    set_confirmation_handler,
    set_action_observer,
    get_confirmation_details_text,
    dispatch
)
from commands import show_help, show_status


class AkakiyCloud(tk.Canvas):
    """
    Футуристичное анимированное ядро / облако Акакия.
    Поддерживает состояния:
    - 'idle': спокойная голубая пульсация (ядро дышит);
    - 'thinking': активное вращение фиолетовых/циановых частиц;
    - 'working': расширяющиеся неоновые волны (бирюзовые импульсы);
    - 'waiting': янтарно-золотистое мерцание (ожидание подтверждения);
    - 'error': красная тревожная пульсация;
    - 'listening': колебания волны (архитектурный задел под голос);
    - 'speaking': модуляция амплитуды (архитектурный задел под голос).
    """

    def __init__(self, parent, size=150, **kwargs):
        super().__init__(
            parent,
            width=size,
            height=size,
            bg="#0d1117",
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
                "speed": 0.03 + (i % 3) * 0.015,
                "radius": 32 + (i % 4) * 6
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
        pulse = math.sin(t) * 5

        # Выбор цветовой схемы и динамики в зависимости от состояния
        if self.state == "idle":
            base_r = 36 + pulse
            core_color = "#388bfd"
            halo_color = "#1f6feb"
            glow_color = "#0d419d"
            sub_text = "IDLE"
            status_color = "#58a6ff"

        elif self.state == "thinking":
            base_r = 38 + math.sin(t * 2) * 7
            core_color = "#a371f7"
            halo_color = "#8957e5"
            glow_color = "#5a32a3"
            sub_text = "THINKING"
            status_color = "#bc8cff"

        elif self.state == "working":
            base_r = 40 + math.sin(t * 2.5) * 8
            core_color = "#39d353"
            halo_color = "#2ea043"
            glow_color = "#196c2e"
            sub_text = "WORKING"
            status_color = "#56d364"

        elif self.state == "waiting":
            base_r = 38 + math.sin(t * 3) * 9
            core_color = "#d29922"
            halo_color = "#bb8009"
            glow_color = "#7d4e00"
            sub_text = "WAITING"
            status_color = "#e3b341"

        elif self.state == "error":
            base_r = 38 + math.sin(t * 4) * 9
            core_color = "#f85149"
            halo_color = "#da3633"
            glow_color = "#8e1519"
            sub_text = "ERROR"
            status_color = "#ff7b72"

        elif self.state == "listening":
            base_r = 36 + self.audio_level * 18 + pulse
            core_color = "#58a6ff"
            halo_color = "#1f6feb"
            glow_color = "#388bfd"
            sub_text = "LISTENING"
            status_color = "#79c0ff"

        elif self.state == "speaking":
            base_r = 36 + self.audio_level * 22 + math.sin(t * 3) * 6
            core_color = "#2ea043"
            halo_color = "#39d353"
            glow_color = "#238636"
            sub_text = "SPEAKING"
            status_color = "#7ee787"

        # 1. Внешнее свечение (Aura)
        aura_r = base_r + 18
        self.create_oval(
            self.cx - aura_r, self.cy - aura_r,
            self.cx + aura_r, self.cy + aura_r,
            fill="", outline=glow_color, width=2
        )

        # 2. Расширяющиеся импульсные кольца (для working / waiting)
        if self.state in ("working", "waiting", "thinking"):
            wave_r = (base_r + (self.tick * 1.5) % 30)
            self.create_oval(
                self.cx - wave_r, self.cy - wave_r,
                self.cx + wave_r, self.cy + wave_r,
                fill="", outline=halo_color, width=1
            )

        # 3. Средний ореол ядра
        self.create_oval(
            self.cx - base_r, self.cy - base_r,
            self.cx + base_r, self.cy + base_r,
            fill=halo_color, outline=""
        )

        # 4. Внутреннее горячее ядро
        inner_r = base_r * 0.65
        self.create_oval(
            self.cx - inner_r, self.cy - inner_r,
            self.cx + inner_r, self.cy + inner_r,
            fill=core_color, outline=""
        )

        # 5. Орбитальные частицы (квантовые точки вокруг ядра)
        for p in self.particles:
            p["angle"] += p["speed"]
            px = self.cx + math.cos(p["angle"]) * (p["radius"] + pulse * 0.5)
            py = self.cy + math.sin(p["angle"]) * (p["radius"] + pulse * 0.5)
            self.create_oval(px - 2, py - 2, px + 2, py + 2, fill=core_color, outline="")

        # 6. Текстовая подпись состояния ядра
        self.create_text(
            self.cx, self.cy + 52,
            text=f"● {sub_text}",
            fill=status_color,
            font=("Consolas", 8, "bold")
        )

        self.after(33, self._animate)


class AkakiyGUI:
    """
    Главная Desktop-оболочка Акакия.
    Работает поверх существующего Agent, не блокируя UI при обращении к Ollama.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Акакий 2.0 // Desktop Shell")
        self.root.geometry("1120x760")
        self.root.minsize(960, 680)
        self.root.configure(bg="#0d1117")

        # Инициализация сущностей
        self.agent = Agent()
        self.queue = queue.Queue()
        self.confirm_event = threading.Event()
        self.confirm_result = False
        self.is_busy = False

        # Устанавливаем обработчики в Dispatcher
        set_confirmation_handler(self._on_confirmation_requested)
        set_action_observer(self._on_action_observed)

        self._create_widgets()
        self._poll_queue()

        # Приветственное сообщение
        self._append_chat(
            "Акакий",
            "Привет! Я Акакий — твой локальный ИИ-ассистент.\n"
            "Я умею отвечать на вопросы, работать с кодом и выполнять комплексные задачи через Teamwork.\n"
            "Используй кнопки быстрых команд или пиши любой запрос в поле ввода ниже.",
            tag="akakiy"
        )
        self._log_process("Система готова к приёму команд.")

    def _create_widgets(self):
        # =============================================================
        # 1. Верхний заголовочный бар (Header)
        # =============================================================
        header_frame = tk.Frame(self.root, bg="#161b22", height=130, bd=1, relief="flat")
        header_frame.pack(side="top", fill="x", padx=10, pady=(10, 5))

        # Левая часть: название и статус
        info_frame = tk.Frame(header_frame, bg="#161b22")
        info_frame.pack(side="left", padx=20, pady=10)

        title_label = tk.Label(
            info_frame,
            text="АКAKИЙ // ДЕСКТОП",
            font=("Segoe UI", 16, "bold"),
            fg="#58a6ff",
            bg="#161b22"
        )
        title_label.pack(anchor="w")

        subtitle_label = tk.Label(
            info_frame,
            text="Автономный агент разработки • qwen3:8b",
            font=("Segoe UI", 9),
            fg="#8b949e",
            bg="#161b22"
        )
        subtitle_label.pack(anchor="w", pady=(2, 8))

        status_row = tk.Frame(info_frame, bg="#161b22")
        status_row.pack(anchor="w")

        tk.Label(status_row, text="Статус: ", font=("Segoe UI", 9, "bold"), fg="#8b949e", bg="#161b22").pack(side="left")
        self.status_badge = tk.Label(
            status_row,
            text=" ГОТОВ ",
            font=("Consolas", 9, "bold"),
            fg="#0d1117",
            bg="#3fb950",
            padx=6, pady=2
        )
        self.status_badge.pack(side="left")

        # Центр: Анимированное ядро / облако
        cloud_frame = tk.Frame(header_frame, bg="#161b22")
        cloud_frame.pack(side="left", expand=True, pady=5)

        self.cloud = AkakiyCloud(cloud_frame, size=120)
        self.cloud.pack()

        # Правая часть: кнопка отключения
        right_frame = tk.Frame(header_frame, bg="#161b22")
        right_frame.pack(side="right", padx=20, pady=15)

        self.shutdown_btn = tk.Button(
            right_frame,
            text="⏻ Отключить Акакия",
            font=("Segoe UI", 9, "bold"),
            fg="#f85149",
            bg="#21262d",
            activebackground="#da3633",
            activeforeground="#ffffff",
            bd=1,
            relief="solid",
            padx=12, pady=6,
            command=self._on_shutdown
        )
        self.shutdown_btn.pack(anchor="e")

        # =============================================================
        # 2. Основная рабочая область (Split Layout: Чат слева, Инфо справа)
        # =============================================================
        main_paned = tk.PanedWindow(self.root, orient="horizontal", bg="#0d1117", bd=0, sashwidth=4)
        main_paned.pack(fill="both", expand=True, padx=10, pady=5)

        # ----------------- ЛЕВАЯ ПАНЕЛЬ: ЧАТ -------------------------
        chat_container = tk.Frame(main_paned, bg="#161b22", bd=1, relief="flat")
        main_paned.add(chat_container, minsize=480, stretch="always")

        chat_header = tk.Frame(chat_container, bg="#21262d", height=32)
        chat_header.pack(fill="x")
        tk.Label(
            chat_header,
            text="💬 ДИАЛОГ С АКАКИЕМ",
            font=("Segoe UI", 9, "bold"),
            fg="#c9d1d9",
            bg="#21262d",
            padx=10, pady=6
        ).pack(side="left")

        # История сообщений
        self.chat_history = scrolledtext.ScrolledText(
            chat_container,
            wrap="word",
            bg="#0d1117",
            fg="#c9d1d9",
            font=("Segoe UI", 10),
            bd=0,
            insertbackground="#58a6ff"
        )
        self.chat_history.pack(fill="both", expand=True, padx=8, pady=8)

        # Теги стилей сообщений
        self.chat_history.tag_configure("user", foreground="#58a6ff", font=("Segoe UI", 10, "bold"))
        self.chat_history.tag_configure("akakiy", foreground="#7ee787", font=("Segoe UI", 10, "bold"))
        self.chat_history.tag_configure("system", foreground="#8b949e", font=("Segoe UI", 9, "italic"))
        self.chat_history.tag_configure("body", foreground="#c9d1d9", font=("Segoe UI", 10))
        self.chat_history.tag_configure("error", foreground="#f85149", font=("Segoe UI", 10, "bold"))

        # Панель быстрых команд
        quick_bar = tk.Frame(chat_container, bg="#161b22")
        quick_bar.pack(fill="x", padx=8, pady=(0, 6))

        quick_buttons = [
            ("📊 Статус", "статус"),
            ("❓ Помощь", "помощь"),
            ("📁 Список файлов", "покажи список файлов"),
            ("🧹 Очистить чат", "!clear"),
        ]
        for label, cmd in quick_buttons:
            btn = tk.Button(
                quick_bar,
                text=label,
                font=("Segoe UI", 8),
                fg="#c9d1d9",
                bg="#21262d",
                activebackground="#30363d",
                bd=1,
                relief="solid",
                padx=8, pady=3,
                command=lambda c=cmd: self._on_quick_command(c)
            )
            btn.pack(side="left", padx=(0, 6))

        # Поле ввода и кнопка отправки
        input_frame = tk.Frame(chat_container, bg="#161b22")
        input_frame.pack(fill="x", padx=8, pady=(0, 8))

        self.input_entry = tk.Entry(
            input_frame,
            font=("Segoe UI", 11),
            bg="#21262d",
            fg="#f0f6fc",
            insertbackground="#58a6ff",
            bd=1,
            relief="solid"
        )
        self.input_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 6))
        self.input_entry.bind("<Return>", lambda event: self._on_send())

        self.send_btn = tk.Button(
            input_frame,
            text="Отправить ↵",
            font=("Segoe UI", 10, "bold"),
            fg="#ffffff",
            bg="#238636",
            activebackground="#2ea043",
            activeforeground="#ffffff",
            bd=0,
            padx=14, pady=6,
            command=self._on_send
        )
        self.send_btn.pack(side="right")

        # ----------------- ПРАВАЯ ПАНЕЛЬ: ПРОЦЕСС И РЕЗУЛЬТАТ --------
        side_container = tk.Frame(main_paned, bg="#161b22", bd=1, relief="flat")
        main_paned.add(side_container, minsize=400, stretch="always")

        # А. Область "Процесс" (верхняя часть правой панели)
        proc_header = tk.Frame(side_container, bg="#21262d", height=32)
        proc_header.pack(fill="x")
        tk.Label(
            proc_header,
            text="⚙️ ПРОЦЕСС (ТЕКУЩЕЕ ДЕЙСТВИЕ)",
            font=("Segoe UI", 9, "bold"),
            fg="#c9d1d9",
            bg="#21262d",
            padx=10, pady=6
        ).pack(side="left")

        self.proc_text = scrolledtext.ScrolledText(
            side_container,
            height=8,
            wrap="word",
            bg="#0d1117",
            fg="#8b949e",
            font=("Consolas", 9),
            bd=0
        )
        self.proc_text.pack(fill="both", expand=True, padx=8, pady=6)

        # Б. Область "Подтверждение" (Confirmation Panel)
        self.confirm_frame = tk.LabelFrame(
            side_container,
            text=" ⚠️ ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ ",
            font=("Segoe UI", 9, "bold"),
            fg="#d29922",
            bg="#161b22",
            bd=1,
            relief="solid",
            padx=8, pady=6
        )
        # Панель скрыта до момента запроса
        self.confirm_detail_label = tk.Label(
            self.confirm_frame,
            text="Действие требует одобрения...",
            font=("Consolas", 8),
            fg="#f0f6fc",
            bg="#161b22",
            justify="left",
            anchor="w"
        )
        self.confirm_detail_label.pack(fill="x", pady=(0, 6))

        confirm_btn_row = tk.Frame(self.confirm_frame, bg="#161b22")
        confirm_btn_row.pack(fill="x")

        self.btn_confirm_yes = tk.Button(
            confirm_btn_row,
            text="✓ Разрешить (Да)",
            font=("Segoe UI", 9, "bold"),
            fg="#ffffff",
            bg="#238636",
            activebackground="#2ea043",
            bd=0,
            padx=16, pady=4,
            command=lambda: self._resolve_confirmation(True)
        )
        self.btn_confirm_yes.pack(side="left", padx=(0, 8))

        self.btn_confirm_no = tk.Button(
            confirm_btn_row,
            text="✗ Отклонить (Нет)",
            font=("Segoe UI", 9, "bold"),
            fg="#ffffff",
            bg="#da3633",
            activebackground="#f85149",
            bd=0,
            padx=16, pady=4,
            command=lambda: self._resolve_confirmation(False)
        )
        self.btn_confirm_no.pack(side="left")

        # В. Область "Результат" (нижняя часть правой панели)
        res_header = tk.Frame(side_container, bg="#21262d", height=32)
        res_header.pack(fill="x")
        tk.Label(
            res_header,
            text="📋 ИТОГОВЫЙ РЕЗУЛЬТАТ",
            font=("Segoe UI", 9, "bold"),
            fg="#c9d1d9",
            bg="#21262d",
            padx=10, pady=6
        ).pack(side="left")

        self.res_text = scrolledtext.ScrolledText(
            side_container,
            height=12,
            wrap="word",
            bg="#0d1117",
            fg="#f0f6fc",
            font=("Segoe UI", 9),
            bd=0
        )
        self.res_text.pack(fill="both", expand=True, padx=8, pady=6)

    # =============================================================
    # Логика обновления состояний и очередей (Thread-Safe)
    # =============================================================
    def set_gui_state(self, state_name):
        """
        Переключает статус интерфейса:
        - 'готов': зелёный
        - 'работает': синий/циановый
        - 'ожидание': янтарный
        - 'ошибка': красный
        """
        if state_name == "готов":
            self.status_badge.config(text=" ГОТОВ ", bg="#3fb950", fg="#0d1117")
            self.cloud.set_state("idle")
            self.is_busy = False
            self.send_btn.config(state="normal")
            self.input_entry.config(state="normal")
        elif state_name == "работает":
            self.status_badge.config(text=" РАБОТАЕТ ", bg="#58a6ff", fg="#0d1117")
            self.cloud.set_state("working")
            self.is_busy = True
            self.send_btn.config(state="disabled")
        elif state_name == "ожидание":
            self.status_badge.config(text=" ОЖИДАНИЕ ПОДТВЕРЖДЕНИЯ ", bg="#d29922", fg="#0d1117")
            self.cloud.set_state("waiting")
        elif state_name == "ошибка":
            self.status_badge.config(text=" ОШИБКА ", bg="#f85149", fg="#ffffff")
            self.cloud.set_state("error")
            self.is_busy = False
            self.send_btn.config(state="normal")

    def _append_chat(self, author, text, tag="body"):
        self.chat_history.insert(tk.END, f"\n{author}:\n", tag)
        self.chat_history.insert(tk.END, f"{text.strip()}\n", "body")
        self.chat_history.see(tk.END)

    def _log_process(self, message):
        t_str = time.strftime("%H:%M:%S")
        self.proc_text.insert(tk.END, f"[{t_str}] {message}\n")
        self.proc_text.see(tk.END)

    def _set_result(self, text):
        self.res_text.delete("1.0", tk.END)
        self.res_text.insert(tk.END, text.strip())
        self.res_text.see(tk.END)

    def _on_quick_command(self, cmd):
        if cmd == "!clear":
            self.chat_history.delete("1.0", tk.END)
            self.proc_text.delete("1.0", tk.END)
            self.res_text.delete("1.0", tk.END)
            self._log_process("Чат и экраны очищены.")
            return

        self.input_entry.delete(0, tk.END)
        self.input_entry.insert(0, cmd)
        self._on_send()

    def _on_send(self):
        if self.is_busy:
            return

        text = self.input_entry.get().strip()
        if not text:
            return

        self.input_entry.delete(0, tk.END)
        self._append_chat("Ты", text, tag="user")
        self._log_process(f"Получен запрос: {text[:60]}...")
        self.set_gui_state("работает")

        # Запуск фонового потока
        worker = threading.Thread(
            target=self._execute_agent_task,
            args=(text,),
            daemon=True
        )
        worker.start()

    def _execute_agent_task(self, user_input):
        """Выполняется в отдельном потоке."""
        try:
            result = self.agent.process(user_input)
            self.queue.put(("task_success", result))
        except Exception as e:
            self.queue.put(("task_error", str(e)))

    # =============================================================
    # Обработчик подтверждений из Dispatcher (GUI Hook)
    # =============================================================
    def _on_confirmation_requested(self, tool_name, kwargs):
        """
        Вызывается Dispatcher в рабочем потоке!
        Отправляет запрос в GUI поток и ждёт нажатия пользователем кнопки.
        """
        details = get_confirmation_details_text(tool_name, kwargs)
        self.confirm_event.clear()
        self.queue.put(("ask_confirmation", {"tool": tool_name, "details": details}))

        # Блокируем рабочий поток до решения пользователя в GUI
        self.confirm_event.wait()
        return self.confirm_result

    def _on_action_observed(self, event_type, data):
        """Вызывается Dispatcher для логирования действий."""
        if event_type == "before_tool":
            tool = data.get("tool", "")
            self.queue.put(("process_log", f"Запуск инструмента: {tool}"))
        elif event_type == "after_tool":
            tool = data.get("tool", "")
            self.queue.put(("process_log", f"Инструмент {tool} завершён."))
        elif event_type == "confirmation_rejected":
            tool = data.get("tool", "")
            self.queue.put(("process_log", f"Пользователь отклонил выполнение {tool}."))

    def _resolve_confirmation(self, approved: bool):
        """Вызывается по кнопке Да / Нет в GUI."""
        self.confirm_result = approved
        self.confirm_frame.pack_forget()
        self.set_gui_state("работает")
        self._log_process(f"Пользователь ответил: {'ДА' if approved else 'НЕТ'}")
        self.confirm_event.set()

    # =============================================================
    # Опрос очереди событий рабочего потока
    # =============================================================
    def _poll_queue(self):
        try:
            while True:
                msg_type, payload = self.queue.get_nowait()

                if msg_type == "process_log":
                    self._log_process(payload)

                elif msg_type == "ask_confirmation":
                    self.set_gui_state("ожидание")
                    tool = payload.get("tool", "")
                    details = payload.get("details", "")
                    self.confirm_detail_label.config(
                        text=f"Инструмент: {tool}\n{details[:250]}"
                    )
                    # Показываем панель подтверждения над полем результата
                    self.confirm_frame.pack(fill="x", padx=8, pady=(0, 6), before=self.res_text)
                    self._log_process(f"Требуется подтверждение для: {tool}")

                elif msg_type == "task_success":
                    self._handle_task_success(payload)
                    self.set_gui_state("готов")

                elif msg_type == "task_error":
                    self._append_chat("Акакий", f"Ошибка: {payload}", tag="error")
                    self._log_process(f"Сбой выполнения: {payload}")
                    self._set_result(f"Ошибка:\n{payload}")
                    self.set_gui_state("ошибка")

        except queue.Empty:
            pass

        self.root.after(50, self._poll_queue)

    def _handle_task_success(self, result):
        if not isinstance(result, dict):
            self._append_chat("Акакий", str(result), tag="akakiy")
            self._set_result(str(result))
            return

        r_type = result.get("type")

        if r_type == "chat":
            ans = result.get("answer", "")
            self._append_chat("Акакий", ans, tag="akakiy")
            self._set_result(ans)

        elif r_type == "plan_execution":
            exec_res = result.get("result", {})
            summary = exec_res.get("summary", "") if isinstance(exec_res, dict) else ""
            msg = exec_res.get("message", "") if isinstance(exec_res, dict) else str(exec_res)
            display_text = summary if summary else msg
            self._append_chat("Акакий", display_text, tag="akakiy")
            self._set_result(display_text)
            self._log_process(f"План завершён: {msg}")

        elif r_type == "tool":
            tool_name = result.get("tool", "")
            tool_res = result.get("result", {})
            ans = str(tool_res.get("result", tool_res))
            self._append_chat("Акакий", f"[{tool_name}]: {ans}", tag="akakiy")
            self._set_result(ans)

        else:
            ans = str(result)
            self._append_chat("Акакий", ans, tag="akakiy")
            self._set_result(ans)

    def _on_shutdown(self):
        self._log_process("Завершение работы Акакия...")
        set_confirmation_handler(None)
        set_action_observer(None)
        self.root.destroy()


def main():
    root = tk.Tk()
    app = AkakiyGUI(root)
    root.protocol("WM_DELETE_WINDOW", app._on_shutdown)
    root.mainloop()


if __name__ == "__main__":
    main()
