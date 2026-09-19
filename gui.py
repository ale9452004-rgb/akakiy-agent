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


def _bind_hover(widget, normal_bg, hover_bg, normal_fg=None, hover_fg=None):
    """Добавляет тактильный визуальный отклик (hover-эффект) при наведении курсора."""
    def on_enter(e):
        try:
            widget.config(bg=hover_bg)
            if hover_fg is not None:
                widget.config(fg=hover_fg)
        except Exception:
            pass

    def on_leave(e):
        try:
            widget.config(bg=normal_bg)
            if normal_fg is not None:
                widget.config(fg=normal_fg)
        except Exception:
            pass

    widget.bind("<Enter>", on_enter)
    widget.bind("<Leave>", on_leave)


from ui.cloud import AkakiyCloud as AkakiyCloud
from voice import VoiceService


class AkakiyGUI:
    """
    Главная Desktop-оболочка Акакия.
    Работает поверх существующего Agent, не блокируя UI при обращении к Ollama.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Акакий 2.0 // Desktop Shell")
        self.root.geometry("1140x780")
        self.root.minsize(980, 680)
        self.root.configure(bg="#090d13")

        # Инициализация сущностей
        self.agent = Agent()
        self.queue = queue.Queue()
        self.confirm_event = threading.Event()
        self.confirm_result = False
        self.is_busy = False
        self.voice_enabled = False
        self.voice = VoiceService(agent=self.agent, event_sink=self._on_voice_event)

        # Устанавливаем обработчики в Dispatcher
        set_confirmation_handler(self._on_confirmation_requested)
        set_action_observer(self._on_action_observed)

        self._create_widgets()
        self._poll_queue()

        # Приветственное сообщение
        self._append_chat(
            "Акакий",
            "Привет! Я Акакий — твой автономный ИИ-ассистент разработки.\n"
            "• Умею анализировать кодовую базу, редактировать файлы и проверять синтаксис.\n"
            "• Сложные многошаговые задачи координирую через pipeline Teamwork.\n"
            "• Используй быстрые команды внизу или напиши любую задачу в поле ввода.",
            tag="akakiy"
        )
        self._log_process("Ядро Акакия инициализировано. Готов к работе.")

    def _create_widgets(self):
        # =============================================================
        # 1. Верхний заголовочный бар (Header)
        # =============================================================
        header_frame = tk.Frame(self.root, bg="#161b22", height=125, bd=0)
        header_frame.pack(side="top", fill="x", padx=12, pady=(10, 6))

        # Левая часть: название, чипы и статус
        info_frame = tk.Frame(header_frame, bg="#161b22")
        info_frame.pack(side="left", padx=16, pady=12)

        title_row = tk.Frame(info_frame, bg="#161b22")
        title_row.pack(anchor="w")

        tk.Label(
            title_row,
            text="АКAKИЙ",
            font=("Segoe UI", 16, "bold"),
            fg="#58a6ff",
            bg="#161b22"
        ).pack(side="left")

        tk.Label(
            title_row,
            text=" // DESKTOP CORE",
            font=("Segoe UI", 13, "bold"),
            fg="#8b949e",
            bg="#161b22"
        ).pack(side="left")

        # Чипы конфигурации
        chips_row = tk.Frame(info_frame, bg="#161b22")
        chips_row.pack(anchor="w", pady=(4, 8))

        chips = [
            ("LLM: QWEN3:8B", "#388bfd", "#1c2128"),
            ("TEAMWORK", "#a371f7", "#1c2128"),
            ("v2.0", "#3fb950", "#1c2128")
        ]
        for label, text_col, bg_col in chips:
            c = tk.Label(
                chips_row,
                text=label,
                font=("Consolas", 7, "bold"),
                fg=text_col,
                bg=bg_col,
                padx=6, pady=1,
                bd=1, relief="solid"
            )
            c.pack(side="left", padx=(0, 5))

        self.voice_chip = tk.Label(
            chips_row,
            text="ГОЛОС: ВЫКЛ",
            font=("Consolas", 7, "bold"),
            fg="#8b949e",
            bg="#1c2128",
            padx=6, pady=1,
            bd=1, relief="solid"
        )
        self.voice_chip.pack(side="left", padx=(0, 5))

        # Строка статуса
        status_row = tk.Frame(info_frame, bg="#161b22")
        status_row.pack(anchor="w")

        tk.Label(status_row, text="РЕЖИМ: ", font=("Consolas", 8, "bold"), fg="#8b949e", bg="#161b22").pack(side="left")
        self.status_badge = tk.Label(
            status_row,
            text=" ГОТОВ ",
            font=("Consolas", 8, "bold"),
            fg="#0d1117",
            bg="#3fb950",
            padx=8, pady=2
        )
        self.status_badge.pack(side="left")

        # Центр: Анимированное кибернетическое ядро / облако
        cloud_frame = tk.Frame(header_frame, bg="#161b22")
        cloud_frame.pack(side="left", expand=True, pady=4)

        self.cloud = AkakiyCloud(cloud_frame, size=115)
        self.cloud.pack()

        # Правая часть: кнопка отключения и системная инфо
        right_frame = tk.Frame(header_frame, bg="#161b22")
        right_frame.pack(side="right", padx=16, pady=16)

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
            padx=14, pady=6,
            cursor="hand2",
            command=self._on_shutdown
        )
        self.shutdown_btn.pack(anchor="e")
        _bind_hover(self.shutdown_btn, "#21262d", "#8e1519", normal_fg="#f85149", hover_fg="#ffffff")

        # =============================================================
        # 2. Основная рабочая область (Split Layout: Чат слева, Инфо справа)
        # =============================================================
        main_paned = tk.PanedWindow(self.root, orient="horizontal", bg="#090d13", bd=0, sashwidth=5)
        main_paned.pack(fill="both", expand=True, padx=12, pady=4)

        # ----------------- ЛЕВАЯ ПАНЕЛЬ: ЧАТ -------------------------
        chat_container = tk.Frame(main_paned, bg="#161b22", bd=0)
        main_paned.add(chat_container, minsize=490, stretch="always")

        chat_header = tk.Frame(chat_container, bg="#1c2128", height=32)
        chat_header.pack(fill="x")
        tk.Label(
            chat_header,
            text="💬 ДИАЛОГ С АКАКИЕМ",
            font=("Segoe UI", 9, "bold"),
            fg="#58a6ff",
            bg="#1c2128",
            padx=12, pady=7
        ).pack(side="left")

        # История сообщений
        self.chat_history = scrolledtext.ScrolledText(
            chat_container,
            wrap="word",
            bg="#0d1117",
            fg="#c9d1d9",
            font=("Segoe UI", 10),
            bd=0,
            padx=10, pady=8,
            insertbackground="#58a6ff"
        )
        self.chat_history.pack(fill="both", expand=True, padx=8, pady=(8, 6))

        # Теги стилей сообщений чата
        self.chat_history.tag_configure("user_pill", foreground="#58a6ff", font=("Consolas", 8, "bold"))
        self.chat_history.tag_configure("akakiy_pill", foreground="#3fb950", font=("Consolas", 8, "bold"))
        self.chat_history.tag_configure("system_pill", foreground="#8b949e", font=("Consolas", 8, "bold"))
        self.chat_history.tag_configure("timestamp", foreground="#484f58", font=("Consolas", 8))
        self.chat_history.tag_configure("user_msg", foreground="#f0f6fc", font=("Segoe UI", 10))
        self.chat_history.tag_configure("akakiy_msg", foreground="#e6edf3", font=("Segoe UI", 10))
        self.chat_history.tag_configure("system_msg", foreground="#8b949e", font=("Segoe UI", 9, "italic"))
        self.chat_history.tag_configure("heading2", foreground="#58a6ff", font=("Segoe UI", 10, "bold"))
        self.chat_history.tag_configure("heading3", foreground="#d2a8ff", font=("Segoe UI", 9, "bold"))
        self.chat_history.tag_configure("bullet", foreground="#7ee787", font=("Segoe UI", 9))
        self.chat_history.tag_configure("code_inline", foreground="#79c0ff", font=("Consolas", 9), background="#161b22")
        self.chat_history.tag_configure("divider", foreground="#21262d", font=("Consolas", 8))
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
                activeforeground="#58a6ff",
                bd=1,
                relief="solid",
                padx=10, pady=3,
                cursor="hand2",
                command=lambda c=cmd: self._on_quick_command(c)
            )
            btn.pack(side="left", padx=(0, 6))
            _bind_hover(btn, "#21262d", "#30363d", normal_fg="#c9d1d9", hover_fg="#58a6ff")

        # Переключатель голосового режима
        self.voice_mode_btn = tk.Button(
            quick_bar,
            text="🎙 Голос: ВЫКЛ",
            font=("Segoe UI", 8, "bold"),
            fg="#8b949e",
            bg="#21262d",
            activebackground="#30363d",
            activeforeground="#58a6ff",
            bd=1,
            relief="solid",
            padx=12, pady=3,
            cursor="hand2",
            command=self._on_toggle_voice_mode
        )
        self.voice_mode_btn.pack(side="right")
        _bind_hover(self.voice_mode_btn, "#21262d", "#30363d", normal_fg="#8b949e", hover_fg="#58a6ff")

        # Поле ввода и кнопка отправки
        input_frame = tk.Frame(chat_container, bg="#161b22")
        input_frame.pack(fill="x", padx=8, pady=(0, 4))

        self.input_entry = tk.Entry(
            input_frame,
            font=("Segoe UI", 10),
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
            font=("Segoe UI", 9, "bold"),
            fg="#ffffff",
            bg="#238636",
            activebackground="#2ea043",
            activeforeground="#ffffff",
            bd=0,
            padx=14, pady=6,
            cursor="hand2",
            command=self._on_send
        )
        self.send_btn.pack(side="right")
        _bind_hover(self.send_btn, "#238636", "#2ea043")

        self.voice_btn = tk.Button(
            input_frame,
            text="🎙 Запись",
            font=("Segoe UI", 9, "bold"),
            fg="#484f58",
            bg="#1c2128",
            activebackground="#1f6feb",
            activeforeground="#ffffff",
            bd=1,
            relief="solid",
            padx=12, pady=6,
            cursor="arrow",
            state="disabled",
            command=self._on_voice_toggle
        )
        self.voice_btn.pack(side="right", padx=(0, 6))
        _bind_hover(self.voice_btn, "#21262d", "#30363d", normal_fg="#58a6ff", hover_fg="#79c0ff")

        # Подстрочный хинт
        hint_label = tk.Label(
            chat_container,
            text="[Enter] отправить сообщение  •  [🎙 Голос: ВЫКЛ/ВКЛ] переключатель режима  •  быстрые команды: статус, помощь, список файлов",
            font=("Segoe UI", 7),
            fg="#484f58",
            bg="#161b22"
        )
        hint_label.pack(anchor="w", padx=10, pady=(0, 6))

        # ----------------- ПРАВАЯ ПАНЕЛЬ: ПРОЦЕСС И РЕЗУЛЬТАТ --------
        side_container = tk.Frame(main_paned, bg="#161b22", bd=0)
        main_paned.add(side_container, minsize=420, stretch="always")

        # А. Область "Процесс" (верхняя часть правой панели)
        proc_header = tk.Frame(side_container, bg="#1c2128", height=32)
        proc_header.pack(fill="x")
        tk.Label(
            proc_header,
            text="⚙️ ТЕЛЕМЕТРИЯ // ПРОЦЕСС",
            font=("Segoe UI", 9, "bold"),
            fg="#d2a8ff",
            bg="#1c2128",
            padx=12, pady=7
        ).pack(side="left")

        self.proc_text = scrolledtext.ScrolledText(
            side_container,
            height=9,
            wrap="word",
            bg="#090d13",
            fg="#8b949e",
            font=("Consolas", 8),
            bd=0,
            padx=8, pady=6
        )
        self.proc_text.pack(fill="both", expand=True, padx=8, pady=(8, 6))

        # Теги для лога процесса
        self.proc_text.tag_configure("log_time", foreground="#484f58")
        self.proc_text.tag_configure("log_info", foreground="#8b949e")
        self.proc_text.tag_configure("log_tool", foreground="#58a6ff", font=("Consolas", 8, "bold"))
        self.proc_text.tag_configure("log_done", foreground="#3fb950")
        self.proc_text.tag_configure("log_warn", foreground="#d29922", font=("Consolas", 8, "bold"))
        self.proc_text.tag_configure("log_err", foreground="#f85149", font=("Consolas", 8, "bold"))
        self.proc_text.tag_configure("log_body", foreground="#c9d1d9")

        # Б. Область "Подтверждение" (Confirmation Panel)
        self.confirm_frame = tk.LabelFrame(
            side_container,
            text=" ⚠️ ТРЕБУЕТСЯ ОДОБРЕНИЕ ДЕЙСТВИЯ ",
            font=("Segoe UI", 9, "bold"),
            fg="#d29922",
            bg="#1c2128",
            bd=1,
            relief="solid",
            padx=10, pady=8
        )
        # Панель скрыта до момента запроса
        self.confirm_detail_label = tk.Label(
            self.confirm_frame,
            text="Действие требует одобрения...",
            font=("Consolas", 8),
            fg="#f0f6fc",
            bg="#1c2128",
            justify="left",
            anchor="w"
        )
        self.confirm_detail_label.pack(fill="x", pady=(0, 8))

        confirm_btn_row = tk.Frame(self.confirm_frame, bg="#1c2128")
        confirm_btn_row.pack(fill="x")

        self.btn_confirm_yes = tk.Button(
            confirm_btn_row,
            text="✓ Разрешить (Да)",
            font=("Segoe UI", 9, "bold"),
            fg="#ffffff",
            bg="#238636",
            activebackground="#2ea043",
            bd=0,
            padx=18, pady=5,
            cursor="hand2",
            command=lambda: self._resolve_confirmation(True)
        )
        self.btn_confirm_yes.pack(side="left", padx=(0, 10))
        _bind_hover(self.btn_confirm_yes, "#238636", "#2ea043")

        self.btn_confirm_no = tk.Button(
            confirm_btn_row,
            text="✗ Отклонить (Нет)",
            font=("Segoe UI", 9, "bold"),
            fg="#ffffff",
            bg="#da3633",
            activebackground="#f85149",
            bd=0,
            padx=18, pady=5,
            cursor="hand2",
            command=lambda: self._resolve_confirmation(False)
        )
        self.btn_confirm_no.pack(side="left")
        _bind_hover(self.btn_confirm_no, "#da3633", "#f85149")

        # В. Область "Результат" (нижняя часть правой панели)
        res_header = tk.Frame(side_container, bg="#1c2128", height=32)
        res_header.pack(fill="x")
        tk.Label(
            res_header,
            text="📋 ФИНАЛЬНЫЙ РЕЗУЛЬТАТ // ОТЧЁТ",
            font=("Segoe UI", 9, "bold"),
            fg="#3fb950",
            bg="#1c2128",
            padx=12, pady=7
        ).pack(side="left")

        self.res_text = scrolledtext.ScrolledText(
            side_container,
            height=13,
            wrap="word",
            bg="#0d1117",
            fg="#f0f6fc",
            font=("Segoe UI", 9),
            bd=0,
            padx=8, pady=6
        )
        self.res_text.pack(fill="both", expand=True, padx=8, pady=(8, 8))

        # Теги для области результатов
        self.res_text.tag_configure("res_heading", foreground="#58a6ff", font=("Segoe UI", 10, "bold"))
        self.res_text.tag_configure("res_subheading", foreground="#d2a8ff", font=("Segoe UI", 9, "bold"))
        self.res_text.tag_configure("res_bullet", foreground="#7ee787", font=("Segoe UI", 9))
        self.res_text.tag_configure("res_success", foreground="#3fb950", font=("Segoe UI", 9, "bold"))
        self.res_text.tag_configure("res_error", foreground="#f85149", font=("Segoe UI", 9, "bold"))
        self.res_text.tag_configure("res_body", foreground="#f0f6fc")

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
            if hasattr(self, "voice_btn"):
                if getattr(self, "voice_enabled", False):
                    self.voice_btn.config(text="🎙 Запись", fg="#58a6ff", bg="#21262d", state="normal", cursor="hand2")
                else:
                    self.voice_btn.config(text="🎙 Запись", fg="#484f58", bg="#1c2128", state="disabled", cursor="arrow")
        elif state_name == "слушает":
            self.status_badge.config(text=" СЛУШАЕТ ", bg="#58a6ff", fg="#0d1117")
            self.cloud.set_state("listening")
            self.is_busy = True
            self.send_btn.config(state="disabled")
            if hasattr(self, "voice_btn"):
                self.voice_btn.config(text="⏹ Стоп", fg="#f85149", bg="#30363d", state="normal", cursor="hand2")
        elif state_name == "ответ":
            self.status_badge.config(text=" ОТВЕТ ", bg="#3fb950", fg="#0d1117")
            self.cloud.set_state("speaking")
            self.is_busy = True
            self.send_btn.config(state="disabled")
            if hasattr(self, "voice_btn"):
                self.voice_btn.config(text="⏹ Стоп", fg="#f85149", bg="#30363d", state="normal", cursor="hand2")
        elif state_name == "работает":
            self.status_badge.config(text=" РАБОТАЕТ ", bg="#58a6ff", fg="#0d1117")
            self.cloud.set_state("working")
            self.is_busy = True
            self.send_btn.config(state="disabled")
            if hasattr(self, "voice_btn"):
                self.voice_btn.config(text="🎙 Запись", fg="#8b949e", bg="#21262d", state="disabled", cursor="arrow")
        elif state_name == "ожидание":
            self.status_badge.config(text=" ОЖИДАНИЕ ПОДТВЕРЖДЕНИЯ ", bg="#d29922", fg="#0d1117")
            self.cloud.set_state("waiting")
        elif state_name == "ошибка":
            self.status_badge.config(text=" ОШИБКА ", bg="#f85149", fg="#ffffff")
            self.cloud.set_state("error")
            self.is_busy = False
            self.send_btn.config(state="normal")
            if hasattr(self, "voice_btn"):
                if getattr(self, "voice_enabled", False):
                    self.voice_btn.config(text="🎙 Запись", fg="#58a6ff", bg="#21262d", state="normal", cursor="hand2")
                else:
                    self.voice_btn.config(text="🎙 Запись", fg="#484f58", bg="#1c2128", state="disabled", cursor="arrow")

    def _append_chat(self, author, text, tag="body"):
        t_str = time.strftime("%H:%M:%S")
        self.chat_history.insert(tk.END, "\n")

        if author in ("Ты", "User"):
            self.chat_history.insert(tk.END, "● ВЫ  ", "user_pill")
            self.chat_history.insert(tk.END, f"{t_str}\n", "timestamp")
            msg_tag = "user_msg"
        elif author in ("Акакий", "Akakiy"):
            self.chat_history.insert(tk.END, "● АКАКИЙ  ", "akakiy_pill")
            self.chat_history.insert(tk.END, f"{t_str}\n", "timestamp")
            msg_tag = "akakiy_msg"
        else:
            self.chat_history.insert(tk.END, f"● {author.upper()}  ", "system_pill")
            self.chat_history.insert(tk.END, f"{t_str}\n", "timestamp")
            msg_tag = "system_msg" if tag != "error" else "error"

        # Структурированный вывод строк с подсветкой элементов markdown
        for line in text.strip().splitlines():
            s_line = line.strip()
            if s_line.startswith("## "):
                self.chat_history.insert(tk.END, f"  {s_line}\n", "heading2")
            elif s_line.startswith("### "):
                self.chat_history.insert(tk.END, f"  {s_line}\n", "heading3")
            elif s_line.startswith(("- ", "• ", "* ")):
                self.chat_history.insert(tk.END, f"    {s_line}\n", "bullet")
            elif s_line.startswith("`") and s_line.endswith("`"):
                self.chat_history.insert(tk.END, f"    {s_line}\n", "code_inline")
            else:
                self.chat_history.insert(tk.END, f"  {line}\n", msg_tag)

        self.chat_history.insert(tk.END, "\n" + "─" * 46 + "\n", "divider")
        self.chat_history.see(tk.END)

    def _log_process(self, message):
        t_str = time.strftime("%H:%M:%S")
        prefix = "[INFO]"
        tag = "log_info"
        low = message.lower()
        if "сбой" in low or "ошибка" in low or "отклонил" in low:
            prefix = "[ERR ]"
            tag = "log_err"
        elif "требуется" in low or "подтверждение" in low:
            prefix = "[WARN]"
            tag = "log_warn"
        elif "завершён" in low or "успешно" in low or "выполнен" in low:
            prefix = "[DONE]"
            tag = "log_done"
        elif "запуск" in low or "инструмент" in low:
            prefix = "[TOOL]"
            tag = "log_tool"
        else:
            prefix = "[INFO]"
            tag = "log_info"

        self.proc_text.insert(tk.END, f"[{t_str}] ", "log_time")
        self.proc_text.insert(tk.END, f"{prefix} ", tag)
        self.proc_text.insert(tk.END, f"{message}\n", "log_body")
        self.proc_text.see(tk.END)

    def _set_result(self, text):
        self.res_text.delete("1.0", tk.END)
        for line in text.strip().splitlines():
            s_line = line.strip()
            if s_line.startswith("## "):
                self.res_text.insert(tk.END, f"{s_line}\n", "res_heading")
            elif s_line.startswith("### "):
                self.res_text.insert(tk.END, f"{s_line}\n", "res_subheading")
            elif s_line.startswith(("- ", "• ", "* ")):
                self.res_text.insert(tk.END, f"  {s_line}\n", "res_bullet")
            elif s_line.startswith("✓") or "успешно" in s_line.lower():
                self.res_text.insert(tk.END, f"{line}\n", "res_success")
            elif s_line.startswith("✗") or "ошибка" in s_line.lower():
                self.res_text.insert(tk.END, f"{line}\n", "res_error")
            else:
                self.res_text.insert(tk.END, f"{line}\n", "res_body")
        self.res_text.see("1.0")

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

    def _on_toggle_voice_mode(self):
        """Переключатель глобального режима (Голос: ВЫКЛ / Голос: ВКЛ)."""
        if getattr(self, "voice_enabled", False):
            # Выключаем
            self.voice_enabled = False
            if hasattr(self, "voice_mode_btn"):
                self.voice_mode_btn.config(text="🎙 Голос: ВЫКЛ", fg="#8b949e", bg="#21262d")
            if hasattr(self, "voice_chip"):
                self.voice_chip.config(text="ГОЛОС: ВЫКЛ", fg="#8b949e")

            # 1. Остановить активный сеанс и TTS
            was_voice_busy = False
            if hasattr(self, "voice") and self.voice:
                try:
                    was_voice_busy = self.voice.is_busy()
                    self.voice.stop_session()
                    self.voice.tts.stop()
                except Exception:
                    pass

            # 2. Если выполнялся голосовой сеанс — вернуть ядро в idle и статус в готов
            if was_voice_busy:
                self.cloud.set_state("idle")
                self.cloud.set_audio_level(0.0)
                self.set_gui_state("готов")

            # 3. Деактивировать кнопку ввода
            if hasattr(self, "voice_btn"):
                self.voice_btn.config(text="🎙 Запись", state="disabled", fg="#484f58", bg="#1c2128", cursor="arrow")

            self._log_process("Голосовой режим отключён (Голос: ВЫКЛ).")
        else:
            # Включаем
            self.voice_enabled = True
            if hasattr(self, "voice_mode_btn"):
                self.voice_mode_btn.config(text="🎙 Голос: ВКЛ", fg="#ffffff", bg="#1f6feb")
            if hasattr(self, "voice_chip"):
                self.voice_chip.config(text="ГОЛОС: ВКЛ", fg="#3fb950")

            if hasattr(self, "voice_btn"):
                self.voice_btn.config(text="🎙 Запись", state="normal", fg="#58a6ff", bg="#21262d", cursor="hand2")

            self._log_process("Голосовой режим включён (Голос: ВКЛ). Нажмите '🎙 Запись' для ввода.")

    def _on_voice_toggle(self):
        if not hasattr(self, "voice") or self.voice is None:
            self._log_process("Голосовой модуль недоступен.")
            return

        if not getattr(self, "voice_enabled", False):
            self._log_process("Голосовой режим выключен. Нажмите '🎙 Голос: ВЫКЛ' для активации.")
            return

        if self.voice.is_busy():
            self.voice.stop_session()
            self._log_process("Голосовой сеанс остановлен пользователем.")
        else:
            if self.is_busy:
                self._log_process("Акакий занят выполнением другой задачи.")
                return
            started = self.voice.start_session()
            if started:
                self._log_process("Голосовой сеанс начат. Говорите в микрофон...")
            else:
                self._log_process("Не удалось запустить голосовой сеанс.")

    def _on_voice_event(self, event_type: str, data: dict):
        """Пересылает события от VoiceService в очередь GUI."""
        if not getattr(self, "voice_enabled", False):
            return
        self.queue.put((event_type, data))

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

                elif msg_type.startswith("voice_"):
                    if not getattr(self, "voice_enabled", False):
                        continue

                    if msg_type == "voice_audio_level":
                        level = payload.get("level", 0.0) if isinstance(payload, dict) else 0.0
                        self.cloud.set_audio_level(level)

                    elif msg_type == "voice_state":
                        v_state = payload.get("state") if isinstance(payload, dict) else payload
                        if v_state == "listening":
                            self.set_gui_state("слушает")
                        elif v_state == "thinking":
                            self.set_gui_state("работает")
                        elif v_state == "speaking":
                            self.set_gui_state("ответ")
                        elif v_state == "idle":
                            self.set_gui_state("готов")
                        elif v_state == "error":
                            self.set_gui_state("ошибка")

                    elif msg_type == "voice_recognized":
                        text = payload.get("text", "") if isinstance(payload, dict) else str(payload)
                        if text:
                            self._append_chat("Ты (голос)", text, tag="user")
                            self._log_process(f"Распознано: {text}")

                    elif msg_type == "voice_agent_result":
                        res_payload = payload.get("payload") if isinstance(payload, dict) else payload
                        if res_payload:
                            self._handle_task_success(res_payload)

                    elif msg_type == "voice_error":
                        err_msg = payload.get("message", "Сбой голосового сеанса") if isinstance(payload, dict) else str(payload)
                        self._log_process(f"Голосовой сбой: {err_msg}")

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
        if hasattr(self, "voice") and self.voice:
            try:
                self.voice.shutdown()
            except Exception:
                pass
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
