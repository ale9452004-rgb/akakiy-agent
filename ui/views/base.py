"""
Базовый класс экрана (View) и UI-утилиты для Desktop Hub Акакия 2.0.
"""

import tkinter as tk
from typing import Any, Optional


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

    # Константы темы Desktop Hub 2.0
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
