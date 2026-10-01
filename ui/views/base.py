"""
Базовый класс экрана (View) и UI-утилиты для Desktop Hub Акакия 2.0.
"""

import tkinter as tk
from typing import Any, Optional

from ui.typography import typography


def _bind_hover(
    widget: tk.Widget,
    normal_bg: str,
    hover_bg: str,
    normal_fg: Optional[str] = None,
    hover_fg: Optional[str] = None
) -> None:
    """Добавляет плавный hover-эффект при наведении курсора на виджет."""
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


bind_hover = _bind_hover


class BaseView(tk.Frame):
    """
    Базовый класс для всех экранов рабочего пространства (Main Workspace).

    Обеспечивает:
    1. Единый контракт жизненного цикла: render() для построения UI, refresh() для реактивного обновления.
    2. Доступ к родительской оболочке shell (AkakiyGUI).
    3. Доступ к общим сервисам (agent, household, memory, voice) через shell без их дублирования.
    4. Стандартную палитру стилей и тему оформления.
    """

    # Базовая палитра Visual Direction 2.0 (Deep Graphite & Electric Cyan)
    BG_MAIN = "#070a0f"
    BG_CANVAS = "#070a0f"
    BG_PANEL = "#070a0f"
    BG_HERO = "#0a0e17"
    BG_CARD = "#0c111c"
    BG_CARD_INNER = "#080c14"
    BG_HOVER = "#0e1524"
    BG_ACTIVE = "#0f172a"
    BORDER_COL = "#131b28"
    BORDER_SUBTLE = "#141c2a"
    BORDER_LIGHT = "#1e293b"

    FG_WHITE = "#f8fafc"
    FG_MAIN = "#cbd5e1"
    FG_MUTED = "#64748b"
    FG_DIM = "#475569"

    ACCENT_CYAN = "#38bdf8"
    ACCENT_BLUE = "#0284c7"
    ACCENT_PURPLE = "#a78bfa"
    ACCENT_VIOLET = "#a78bfa"
    ACCENT_GREEN = "#34d399"
    ACCENT_AMBER = "#fbbf24"
    ACCENT_RED = "#fb7185"

    # Типографическая система
    FONT_DISPLAY = typography.FONT_DISPLAY
    FONT_TITLE = typography.FONT_TITLE
    FONT_HEADING = typography.FONT_HEADING
    FONT_BODY = typography.FONT_BODY
    FONT_CAPTION = typography.FONT_CAPTION
    FONT_MONO = typography.FONT_MONO

    DISPLAY_FAMILY = typography.display_family
    UI_FAMILY = typography.ui_family
    MONO_FAMILY = typography.mono_family

    def __init__(self, master: tk.Widget, shell: Any = None, **kwargs):
        if "bg" not in kwargs:
            kwargs["bg"] = self.BG_MAIN
        super().__init__(master, **kwargs)
        self.shell = shell

    @property
    def agent(self) -> Any:
        """Доступ к оркестратору Agent через Shell."""
        return getattr(self.shell, "agent", None) if self.shell else None

    @property
    def household(self) -> Any:
        """Доступ к HouseholdManager через Shell."""
        return getattr(self.shell, "household", None) if self.shell else None

    @property
    def memory(self) -> Any:
        """Доступ к MemoryManager через Shell."""
        return getattr(self.shell, "memory", None) if self.shell else None

    @property
    def voice(self) -> Any:
        """Доступ к VoiceService через Shell."""
        return getattr(self.shell, "voice", None) if self.shell else None

    @property
    def settings(self) -> Any:
        """Доступ к AppSettings через Shell или синглтон."""
        if self.shell and hasattr(self.shell, "settings") and self.shell.settings is not None:
            return self.shell.settings
        from tools.settings import get_app_settings
        return get_app_settings()

    def switch_section(self, code: str) -> None:
        """Переключает раздел через Shell."""
        if self.shell and hasattr(self.shell, "switch_section"):
            self.shell.switch_section(code)

    def switch_view(self, code: str) -> None:
        """Переключает экран через Shell."""
        if self.shell and hasattr(self.shell, "switch_view"):
            self.shell.switch_view(code)

    def bind_hover(
        self,
        widget: tk.Widget,
        normal_bg: str,
        hover_bg: str,
        normal_fg: Optional[str] = None,
        hover_fg: Optional[str] = None
    ) -> None:
        """Хелпер привязки hover-эффекта к виджету."""
        _bind_hover(widget, normal_bg, hover_bg, normal_fg, hover_fg)

    def render(self) -> None:
        """
        Создаёт и размещает элементы интерфейса экрана.
        Переопределяется в дочерних классах экранов.
        """
        pass

    def refresh(self) -> None:
        """
        Реактивно обновляет отображаемые данные экрана.
        Переопределяется в дочерних классах экранов.
        """
        pass
