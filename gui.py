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

import logging
from datetime import datetime
import math
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(r"c:\Akakiy agent")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

from tools.agent import Agent
from tools.dispatcher import (
    get_confirmation_details_text,
    set_action_observer,
    set_confirmation_handler
)
from tools.household import get_household_manager
from tools.memory import get_memory_manager
from tools.settings import get_app_settings
from tools.validation import validate_project
from ui.akakiy_core import AkakiyCore
from ui.neural_core import NeuralCore
from ui.cloud import AkakiyCloud
from ui.typography import typography, configure_tkinter_fonts
from voice import VoiceService, GlobalHotKeyManager
from notifications import NotificationService, ReminderMonitor
from infrastructure.ollama_manager import get_ollama_manager, OllamaManager


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

    # Базовая палитра Visual Direction 2.0 (Deep Graphite & Electric Cyan)
    BG_MAIN = "#070a0f"
    BG_PANEL = "#070a0f"
    BG_CARD = "#0c111c"
    BG_HOVER = "#0e1524"
    BG_ACTIVE = "#0f172a"
    BORDER_COL = "#131b28"
    BORDER_SUBTLE = "#141c2a"
    BORDER_LIGHT = "#1e293b"

    FG_WHITE = "#f8fafc"
    FG_MAIN = "#cbd5e1"
    FG_MUTED = "#64748b"
    FG_DIM = "#475569"

    ACCENT_BLUE = "#0284c7"
    ACCENT_CYAN = "#38bdf8"
    ACCENT_PURPLE = "#a78bfa"
    ACCENT_GREEN = "#34d399"
    ACCENT_AMBER = "#fbbf24"
    ACCENT_RED = "#fb7185"

    FONT_DISPLAY = typography.FONT_DISPLAY
    FONT_TITLE = typography.FONT_TITLE
    FONT_HEADING = typography.FONT_HEADING
    FONT_BODY = typography.FONT_BODY
    FONT_CAPTION = typography.FONT_CAPTION
    FONT_MONO = typography.FONT_MONO

    DISPLAY_FAMILY = typography.display_family
    UI_FAMILY = typography.ui_family
    MONO_FAMILY = typography.mono_family

    def __init__(self, root: tk.Tk, agent: Agent = None, household = None, memory = None, voice = None, ollama_mgr: Optional[OllamaManager] = None):
        self.root = root
        self.ollama_mgr = ollama_mgr
        configure_tkinter_fonts(self.root, typography)
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
        self.entry_task_search = None
        self.entry_rem_text = None
        self.entry_rem_time = None
        self.entry_note_search = None
        self.entry_note_title = None
        self.entry_note_content = None
        self.entry_new_list = None
        self._entry_item_text = None
        self.entry_mem = None
        self.lbl_val_res = None
        self.lbl_backup_res = None
        self.tasks_list_frame = None
        self.rems_list_frame = None
        self.notes_list_frame = None
        self.list_names_box = None
        self.list_items_box = None
        self.mem_list_frame = None
        self.chat_messages: List[Tuple[str, str, str]] = []  # [(author, message, time_str)]
        self.log_messages: List[Tuple[str, str, str]] = []   # [(prefix, text, time_str)]
        self.recent_work_results: list = []  # Структурированные результаты Agent/Sub-Agent/Planner/Tools
        self._last_submitted_query: str = ""
        self._active_agent_name: Optional[str] = None
        self._active_agent_step: Optional[str] = None
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

        # Настройки приложения (персистентность в data/settings.json)
        self.settings = get_app_settings()

        # Модульная система уведомлений и мониторинга напоминаний
        self.notification_service = NotificationService(master=self.root, settings=self.settings)
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
            if hasattr(self, "ollama_mgr") and self.ollama_mgr:
                self.ollama_mgr.cleanup()
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
        # 1. Topbar (72px)
        # -------------------------------------------------------------
        self.topbar = tk.Frame(self.root, bg=self.BG_PANEL, height=72, bd=0)
        self.topbar.pack(side="top", fill="x", padx=0, pady=0)
        self.topbar.pack_propagate(False)

        self._build_topbar_content()

        # Тонкий разделитель под Topbar
        tk.Frame(self.root, bg=self.BORDER_COL, height=1).pack(side="top", fill="x")

        # -------------------------------------------------------------
        # 2. Command Bar (80px) - внизу экрана
        # -------------------------------------------------------------
        tk.Frame(self.root, bg=self.BORDER_COL, height=1).pack(side="bottom", fill="x")

        self.cmd_bar = tk.Frame(self.root, bg=self.BG_PANEL, height=80, bd=0)
        self.cmd_bar.pack(side="bottom", fill="x", padx=0, pady=0)
        self.cmd_bar.pack_propagate(False)

        self._build_command_bar_content()

        # -------------------------------------------------------------
        # 3. Центральное тело: Sidebar (220px) + Main Workspace
        # -------------------------------------------------------------
        self.center_body = tk.Frame(self.root, bg=self.BG_MAIN)
        self.center_body.pack(side="top", fill="both", expand=True)

        # Sidebar (220px)
        self.sidebar = tk.Frame(self.center_body, bg=self.BG_PANEL, width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self._build_sidebar_content()

        # Тонкий вертикальный разделитель
        tk.Frame(self.center_body, bg=self.BORDER_COL, width=1).pack(side="left", fill="y")

        # Main Workspace Container
        self.workspace = tk.Frame(self.center_body, bg=self.BG_MAIN)
        self.workspace.pack(side="left", fill="both", expand=True, padx=20, pady=16)
        self.main_workspace = self.workspace
        self.command_bar = self.cmd_bar

    # =========================================================================
    # 1. Topbar (72px)
    # =========================================================================

    def _build_topbar_content(self):
        # Левая колонка: Логотип и статус
        left_box = tk.Frame(self.topbar, bg=self.BG_PANEL)
        left_box.pack(side="left", padx=20, pady=(6, 6))

        logo_row = tk.Frame(left_box, bg=self.BG_PANEL)
        logo_row.pack(anchor="w")

        tk.Label(
            logo_row,
            text="✦  А К А К И Й",
            font=(self.DISPLAY_FAMILY, 15, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_PANEL
        ).pack(side="left")

        tk.Label(
            logo_row,
            text="2.0  •  DESKTOP HUB",
            font=self.FONT_CAPTION,
            fg=self.FG_MUTED,
            bg=self.BG_PANEL
        ).pack(side="left", padx=(12, 0))

        status_row = tk.Frame(left_box, bg=self.BG_PANEL)
        status_row.pack(anchor="w", pady=(2, 0))

        self.status_badge = tk.Label(
            status_row,
            text="● ГОТОВ",
            font=self.FONT_HEADING,
            fg=self.ACCENT_CYAN,
            bg="#0e1726",
            padx=10, pady=2,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.BORDER_LIGHT
        )
        self.status_badge.pack(side="left")

        # Правая колонка: Часы, Дата и Индикаторы
        right_box = tk.Frame(self.topbar, bg=self.BG_PANEL)
        right_box.pack(side="right", padx=20, pady=(6, 6))

        # Индикаторы сервисов
        chips_box = tk.Frame(right_box, bg=self.BG_PANEL)
        chips_box.pack(side="left", padx=(0, 20))

        self.chip_ollama = tk.Label(
            chips_box,
            text="QWEN3:8B ●",
            font=self.FONT_MONO,
            fg=self.ACCENT_GREEN,
            bg="#091b12",
            padx=8, pady=2,
            bd=0,
            highlightthickness=1,
            highlightbackground="#133b25"
        )
        self.chip_ollama.pack(side="left", padx=4)

        self.chip_voice = tk.Label(
            chips_box,
            text="ГОЛОС: ВЫКЛ",
            font=self.FONT_MONO,
            fg=self.FG_MUTED,
            bg="#0d131f",
            padx=8, pady=2,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.BORDER_LIGHT
        )
        self.chip_voice.pack(side="left", padx=4)

        # Часы
        clock_box = tk.Frame(right_box, bg=self.BG_PANEL)
        clock_box.pack(side="right")

        self.lbl_time = tk.Label(
            clock_box,
            text="00:00:00",
            font=self.FONT_TITLE,
            fg=self.FG_MAIN,
            bg=self.BG_PANEL
        )
        self.lbl_time.pack(anchor="e")

        self.lbl_date = tk.Label(
            clock_box,
            text="Понедельник, 1 января 2026",
            font=self.FONT_CAPTION,
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
        nav_header.pack(fill="x", padx=16, pady=(16, 8))

        tk.Label(
            nav_header,
            text="НАВИГАЦИЯ",
            font=self.FONT_CAPTION,
            fg=self.FG_DIM,
            bg=self.BG_PANEL
        ).pack(anchor="w")

        self.nav_buttons = {}
        items = [
            ("home", "⌂  Главная"),
            ("chat", "💬  Чат"),
            ("tasks", "✓  Задачи"),
            ("reminders", "🔔  События"),
            ("notes", "📝  Заметки"),
            ("lists", "📋  Списки"),
            ("memory", "🧠  Память"),
            ("settings", "⚙  Настройки"),
        ]

        for code, label in items:
            btn = tk.Button(
                self.sidebar,
                text=label,
                font=self.FONT_HEADING,
                fg=self.FG_MUTED,
                bg=self.BG_PANEL,
                activeforeground=self.FG_WHITE,
                activebackground=self.BG_HOVER,
                anchor="w",
                padx=16, pady=7,
                bd=0,
                relief="flat",
                cursor="hand2",
                command=lambda c=code: self._switch_section(c)
            )
            btn.pack(fill="x", padx=6, pady=1)
            _bind_hover(btn, self.BG_PANEL, self.BG_HOVER, self.FG_MUTED, self.FG_WHITE)
            self.nav_buttons[code] = btn

        # Нижний информационный блок Sidebar
        sidebar_footer = tk.Frame(
            self.sidebar,
            bg=self.BG_CARD,
            bd=0,
            highlightbackground=self.BORDER_SUBTLE,
            highlightthickness=1
        )
        sidebar_footer.pack(side="bottom", fill="x", padx=10, pady=14)

        tk.Label(
            sidebar_footer,
            text="АКAKИЙ CORE",
            font=self.FONT_MONO,
            fg=self.ACCENT_CYAN,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=10, pady=(8, 2))

        tk.Label(
            sidebar_footer,
            text="Autonomous Agent Hub\nNative Tool Calling: Active",
            font=self.FONT_CAPTION,
            fg=self.FG_MUTED,
            bg=self.BG_CARD,
            justify="left"
        ).pack(anchor="w", padx=10, pady=(0, 8))

    # =========================================================================
    # 3. Command Bar (80px)
    # =========================================================================

    def _build_command_bar_content(self):
        box = tk.Frame(self.cmd_bar, bg=self.BG_PANEL)
        box.pack(fill="both", expand=True, padx=20, pady=10)

        # Контейнер для поля ввода (Floating Pill Frame)
        input_wrap = tk.Frame(
            box,
            bg="#0d131f",
            bd=0,
            highlightbackground=self.BORDER_LIGHT,
            highlightthickness=1
        )
        input_wrap.pack(side="left", fill="both", expand=True, padx=(0, 10))

        tk.Label(
            input_wrap,
            text="✦",
            font=self.FONT_HEADING,
            fg=self.ACCENT_CYAN,
            bg="#0d131f"
        ).pack(side="left", padx=(12, 6))

        self.cmd_input = tk.Entry(
            input_wrap,
            font=self.FONT_BODY,
            bg="#0d131f",
            fg=self.FG_WHITE,
            insertbackground=self.ACCENT_CYAN,
            bd=0
        )
        self.cmd_input.pack(side="left", fill="both", expand=True, pady=6)
        self.cmd_input.bind("<Return>", lambda e: self._on_send_command())

        # Placeholder
        self.cmd_placeholder = "Спросите что-нибудь или введите задачу (:help)..."
        self.cmd_input.insert(0, self.cmd_placeholder)
        self.cmd_input.config(fg=self.FG_MUTED)

        def on_focus_in(e):
            input_wrap.config(highlightbackground=self.ACCENT_BLUE)
            if self.cmd_input.get() == self.cmd_placeholder:
                self.cmd_input.delete(0, tk.END)
                self.cmd_input.config(fg=self.FG_WHITE)

        def on_focus_out(e):
            input_wrap.config(highlightbackground=self.BORDER_LIGHT)
            if not self.cmd_input.get().strip():
                self.cmd_input.insert(0, self.cmd_placeholder)
                self.cmd_input.config(fg=self.FG_MUTED)

        self.cmd_input.bind("<FocusIn>", on_focus_in)
        self.cmd_input.bind("<FocusOut>", on_focus_out)

        # Кнопка голосового режима
        self.btn_mic = tk.Button(
            box,
            text="🎙 Голос",
            font=self.FONT_CAPTION,
            fg=self.FG_WHITE,
            bg="#131c2e",
            activeforeground=self.FG_WHITE,
            activebackground=self.ACCENT_BLUE,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.BORDER_LIGHT,
            padx=14, pady=6,
            cursor="hand2",
            command=self._on_toggle_voice
        )
        self.btn_mic.pack(side="left", padx=(0, 8))
        _bind_hover(self.btn_mic, "#131c2e", "#1e293b", self.FG_WHITE, self.FG_WHITE)

        # Кнопка отправки команды
        self.btn_send = tk.Button(
            box,
            text="Выполнить ➔",
            font=self.FONT_HEADING,
            fg="#070a0f",
            bg=self.ACCENT_CYAN,
            activeforeground="#070a0f",
            activebackground="#7dd3fc",
            bd=0,
            padx=16, pady=6,
            cursor="hand2",
            command=self._on_send_command
        )
        self.btn_send.pack(side="left")
        _bind_hover(self.btn_send, self.ACCENT_CYAN, "#7dd3fc", "#070a0f", "#070a0f")

    # =========================================================================
    # Навигация и переключение экранов
    # =========================================================================

    def _switch_section(self, code: str):
        self.current_section = code

        # Обновление подсветки кнопок в Sidebar
        for c, btn in self.nav_buttons.items():
            if c == code:
                btn.config(bg=self.BG_ACTIVE, fg=self.ACCENT_CYAN, font=self.FONT_HEADING)
            else:
                btn.config(bg=self.BG_PANEL, fg=self.FG_MUTED, font=self.FONT_BODY)

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

    def _insert_chat_ui(self, author: str, message: str, t_str: str, artifacts: Optional[List[Any]] = None, domain_badge: Optional[str] = None):
        if hasattr(self, "chat_view") and self.chat_view:
            return self.chat_view.insert_chat_ui(author, message, t_str, artifacts=artifacts, domain_badge=domain_badge)
        elif hasattr(self, "chat_text") and self.chat_text and self.chat_text.winfo_exists():
            self.chat_text.insert(tk.END, "\n")
            author_upper = author.upper()
            if "ВЫ" in author_upper:
                self.chat_text.insert(tk.END, f"● {author_upper}  ", "user_title")
                self.chat_text.insert(tk.END, f"[{t_str}]\n", "time")
                self.chat_text.insert(tk.END, f"{message}\n", "user_body")
            else:
                self.chat_text.insert(tk.END, f"● {author_upper}  ", "akakiy_title")
                if domain_badge:
                    self.chat_text.insert(tk.END, f"[{domain_badge}]  ", "domain_badge")
                self.chat_text.insert(tk.END, f"[{t_str}]\n", "time")
                self.chat_text.insert(tk.END, f"{message}\n", "akakiy_body")

            if artifacts:
                try:
                    from ui.artifact_card import create_artifact_card
                    for art in artifacts:
                        card = create_artifact_card(self.chat_text, art, compact=False)
                        self.chat_text.insert(tk.END, "\n")
                        self.chat_text.window_create(tk.END, window=card)
                        self.chat_text.insert(tk.END, "\n")
                except Exception:
                    pass

            self.chat_text.insert(tk.END, "─" * 48 + "\n", "div")
            self.chat_text.see(tk.END)

    def _append_chat(self, author: str, message: str, artifacts: Optional[List[Any]] = None, domain_badge: Optional[str] = None):
        t_str = time.strftime("%H:%M:%S")
        self.chat_messages.append((author, message, t_str, artifacts or [], domain_badge))
        self._insert_chat_ui(author, message, t_str, artifacts=artifacts, domain_badge=domain_badge)

    def _insert_log_ui(self, prefix: str, text: str, t_str: str):
        if hasattr(self, "chat_view") and self.chat_view:
            return self.chat_view.insert_log_ui(prefix, text, t_str)
        elif hasattr(self, "log_text") and self.log_text and self.log_text.winfo_exists():
            tag = "info"
            if prefix == "TOOL":
                tag = "tool"
            elif prefix == "AGENT":
                tag = "agent"
            elif prefix == "STEP":
                tag = "step"
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
        self.entry_task_search = getattr(self.tasks_view, "entry_task_search", None)
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
        self.lbl_backup_res = getattr(self.settings_view, "lbl_backup_res", None)

    def _ui_run_validation(self):
        if hasattr(self, "settings_view") and self.settings_view:
            res = self.settings_view.ui_run_validation(val_func=validate_project)
            self.lbl_val_res = self.settings_view.lbl_val_res
            return res

    def _ui_export_data(self):
        if hasattr(self, "settings_view") and self.settings_view:
            return self.settings_view.ui_export_data()

    def _ui_import_data(self):
        if hasattr(self, "settings_view") and self.settings_view:
            return self.settings_view.ui_import_data()

    # =========================================================================
    # Выполнение команд (Command Bar & Worker)
    # =========================================================================

    def record_work_result(self, payload: Any, query: str = "") -> dict:
        """
        Регистрирует структурированный рабочий результат выполнения Agent/Sub-Agent/Planner/Tools
        для отображения на Главном экране (Desktop Hub) и в истории сеанса.
        """
        t_str = time.strftime("%H:%M:%S")
        r_type = "chat"
        title = "Выполнение команды"
        message = ""
        success = True
        artifacts = []
        created_files = []
        error = None

        if isinstance(payload, dict) or hasattr(payload, "get"):
            r_type = payload.get("type", "chat")
            tool_name = payload.get("tool", "")
            if tool_name and r_type == "tool":
                r_type = tool_name

            # Проверка ошибок на верхнем и вложенных уровнях
            if payload.get("success") is False or payload.get("error"):
                success = False
                error = payload.get("error") or "Ошибка выполнения"

            res_obj = payload.get("result")
            if isinstance(res_obj, dict) or hasattr(res_obj, "get"):
                if res_obj.get("success") is False or bool(res_obj.get("error")):
                    success = False
                    error = res_obj.get("error") or res_obj.get("message")
                inner_res = res_obj.get("result")
                if isinstance(inner_res, dict) or hasattr(inner_res, "get"):
                    if inner_res.get("success") is False or bool(inner_res.get("error")):
                        success = False
                        error = inner_res.get("error") or inner_res.get("message")
            elif hasattr(res_obj, "success") and not res_obj.success:
                success = False
                error = getattr(res_obj, "error", None) or getattr(res_obj, "message", None)

            # Извлечение основного сообщения
            ans = payload.get("answer")
            if not ans and (isinstance(res_obj, dict) or hasattr(res_obj, "get")):
                ans = res_obj.get("message") or res_obj.get("summary") or res_obj.get("error")
            elif not ans and hasattr(res_obj, "message"):
                ans = getattr(res_obj, "message", None)
            message = str(ans or "")

            # Извлечение созданных файлов
            c_files = payload.get("created_files") or []
            if isinstance(c_files, list):
                for f in c_files:
                    f_str = str(f)
                    if f_str not in created_files:
                        created_files.append(f_str)

            # Извлечение артефактов
            arts = payload.get("artifacts") or []
            if isinstance(arts, list):
                for a in arts:
                    if isinstance(a, dict):
                        artifacts.append(a)
                    elif hasattr(a, "to_dict"):
                        artifacts.append(a.to_dict())
                    elif isinstance(a, str):
                        artifacts.append({"name": Path(a).name, "path": a})

            if res_obj and hasattr(res_obj, "artifacts"):
                for a in res_obj.artifacts:
                    a_dict = a.to_dict() if hasattr(a, "to_dict") else {"name": getattr(a, "name", str(a))}
                    if a_dict not in artifacts:
                        artifacts.append(a_dict)
            if res_obj and hasattr(res_obj, "created_files"):
                for f in res_obj.created_files:
                    f_str = str(f)
                    if f_str not in created_files:
                        created_files.append(f_str)

            # Человекочитаемые заголовки типов
            titles_map = {
                "household": "Домашние дела",
                "tasks": "Управление задачами",
                "reminders": "Напоминания",
                "notes": "Заметки",
                "lists": "Списки дел и покупок",
                "research": "Аналитическое исследование",
                "image": "Генерация изображения",
                "presentation": "Создание презентации",
                "document": "Создание документа",
                "coding": "Задача по коду",
                "file": "Файловая операция",
                "plan": "Планирование задач",
                "plan_execution": "Исполнение плана",
                "chat": "Диалог с ассистентом",
            }
            title = titles_map.get(r_type, f"Действие: {r_type}")
        elif isinstance(payload, str):
            message = payload
        else:
            message = str(payload)

        if not message:
            message = "Действие успешно завершено." if success else (error or "Ошибка обработки запроса.")

        # Определение domain_badge для UI (HomeView cards & ChatView)
        domain_badge = None
        if r_type not in ("plan", "plan_execution"):
            d_name = None
            if isinstance(payload, dict):
                d_name = payload.get("display_name")
            if not d_name and res_obj:
                if isinstance(res_obj, dict):
                    d_name = res_obj.get("display_name") or res_obj.get("data", {}).get("display_name")
                elif hasattr(res_obj, "data") and isinstance(res_obj.data, dict):
                    d_name = res_obj.data.get("display_name")
            if not d_name:
                d_name = getattr(self, "_active_agent_name", None)

            if d_name:
                d_lower = d_name.lower()
                if "домашн" in d_lower or "household" in d_lower:
                    domain_badge = "🏠 Домашние дела"
                elif "исследован" in d_lower or "research" in d_lower:
                    domain_badge = "🔍 Исследования"
                else:
                    domain_badge = d_name
            elif r_type in ("household", "tasks", "reminders", "notes", "lists"):
                domain_badge = "🏠 Домашние дела"
            elif r_type == "research":
                domain_badge = "🔍 Исследования"

        entry = {
            "type": r_type,
            "title": title,
            "domain_badge": domain_badge,
            "message": message,
            "query": query,
            "success": success,
            "error": error,
            "created_files": created_files,
            "artifacts": artifacts,
            "time": t_str,
        }

        self.recent_work_results.append(entry)
        if len(self.recent_work_results) > 25:
            self.recent_work_results.pop(0)

        return entry

    def _on_send_command(self):
        text = self.cmd_input.get().strip()
        if not text or text == self.cmd_placeholder:
            return

        self.cmd_input.delete(0, tk.END)
        self._append_chat("Вы", text)
        self._append_log("USER", text)
        self._last_submitted_query = text

        # Чат остаётся отдельным рабочим экраном, а не центром всего приложения.
        # Пользователь остаётся на текущем активном экране (Главная, Задачи и т.д.),
        # а результаты и изменения отображаются реактивно через refresh_current_view.

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
                res = self.household.complete_reminder(rem_id)
                self.refresh_current_view()
                if res.get("rescheduled") or reminder.get("repeat"):
                    self._append_log("DONE", f"Повторяющееся напоминание #{rem_id} выполнено.")
                else:
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

        # Озвучивание напоминания через существующий VoiceService/TTS (если включено в настройках)
        speak_enabled = getattr(self.settings, "speak_reminders", True) if self.settings else True
        if speak_enabled and self.voice and hasattr(self.voice, "tts") and self.voice.tts:
            try:
                speech_phrase = f"Напоминание: {rem_text}"
                self.voice.tts.speak(speech_phrase)
            except Exception as e:
                logger.warning(f"Ошибка озвучивания напоминания #{rem_id}: {e}")

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

    def _set_state(
        self,
        state_name: str,
        active_agent: Optional[str] = None,
        active_step: Optional[str] = None
    ):
        states_map = {
            "idle": ("✓ ГОТОВ", self.ACCENT_BLUE, "#111c2e"),
            "thinking": ("◌ ДУМАЕТ...", self.ACCENT_PURPLE, "#21153b"),
            "working": ("⚙ ВЫПОЛНЯЕТ ДЕЙСТВИЕ", self.ACCENT_GREEN, "#112d1b"),
            "listening": ("🎙 СЛУШАЕТ...", self.ACCENT_CYAN, "#112b3c"),
            "speaking": ("🔊 ОТВЕЧАЕТ (ОТВЕТ)...", self.ACCENT_GREEN, "#112d1b"),
            "success": ("✦ УСПЕШНО", self.ACCENT_CYAN, "#0f2b38"),
            "error": ("✖ ОШИБКА", self.ACCENT_RED, "#361414"),
        }
        self.current_state = state_name

        if active_agent is not None:
            self._active_agent_name = active_agent
        elif state_name in ("idle", "success", "error"):
            self._active_agent_name = None

        if active_step is not None:
            self._active_agent_step = active_step
        elif state_name in ("idle", "success", "error"):
            self._active_agent_step = None

        if state_name in states_map:
            txt, fg_col, bg_col = states_map[state_name]
            if state_name == "working" and self._active_agent_name:
                clean_name = self._active_agent_name.strip()
                if clean_name.startswith("🏠") or clean_name.startswith("🔍"):
                    txt = clean_name.upper()
                else:
                    txt = f"⚙ {clean_name.upper()}"
            self.status_badge.config(text=txt, fg=fg_col, bg=bg_col)
            if hasattr(self, "neural_core") and self.neural_core:
                self.neural_core.set_state(state_name)
            if hasattr(self, "home_view") and self.home_view and hasattr(self.home_view, "update_state_display"):
                self.home_view.update_state_display(
                    state_name,
                    active_agent=self._active_agent_name,
                    active_step=self._active_agent_step
                )

        if state_name == "success":
            try:
                self.root.after(1800, lambda: self._set_state("idle") if self.current_state == "success" else None)
            except Exception:
                pass

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

                    work_entry = self.record_work_result(data, query=getattr(self, "_last_submitted_query", ""))
                    has_err = not work_entry.get("success", True)
                    err_msg = work_entry.get("error") or ""
                    d_badge = work_entry.get("domain_badge")

                    if has_err:
                        self._set_state("error")
                        err_text = f"Ошибка: {err_msg or 'Действие не выполнено.'}"
                        self._append_chat("Акакий", err_text, domain_badge=d_badge)
                        self._append_log("ERR", err_text)
                    else:
                        self._set_state("success")
                        ans = work_entry.get("message") or "Действие выполнено."
                        chat_ans = ans
                        c_files = work_entry.get("created_files") or []
                        if c_files:
                            c_names = [Path(f).name for f in c_files]
                            if not any(f in chat_ans for f in c_files):
                                chat_ans += f"\n\n✦ Созданные артефакты:\n" + "\n".join(f"  • {f}" for f in c_files)
                            self._append_log("DONE", f"Артефакты ({len(c_names)}): {', '.join(c_names)}")
                        artifacts = work_entry.get("artifacts") or []
                        self._append_chat("Акакий", chat_ans, artifacts=artifacts, domain_badge=d_badge)
                        self._append_log("DONE", f"Запрос успешно обработан [{work_entry.get('type')}].")
                    self.refresh_current_view()

                elif msg_type == "process_error":
                    self.is_busy = False
                    self.btn_send.config(state="normal")
                    self._set_state("error")
                    self.record_work_result({"type": "error", "error": str(data), "success": False}, query=getattr(self, "_last_submitted_query", ""))
                    self._append_chat("Акакий", f"Ошибка: {data}")
                    self._append_log("ERR", str(data))
                    self.refresh_current_view()

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
                    elif ev_type == "before_agent":
                        agent_raw = payload.get("display_name") or payload.get("agent") or "Агент"
                        if "household" in agent_raw.lower() or "домашн" in agent_raw.lower():
                            agent_display = "🏠 Домашние дела"
                        elif "research" in agent_raw.lower() or "исследован" in agent_raw.lower():
                            agent_display = "🔍 Исследования"
                        else:
                            agent_display = agent_raw
                        self._active_agent_name = agent_display
                        self._active_agent_step = "Маршрутизация…"
                        self._set_state("working", active_agent=agent_display, active_step="Маршрутизация…")
                        self._append_log("AGENT", f"Запуск агента: {agent_display}")
                    elif ev_type == "agent_progress":
                        step_txt = payload.get("step", "")
                        agent_raw = payload.get("display_name") or payload.get("agent") or self._active_agent_name or "Агент"
                        if "household" in agent_raw.lower() or "домашн" in agent_raw.lower():
                            agent_display = "🏠 Домашние дела"
                        elif "research" in agent_raw.lower() or "исследован" in agent_raw.lower():
                            agent_display = "🔍 Исследования"
                        else:
                            agent_display = agent_raw
                        self._active_agent_name = agent_display
                        self._active_agent_step = step_txt
                        self._set_state("working", active_agent=agent_display, active_step=step_txt)
                        self._append_log("STEP", f"{agent_display}: {step_txt}")
                    elif ev_type == "after_agent":
                        agent_raw = payload.get("display_name") or payload.get("agent") or self._active_agent_name or "Агент"
                        if "household" in agent_raw.lower() or "домашн" in agent_raw.lower():
                            agent_display = "🏠 Домашние дела"
                        elif "research" in agent_raw.lower() or "исследован" in agent_raw.lower():
                            agent_display = "🔍 Исследования"
                        else:
                            agent_display = agent_raw
                        is_ok = payload.get("success", True)
                        if is_ok:
                            self._append_log("DONE", f"{agent_display} завершил работу.")
                        else:
                            self._append_log("ERR", f"{agent_display} завершился с ошибкой.")
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
                        v_query = payload.get("query", "")
                        work_entry = self.record_work_result(res_payload, query=v_query)
                        has_err = not work_entry.get("success", True)
                        err_msg = work_entry.get("error") or ""
                        d_badge = work_entry.get("domain_badge")

                        if has_err:
                            self._set_state("error")
                            ans = f"Ошибка: {err_msg or 'Действие не выполнено.'}"
                            self._append_chat("Акакий (Голос)", ans, domain_badge=d_badge)
                            self._append_log("ERR", ans)
                        else:
                            ans = work_entry.get("message") or ""
                            chat_ans = ans
                            c_files = work_entry.get("created_files") or []
                            if c_files:
                                if not any(f in chat_ans for f in c_files):
                                    chat_ans += f"\n\n✦ Созданные артефакты:\n" + "\n".join(f"  • {f}" for f in c_files)
                                c_names = [Path(f).name for f in c_files]
                                self._append_log("DONE", f"Артефакты ({len(c_names)}): {', '.join(c_names)}")
                            artifacts = work_entry.get("artifacts") or []
                            if chat_ans:
                                self._append_chat("Акакий (Голос)", chat_ans, artifacts=artifacts, domain_badge=d_badge)
                                self._append_log("DONE", f"Голосовой ответ сформирован [{work_entry.get('type')}].")
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
    ollama_mgr = get_ollama_manager()
    success, status_msg = ollama_mgr.start_or_connect()
    if not success:
        logger.warning(f"Ollama startup: {status_msg}")
    else:
        logger.info(f"Ollama startup: {status_msg}")

    root = tk.Tk()
    app = AkakiyGUI(root, ollama_mgr=ollama_mgr)
    try:
        root.mainloop()
    finally:
        ollama_mgr.cleanup()


if __name__ == "__main__":
    main()
