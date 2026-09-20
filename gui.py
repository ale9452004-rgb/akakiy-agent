"""
Акакий 2.0 // Futuristic Desktop Hub (GUI 2.0).

Главный интерфейс локального ИИ-ассистента:
1. Главный дизайн-канвас: 1920x1280 (адаптивный, minsize 1280x800).
2. Архитектура:
   - Topbar: 80px (брендинг, часы, системные индикаторы, переключатель голоса);
   - Sidebar: 280px (Главная, Чат, Задачи, Напоминания, Заметки, Списки, Память, Настройки);
   - Main Workspace: 8 специализированных экранов;
   - Command Bar: 96px (поле «✦ Что сделать?», микрофон, отправка в Agent).
3. Neural Core (ui/neural_core.py): 3D процедурная нейросфера с 6 состояниями.
4. Прямой доступ к Household & Memory бэкенду для мгновенного отклика без LLM.
5. Интеграция с Native Tool Calling, Confirmation Dialog и VoiceService.
"""

from datetime import datetime
import math
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(r"c:\Akakiy agent")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.agent import Agent
from tools.dispatcher import (
    get_confirmation_details_text,
    set_action_observer,
    set_confirmation_handler
)
from tools.household import get_household_manager
from tools.memory import get_memory_manager
from tools.validation import validate_project
from ui.neural_core import NeuralCore
from ui.cloud import AkakiyCloud
from voice import VoiceService, GlobalHotKeyManager
from notifications import NotificationService, ReminderMonitor


from ui.views import (
    BaseView,
    _bind_hover,
    HomeView,
    ChatView,
    TasksView,
    RemindersView,
    NotesView,
    ListsView,
    MemoryView,
    SettingsView
)


