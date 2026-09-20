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
from voice import VoiceService


from ui.views.base import BaseView, _bind_hover


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
        # Верхний ряд: Приветствие + блок Сегодня + Neural Core
        top_row = tk.Frame(self.workspace, bg=self.BG_MAIN)
        top_row.pack(fill="x", pady=(0, 20))

        # Левая часть верхнего ряда: приветствие и «Сегодня»
        welcome_box = tk.Frame(top_row, bg=self.BG_CARD, bd=1, relief="solid")
        welcome_box.pack(side="left", fill="both", expand=True, padx=(0, 20))

        tk.Label(
            welcome_box,
            text="ДОБРО ПОЖАЛОВАТЬ В АКАКИЙ 2.0",
            font=("Segoe UI", 15, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=24, pady=(20, 4))

        tk.Label(
            welcome_box,
            text="Ваш персональный автономный ИИ-хаб и бытовой ассистент.",
            font=("Segoe UI", 10),
            fg=self.FG_MUTED,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=24, pady=(0, 16))

        # Внутренний блок «Сегодня»
        today_box = tk.Frame(welcome_box, bg="#13171f", bd=1, relief="solid")
        today_box.pack(fill="x", padx=24, pady=(0, 20))

        tk.Label(
            today_box,
            text="📅  СВОДКА «СЕГОДНЯ»",
            font=("Segoe UI", 10, "bold"),
            fg=self.ACCENT_CYAN,
            bg="#13171f"
        ).pack(anchor="w", padx=16, pady=(12, 6))

        pending_tasks = len(self.household.list_tasks(status="pending")["tasks"])
        due_reminders = self.household.check_due_reminders()["due_count"]
        total_lists = len(self.household.lists)

        info_text = (
            f"• Активных задач: {pending_tasks}\n"
            f"• Наступивших/ближайших напоминаний: {due_reminders}\n"
            f"• Именованных списков дел: {total_lists}"
        )
        tk.Label(
            today_box,
            text=info_text,
            font=("Segoe UI", 10),
            fg=self.FG_MAIN,
            bg="#13171f",
            justify="left"
        ).pack(anchor="w", padx=16, pady=(0, 14))

        # Правая часть верхнего ряда: NEURAL CORE
        core_box = tk.Frame(top_row, bg=self.BG_CARD, bd=1, relief="solid", width=260)
        core_box.pack(side="right", fill="y")
        core_box.pack_propagate(False)

        tk.Label(
            core_box,
            text="NEURAL CORE",
            font=("Segoe UI", 9, "bold"),
            fg=self.FG_MUTED,
            bg=self.BG_CARD
        ).pack(pady=(12, 4))

        self.neural_core = NeuralCore(core_box, size=180, bg=self.BG_CARD)
        self.neural_core.pack(pady=4)
        if hasattr(self, "current_state"):
            self.neural_core.set_state(self.current_state)

        # Средний ряд: 3 интерактивные карточки (Задачи / Напоминания / Списки)
        mid_row = tk.Frame(self.workspace, bg=self.BG_MAIN)
        mid_row.pack(fill="x", pady=(0, 20))

        # Карточка 1: Задачи
        card_t = tk.Frame(mid_row, bg=self.BG_CARD, bd=1, relief="solid")
        card_t.pack(side="left", fill="both", expand=True, padx=(0, 14))

        tk.Label(
            card_t, text="✓  ЗАДАЧИ",
            font=("Segoe UI", 11, "bold"), fg=self.ACCENT_CYAN, bg=self.BG_CARD
        ).pack(anchor="w", padx=16, pady=(14, 8))

        tasks = self.household.list_tasks(status="pending")["tasks"][:3]
        if not tasks:
            tk.Label(card_t, text="Нет активных задач.", font=("Segoe UI", 9), fg=self.FG_MUTED, bg=self.BG_CARD).pack(anchor="w", padx=16, pady=4)
        else:
            for t in tasks:
                t_row = tk.Frame(card_t, bg=self.BG_CARD)
                t_row.pack(fill="x", padx=16, pady=2)
                chk = tk.Button(
                    t_row, text="☐", font=("Segoe UI", 10), bg=self.BG_CARD, fg=self.FG_MUTED, bd=0, cursor="hand2",
                    command=lambda tid=t["id"]: self._quick_complete_task(tid)
                )
                chk.pack(side="left")
                lbl = t["title"] if len(t["title"]) <= 28 else t["title"][:25] + "..."
                tk.Label(t_row, text=lbl, font=("Segoe UI", 9), fg=self.FG_MAIN, bg=self.BG_CARD).pack(side="left", padx=4)

        btn_all_t = tk.Button(
            card_t, text="Все задачи →", font=("Segoe UI", 8, "bold"), fg=self.ACCENT_BLUE, bg=self.BG_CARD, bd=0, cursor="hand2",
            command=lambda: self._switch_section("tasks")
        )
        btn_all_t.pack(anchor="w", padx=16, pady=(10, 12))

        # Карточка 2: Напоминания
        card_r = tk.Frame(mid_row, bg=self.BG_CARD, bd=1, relief="solid")
        card_r.pack(side="left", fill="both", expand=True, padx=(0, 14))

        tk.Label(
            card_r, text="🔔  НАПОМИНАНИЯ",
            font=("Segoe UI", 11, "bold"), fg=self.ACCENT_PURPLE, bg=self.BG_CARD
        ).pack(anchor="w", padx=16, pady=(14, 8))

        rems_dict = self.household.list_reminders() if hasattr(self.household, "list_reminders") else {}
        rems = rems_dict.get("reminders", [])[:3] if isinstance(rems_dict, dict) else []
        if not rems:
            tk.Label(card_r, text="Напоминаний нет.", font=("Segoe UI", 9), fg=self.FG_MUTED, bg=self.BG_CARD).pack(anchor="w", padx=16, pady=4)
        else:
            for r in rems:
                r_lbl = f"• {r['text'][:22]} ({r['remind_at']})"
                tk.Label(card_r, text=r_lbl, font=("Segoe UI", 9), fg=self.FG_MAIN, bg=self.BG_CARD).pack(anchor="w", padx=16, pady=2)

        btn_all_r = tk.Button(
            card_r, text="Все напоминания →", font=("Segoe UI", 8, "bold"), fg=self.ACCENT_PURPLE, bg=self.BG_CARD, bd=0, cursor="hand2",
            command=lambda: self._switch_section("reminders")
        )
        btn_all_r.pack(anchor="w", padx=16, pady=(10, 12))

        # Карточка 3: Списки
        card_l = tk.Frame(mid_row, bg=self.BG_CARD, bd=1, relief="solid")
        card_l.pack(side="left", fill="both", expand=True)

        tk.Label(
            card_l, text="📋  СПИСКИ",
            font=("Segoe UI", 11, "bold"), fg=self.ACCENT_GREEN, bg=self.BG_CARD
        ).pack(anchor="w", padx=16, pady=(14, 8))

        lists_keys = list(self.household.lists.keys())[:3]
        if not lists_keys:
            tk.Label(card_l, text="Списков пока нет.", font=("Segoe UI", 9), fg=self.FG_MUTED, bg=self.BG_CARD).pack(anchor="w", padx=16, pady=4)
        else:
            for l_name in lists_keys:
                cnt = len(self.household.lists[l_name])
                tk.Label(card_l, text=f"• {l_name} ({cnt} эл.)", font=("Segoe UI", 9), fg=self.FG_MAIN, bg=self.BG_CARD).pack(anchor="w", padx=16, pady=2)

        btn_all_l = tk.Button(
            card_l, text="Все списки →", font=("Segoe UI", 8, "bold"), fg=self.ACCENT_GREEN, bg=self.BG_CARD, bd=0, cursor="hand2",
            command=lambda: self._switch_section("lists")
        )
        btn_all_l.pack(anchor="w", padx=16, pady=(10, 12))

        # Нижний ряд: Последние заметки
        notes_box = tk.Frame(self.workspace, bg=self.BG_CARD, bd=1, relief="solid")
        notes_box.pack(fill="both", expand=True)

        tk.Label(
            notes_box, text="📝  ПОСЛЕДНИЕ ЗАМЕТКИ",
            font=("Segoe UI", 11, "bold"), fg=self.ACCENT_CYAN, bg=self.BG_CARD
        ).pack(anchor="w", padx=20, pady=(14, 8))

        notes = self.household.notes[-3:] if self.household.notes else []
        if not notes:
            tk.Label(notes_box, text="Заметок пока нет. Создайте первую заметку через раздел Заметки или команду внизу.", font=("Segoe UI", 9), fg=self.FG_MUTED, bg=self.BG_CARD).pack(anchor="w", padx=20, pady=6)
        else:
            n_row = tk.Frame(notes_box, bg=self.BG_CARD)
            n_row.pack(fill="both", expand=True, padx=20, pady=(0, 14))
            for n in notes:
                item_card = tk.Frame(n_row, bg="#13171f", bd=1, relief="solid")
                item_card.pack(side="left", fill="both", expand=True, padx=6)
                tk.Label(item_card, text=n["title"], font=("Segoe UI", 10, "bold"), fg=self.FG_WHITE, bg="#13171f").pack(anchor="w", padx=12, pady=(10, 4))
                c_prev = n["content"][:80] + ("..." if len(n["content"]) > 80 else "")
                tk.Label(item_card, text=c_prev, font=("Segoe UI", 9), fg=self.FG_MUTED, bg="#13171f", justify="left", wraplength=280).pack(anchor="w", padx=12, pady=(0, 10))

    def _quick_complete_task(self, task_id):
        self.household.complete_task(task_id)
        if self.current_section == "home":
            self._switch_section("home")

    # =========================================================================
    # ЭКРАН 2: ЧАТ И АССИСТЕНТ
    # =========================================================================

    def _render_chat_view(self):
        chat_split = tk.Frame(self.workspace, bg=self.BG_MAIN)
        chat_split.pack(fill="both", expand=True)

        # Левая колонка: Лента диалога
        left_chat = tk.Frame(chat_split, bg=self.BG_CARD, bd=1, relief="solid")
        left_chat.pack(side="left", fill="both", expand=True, padx=(0, 14))

        chat_header = tk.Frame(left_chat, bg=self.BG_CARD)
        chat_header.pack(fill="x", padx=16, pady=12)

        tk.Label(
            chat_header, text="ДИАЛОГ С АКАКИЕМ",
            font=("Segoe UI", 11, "bold"), fg=self.FG_WHITE, bg=self.BG_CARD
        ).pack(side="left")

        btn_clear = tk.Button(
            chat_header, text="Очистить", font=("Segoe UI", 8),
            fg=self.FG_MUTED, bg="#21262d", bd=0, cursor="hand2",
            command=self._clear_chat
        )
        btn_clear.pack(side="right")
        _bind_hover(btn_clear, "#21262d", "#30363d")

        self.chat_text = tk.Text(
            left_chat, bg="#0d1117", fg=self.FG_MAIN,
            font=("Segoe UI", 10), wrap="word", bd=0, padx=14, pady=14
        )
        self.chat_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Теги для подсветки сообщений
        self.chat_text.tag_config("user_title", foreground=self.ACCENT_CYAN, font=("Segoe UI", 9, "bold"))
        self.chat_text.tag_config("akakiy_title", foreground=self.ACCENT_GREEN, font=("Segoe UI", 9, "bold"))
        self.chat_text.tag_config("time", foreground=self.FG_DIM, font=("Segoe UI", 8))
        self.chat_text.tag_config("user_body", foreground=self.FG_WHITE)
        self.chat_text.tag_config("akakiy_body", foreground=self.FG_MAIN)
        self.chat_text.tag_config("div", foreground=self.BORDER_COL)

        # Правая колонка: Лог инструментов и процессов
        right_log = tk.Frame(chat_split, bg=self.BG_CARD, bd=1, relief="solid", width=380)
        right_log.pack(side="right", fill="both")
        right_log.pack_propagate(False)

        tk.Label(
            right_log, text="СИСТЕМНЫЙ ЛОГ И ИНСТРУМЕНТЫ",
            font=("Segoe UI", 10, "bold"), fg=self.FG_MUTED, bg=self.BG_CARD
        ).pack(anchor="w", padx=16, pady=12)

        self.log_text = tk.Text(
            right_log, bg="#0d1117", fg=self.FG_MUTED,
            font=("Consolas", 8), wrap="word", bd=0, padx=10, pady=10
        )
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log_text.tag_config("info", foreground=self.ACCENT_CYAN)
        self.log_text.tag_config("tool", foreground=self.ACCENT_PURPLE)
        self.log_text.tag_config("done", foreground=self.ACCENT_GREEN)
        self.log_text.tag_config("err", foreground=self.ACCENT_RED)

        # Восстановление сохранённых сообщений сессии
        if not self.chat_messages:
            self._append_chat("Акакий", "Привет! Чем я могу помочь? Задавай вопросы, управляй делами или работай с проектом.")
        else:
            for author, message, t_str in self.chat_messages:
                self._insert_chat_ui(author, message, t_str)

        for prefix, text, t_str in self.log_messages:
            self._insert_log_ui(prefix, text, t_str)

    def _insert_chat_ui(self, author: str, message: str, t_str: str):
        if not hasattr(self, "chat_text") or not self.chat_text.winfo_exists():
            return
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
        if not hasattr(self, "log_text") or not self.log_text.winfo_exists():
            return
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
        if hasattr(self, "chat_text") and self.chat_text.winfo_exists():
            self.chat_text.delete("1.0", tk.END)
        if hasattr(self, "log_text") and self.log_text.winfo_exists():
            self.log_text.delete("1.0", tk.END)
        if hasattr(self.agent, "context_mgr") and hasattr(self.agent.context_mgr, "clear_history"):
            self.agent.context_mgr.clear_history()

    # =========================================================================
    # ЭКРАН 3: ЗАДАЧИ (TASKS)
    # =========================================================================

    def _render_tasks_view(self):
        header_row = tk.Frame(self.workspace, bg=self.BG_MAIN)
        header_row.pack(fill="x", pady=(0, 16))

        tk.Label(
            header_row, text="УПРАВЛЕНИЕ ЗАДАЧАМИ (TASKS)",
            font=("Segoe UI", 14, "bold"), fg=self.FG_WHITE, bg=self.BG_MAIN
        ).pack(side="left")

        # Форма добавления задачи
        add_box = tk.Frame(self.workspace, bg=self.BG_CARD, bd=1, relief="solid")
        add_box.pack(fill="x", pady=(0, 16), ipady=4)

        tk.Label(add_box, text="Новая задача:", font=("Segoe UI", 10, "bold"), fg=self.FG_WHITE, bg=self.BG_CARD).pack(side="left", padx=16)

        self.entry_task = tk.Entry(add_box, font=("Segoe UI", 11), bg="#13171f", fg=self.FG_WHITE, bd=1, relief="solid")
        self.entry_task.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self.entry_task.bind("<Return>", lambda e: self._ui_create_task())

        btn_add = tk.Button(
            add_box, text="Добавить", font=("Segoe UI", 9, "bold"), bg=self.ACCENT_CYAN, fg="#0d1117", bd=0, padx=16, pady=6, cursor="hand2",
            command=self._ui_create_task
        )
        btn_add.pack(side="left", padx=16)

        # Контейнер списка задач
        self.tasks_list_frame = tk.Frame(self.workspace, bg=self.BG_CARD, bd=1, relief="solid")
        self.tasks_list_frame.pack(fill="both", expand=True)

        self._refresh_tasks_list()

    def _ui_create_task(self):
        txt = self.entry_task.get().strip()
        if txt:
            self.household.create_task(txt)
            self.entry_task.delete(0, tk.END)
            self._refresh_tasks_list()

    def _refresh_tasks_list(self):
        for w in self.tasks_list_frame.winfo_children():
            w.destroy()

        tasks = self.household.list_tasks(status="all")["tasks"]
        if not tasks:
            tk.Label(self.tasks_list_frame, text="Задач пока нет.", font=("Segoe UI", 11), fg=self.FG_MUTED, bg=self.BG_CARD).pack(pady=40)
            return

        for t in reversed(tasks):
            row = tk.Frame(self.tasks_list_frame, bg="#13171f", bd=1, relief="solid")
            row.pack(fill="x", padx=16, pady=4)

            # Чекбокс
            is_done = t.get("completed", False)
            btn_txt = "☑" if is_done else "☐"
            btn_color = self.ACCENT_GREEN if is_done else self.FG_MUTED

            chk = tk.Button(
                row, text=btn_txt, font=("Segoe UI", 12), fg=btn_color, bg="#13171f", bd=0, cursor="hand2",
                command=lambda tid=t["id"]: self._ui_toggle_task(tid)
            )
            chk.pack(side="left", padx=12, pady=8)

            t_fg = self.FG_MUTED if is_done else self.FG_WHITE
            tk.Label(row, text=f"#{t['id']} {t['title']}", font=("Segoe UI", 10), fg=t_fg, bg="#13171f").pack(side="left", padx=4)

            # Дата
            tk.Label(row, text=t.get("created_at", ""), font=("Consolas", 8), fg=self.FG_DIM, bg="#13171f").pack(side="right", padx=12)

            # Кнопка удаления
            btn_del = tk.Button(
                row, text="✕", font=("Segoe UI", 9), fg=self.ACCENT_RED, bg="#13171f", bd=0, cursor="hand2",
                command=lambda tid=t["id"]: self._ui_delete_task(tid)
            )
            btn_del.pack(side="right", padx=8)

    def _ui_toggle_task(self, task_id):
        self.household.complete_task(task_id)
        self._refresh_tasks_list()

    def _ui_delete_task(self, task_id):
        if messagebox.askyesno("Подтверждение", f"Удалить задачу #{task_id}?"):
            self.household.delete_task(task_id)
            self._refresh_tasks_list()

    # =========================================================================
    # ЭКРАН 4: НАПОМИНАНИЯ (REMINDERS)
    # =========================================================================

    def _render_reminders_view(self):
        header_row = tk.Frame(self.workspace, bg=self.BG_MAIN)
        header_row.pack(fill="x", pady=(0, 16))

        tk.Label(
            header_row, text="НАПОМИНАНИЯ (REMINDERS)",
            font=("Segoe UI", 14, "bold"), fg=self.FG_WHITE, bg=self.BG_MAIN
        ).pack(side="left")

        btn_check = tk.Button(
            header_row, text="🔔 Проверить наступившие", font=("Segoe UI", 9, "bold"),
            bg=self.ACCENT_PURPLE, fg=self.FG_WHITE, bd=0, padx=12, pady=4, cursor="hand2",
            command=self._ui_check_reminders
        )
        btn_check.pack(side="right")

        # Форма добавления
        add_box = tk.Frame(self.workspace, bg=self.BG_CARD, bd=1, relief="solid")
        add_box.pack(fill="x", pady=(0, 16), ipady=4)

        tk.Label(add_box, text="О чём напомнить:", font=("Segoe UI", 9, "bold"), fg=self.FG_WHITE, bg=self.BG_CARD).pack(side="left", padx=12)
        self.entry_rem_text = tk.Entry(add_box, font=("Segoe UI", 10), bg="#13171f", fg=self.FG_WHITE, bd=1, relief="solid")
        self.entry_rem_text.pack(side="left", fill="x", expand=True, padx=6, pady=8)

        tk.Label(add_box, text="Время (19:00 / завтра в 10:00):", font=("Segoe UI", 9, "bold"), fg=self.FG_WHITE, bg=self.BG_CARD).pack(side="left", padx=12)
        self.entry_rem_time = tk.Entry(add_box, font=("Segoe UI", 10), bg="#13171f", fg=self.FG_WHITE, bd=1, relief="solid", width=18)
        self.entry_rem_time.pack(side="left", padx=6, pady=8)

        btn_add = tk.Button(
            add_box, text="Установить", font=("Segoe UI", 9, "bold"), bg=self.ACCENT_PURPLE, fg=self.FG_WHITE, bd=0, padx=14, pady=6, cursor="hand2",
            command=self._ui_create_reminder
        )
        btn_add.pack(side="left", padx=12)

        # Контейнер списка
        self.rems_list_frame = tk.Frame(self.workspace, bg=self.BG_CARD, bd=1, relief="solid")
        self.rems_list_frame.pack(fill="both", expand=True)

        self._refresh_reminders_list()

    def _ui_create_reminder(self):
        txt = self.entry_rem_text.get().strip()
        tm = self.entry_rem_time.get().strip()
        if txt and tm:
            self.household.create_reminder(txt, tm)
            self.entry_rem_text.delete(0, tk.END)
            self.entry_rem_time.delete(0, tk.END)
            self._refresh_reminders_list()

    def _ui_check_reminders(self):
        res = self.household.check_due_reminders()
        messagebox.showinfo("Напоминания", res["message"])
        self._refresh_reminders_list()

    def _refresh_reminders_list(self):
        for w in self.rems_list_frame.winfo_children():
            w.destroy()

        rems = self.household.list_reminders(include_triggered=True)["reminders"]
        if not rems:
            tk.Label(self.rems_list_frame, text="Напоминаний нет.", font=("Segoe UI", 11), fg=self.FG_MUTED, bg=self.BG_CARD).pack(pady=40)
            return

        for r in reversed(rems):
            row = tk.Frame(self.rems_list_frame, bg="#13171f", bd=1, relief="solid")
            row.pack(fill="x", padx=16, pady=4)

            icon = "🔔" if not r.get("triggered") else "✔"
            tk.Label(row, text=icon, font=("Segoe UI", 11), fg=self.ACCENT_PURPLE, bg="#13171f").pack(side="left", padx=12, pady=8)
            tk.Label(row, text=f"#{r['id']} {r['text']}", font=("Segoe UI", 10), fg=self.FG_WHITE, bg="#13171f").pack(side="left", padx=4)

            tk.Label(row, text=f"Время: {r['remind_at']}", font=("Consolas", 9), fg=self.ACCENT_CYAN, bg="#13171f").pack(side="right", padx=16)

            btn_del = tk.Button(
                row, text="✕", font=("Segoe UI", 9), fg=self.ACCENT_RED, bg="#13171f", bd=0, cursor="hand2",
                command=lambda rid=r["id"]: self._ui_delete_reminder(rid)
            )
            btn_del.pack(side="right", padx=8)

    def _ui_delete_reminder(self, reminder_id):
        if messagebox.askyesno("Подтверждение", f"Удалить напоминание #{reminder_id}?"):
            self.household.delete_reminder(reminder_id)
            self._refresh_reminders_list()

    # =========================================================================
    # ЭКРАН 5: ЗАМЕТКИ (NOTES)
    # =========================================================================

    def _render_notes_view(self):
        header_row = tk.Frame(self.workspace, bg=self.BG_MAIN)
        header_row.pack(fill="x", pady=(0, 16))

        tk.Label(
            header_row, text="ЗАМЕТКИ (NOTES)",
            font=("Segoe UI", 14, "bold"), fg=self.FG_WHITE, bg=self.BG_MAIN
        ).pack(side="left")

        # Поиск заметок
        search_box = tk.Frame(header_row, bg=self.BG_MAIN)
        search_box.pack(side="right")
        tk.Label(search_box, text="Поиск:", font=("Segoe UI", 9), fg=self.FG_MUTED, bg=self.BG_MAIN).pack(side="left", padx=4)
        self.entry_note_search = tk.Entry(search_box, font=("Segoe UI", 10), bg=self.BG_CARD, fg=self.FG_WHITE, width=20, bd=1, relief="solid")
        self.entry_note_search.pack(side="left", padx=4)
        self.entry_note_search.bind("<KeyRelease>", lambda e: self._refresh_notes_list())

        # Форма создания
        create_box = tk.Frame(self.workspace, bg=self.BG_CARD, bd=1, relief="solid")
        create_box.pack(fill="x", pady=(0, 16), padx=0)

        tk.Label(create_box, text="Заголовок:", font=("Segoe UI", 9, "bold"), fg=self.FG_WHITE, bg=self.BG_CARD).pack(anchor="w", padx=16, pady=(10, 2))
        self.entry_note_title = tk.Entry(create_box, font=("Segoe UI", 10), bg="#13171f", fg=self.FG_WHITE, bd=1, relief="solid")
        self.entry_note_title.pack(fill="x", padx=16, pady=(0, 6))

        tk.Label(create_box, text="Текст заметки:", font=("Segoe UI", 9, "bold"), fg=self.FG_WHITE, bg=self.BG_CARD).pack(anchor="w", padx=16, pady=(4, 2))
        self.entry_note_content = tk.Entry(create_box, font=("Segoe UI", 10), bg="#13171f", fg=self.FG_WHITE, bd=1, relief="solid")
        self.entry_note_content.pack(fill="x", padx=16, pady=(0, 10))

        btn_save = tk.Button(
            create_box, text="Сохранить заметку", font=("Segoe UI", 9, "bold"), bg=self.ACCENT_CYAN, fg="#0d1117", bd=0, padx=14, pady=6, cursor="hand2",
            command=self._ui_create_note
        )
        btn_save.pack(anchor="e", padx=16, pady=(0, 12))

        # Контейнер плиток
        self.notes_list_frame = tk.Frame(self.workspace, bg=self.BG_MAIN)
        self.notes_list_frame.pack(fill="both", expand=True)

        self._refresh_notes_list()

    def _ui_create_note(self):
        title = self.entry_note_title.get().strip()
        content = self.entry_note_content.get().strip()
        if title or content:
            self.household.create_note(title, content)
            self.entry_note_title.delete(0, tk.END)
            self.entry_note_content.delete(0, tk.END)
            self._refresh_notes_list()

    def _refresh_notes_list(self):
        for w in self.notes_list_frame.winfo_children():
            w.destroy()

        q = getattr(self, "entry_note_search", None)
        query = q.get().strip() if q else ""
        if query:
            notes = self.household.search_notes(query)["notes"]
        else:
            notes = self.household.list_notes()["notes"]

        if not notes:
            tk.Label(self.notes_list_frame, text="Заметок не найдено.", font=("Segoe UI", 11), fg=self.FG_MUTED, bg=self.BG_MAIN).pack(pady=30)
            return

        for n in reversed(notes):
            card = tk.Frame(self.notes_list_frame, bg=self.BG_CARD, bd=1, relief="solid")
            card.pack(fill="x", pady=4)

            top_line = tk.Frame(card, bg=self.BG_CARD)
            top_line.pack(fill="x", padx=14, pady=(10, 4))

            tk.Label(top_line, text=f"#{n['id']} {n['title']}", font=("Segoe UI", 10, "bold"), fg=self.FG_WHITE, bg=self.BG_CARD).pack(side="left")
            tk.Label(top_line, text=n.get("created_at", ""), font=("Consolas", 8), fg=self.FG_DIM, bg=self.BG_CARD).pack(side="right", padx=8)

            btn_del = tk.Button(
                top_line, text="✕", font=("Segoe UI", 9), fg=self.ACCENT_RED, bg=self.BG_CARD, bd=0, cursor="hand2",
                command=lambda nid=n["id"]: self._ui_delete_note(nid)
            )
            btn_del.pack(side="right")

            tk.Label(
                card, text=n.get("content", ""), font=("Segoe UI", 9), fg=self.FG_MAIN, bg=self.BG_CARD, justify="left", wraplength=800
            ).pack(anchor="w", padx=14, pady=(0, 12))

    def _ui_delete_note(self, note_id):
        if messagebox.askyesno("Подтверждение", f"Удалить заметку #{note_id}?"):
            self.household.delete_note(note_id)
            self._refresh_notes_list()

    # =========================================================================
    # ЭКРАН 6: СПИСКИ (LISTS)
    # =========================================================================

    def _render_lists_view(self):
        header_row = tk.Frame(self.workspace, bg=self.BG_MAIN)
        header_row.pack(fill="x", pady=(0, 16))

        tk.Label(
            header_row, text="СПИСКИ (LISTS)",
            font=("Segoe UI", 14, "bold"), fg=self.FG_WHITE, bg=self.BG_MAIN
        ).pack(side="left")

        body_split = tk.Frame(self.workspace, bg=self.BG_MAIN)
        body_split.pack(fill="both", expand=True)

        # Левая часть: перечень списков + добавление списка
        left_pane = tk.Frame(body_split, bg=self.BG_CARD, bd=1, relief="solid", width=300)
        left_pane.pack(side="left", fill="y", padx=(0, 14))
        left_pane.pack_propagate(False)

        tk.Label(left_pane, text="ВАШИ СПИСКИ", font=("Segoe UI", 10, "bold"), fg=self.FG_WHITE, bg=self.BG_CARD).pack(anchor="w", padx=14, pady=12)

        new_l_box = tk.Frame(left_pane, bg=self.BG_CARD)
        new_l_box.pack(fill="x", padx=14, pady=(0, 10))
        self.entry_new_list = tk.Entry(new_l_box, font=("Segoe UI", 9), bg="#13171f", fg=self.FG_WHITE, bd=1, relief="solid")
        self.entry_new_list.pack(side="left", fill="x", expand=True, padx=(0, 4))
        btn_create_l = tk.Button(
            new_l_box, text="+", font=("Segoe UI", 9, "bold"), bg=self.ACCENT_GREEN, fg="#0d1117", bd=0, padx=8, cursor="hand2",
            command=self._ui_create_list
        )
        btn_create_l.pack(side="left")

        self.list_names_box = tk.Frame(left_pane, bg=self.BG_CARD)
        self.list_names_box.pack(fill="both", expand=True, padx=8, pady=4)

        # Правая часть: элементы выбранного списка
        self.right_items_pane = tk.Frame(body_split, bg=self.BG_CARD, bd=1, relief="solid")
        self.right_items_pane.pack(side="left", fill="both", expand=True)

        self._refresh_lists_menu()

    def _ui_create_list(self):
        name = self.entry_new_list.get().strip().lower()
        if name:
            self.household.create_list(name)
            self.entry_new_list.delete(0, tk.END)
            self.current_selected_list = name
            self._refresh_lists_menu()

    def _refresh_lists_menu(self):
        for w in self.list_names_box.winfo_children():
            w.destroy()

        lists = list(self.household.lists.keys())
        if not lists:
            tk.Label(self.list_names_box, text="Нет списков.", font=("Segoe UI", 9), fg=self.FG_MUTED, bg=self.BG_CARD).pack(pady=10)
            self._render_selected_list_items("")
            return

        if not self.current_selected_list or self.current_selected_list not in lists:
            self.current_selected_list = lists[0]

        for l_name in lists:
            cnt = len(self.household.lists[l_name])
            is_active = (l_name == self.current_selected_list)
            btn_bg = self.BG_ACTIVE if is_active else "#13171f"
            btn_fg = self.ACCENT_CYAN if is_active else self.FG_MAIN

            b = tk.Button(
                self.list_names_box,
                text=f"• {l_name} ({cnt})",
                font=("Segoe UI", 9, "bold" if is_active else "normal"),
                fg=btn_fg, bg=btn_bg, bd=0, anchor="w", padx=10, pady=6, cursor="hand2",
                command=lambda name=l_name: self._select_list(name)
            )
            b.pack(fill="x", pady=2)
            _bind_hover(b, btn_bg, self.BG_HOVER)

        self._render_selected_list_items(self.current_selected_list)

    def _select_list(self, name: str):
        self.current_selected_list = name
        self._refresh_lists_menu()

    def _render_selected_list_items(self, list_name: str):
        for w in self.right_items_pane.winfo_children():
            w.destroy()

        if not list_name or list_name not in self.household.lists:
            tk.Label(self.right_items_pane, text="Выберите или создайте список слева.", font=("Segoe UI", 11), fg=self.FG_MUTED, bg=self.BG_CARD).pack(pady=40)
            return

        header = tk.Frame(self.right_items_pane, bg=self.BG_CARD)
        header.pack(fill="x", padx=16, pady=12)

        tk.Label(header, text=f"СПИСОК: {list_name.upper()}", font=("Segoe UI", 12, "bold"), fg=self.ACCENT_GREEN, bg=self.BG_CARD).pack(side="left")

        btn_del_list = tk.Button(
            header, text="Удалить список целиком", font=("Segoe UI", 8), fg=self.ACCENT_RED, bg="#21262d", bd=0, padx=8, pady=4, cursor="hand2",
            command=lambda: self._ui_delete_entire_list(list_name)
        )
        btn_del_list.pack(side="right")

        # Форма добавления пункта
        add_item_box = tk.Frame(self.right_items_pane, bg=self.BG_CARD)
        add_item_box.pack(fill="x", padx=16, pady=(0, 12))

        self.entry_item_text = tk.Entry(add_item_box, font=("Segoe UI", 10), bg="#13171f", fg=self.FG_WHITE, bd=1, relief="solid")
        self.entry_item_text.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_item_text.bind("<Return>", lambda e: self._ui_add_item(list_name))

        btn_add_item = tk.Button(
            add_item_box, text="Добавить пункт", font=("Segoe UI", 9, "bold"), bg=self.ACCENT_GREEN, fg="#0d1117", bd=0, padx=12, pady=5, cursor="hand2",
            command=lambda: self._ui_add_item(list_name)
        )
        btn_add_item.pack(side="left")

        # Пункты списка
        items = self.household.lists[list_name]
        items_scroll = tk.Frame(self.right_items_pane, bg=self.BG_CARD)
        items_scroll.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        if not items:
            tk.Label(items_scroll, text="Список пуст.", font=("Segoe UI", 10), fg=self.FG_MUTED, bg=self.BG_CARD).pack(anchor="w", pady=10)
        else:
            for it in items:
                row = tk.Frame(items_scroll, bg="#13171f", bd=1, relief="solid")
                row.pack(fill="x", pady=2)

                is_done = it.get("completed", False)
                btn_txt = "☑" if is_done else "☐"
                chk = tk.Button(
                    row, text=btn_txt, font=("Segoe UI", 11), fg=self.ACCENT_GREEN if is_done else self.FG_MUTED,
                    bg="#13171f", bd=0, cursor="hand2",
                    command=lambda iid=it["id"]: self._ui_toggle_item(list_name, iid)
                )
                chk.pack(side="left", padx=8, pady=4)

                tk.Label(row, text=it["text"], font=("Segoe UI", 9), fg=self.FG_MUTED if is_done else self.FG_WHITE, bg="#13171f").pack(side="left", padx=4)

                btn_del = tk.Button(
                    row, text="✕", font=("Segoe UI", 8), fg=self.ACCENT_RED, bg="#13171f", bd=0, cursor="hand2",
                    command=lambda iid=it["id"]: self._ui_delete_item(list_name, iid)
                )
                btn_del.pack(side="right", padx=8)

    def _ui_add_item(self, list_name: str):
        txt = self.entry_item_text.get().strip()
        if txt:
            self.household.add_list_item(list_name, txt)
            self._render_selected_list_items(list_name)

    def _ui_toggle_item(self, list_name: str, item_id: int):
        self.household.complete_list_item(list_name, item_id)
        self._render_selected_list_items(list_name)

    def _ui_delete_item(self, list_name: str, item_id: int):
        self.household.delete_list_item(list_name, item_id)
        self._render_selected_list_items(list_name)

    def _ui_delete_entire_list(self, list_name: str):
        if messagebox.askyesno("Подтверждение", f"Удалить весь список '{list_name}'?"):
            self.household.delete_list(list_name)
            self.current_selected_list = ""
            self._refresh_lists_menu()

    # =========================================================================
    # ЭКРАН 7: ПАМЯТЬ (MEMORY)
    # =========================================================================

    def _render_memory_view(self):
        header_row = tk.Frame(self.workspace, bg=self.BG_MAIN)
        header_row.pack(fill="x", pady=(0, 16))

        tk.Label(
            header_row, text="ДОЛГОВРЕМЕННАЯ ПАМЯТЬ (MEMORY)",
            font=("Segoe UI", 14, "bold"), fg=self.FG_WHITE, bg=self.BG_MAIN
        ).pack(side="left")

        # Форма добавления факта
        add_box = tk.Frame(self.workspace, bg=self.BG_CARD, bd=1, relief="solid")
        add_box.pack(fill="x", pady=(0, 16), ipady=4)

        tk.Label(add_box, text="Запомнить факт:", font=("Segoe UI", 9, "bold"), fg=self.FG_WHITE, bg=self.BG_CARD).pack(side="left", padx=12)
        self.entry_mem = tk.Entry(add_box, font=("Segoe UI", 10), bg="#13171f", fg=self.FG_WHITE, bd=1, relief="solid")
        self.entry_mem.pack(side="left", fill="x", expand=True, padx=6, pady=8)
        self.entry_mem.bind("<Return>", lambda e: self._ui_remember())

        btn_add = tk.Button(
            add_box, text="Запомнить", font=("Segoe UI", 9, "bold"), bg=self.ACCENT_CYAN, fg="#0d1117", bd=0, padx=14, pady=6, cursor="hand2",
            command=self._ui_remember
        )
        btn_add.pack(side="left", padx=12)

        # Контейнер списка памяти
        self.mem_list_frame = tk.Frame(self.workspace, bg=self.BG_CARD, bd=1, relief="solid")
        self.mem_list_frame.pack(fill="both", expand=True)

        self._refresh_memory_list()

    def _ui_remember(self):
        txt = self.entry_mem.get().strip()
        if txt:
            ok, msg, _ = self.memory.remember(txt)
            if not ok:
                messagebox.showwarning("Память", msg)
            self.entry_mem.delete(0, tk.END)
            self._refresh_memory_list()

    def _refresh_memory_list(self):
        for w in self.mem_list_frame.winfo_children():
            w.destroy()

        memories = self.memory.get_all()
        if not memories:
            tk.Label(self.mem_list_frame, text="Долговременная память пуста.", font=("Segoe UI", 11), fg=self.FG_MUTED, bg=self.BG_CARD).pack(pady=40)
            return

        for m in reversed(memories):
            row = tk.Frame(self.mem_list_frame, bg="#13171f", bd=1, relief="solid")
            row.pack(fill="x", padx=16, pady=4)

            tk.Label(row, text="🧠", font=("Segoe UI", 10), fg=self.ACCENT_CYAN, bg="#13171f").pack(side="left", padx=10, pady=8)
            tk.Label(row, text=f"#{m['id']} {m['text']}", font=("Segoe UI", 9), fg=self.FG_WHITE, bg="#13171f").pack(side="left", padx=4)

            btn_del = tk.Button(
                row, text="✕", font=("Segoe UI", 8), fg=self.ACCENT_RED, bg="#13171f", bd=0, cursor="hand2",
                command=lambda mid=m["id"]: self._ui_forget(mid)
            )
            btn_del.pack(side="right", padx=8)

            tk.Label(row, text=m.get("created_at", ""), font=("Consolas", 8), fg=self.FG_DIM, bg="#13171f").pack(side="right", padx=8)

    def _ui_forget(self, mem_id):
        if messagebox.askyesno("Подтверждение", f"Забыть запись #{mem_id}?"):
            self.memory.forget(mem_id)
            self._refresh_memory_list()

    # =========================================================================
    # ЭКРАН 8: НАСТРОЙКИ И ДИАГНОСТИКА (SETTINGS)
    # =========================================================================

    def _render_settings_view(self):
        header_row = tk.Frame(self.workspace, bg=self.BG_MAIN)
        header_row.pack(fill="x", pady=(0, 16))

        tk.Label(
            header_row, text="НАСТРОЙКИ И ДИАГНОСТИКА СИСТЕМЫ",
            font=("Segoe UI", 14, "bold"), fg=self.FG_WHITE, bg=self.BG_MAIN
        ).pack(side="left")

        panel = tk.Frame(self.workspace, bg=self.BG_CARD, bd=1, relief="solid")
        panel.pack(fill="both", expand=True, padx=0, pady=0)

        # 1. Секция моделей
        tk.Label(panel, text="ИНТЕЛЛЕКТУАЛЬНЫЙ БЭКЕНД", font=("Segoe UI", 11, "bold"), fg=self.ACCENT_CYAN, bg=self.BG_CARD).pack(anchor="w", padx=20, pady=(20, 8))
        tk.Label(panel, text="• LLM Engine: Ollama Local Server (http://localhost:11434)\n• Модель: qwen3:8b\n• Skills Registry: project, memory, household\n• Context Manager: Sliding Window + Data Injection Shield", font=("Segoe UI", 9), fg=self.FG_MAIN, bg=self.BG_CARD, justify="left").pack(anchor="w", padx=20, pady=(0, 16))

        # 2. Секция валидации
        tk.Label(panel, text="ПРОВЕРКА ЦЕЛОСТНОСТИ ПРОЕКТА", font=("Segoe UI", 11, "bold"), fg=self.ACCENT_GREEN, bg=self.BG_CARD).pack(anchor="w", padx=20, pady=(10, 8))
        btn_val = tk.Button(
            panel, text="Запустить validate_project()", font=("Segoe UI", 9, "bold"), bg=self.ACCENT_GREEN, fg="#0d1117", bd=0, padx=14, pady=6, cursor="hand2",
            command=self._ui_run_validation
        )
        btn_val.pack(anchor="w", padx=20, pady=(0, 8))
        self.lbl_val_res = tk.Label(panel, text="", font=("Consolas", 9), fg=self.FG_MUTED, bg=self.BG_CARD)
        self.lbl_val_res.pack(anchor="w", padx=20, pady=(0, 16))

        # 3. Секция хранилищ
        tk.Label(panel, text="ЛОКАЛЬНЫЕ ДАННЫЕ", font=("Segoe UI", 11, "bold"), fg=self.ACCENT_PURPLE, bg=self.BG_CARD).pack(anchor="w", padx=20, pady=(10, 8))
        tk.Label(panel, text="• Долговременная память: data/memory.json (изолировано)\n• Бытовой слой: data/household.json (Tasks, Reminders, Notes, Lists)\n• Git Protection: data/ вне репозитория (.gitignore)", font=("Segoe UI", 9), fg=self.FG_MAIN, bg=self.BG_CARD, justify="left").pack(anchor="w", padx=20, pady=(0, 20))

    def _ui_run_validation(self):
        res = validate_project()
        if res.get("success"):
            self.lbl_val_res.config(text=f"✓ Проект валиден: проверено {res.get('files_checked')} файлов, 0 синтаксических ошибок.", fg=self.ACCENT_GREEN)
        else:
            self.lbl_val_res.config(text=f"✗ Ошибки валидации: {res.get('errors')}", fg=self.ACCENT_RED)

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
            self._switch_section("home")
        elif sec == "tasks":
            if hasattr(self, "tasks_list_frame") and self.tasks_list_frame.winfo_exists():
                self._refresh_tasks_list()
        elif sec == "reminders":
            if hasattr(self, "rems_list_frame") and self.rems_list_frame.winfo_exists():
                self._refresh_reminders_list()
        elif sec == "notes":
            if hasattr(self, "notes_list_frame") and self.notes_list_frame.winfo_exists():
                self._refresh_notes_list()
        elif sec == "lists":
            if hasattr(self, "list_names_box") and self.list_names_box.winfo_exists():
                self._refresh_lists_menu()
        elif sec == "memory":
            if hasattr(self, "mem_list_frame") and self.mem_list_frame.winfo_exists():
                self._refresh_memory_list()

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
