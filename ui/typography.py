"""
Typography system for Akakiy 2.0.

Provides dynamic in-process font loading via Win32 GDI (AddFontResourceExW),
font family discovery, and a unified typography scale (Display, UI, Caption, Monospace).
"""

import sys
import os
import ctypes
from pathlib import Path
from typing import List, Tuple, Dict, Any

# Режим приватной загрузки шрифта в память процесса (без установки в систему)
FR_PRIVATE = 0x10


def load_local_fonts(base_dir: Path | str = None) -> List[str]:
    """
    Сканирует директорию assets/fonts/ и загружает найденные TTF/OTF шрифты
    в адресное пространство текущего процесса через Win32 GDI AddFontResourceExW.

    Не требует прав администратора и автоматически выгружается ОС при закрытии процесса.
    Возвращает список путей к успешно зарегистрированным шрифтам.
    """
    if sys.platform != "win32":
        return []

    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    else:
        base_dir = Path(base_dir)

    if not base_dir.is_dir():
        return []

    loaded: List[str] = []
    add_font_fn = getattr(ctypes.windll.gdi32, "AddFontResourceExW", None)
    if not add_font_fn:
        return []

    for ext in ("*.ttf", "*.otf"):
        for font_file in base_dir.rglob(ext):
            try:
                res = add_font_fn(str(font_file.resolve()), FR_PRIVATE, 0)
                if res > 0:
                    loaded.append(str(font_file))
            except Exception:
                pass

    return loaded


class TypographySystem:
    """
    Иерархическая шкала шрифтов Akakiy 2.0 Desktop Hub.
    Автоматически выбирает Manrope / Inter при наличии, иначе плавно переключается
    на Segoe UI Variable / Segoe UI.
    """

    def __init__(self, use_system_fallbacks: bool = True):
        self.loaded_files = load_local_fonts()

        # Определение доступности шрифтовых семейств
        has_manrope = any("manrope" in f.lower() for f in self.loaded_files)
        has_inter = any("inter" in f.lower() for f in self.loaded_files)
        has_jb = any("jetbrains" in f.lower() for f in self.loaded_files)

        self.display_family = "Manrope" if has_manrope else ("Segoe UI Variable Display" if use_system_fallbacks else "Segoe UI")
        self.ui_family = "Inter" if has_inter else ("Segoe UI Variable Text" if use_system_fallbacks else "Segoe UI")
        self.mono_family = "JetBrains Mono" if has_jb else ("Cascadia Code" if use_system_fallbacks else "Consolas")

    @property
    def FONT_DISPLAY(self) -> Tuple[str, int, str]:
        """Крупные заголовки Hero, имя Акакия, ключевые экраны фокуса."""
        return (self.display_family, 18, "bold")

    @property
    def FONT_TITLE(self) -> Tuple[str, int, str]:
        """Заголовки секций Desktop Hub."""
        return (self.display_family, 13, "bold")

    @property
    def FONT_HEADING(self) -> Tuple[str, int, str]:
        """Заголовки карточек, разделы задач, кнопки навигации."""
        return (self.ui_family, 10, "bold")

    @property
    def FONT_BODY(self) -> Tuple[str, int]:
        """Основной текст интерфейса, описания задач, заметки, реплики."""
        return (self.ui_family, 9)

    @property
    def FONT_CAPTION(self) -> Tuple[str, int]:
        """Вспомогательный микро-слой: бейджи, временные метки, hotkeys."""
        return (self.ui_family, 8)

    @property
    def FONT_MONO(self) -> Tuple[str, int]:
        """Моноширинный технический слой: артефакты, логи, ID, токены."""
        return (self.mono_family, 8)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "display": self.FONT_DISPLAY,
            "title": self.FONT_TITLE,
            "heading": self.FONT_HEADING,
            "body": self.FONT_BODY,
            "caption": self.FONT_CAPTION,
            "mono": self.FONT_MONO,
            "loaded_fonts_count": len(self.loaded_files)
        }


# Глобальный синглтон типографики
typography = TypographySystem()


def configure_tkinter_fonts(root: Any, typo: TypographySystem = None) -> None:
    """
    Применяет шрифтовую систему к корневому окну Tkinter:
    1. Задаёт опции по умолчанию в Tk Option Database (*Font, *Button.Font, *Entry.Font, *Text.Font);
    2. Обновляет стандартные поименованные шрифты Tk (TkDefaultFont, TkTextFont, TkHeadingFont, TkFixedFont).
    """
    if typo is None:
        typo = typography

    if root is None or not hasattr(root, "option_add"):
        return

    try:
        body_font_str = f"{typo.ui_family} 9"
        heading_font_str = f"{typo.ui_family} 10 bold"
        root.option_add("*Font", body_font_str)
        root.option_add("*Button.Font", heading_font_str)
        root.option_add("*Entry.Font", body_font_str)
        root.option_add("*Text.Font", body_font_str)
    except Exception:
        pass

    try:
        import tkinter.font as tkfont
        for font_name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            try:
                f = tkfont.nametofont(font_name)
                f.configure(family=typo.ui_family, size=9)
            except Exception:
                pass

        for font_name in ("TkHeadingFont", "TkCaptionFont"):
            try:
                f = tkfont.nametofont(font_name)
                f.configure(family=typo.ui_family, size=10, weight="bold")
            except Exception:
                pass

        for font_name in ("TkFixedFont",):
            try:
                f = tkfont.nametofont(font_name)
                f.configure(family=typo.mono_family, size=8)
            except Exception:
                pass
    except Exception:
        pass