class AkakiyGUI:
    """
    Полноэкранный Desktop Hub Акакия 2.0.
    """

    BG_MAIN = "#090d13"
    BG_PANEL = "#161b22"
    BG_CARD = "#1b212a"
    BG_HOVER = "#21262d"
    BG_ACTIVE = "#28303d"
    BORDER_COL = "#30363d"
    BORDER_LIGHT = "#38414e"

    FG_WHITE = "#f0f6fc"
    FG_MAIN = "#c9d1d9"
    FG_MUTED = "#8b949e"
    FG_DIM = "#484f58"

    ACCENT_BLUE = "#58a6ff"
    ACCENT_CYAN = "#38bdf8"
    ACCENT_PURPLE = "#a371f7"
    ACCENT_GREEN = "#3fb950"
    ACCENT_AMBER = "#e3b341"
    ACCENT_RED = "#f85149"

    def __init__(self, root: tk.Tk, agent: Agent = None, household = None, memory = None, voice = None):
        self.root = root
        self.root.title("АКAKИЙ 2.0 // NEURAL HUB")

        # 1. Полноэкранный канвас 1920x1280 (или адаптация к монитору)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        target_w = min(1920, max(1280, screen_w - 40))
        target_h = min(1280, max(800, screen_h - 60))
        self.root.geometry(f"{target_w}x{target_h}+20+10")
        self.root.minsize(1240, 780)
        self.root.configure(bg=self.BG_MAIN)

        # 2. Инициализация логики и бэкенда (с поддержкой dependency injection)
        self.agent = agent if agent is not None else Agent()
        self.household = household if household is not None else get_household_manager()
        self.memory = memory if memory is not None else get_memory_manager()
        self.household_mgr = self.household
        self.memory_mgr = self.memory
        self.queue = queue.Queue()
        self.confirm_event = threading.Event()
        self.confirm_result = False
        self.is_busy = False
        self.voice_enabled = False
        self.current_section = "home"
        self.current_selected_list = ""
        self.current_state = "idle"
        self.home_view = None
        self.chat_view = None
        self.tasks_view = None
        self.reminders_view = None
        self.notes_view = None
        self.lists_view = None
        self.memory_view = None
        self.settings_view = None
        self.chat_text = None
        self.log_text = None
        self.entry_task = None
        self.entry_rem_text = None
        self.entry_rem_time = None
        self.entry_note_search = None
        self.entry_note_title = None
        self.entry_note_content = None
        self.entry_new_list = None
        self._entry_item_text = None
        self.entry_mem = None
        self.lbl_val_res = None
        self.tasks_list_frame = None
        self.rems_list_frame = None
        self.notes_list_frame = None
        self.list_names_box = None
        self.list_items_box = None
        self.mem_list_frame = None
        self.chat_messages: List[Tuple[str, str, str]] = []  # [(author, message, time_str)]
        self.log_messages: List[Tuple[str, str, str]] = []   # [(prefix, text, time_str)]
        self._is_closing = False

        # Голосовой сервис
        if voice is not None:
            self.voice = voice
        else:
            try:
                self.voice = VoiceService(agent=self.agent, event_sink=self._on_voice_event)
            except Exception:
                self.voice = None

        # Регистрация обработчиков подтверждения и наблюдателя
        set_confirmation_handler(self._on_confirmation_requested)
        set_action_observer(self._on_action_observed)

        # Модульная система уведомлений и мониторинга напоминаний
        self.notification_service = NotificationService(master=self.root)
        if self.household is not None:
            self.reminder_monitor = ReminderMonitor(
                household=self.household,
                on_reminder=self._on_reminder_due,
                interval_sec=5.0
            )
            self.reminder_monitor.start()
        else:
            self.reminder_monitor = None

        # Глобальный хоткей Push-to-Talk (Ctrl+Shift+Space)
        self.hotkey_manager = None
        if sys.platform == "win32" and self.voice is not None:
            try:
                self.hotkey_manager = GlobalHotKeyManager(
                    on_press=self._on_hotkey_press,
                    on_release=self._on_hotkey_release
                )
                self.hotkey_manager.start()
            except Exception:
                self.hotkey_manager = None

        # 3. Построение UI
        self._create_layout()
        self._start_clock()
        self._poll_queue()

        # Первичная загрузка главного экрана
        self._switch_section("home")

        # Обработка чистого закрытия окна
        try:
            self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        except Exception:
            pass

    @property
    def current_view_name(self) -> str:
        return self.current_section

    def switch_view(self, code: str):
        self._switch_section(code)

    def switch_section(self, code: str):
        self._switch_section(code)

    def destroy(self):
        self._on_window_close()

    def _on_window_close(self):
        self._is_closing = True
        try:
            if hasattr(self, "reminder_monitor") and self.reminder_monitor:
                self.reminder_monitor.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "hotkey_manager") and self.hotkey_manager:
                self.hotkey_manager.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "notification_service") and self.notification_service:
                self.notification_service.close_all()
        except Exception:
            pass
        try:
            if hasattr(self, "neural_core") and self.neural_core:
                self.neural_core.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "voice") and self.voice and getattr(self.voice, "is_running", False):
                self.voice.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    # =========================================================================
    # Структура UI (Topbar, Sidebar, Workspace, Command Bar)
    # =========================================================================

    def _create_layout(self):
        # -------------------------------------------------------------
        # 1. Topbar (80px)
        # -------------------------------------------------------------
        self.topbar = tk.Frame(self.root, bg=self.BG_PANEL, height=80, bd=0)
        self.topbar.pack(side="top", fill="x", padx=0, pady=0)
        self.topbar.pack_propagate(False)

        self._build_topbar_content()

        # Разделитель под Topbar
        tk.Frame(self.root, bg=self.BORDER_COL, height=1).pack(side="top", fill="x")

        # -------------------------------------------------------------
        # 2. Command Bar (96px) - внизу экрана
        # -------------------------------------------------------------
        tk.Frame(self.root, bg=self.BORDER_COL, height=1).pack(side="bottom", fill="x")

        self.cmd_bar = tk.Frame(self.root, bg=self.BG_PANEL, height=96, bd=0)
        self.cmd_bar.pack(side="bottom", fill="x", padx=0, pady=0)
        self.cmd_bar.pack_propagate(False)

        self._build_command_bar_content()

        # -------------------------------------------------------------
        # 3. Центральное тело: Sidebar (280px) + Main Workspace
        # -------------------------------------------------------------
        self.center_body = tk.Frame(self.root, bg=self.BG_MAIN)
        self.center_body.pack(side="top", fill="both", expand=True)

        # Sidebar (280px)
        self.sidebar = tk.Frame(self.center_body, bg=self.BG_PANEL, width=280)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self._build_sidebar_content()

        # Вертикальный разделитель
        tk.Frame(self.center_body, bg=self.BORDER_COL, width=1).pack(side="left", fill="y")

        # Main Workspace Container
        self.workspace = tk.Frame(self.center_body, bg=self.BG_MAIN)
        self.workspace.pack(side="left", fill="both", expand=True, padx=20, pady=20)
        self.main_workspace = self.workspace
        self.command_bar = self.cmd_bar

    # =========================================================================
    # 1. Topbar (80px)
    # =========================================================================

    def _build_topbar_content(self):
        # Левая колонка: Логотип и статус
        left_box = tk.Frame(self.topbar, bg=self.BG_PANEL)
        left_box.pack(side="left", padx=24, pady=14)

        logo_row = tk.Frame(left_box, bg=self.BG_PANEL)
        logo_row.pack(anchor="w")

        tk.Label(
            logo_row,
            text="АКAKИЙ 2.0",
            font=("Segoe UI", 16, "bold"),
            fg=self.ACCENT_CYAN,
            bg=self.BG_PANEL
        ).pack(side="left")

        tk.Label(
            logo_row,
            text=" // NEURAL DESKTOP HUB",
            font=("Segoe UI", 13, "bold"),
            fg=self.FG_MUTED,
            bg=self.BG_PANEL
        ).pack(side="left")

        status_row = tk.Frame(left_box, bg=self.BG_PANEL)
        status_row.pack(anchor="w", pady=(3, 0))

        self.status_badge = tk.Label(
            status_row,
            text="✓ ГОТОВ",
            font=("Segoe UI", 9, "bold"),
            fg=self.ACCENT_BLUE,
            bg="#111c2e",
            padx=10, pady=2,
            bd=1, relief="solid"
        )
        self.status_badge.pack(side="left")

        # Правая колонка: Часы, Дата и Индикаторы
        right_box = tk.Frame(self.topbar, bg=self.BG_PANEL)
        right_box.pack(side="right", padx=24, pady=14)

        # Индикаторы сервисов
        chips_box = tk.Frame(right_box, bg=self.BG_PANEL)
        chips_box.pack(side="left", padx=(0, 24))

        self.chip_ollama = tk.Label(
            chips_box,
            text="QWEN3:8B ●",
            font=("Consolas", 8, "bold"),
            fg=self.ACCENT_GREEN,
            bg="#112d1b",
            padx=8, pady=3,
            bd=1, relief="solid"
        )
        self.chip_ollama.pack(side="left", padx=4)

        self.chip_voice = tk.Label(
            chips_box,
            text="ГОЛОС: ВЫКЛ",
            font=("Consolas", 8, "bold"),
            fg=self.FG_MUTED,
            bg="#1c2128",
            padx=8, pady=3,
            bd=1, relief="solid"
        )
        self.chip_voice.pack(side="left", padx=4)

        # Часы
        clock_box = tk.Frame(right_box, bg=self.BG_PANEL)
        clock_box.pack(side="right")

        self.lbl_time = tk.Label(
            clock_box,
            text="00:00:00",
            font=("Segoe UI", 16, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_PANEL
        )
        self.lbl_time.pack(anchor="e")

        self.lbl_date = tk.Label(
            clock_box,
            text="Понедельник, 1 января 2026",
            font=("Segoe UI", 9),
            fg=self.FG_MUTED,
            bg=self.BG_PANEL
        )
        self.lbl_date.pack(anchor="e")

    def _start_clock(self):
        def update():
            now = datetime.now()
            self.lbl_time.config(text=now.strftime("%H:%M:%S"))
            # Русские дни недели
            days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
            months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
            d_name = days[now.weekday()]
            m_name = months[now.month - 1]
            self.lbl_date.config(text=f"{d_name}, {now.day} {m_name} {now.year}")
            if not getattr(self, "_is_closing", False):
                try:
                    self.root.after(1000, update)
                except Exception:
                    pass
        update()

    # =========================================================================
    # 2. Sidebar (280px)
    # =========================================================================

    def _build_sidebar_content(self):
        nav_header = tk.Frame(self.sidebar, bg=self.BG_PANEL)
        nav_header.pack(fill="x", padx=16, pady=(18, 10))

        tk.Label(
            nav_header,
            text="РАБОЧЕЕ ПРОСТРАНСТВО",
            font=("Segoe UI", 8, "bold"),
            fg=self.FG_MUTED,
            bg=self.BG_PANEL
        ).pack(anchor="w")

        self.nav_buttons = {}
        items = [
            ("home", "⌂  Главная"),
            ("chat", "💬  Чат и Ассистент"),
            ("tasks", "✓  Задачи"),
            ("reminders", "🔔  Напоминания"),
            ("notes", "📝  Заметки"),
            ("lists", "📋  Списки"),
            ("memory", "🧠  Память"),
            ("settings", "⚙  Настройки"),
        ]

        for code, label in items:
            btn = tk.Button(
                self.sidebar,
                text=label,
                font=("Segoe UI", 11),
                fg=self.FG_MAIN,
                bg=self.BG_PANEL,
                activeforeground=self.FG_WHITE,
                activebackground=self.BG_ACTIVE,
                anchor="w",
                padx=20, pady=10,
                bd=0,
                cursor="hand2",
                command=lambda c=code: self._switch_section(c)
            )
            btn.pack(fill="x", padx=8, pady=2)
            _bind_hover(btn, self.BG_PANEL, self.BG_HOVER, self.FG_MAIN, self.FG_WHITE)
            self.nav_buttons[code] = btn

        # Нижний информационный виджет Sidebar
        sidebar_footer = tk.Frame(self.sidebar, bg="#11161d", bd=1, relief="solid")
        sidebar_footer.pack(side="bottom", fill="x", padx=12, pady=16)

        tk.Label(
            sidebar_footer,
            text="АКAKИЙ CORE ENGINE",
            font=("Consolas", 8, "bold"),
            fg=self.ACCENT_CYAN,
            bg="#11161d"
        ).pack(anchor="w", padx=10, pady=(8, 2))

        tk.Label(
            sidebar_footer,
            text="Skills: project • memory • household\nNative Tool Calling: Active",
            font=("Segoe UI", 8),
            fg=self.FG_MUTED,
            bg="#11161d",
            justify="left"
        ).pack(anchor="w", padx=10, pady=(0, 8))

    # =========================================================================
    # 3. Command Bar (96px)
    # =========================================================================

    def _build_command_bar_content(self):
        box = tk.Frame(self.cmd_bar, bg=self.BG_PANEL)
        box.pack(fill="both", expand=True, padx=24, pady=14)

        # Контейнер для поля ввода
        input_wrap = tk.Frame(box, bg="#1f242c", bd=1, relief="solid")
        input_wrap.pack(side="left", fill="both", expand=True, padx=(0, 14))

        tk.Label(
            input_wrap,
            text="✦",
            font=("Segoe UI", 13),
            fg=self.ACCENT_CYAN,
            bg="#1f242c"
        ).pack(side="left", padx=(14, 6))

        self.cmd_input = tk.Entry(
            input_wrap,
            font=("Segoe UI", 12),
            bg="#1f242c",
            fg=self.FG_WHITE,
            insertbackground=self.ACCENT_CYAN,
            bd=0
        )
        self.cmd_input.pack(side="left", fill="both", expand=True, pady=8)
        self.cmd_input.bind("<Return>", lambda e: self._on_send_command())

        # Placeholder
        self.cmd_placeholder = "Что сделать? (например: 'добавь задачу купить молоко', 'найди заметку рецепт', 'покажи файлы')..."
        self.cmd_input.insert(0, self.cmd_placeholder)
        self.cmd_input.config(fg=self.FG_MUTED)

        def on_focus_in(e):
            if self.cmd_input.get() == self.cmd_placeholder:
                self.cmd_input.delete(0, tk.END)
                self.cmd_input.config(fg=self.FG_WHITE)

        def on_focus_out(e):
            if not self.cmd_input.get().strip():
                self.cmd_input.insert(0, self.cmd_placeholder)
                self.cmd_input.config(fg=self.FG_MUTED)

        self.cmd_input.bind("<FocusIn>", on_focus_in)
        self.cmd_input.bind("<FocusOut>", on_focus_out)

        # Кнопка голосового режима
        self.btn_mic = tk.Button(
            box,
            text="🎙 Голос",
            font=("Segoe UI", 10, "bold"),
            fg=self.FG_WHITE,
            bg="#21262d",
            activeforeground=self.FG_WHITE,
            activebackground=self.ACCENT_BLUE,
            bd=1, relief="solid",
            padx=16, pady=8,
            cursor="hand2",
            command=self._on_toggle_voice
        )
        self.btn_mic.pack(side="left", padx=(0, 10))
        _bind_hover(self.btn_mic, "#21262d", "#30363d", self.FG_WHITE, self.FG_WHITE)

        # Кнопка отправки команды
        self.btn_send = tk.Button(
            box,
            text="Выполнить ➔",
            font=("Segoe UI", 10, "bold"),
            fg="#0d1117",
            bg=self.ACCENT_CYAN,
            activeforeground="#0d1117",
            activebackground="#7dd3fc",
            bd=0,
            padx=20, pady=8,
            cursor="hand2",
            command=self._on_send_command
        )
        self.btn_send.pack(side="left")
        _bind_hover(self.btn_send, self.ACCENT_CYAN, "#7dd3fc", "#0d1117", "#0d1117")

    # =========================================================================
    # Навигация и переключение экранов
    # =========================================================================

    def _switch_section(self, code: str):
        self.current_section = code

        # Обновление подсветки кнопок в Sidebar
        for c, btn in self.nav_buttons.items():
            if c == code:
                btn.config(bg=self.BG_ACTIVE, fg=self.ACCENT_CYAN, font=("Segoe UI", 11, "bold"))
            else:
                btn.config(bg=self.BG_PANEL, fg=self.FG_MAIN, font=("Segoe UI", 11))

        # Очистка рабочего пространства
        for child in self.workspace.winfo_children():
            child.destroy()

        # Построение выбранного экрана
        if code == "home":
            self._render_home_view()
        elif code == "chat":
            self._render_chat_view()
        elif code == "tasks":
            self._render_tasks_view()
        elif code == "reminders":
            self._render_reminders_view()
        elif code == "notes":
            self._render_notes_view()
        elif code == "lists":
            self._render_lists_view()
        elif code == "memory":
            self._render_memory_view()
        elif code == "settings":
            self._render_settings_view()

    # =========================================================================
    # ЭКРАН 1: ГЛАВНАЯ (DASHBOARD HUB)
    # =========================================================================

    def _render_home_view(self):
        self.home_view = HomeView(self.workspace, shell=self)
        self.home_view.pack(fill="both", expand=True)
        if hasattr(self.home_view, "neural_core") and self.home_view.neural_core:
            self.neural_core = self.home_view.neural_core

    def _quick_complete_task(self, task_id: int):
        if hasattr(self, "home_view") and self.home_view:
            return self.home_view.quick_complete_task(task_id)
        elif self.household:
            self.household.complete_task(task_id)

    # =========================================================================
    # ЭКРАН 2: ЧАТ И АССИСТЕНТ
    # =========================================================================

    def _render_chat_view(self):
        self.chat_view = ChatView(self.workspace, shell=self)
        self.chat_view.pack(fill="both", expand=True)
        self.chat_text = self.chat_view.chat_text
        self.log_text = self.chat_view.log_text

    def _insert_chat_ui(self, author: str, message: str, t_str: str):
        if hasattr(self, "chat_view") and self.chat_view:
            return self.chat_view.insert_chat_ui(author, message, t_str)
        elif hasattr(self, "chat_text") and self.chat_text and self.chat_text.winfo_exists():
            self.chat_text.insert(tk.END, "\n")
            author_upper = author.upper()
            if "ВЫ" in author_upper:
                self.chat_text.insert(tk.END, f"● {author_upper}  ", "user_title")
                self.chat_text.insert(tk.END, f"[{t_str}]\n", "time")
                self.chat_text.insert(tk.END, f"{message}\n", "user_body")
            else:
                self.chat_text.insert(tk.END, f"● {author_upper}  ", "akakiy_title")
                self.chat_text.insert(tk.END, f"[{t_str}]\n", "time")
                self.chat_text.insert(tk.END, f"{message}\n", "akakiy_body")
            self.chat_text.insert(tk.END, "─" * 48 + "\n", "div")
            self.chat_text.see(tk.END)

    def _append_chat(self, author: str, message: str):
        t_str = time.strftime("%H:%M:%S")
        self.chat_messages.append((author, message, t_str))
        self._insert_chat_ui(author, message, t_str)

    def _insert_log_ui(self, prefix: str, text: str, t_str: str):
        if hasattr(self, "chat_view") and self.chat_view:
            return self.chat_view.insert_log_ui(prefix, text, t_str)
        elif hasattr(self, "log_text") and self.log_text and self.log_text.winfo_exists():
            tag = "info"
            if prefix == "TOOL":
                tag = "tool"
            elif prefix in ("DONE", "OK"):
                tag = "done"
            elif prefix in ("ERR", "FAIL"):
                tag = "err"
            self.log_text.insert(tk.END, f"[{t_str}] [{prefix}] {text}\n", tag)
            self.log_text.see(tk.END)

    def _append_log(self, prefix: str, text: str):
        t_str = time.strftime("%H:%M:%S")
        self.log_messages.append((prefix, text, t_str))
        self._insert_log_ui(prefix, text, t_str)

    def _clear_chat(self):
        self.chat_messages.clear()
        self.log_messages.clear()
        if hasattr(self, "chat_view") and self.chat_view:
            self.chat_view.clear_chat()
        elif hasattr(self, "chat_text") and self.chat_text and self.chat_text.winfo_exists():
            self.chat_text.delete("1.0", tk.END)
        if hasattr(self, "log_text") and self.log_text and self.log_text.winfo_exists():
            self.log_text.delete("1.0", tk.END)
        if hasattr(self.agent, "context_mgr") and hasattr(self.agent.context_mgr, "clear_history"):
            self.agent.context_mgr.clear_history()

    # =========================================================================
    # ЭКРАН 3: ЗАДАЧИ (TASKS)
    # =========================================================================

    def _render_tasks_view(self):
        self.tasks_view = TasksView(self.workspace, shell=self)
        self.tasks_view.pack(fill="both", expand=True)
        self.entry_task = self.tasks_view.entry_task
        self.tasks_list_frame = self.tasks_view.tasks_list_frame

    def _ui_create_task(self):
        if hasattr(self, "tasks_view") and self.tasks_view:
            return self.tasks_view.ui_create_task()

    def _ui_toggle_task(self, task_id):
        if hasattr(self, "tasks_view") and self.tasks_view:
            return self.tasks_view.ui_toggle_task(task_id)

    def _ui_delete_task(self, task_id):
        if hasattr(self, "tasks_view") and self.tasks_view:
            return self.tasks_view.ui_delete_task(task_id)

    def _refresh_tasks_list(self):
        if hasattr(self, "tasks_view") and self.tasks_view:
            return self.tasks_view.refresh()

    # =========================================================================
    # ЭКРАН 4: НАПОМИНАНИЯ (REMINDERS)
    # =========================================================================

    def _render_reminders_view(self):
        self.reminders_view = RemindersView(self.workspace, shell=self)
        self.reminders_view.pack(fill="both", expand=True)
        self.entry_rem_text = self.reminders_view.entry_rem_text
        self.entry_rem_time = self.reminders_view.entry_rem_time
        self.rems_list_frame = self.reminders_view.rems_list_frame

    def _ui_create_reminder(self):
        if hasattr(self, "reminders_view") and self.reminders_view:
            return self.reminders_view.ui_create_reminder()

    def _ui_check_reminders(self):
        if hasattr(self, "reminders_view") and self.reminders_view:
            return self.reminders_view.ui_check_reminders()

    def _ui_delete_reminder(self, reminder_id):
        if hasattr(self, "reminders_view") and self.reminders_view:
            return self.reminders_view.ui_delete_reminder(reminder_id)

    def _refresh_reminders_list(self):
        if hasattr(self, "reminders_view") and self.reminders_view:
            return self.reminders_view.refresh()

    # =========================================================================
    # ЭКРАН 5: ЗАМЕТКИ (NOTES)
    # =========================================================================

    def _render_notes_view(self):
        self.notes_view = NotesView(self.workspace, shell=self)
        self.notes_view.pack(fill="both", expand=True)
        self.entry_note_search = self.notes_view.entry_note_search
        self.entry_note_title = self.notes_view.entry_note_title
        self.entry_note_content = self.notes_view.entry_note_content
        self.notes_list_frame = self.notes_view.notes_list_frame

    def _ui_create_note(self):
        if hasattr(self, "notes_view") and self.notes_view:
            return self.notes_view.ui_create_note()

    def _ui_delete_note(self, note_id):
        if hasattr(self, "notes_view") and self.notes_view:
            return self.notes_view.ui_delete_note(note_id)

    def _refresh_notes_list(self):
        if hasattr(self, "notes_view") and self.notes_view:
            return self.notes_view.refresh()

    # =========================================================================
    # ЭКРАН 6: СПИСКИ (LISTS)
    # =========================================================================

    def _render_lists_view(self):
        self.lists_view = ListsView(self.workspace, shell=self)
        self.lists_view.pack(fill="both", expand=True)
        self.entry_new_list = self.lists_view.entry_new_list
        self.list_names_box = self.lists_view.list_names_box
        self.list_items_box = self.lists_view.list_items_box
        self.current_selected_list = self.lists_view.current_selected_list

    @property
    def entry_item_text(self):
        if hasattr(self, "lists_view") and self.lists_view and hasattr(self.lists_view, "entry_item_text"):
            return self.lists_view.entry_item_text
        return getattr(self, "_entry_item_text", None)

    @entry_item_text.setter
    def entry_item_text(self, val):
        self._entry_item_text = val
        if hasattr(self, "lists_view") and self.lists_view:
            self.lists_view.entry_item_text = val

    def _refresh_lists_menu(self):
        if hasattr(self, "lists_view") and self.lists_view:
            return self.lists_view.refresh()

    def _select_list(self, name: str):
        if hasattr(self, "lists_view") and self.lists_view:
            res = self.lists_view.select_list(name)
            self.current_selected_list = self.lists_view.current_selected_list
            return res

    def _render_selected_list_items(self, list_name: str):
        if hasattr(self, "lists_view") and self.lists_view:
            res = self.lists_view.render_selected_list_items(list_name)
            self.current_selected_list = self.lists_view.current_selected_list
            return res

    def _ui_create_list(self):
        if hasattr(self, "lists_view") and self.lists_view:
            res = self.lists_view.ui_create_list()
            self.current_selected_list = self.lists_view.current_selected_list
            return res

    def _ui_add_item(self, list_name: str):
        if hasattr(self, "lists_view") and self.lists_view:
            return self.lists_view.ui_add_item(list_name)

    def _ui_toggle_item(self, list_name: str, item_id: int):
        if hasattr(self, "lists_view") and self.lists_view:
            return self.lists_view.ui_toggle_item(list_name, item_id)

    def _ui_delete_item(self, list_name: str, item_id: int):
        if hasattr(self, "lists_view") and self.lists_view:
            return self.lists_view.ui_delete_item(list_name, item_id)

    def _ui_delete_entire_list(self, list_name: str):
        if hasattr(self, "lists_view") and self.lists_view:
            res = self.lists_view.ui_delete_entire_list(list_name)
            self.current_selected_list = self.lists_view.current_selected_list
            return res

    # =========================================================================
    # ЭКРАН 7: ПАМЯТЬ (MEMORY)
    # =========================================================================

    def _render_memory_view(self):
        self.memory_view = MemoryView(self.workspace, shell=self)
        self.memory_view.pack(fill="both", expand=True)
        self.entry_mem = self.memory_view.entry_mem
        self.mem_list_frame = self.memory_view.mem_list_frame

    def _ui_remember(self):
        if hasattr(self, "memory_view") and self.memory_view:
            return self.memory_view.ui_remember()

    def _refresh_memory_list(self):
        if hasattr(self, "memory_view") and self.memory_view:
            return self.memory_view.refresh()

    def _ui_forget(self, mem_id):
        if hasattr(self, "memory_view") and self.memory_view:
            return self.memory_view.ui_forget(mem_id)

    # =========================================================================
    # ЭКРАН 8: НАСТРОЙКИ И ДИАГНОСТИКА (SETTINGS)
    # =========================================================================

    def _render_settings_view(self):
        self.settings_view = SettingsView(self.workspace, shell=self)
        self.settings_view.pack(fill="both", expand=True)
        self.lbl_val_res = self.settings_view.lbl_val_res

    def _ui_run_validation(self):
        if hasattr(self, "settings_view") and self.settings_view:
            res = self.settings_view.ui_run_validation(val_func=validate_project)
            self.lbl_val_res = self.settings_view.lbl_val_res
            return res

    # =========================================================================
    # Выполнение команд (Command Bar & Worker)
    # =========================================================================

    def _on_send_command(self):
        text = self.cmd_input.get().strip()
        if not text or text == self.cmd_placeholder:
            return

        self.cmd_input.delete(0, tk.END)
        self._append_chat("Вы", text)
        self._append_log("USER", text)

        # Переключаемся на Чат, если мы не на нём
        if self.current_section != "chat":
            self._switch_section("chat")

        self.is_busy = True
        self.btn_send.config(state="disabled")
        self._set_state("thinking")

        threading.Thread(target=self._worker_process, args=(text,), daemon=True).start()

    def _worker_process(self, user_input: str):
        try:
            resp = self.agent.process(user_input)
            self.queue.put(("process_result", resp))
        except Exception as e:
            self.queue.put(("process_error", str(e)))

    def _on_confirmation_requested(self, tool_name: str, kwargs: dict) -> bool:
        """Потокобезопасный вызов модального подтверждения в GUI."""
        self.confirm_event.clear()
        self.queue.put(("request_confirmation", (tool_name, kwargs)))
        self.confirm_event.wait()
        return self.confirm_result

    def _on_action_observed(self, event_type: str, data: dict):
        self.queue.put(("action_observed", (event_type, data)))

    def _on_voice_event(self, event_type: str, data: dict):
        self.queue.put(("voice_event", (event_type, data)))

    def _on_reminder_due(self, reminder: dict):
        """Потокобезопасная передача наступившего напоминания в очередь GUI."""
        self.queue.put(("reminder_due", reminder))

    def _handle_reminder_due(self, reminder: dict):
        """Отображение всплывающего уведомления о наступившем напоминании."""
        rem_id = reminder.get("id")
        rem_text = reminder.get("text", "")
        rem_time = reminder.get("remind_at", "")

        def on_complete():
            if self.household and rem_id is not None:
                self.household.delete_reminder(rem_id)
                self.refresh_current_view()
                self._append_log("DONE", f"Напоминание #{rem_id} выполнено.")

        def on_snooze():
            if self.household:
                self.household.create_reminder(rem_text, "через 10 минут")
                self.refresh_current_view()
                self._append_log("INFO", f"Напоминание '{rem_text}' отложено на 10 минут.")

        if hasattr(self, "notification_service") and self.notification_service:
            self.notification_service.show_reminder(
                title="Напоминание",
                text=rem_text,
                timestamp_str=rem_time,
                on_complete=on_complete,
                on_snooze=on_snooze,
                reminder_id=f"rem_{rem_id}"
            )

    def _on_hotkey_press(self):
        """Коллбэк нажатия глобального хоткея (вызывается из фонового потока)."""
        try:
            self.root.after(0, self._handle_hotkey_press)
        except Exception:
            pass

    def _handle_hotkey_press(self):
        """Обработка нажатия хоткея в главном UI-потоке."""
        if self._is_closing or not hasattr(self, "voice") or self.voice is None:
            return
        self._on_toggle_voice()

    def _on_hotkey_release(self):
        """Коллбэк отпускания глобального хоткея после удержания (Push-to-Talk)."""
        try:
            self.root.after(0, self._handle_hotkey_release)
        except Exception:
            pass

    def _handle_hotkey_release(self):
        """Обработка отпускания хоткея в главном UI-потоке."""
        if self._is_closing or not hasattr(self, "voice") or self.voice is None:
            return
        if getattr(self.voice, "state", None) == "listening" and hasattr(self.voice, "finish_listening"):
            self.voice.finish_listening()

    def _on_toggle_voice(self):
        if not hasattr(self, "voice") or self.voice is None:
            self._append_log("VOICE", "Голосовой модуль недоступен.")
            return

        if self.voice_enabled or self.voice.is_busy():
            self.voice_enabled = False
            self.btn_mic.config(text="🎙 Голос", bg="#21262d", fg=self.FG_WHITE)
            self.chip_voice.config(text="ГОЛОС: ВЫКЛ", fg=self.FG_MUTED)
            self.voice.stop_session()
            self._set_state("idle")
            self._append_log("VOICE", "Голосовой режим отключён.")
        else:
            if self.is_busy:
                self._append_log("VOICE", "Акакий занят выполнением другой задачи.")
                return

            started = self.voice.start_session(continuous=True)
            if started:
                self.voice_enabled = True
                self.btn_mic.config(text="⏹ Стоп", bg=self.ACCENT_RED, fg=self.FG_WHITE)
                self.chip_voice.config(text="ГОЛОС: ВКЛ", fg=self.ACCENT_GREEN)
                self._set_state("listening")
                self._append_log("VOICE", "Голосовой сеанс начат. Слушаю...")
            else:
                self._append_log("VOICE", "Не удалось запустить голосовой сеанс.")

    def _set_state(self, state_name: str):
        states_map = {
            "idle": ("✓ ГОТОВ", self.ACCENT_BLUE, "#111c2e"),
            "thinking": ("◌ ДУМАЕТ...", self.ACCENT_PURPLE, "#21153b"),
            "working": ("⚙ ВЫПОЛНЯЕТ ДЕЙСТВИЕ", self.ACCENT_GREEN, "#112d1b"),
            "listening": ("🎙 СЛУШАЕТ...", self.ACCENT_CYAN, "#112b3c"),
            "speaking": ("🔊 ОТВЕЧАЕТ (ОТВЕТ)...", self.ACCENT_GREEN, "#112d1b"),
            "error": ("✖ ОШИБКА", self.ACCENT_RED, "#361414"),
        }
        self.current_state = state_name
        if state_name in states_map:
            txt, fg_col, bg_col = states_map[state_name]
            self.status_badge.config(text=txt, fg=fg_col, bg=bg_col)
            if hasattr(self, "neural_core") and self.neural_core:
                self.neural_core.set_state(state_name)

    def refresh_current_view(self):
        """Реактивно обновляет данные текущего активного экрана без перезагрузки GUI."""
        sec = self.current_section
        if sec == "home":
            if hasattr(self, "home_view") and self.home_view and self.home_view.winfo_exists():
                self.home_view.refresh()
            else:
                self._switch_section("home")
        elif sec == "chat":
            if hasattr(self, "chat_view") and self.chat_view and self.chat_view.winfo_exists():
                self.chat_view.refresh()
        elif sec == "tasks":
            if hasattr(self, "tasks_view") and self.tasks_view and self.tasks_view.winfo_exists():
                self.tasks_view.refresh()
            elif hasattr(self, "tasks_list_frame") and self.tasks_list_frame and self.tasks_list_frame.winfo_exists():
                self._refresh_tasks_list()
        elif sec == "reminders":
            if hasattr(self, "reminders_view") and self.reminders_view and self.reminders_view.winfo_exists():
                self.reminders_view.refresh()
            elif hasattr(self, "rems_list_frame") and self.rems_list_frame and self.rems_list_frame.winfo_exists():
                self._refresh_reminders_list()
        elif sec == "notes":
            if hasattr(self, "notes_view") and self.notes_view and self.notes_view.winfo_exists():
                self.notes_view.refresh()
            elif hasattr(self, "notes_list_frame") and self.notes_list_frame and self.notes_list_frame.winfo_exists():
                self._refresh_notes_list()
        elif sec == "lists":
            if hasattr(self, "lists_view") and self.lists_view and self.lists_view.winfo_exists():
                self.lists_view.refresh()
            elif hasattr(self, "list_names_box") and self.list_names_box and self.list_names_box.winfo_exists():
                self._refresh_lists_menu()
        elif sec == "memory":
            if hasattr(self, "memory_view") and self.memory_view and self.memory_view.winfo_exists():
                self.memory_view.refresh()
            elif hasattr(self, "mem_list_frame") and self.mem_list_frame and self.mem_list_frame.winfo_exists():
                self._refresh_memory_list()
        elif sec == "settings":
            if hasattr(self, "settings_view") and self.settings_view and self.settings_view.winfo_exists():
                self.settings_view.refresh()

    # =========================================================================
    # Опрос очереди событий (Queue Polling)
    # =========================================================================

    def _poll_queue(self):
        try:
            while True:
                msg_type, data = self.queue.get_nowait()

                if msg_type == "process_result":
                    self.is_busy = False
                    self.btn_send.config(state="normal")

                    # Проверяем, завершилась ли операция ошибкой
                    has_err = False
                    err_msg = ""
                    if isinstance(data, dict):
                        if data.get("type") == "error" or data.get("error"):
                            has_err = True
                            err_msg = data.get("error")
                        res_obj = data.get("result")
                        if isinstance(res_obj, dict):
                            if res_obj.get("success") is False or "error" in res_obj:
                                has_err = True
                                err_msg = res_obj.get("error") or res_obj.get("message")
                            inner_res = res_obj.get("result")
                            if isinstance(inner_res, dict) and (inner_res.get("success") is False or "error" in inner_res):
                                has_err = True
                                err_msg = inner_res.get("error") or inner_res.get("message")

                    if has_err:
                        self._set_state("error")
                        err_text = f"Ошибка: {err_msg or 'Действие не выполнено.'}"
                        self._append_chat("Акакий", err_text)
                        self._append_log("ERR", err_text)
                    else:
                        self._set_state("idle")
                        ans = data.get("answer") if isinstance(data, dict) else str(data)
                        if not ans and isinstance(data, dict):
                            ans = data.get("result", {}).get("message") or str(data.get("result"))
                        self._append_chat("Акакий", ans or "Действие выполнено.")
                        self._append_log("DONE", "Запрос успешно обработан.")
                    self.refresh_current_view()

                elif msg_type == "process_error":
                    self.is_busy = False
                    self.btn_send.config(state="normal")
                    self._set_state("error")
                    self._append_chat("Акакий", f"Ошибка: {data}")
                    self._append_log("ERR", data)

                elif msg_type == "action_observed":
                    ev_type, payload = data
                    if ev_type == "before_tool":
                        t_name = payload.get("tool")
                        self._set_state("working")
                        self._append_log("TOOL", f"Запуск инструмента: {t_name}")
                    elif ev_type == "after_tool":
                        t_name = payload.get("tool")
                        t_res = payload.get("result")
                        if isinstance(t_res, dict) and (t_res.get("success") is False or "error" in t_res):
                            err_detail = t_res.get("error") or t_res.get("message") or "Сбой выполнения"
                            self._append_log("ERR", f"Инструмент {t_name} завершился с ошибкой: {err_detail}")
                        else:
                            self._append_log("DONE", f"Инструмент {t_name} выполнен.")
                        self.refresh_current_view()

                elif msg_type == "voice_event":
                    ev_type, payload = data
                    if ev_type == "voice_state":
                        st = payload.get("state", "idle")
                        self._set_state(st)
                    elif ev_type == "voice_audio_level":
                        lvl = payload.get("level", 0.0)
                        if hasattr(self, "neural_core") and self.neural_core:
                            self.neural_core.set_audio_level(lvl)
                    elif ev_type == "voice_recognized":
                        txt = payload.get("text", "")
                        if txt:
                            self._append_chat("Вы (Голос)", txt)
                            self._append_log("VOICE", f"Распознано: {txt}")
                    elif ev_type == "voice_agent_result":
                        res_payload = payload.get("payload", {})
                        has_err = False
                        err_msg = ""
                        if isinstance(res_payload, dict):
                            if res_payload.get("type") == "error" or res_payload.get("error"):
                                has_err = True
                                err_msg = res_payload.get("error")
                            res_inner = res_payload.get("result")
                            if isinstance(res_inner, dict):
                                if res_inner.get("success") is False or "error" in res_inner:
                                    has_err = True
                                    err_msg = res_inner.get("error") or res_inner.get("message")
                                sub_inner = res_inner.get("result")
                                if isinstance(sub_inner, dict) and (sub_inner.get("success") is False or "error" in sub_inner):
                                    has_err = True
                                    err_msg = sub_inner.get("error") or sub_inner.get("message")

                        if has_err:
                            self._set_state("error")
                            ans = f"Ошибка: {err_msg or 'Действие не выполнено.'}"
                            self._append_chat("Акакий (Голос)", ans)
                            self._append_log("ERR", ans)
                        else:
                            ans = ""
                            if isinstance(res_payload, dict):
                                ans = res_payload.get("answer") or ""
                                if not ans:
                                    ans = res_payload.get("result", {}).get("message") or str(res_payload.get("result", ""))
                            elif isinstance(res_payload, str):
                                ans = res_payload
                            if ans:
                                self._append_chat("Акакий (Голос)", ans)
                                self._append_log("DONE", "Голосовой ответ сформирован.")
                        self.refresh_current_view()
                    elif ev_type == "voice_mode_toggle":
                        enabled = payload.get("enabled", False) if isinstance(payload, dict) else bool(payload)
                        if not enabled and self.voice_enabled:
                            self.voice_enabled = False
                            self.btn_mic.config(text="🎙 Голос", bg="#21262d", fg=self.FG_WHITE)
                            self.chip_voice.config(text="ГОЛОС: ВЫКЛ", fg=self.FG_MUTED)
                            self._set_state("idle")
                            self._append_log("VOICE", "Голосовой режим отключён командой.")
                    elif ev_type == "voice_error":
                        err_msg = payload.get("message", "Сбой голосового сеанса") if isinstance(payload, dict) else str(payload)
                        self._set_state("error")
                        self._append_log("ERR", f"Голосовой сбой: {err_msg}")

                elif msg_type == "request_confirmation":
                    tool_name, kwargs = data
                    details = get_confirmation_details_text(tool_name, kwargs)
                    prompt = f"Требуется подтверждение для действия:\n\nИнструмент: {tool_name}\n\n{details}\n\nРазрешить выполнение?"
                    self.confirm_result = messagebox.askyesno("Подтверждение безопасности", prompt)
                    self.confirm_event.set()

                elif msg_type == "reminder_due":
                    self._handle_reminder_due(data)

        except queue.Empty:
            pass

        if not getattr(self, "_is_closing", False):
            try:
                self.root.after(40, self._poll_queue)
            except Exception:
                pass


def main():
    """Точка входа для отдельного запуска GUI."""
    root = tk.Tk()
    app = AkakiyGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
