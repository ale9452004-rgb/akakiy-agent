"""
Модульное окно уведомления (NotificationWindow) для интерфейса Акакия.
Отображается поверх окон в фирменном тёмном стиле.
"""

import tkinter as tk
from typing import Callable, List, Optional

from notifications.models import NotificationAction, NotificationItem


def _bind_hover(
    widget: tk.Widget,
    normal_bg: str,
    hover_bg: str,
    normal_fg: Optional[str] = None,
    hover_fg: Optional[str] = None
) -> None:
    """Безопасная привязка эффектов наведения курсора."""
    def on_enter(e):
        try:
            if widget.winfo_exists():
                widget.config(bg=hover_bg)
                if hover_fg is not None:
                    widget.config(fg=hover_fg)
        except Exception:
            pass

    def on_leave(e):
        try:
            if widget.winfo_exists():
                widget.config(bg=normal_bg)
                if normal_fg is not None:
                    widget.config(fg=normal_fg)
        except Exception:
            pass

    widget.bind("<Enter>", on_enter)
    widget.bind("<Leave>", on_leave)


class NotificationWindow(tk.Toplevel):
    """
    Плавающее окно уведомления (Toplevel).
    """

    BG_OUTER = "#30363d"       # Рамка 1px
    BG_CARD = "#161b22"        # Основной фон карточки
    FG_WHITE = "#ffffff"
    FG_MAIN = "#c9d1d9"
    FG_MUTED = "#8b949e"

    TYPE_CONFIGS = {
        "reminder": {
            "badge_text": "🔔  НАПОМИНАНИЕ",
            "badge_fg": "#c084fc",
            "badge_bg": "#21153b",
        },
        "info": {
            "badge_text": "ℹ  ИНФОРМАЦИЯ",
            "badge_fg": "#38bdf8",
            "badge_bg": "#112338",
        },
        "warning": {
            "badge_text": "⚠  ВНИМАНИЕ",
            "badge_fg": "#fbbf24",
            "badge_bg": "#2d2010",
        },
        "success": {
            "badge_text": "✓  УСПЕШНО",
            "badge_fg": "#34d399",
            "badge_bg": "#112d1b",
        },
        "error": {
            "badge_text": "✖  ОШИБКА",
            "badge_fg": "#f87171",
            "badge_bg": "#361414",
        },
    }

    def __init__(
        self,
        master: tk.Widget,
        item: NotificationItem,
        on_dismiss: Optional[Callable[[str], None]] = None,
        width: int = 340,
        height: int = 135,
        **kwargs
    ):
        super().__init__(master, **kwargs)
        self.item = item
        self.on_dismiss = on_dismiss
        self.width = width
        self.height = height
        self._is_closed = False

        self.action_buttons: List[tk.Button] = []
        self.btn_close: Optional[tk.Button] = None

        self._setup_window()
        self._build_ui()

    def _setup_window(self) -> None:
        """Настройка свойств окна Toplevel."""
        try:
            self.overrideredirect(True)
        except Exception:
            pass
        try:
            self.attributes("-topmost", True)
        except Exception:
            pass
        self.config(bg=self.BG_OUTER)

    def _build_ui(self) -> None:
        """Построение интерфейса карточки уведомления."""
        # Внутренний контейнер с отступом 1px (образует 1px рамку)
        self.inner_frame = tk.Frame(self, bg=self.BG_CARD)
        self.inner_frame.pack(fill="both", expand=True, padx=1, pady=1)

        type_cfg = self.TYPE_CONFIGS.get(
            self.item.notification_type,
            self.TYPE_CONFIGS["info"]
        )

        # 1. Верхняя строка: Бейдж типа + Кнопка закрытия
        top_row = tk.Frame(self.inner_frame, bg=self.BG_CARD)
        top_row.pack(fill="x", padx=12, pady=(10, 4))

        lbl_badge = tk.Label(
            top_row,
            text=type_cfg["badge_text"],
            font=("Segoe UI", 8, "bold"),
            fg=type_cfg["badge_fg"],
            bg=type_cfg["badge_bg"],
            padx=8,
            pady=2
        )
        lbl_badge.pack(side="left")

        self.btn_close = tk.Button(
            top_row,
            text="×",
            font=("Segoe UI", 12, "bold"),
            fg=self.FG_MUTED,
            bg=self.BG_CARD,
            activeforeground=self.FG_WHITE,
            activebackground="#21262d",
            bd=0,
            cursor="hand2",
            padx=4,
            pady=0,
            command=self.close
        )
        self.btn_close.pack(side="right")
        _bind_hover(self.btn_close, self.BG_CARD, "#21262d", self.FG_MUTED, self.FG_WHITE)

        # 2. Основной текст
        body_frame = tk.Frame(self.inner_frame, bg=self.BG_CARD)
        body_frame.pack(fill="x", padx=12, pady=(2, 6))

        text_to_show = self.item.text
        if len(text_to_show) > 100:
            text_to_show = text_to_show[:97] + "..."

        self.lbl_text = tk.Label(
            body_frame,
            text=text_to_show,
            font=("Segoe UI", 9),
            fg=self.FG_WHITE,
            bg=self.BG_CARD,
            justify="left",
            wraplength=310,
            anchor="w"
        )
        self.lbl_text.pack(fill="x", anchor="w")

        if self.item.timestamp_str:
            self.lbl_time = tk.Label(
                body_frame,
                text=f"Время: {self.item.timestamp_str}",
                font=("Segoe UI", 8),
                fg=self.FG_MUTED,
                bg=self.BG_CARD,
                anchor="w"
            )
            self.lbl_time.pack(fill="x", anchor="w", pady=(2, 0))

        # 3. Нижняя строка действий
        if self.item.actions:
            actions_row = tk.Frame(self.inner_frame, bg=self.BG_CARD)
            actions_row.pack(fill="x", padx=12, pady=(4, 10))

            for action in self.item.actions:
                btn = self._create_action_button(actions_row, action)
                btn.pack(side="left", padx=(0, 8))
                self.action_buttons.append(btn)

    def _create_action_button(self, parent: tk.Frame, action: NotificationAction) -> tk.Button:
        """Создание кнопки действия."""
        if action.style in ("success", "primary"):
            bg_col = "#238636"
            hover_bg = "#2ea043"
            fg_col = self.FG_WHITE
        elif action.style == "danger":
            bg_col = "#da3633"
            hover_bg = "#f85149"
            fg_col = self.FG_WHITE
        else:
            bg_col = "#21262d"
            hover_bg = "#30363d"
            fg_col = self.FG_MAIN

        btn = tk.Button(
            parent,
            text=action.label,
            font=("Segoe UI", 8, "bold"),
            fg=fg_col,
            bg=bg_col,
            activeforeground=self.FG_WHITE,
            activebackground=hover_bg,
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
            command=lambda act=action: self._handle_action(act)
        )
        _bind_hover(btn, bg_col, hover_bg, fg_col, self.FG_WHITE)
        return btn

    def _handle_action(self, action: NotificationAction) -> None:
        """Выполнение действия и закрытие уведомления."""
        try:
            action.callback()
        except Exception as e:
            pass
        self.close()

    def set_position(self, x: int, y: int) -> None:
        """Установка координат окна на экране."""
        try:
            self.geometry(f"{self.width}x{self.height}+{x}+{y}")
        except Exception:
            pass

    def close(self) -> None:
        """Закрытие окна уведомления."""
        if self._is_closed:
            return
        self._is_closed = True

        try:
            if self.item.on_close:
                self.item.on_close()
        except Exception:
            pass

        dismiss_cb = self.on_dismiss
        self.on_dismiss = None
        if dismiss_cb:
            try:
                dismiss_cb(self.item.id)
            except Exception:
                pass

        try:
            self.destroy()
        except Exception:
            pass
