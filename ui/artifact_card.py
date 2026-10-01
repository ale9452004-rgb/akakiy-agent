"""
Модуль визуальных карточек артефактов (Artifact Cards & Renderers) для Desktop Hub Акакия.

Обеспечивает:
- ImageArtifactCard: отображение изображений (PNG, JPG, WebP, BMP, GIF) с preview,
  сохранением пропорций, метаданными (разрешение, размер, prompt) и действиями («Открыть», «Сохранить как…»);
- FileArtifactCard: аккуратная карточка для документов, презентаций и файлов;
- create_artifact_card: универсальная фабрика карточек на основе Artifact / ArtifactType;
- корректную обработку ошибок и отсутствующих файлов без сбоев интерфейса;
- сохранение ссылок на PhotoImage во избежание сбора мусора Tkinter.
"""

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union
import tkinter as tk
from tkinter import filedialog, messagebox

from config import PROJECT_PATH
from tools.agents.result import Artifact, ArtifactType
from ui.typography import typography

# Попытка импорта Pillow для качественного масштабирования (LANCZOS)
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def _resolve_artifact_path(path_str: Optional[str]) -> Optional[str]:
    """Разрешает абсолютный или относительный путь к файлу артефакта."""
    if not path_str:
        return None
    p = Path(path_str)
    if p.is_absolute() and p.exists():
        return str(p)
    # Проверка относительно PROJECT_PATH
    cand_proj = (PROJECT_PATH / p).resolve()
    if cand_proj.exists():
        return str(cand_proj)
    # Проверка относительно текущей рабочей директории
    cand_cwd = p.resolve()
    if cand_cwd.exists():
        return str(cand_cwd)
    # Если файл пока не найден на диске, возвращаем нормализованный путь
    return str(cand_proj if not p.is_absolute() else p)


def _format_size(size_bytes: Optional[int]) -> str:
    """Форматирует размер файла в удобочитаемый вид."""
    if size_bytes is None or size_bytes < 0:
        return ""
    if size_bytes < 1024:
        return f"{size_bytes} Б"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} КБ"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} МБ"


def _bind_btn_hover(btn: tk.Widget, normal_bg: str, hover_bg: str) -> None:
    """Плавное изменение фона кнопки при наведении."""
    def on_enter(e):
        try:
            btn.config(bg=hover_bg)
        except Exception:
            pass

    def on_leave(e):
        try:
            btn.config(bg=normal_bg)
        except Exception:
            pass

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)


class ImageArtifactCard(tk.Frame):
    """
    Визуальная карточка для отображения IMAGE Artifact.
    Поддерживает полноразмерный и компактный режимы (ChatView vs HomeView).
    """

    BG_CARD = "#0c111c"
    BG_CARD_INNER = "#070a0f"
    BORDER_LIGHT = "#1e293b"
    BORDER_SUBTLE = "#141c2a"
    FG_WHITE = "#f8fafc"
    FG_MAIN = "#cbd5e1"
    FG_MUTED = "#64748b"
    ACCENT_CYAN = "#38bdf8"
    ACCENT_GREEN = "#34d399"
    ACCENT_AMBER = "#fbbf24"
    ACCENT_RED = "#fb7185"

    def __init__(
        self,
        master: tk.Widget,
        artifact: Union[Artifact, Dict[str, Any], str],
        compact: bool = False,
        max_size: Optional[Tuple[int, int]] = None,
        **kwargs
    ):
        if "bg" not in kwargs:
            kwargs["bg"] = self.BG_CARD
        super().__init__(
            master,
            bd=0,
            highlightbackground=self.BORDER_LIGHT,
            highlightthickness=1,
            **kwargs
        )
        self.compact = compact
        self.max_size = max_size or ((260, 160) if compact else (440, 280))

        # Нормализация входного артефакта
        if isinstance(artifact, str):
            self.artifact_name = Path(artifact).name
            self.raw_path = artifact
            self.metadata: Dict[str, Any] = {}
        elif isinstance(artifact, dict):
            self.artifact_name = str(artifact.get("name") or Path(artifact.get("path", "image.png")).name)
            self.raw_path = artifact.get("path")
            self.metadata = dict(artifact.get("metadata") or {})
            for k in ("prompt", "width", "height", "size_bytes"):
                if k in artifact and k not in self.metadata:
                    self.metadata[k] = artifact[k]
        else:
            self.artifact_name = getattr(artifact, "name", "image.png")
            self.raw_path = getattr(artifact, "path", None)
            self.metadata = dict(getattr(artifact, "metadata", {}) or {})

        self.resolved_path = _resolve_artifact_path(self.raw_path)
        self._photo_ref: Optional[Any] = None
        self._is_error = False

        self._build_ui()

    def _build_ui(self) -> None:
        """Построение интерфейса карточки."""
        for w in self.winfo_children():
            w.destroy()

        if self.compact:
            self._build_compact_ui()
        else:
            self._build_standard_ui()

    def _load_thumbnail(self) -> Optional[Any]:
        """Загрузка и масштабирование thumbnail с сохранением пропорций через Pillow."""
        if not self.resolved_path or not os.path.exists(self.resolved_path):
            return None

        if not HAS_PIL:
            # Fallback на нативный PhotoImage (только PNG/GIF)
            try:
                photo = tk.PhotoImage(file=self.resolved_path)
                self._photo_ref = photo
                return photo
            except Exception:
                return None

        try:
            with Image.open(self.resolved_path) as img:
                self.orig_width, self.orig_height = img.size
                self.img_format = img.format or Path(self.resolved_path).suffix.upper().lstrip(".")

                # Масштабирование с сохранением пропорций
                img_copy = img.copy()
                resample = getattr(Image, "Resampling", Image).LANCZOS
                img_copy.thumbnail(self.max_size, resample)
                photo = ImageTk.PhotoImage(img_copy)
                self._photo_ref = photo
                return photo
        except Exception:
            return None

    def _build_standard_ui(self) -> None:
        """Стандартный вид карточки (для диалога / ChatView)."""
        # Верхняя панель: бейдж, имя и метаданные
        header = tk.Frame(self, bg=self.BG_CARD)
        header.pack(fill="x", padx=12, pady=(10, 6))

        tk.Label(
            header,
            text="[ИЗОБРАЖЕНИЕ]",
            font=typography.FONT_MONO,
            fg=self.ACCENT_GREEN,
            bg="#091b12",
            padx=6,
            pady=2
        ).pack(side="left")

        tk.Label(
            header,
            text=f"  {self.artifact_name}",
            font=typography.FONT_HEADING,
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(side="left")

        # Размер файла и разрешение
        size_str = ""
        if self.resolved_path and os.path.exists(self.resolved_path):
            try:
                size_str = _format_size(os.path.getsize(self.resolved_path))
            except Exception:
                pass
        if not size_str and "size_bytes" in self.metadata:
            size_str = _format_size(self.metadata["size_bytes"])

        meta_parts = []
        if "width" in self.metadata and "height" in self.metadata:
            meta_parts.append(f"{self.metadata['width']}×{self.metadata['height']}")
        if size_str:
            meta_parts.append(size_str)

        if meta_parts:
            tk.Label(
                header,
                text=" • ".join(meta_parts),
                font=typography.FONT_MONO,
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(side="right")

        # Описание / Prompt, если указан
        prompt_text = str(self.metadata.get("prompt") or self.metadata.get("description") or "").strip()
        if prompt_text:
            p_display = prompt_text if len(prompt_text) <= 120 else prompt_text[:117] + "..."
            tk.Label(
                self,
                text=f"«{p_display}»",
                font=typography.FONT_CAPTION,
                fg=self.FG_MAIN,
                bg=self.BG_CARD,
                anchor="w",
                justify="left",
                wraplength=420
            ).pack(fill="x", padx=14, pady=(0, 6))

        # Область изображения или ошибки
        photo = self._load_thumbnail()
        if photo:
            img_container = tk.Frame(self, bg=self.BG_CARD_INNER, bd=1, relief="solid")
            img_container.pack(padx=12, pady=(0, 8))

            lbl_img = tk.Label(
                img_container,
                image=photo,
                bg=self.BG_CARD_INNER,
                cursor="hand2"
            )
            lbl_img.image = photo  # Гарантированное сохранение ссылки
            lbl_img.pack()
            lbl_img.bind("<Button-1>", lambda e: self.on_open_file())
        else:
            self._is_error = True
            err_box = tk.Frame(
                self,
                bg="#1a1118",
                bd=0,
                highlightbackground="#3b1d28",
                highlightthickness=1
            )
            err_box.pack(fill="x", padx=12, pady=(0, 8))

            tk.Label(
                err_box,
                text="⚠️ Файл изображения недоступен на диске",
                font=typography.FONT_BODY,
                fg=self.ACCENT_RED,
                bg="#1a1118"
            ).pack(anchor="w", padx=10, pady=(6, 2))

            path_hint = self.raw_path or self.artifact_name
            tk.Label(
                err_box,
                text=f"Путь: {path_hint}",
                font=typography.FONT_MONO,
                fg=self.FG_MUTED,
                bg="#1a1118"
            ).pack(anchor="w", padx=10, pady=(0, 6))

        # Панель действий
        actions_bar = tk.Frame(self, bg=self.BG_CARD)
        actions_bar.pack(fill="x", padx=12, pady=(0, 10))

        btn_open = tk.Button(
            actions_bar,
            text="↗ Открыть",
            font=typography.FONT_CAPTION,
            fg=self.FG_WHITE,
            bg="#162238",
            bd=0,
            padx=12,
            pady=4,
            cursor="hand2",
            state="normal" if not self._is_error else "disabled",
            command=self.on_open_file
        )
        btn_open.pack(side="left", padx=(0, 8))
        _bind_btn_hover(btn_open, "#162238", "#233658")

        btn_save = tk.Button(
            actions_bar,
            text="💾 Сохранить как…",
            font=typography.FONT_CAPTION,
            fg=self.FG_MAIN,
            bg="#131c2e",
            bd=0,
            padx=12,
            pady=4,
            cursor="hand2",
            state="normal" if not self._is_error else "disabled",
            command=self.on_save_as
        )
        btn_save.pack(side="left")
        _bind_btn_hover(btn_save, "#131c2e", "#1e2d48")

    def _build_compact_ui(self) -> None:
        """Компактный вид карточки (для HomeView / Активность и результаты)."""
        main_row = tk.Frame(self, bg=self.BG_CARD)
        main_row.pack(fill="x", padx=8, pady=6)

        # Левая часть: миниатюра или бейдж ошибки
        photo = self._load_thumbnail()
        if photo:
            img_container = tk.Frame(main_row, bg=self.BG_CARD_INNER, bd=1, relief="solid")
            img_container.pack(side="left", padx=(0, 10))

            lbl_img = tk.Label(
                img_container,
                image=photo,
                bg=self.BG_CARD_INNER,
                cursor="hand2"
            )
            lbl_img.image = photo
            lbl_img.pack()
            lbl_img.bind("<Button-1>", lambda e: self.on_open_file())
        else:
            self._is_error = True
            err_box = tk.Frame(main_row, bg="#1a1118", bd=1, relief="solid")
            err_box.pack(side="left", padx=(0, 10))
            tk.Label(
                err_box,
                text="🖼️ Нет файла",
                font=typography.FONT_CAPTION,
                fg=self.ACCENT_RED,
                bg="#1a1118",
                padx=8,
                pady=16
            ).pack()

        # Правая часть: метаданные и кнопки действий
        info_col = tk.Frame(main_row, bg=self.BG_CARD)
        info_col.pack(side="left", fill="both", expand=True)

        top_line = tk.Frame(info_col, bg=self.BG_CARD)
        top_line.pack(fill="x")

        tk.Label(
            top_line,
            text="[ИЗОБРАЖЕНИЕ]",
            font=typography.FONT_MONO,
            fg=self.ACCENT_GREEN,
            bg="#091b12",
            padx=4,
            pady=1
        ).pack(side="left")

        tk.Label(
            top_line,
            text=f"  {self.artifact_name}",
            font=typography.FONT_HEADING,
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(side="left")

        # Размер / Разрешение
        size_str = ""
        if self.resolved_path and os.path.exists(self.resolved_path):
            try:
                size_str = _format_size(os.path.getsize(self.resolved_path))
            except Exception:
                pass
        if size_str:
            tk.Label(
                info_col,
                text=size_str,
                font=typography.FONT_MONO,
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(anchor="w", pady=(2, 2))

        prompt_text = str(self.metadata.get("prompt") or "").strip()
        if prompt_text:
            p_display = prompt_text if len(prompt_text) <= 60 else prompt_text[:57] + "..."
            tk.Label(
                info_col,
                text=f"«{p_display}»",
                font=typography.FONT_CAPTION,
                fg=self.FG_MAIN,
                bg=self.BG_CARD,
                anchor="w"
            ).pack(anchor="w", pady=(0, 4))

        btn_row = tk.Frame(info_col, bg=self.BG_CARD)
        btn_row.pack(anchor="w", pady=(2, 0))

        btn_open = tk.Button(
            btn_row,
            text="↗ Открыть",
            font=typography.FONT_CAPTION,
            fg=self.FG_WHITE,
            bg="#162238",
            bd=0,
            padx=8,
            pady=2,
            cursor="hand2",
            state="normal" if not self._is_error else "disabled",
            command=self.on_open_file
        )
        btn_open.pack(side="left", padx=(0, 6))
        _bind_btn_hover(btn_open, "#162238", "#233658")

        btn_save = tk.Button(
            btn_row,
            text="💾 Сохранить",
            font=typography.FONT_CAPTION,
            fg=self.FG_MAIN,
            bg="#131c2e",
            bd=0,
            padx=8,
            pady=2,
            cursor="hand2",
            state="normal" if not self._is_error else "disabled",
            command=self.on_save_as
        )
        btn_save.pack(side="left")
        _bind_btn_hover(btn_save, "#131c2e", "#1e2d48")

    def on_open_file(self) -> None:
        """Открытие файла в стандартном системном приложении."""
        if not self.resolved_path or not os.path.exists(self.resolved_path):
            messagebox.showwarning("Файл не найден", f"Файл не найден на диске:\n{self.resolved_path or self.raw_path}")
            return

        try:
            if sys.platform == "win32":
                os.startfile(self.resolved_path)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", self.resolved_path])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", self.resolved_path])
        except Exception as ex:
            messagebox.showerror("Ошибка открытия", f"Не удалось открыть файл:\n{ex}")

    def on_save_as(self) -> None:
        """Диалог сохранения копии файла."""
        if not self.resolved_path or not os.path.exists(self.resolved_path):
            messagebox.showwarning("Файл не найден", f"Файл не найден на диске:\n{self.resolved_path or self.raw_path}")
            return

        src_p = Path(self.resolved_path)
        ext = src_p.suffix.lower()
        filetypes = [("Файлы изображений", f"*{ext}"), ("Все файлы", "*.*")]

        dest = filedialog.asksaveasfilename(
            initialfile=src_p.name,
            defaultextension=ext,
            filetypes=filetypes,
            title="Сохранить изображение как…"
        )
        if dest:
            try:
                shutil.copy2(self.resolved_path, dest)
                messagebox.showinfo("Сохранено", f"Изображение успешно сохранено:\n{dest}")
            except Exception as ex:
                messagebox.showerror("Ошибка сохранения", f"Не удалось сохранить файл:\n{ex}")


class FileArtifactCard(tk.Frame):
    """
    Универсальная карточка для неграфических артефактов (документы, презентации, файлы).
    """

    BG_CARD = "#0c111c"
    BORDER_LIGHT = "#1e293b"
    FG_WHITE = "#f8fafc"
    FG_MAIN = "#cbd5e1"
    FG_MUTED = "#64748b"
    ACCENT_CYAN = "#38bdf8"

    def __init__(
        self,
        master: tk.Widget,
        artifact: Union[Artifact, Dict[str, Any], str],
        compact: bool = False,
        **kwargs
    ):
        if "bg" not in kwargs:
            kwargs["bg"] = self.BG_CARD
        super().__init__(
            master,
            bd=0,
            highlightbackground=self.BORDER_LIGHT,
            highlightthickness=1,
            **kwargs
        )
        self.compact = compact

        if isinstance(artifact, str):
            self.artifact_name = Path(artifact).name
            self.raw_path = artifact
            self.art_type = ArtifactType.guess_type(artifact)
        elif isinstance(artifact, dict):
            self.artifact_name = str(artifact.get("name") or Path(artifact.get("path", "file")).name)
            self.raw_path = artifact.get("path")
            self.art_type = str(artifact.get("type") or ArtifactType.guess_type(self.artifact_name))
        else:
            self.artifact_name = getattr(artifact, "name", "file")
            self.raw_path = getattr(artifact, "path", None)
            self.art_type = getattr(artifact, "type", ArtifactType.FILE)

        self.resolved_path = _resolve_artifact_path(self.raw_path)
        self._build_ui()

    def _build_ui(self) -> None:
        main_row = tk.Frame(self, bg=self.BG_CARD)
        main_row.pack(fill="x", padx=10, pady=8)

        # Иконка по типу
        icon = "📁"
        if self.art_type == ArtifactType.PRESENTATION:
            icon = "📊"
        elif self.art_type == ArtifactType.DOCUMENT:
            icon = "📑"
        elif self.art_type == ArtifactType.CODE:
            icon = "💻"
        elif self.art_type == ArtifactType.TEXT:
            icon = "📝"

        tk.Label(
            main_row,
            text=f"[{self.art_type.upper()}]",
            font=typography.FONT_MONO,
            fg=self.ACCENT_CYAN,
            bg="#142236",
            padx=4,
            pady=1
        ).pack(side="left")

        tk.Label(
            main_row,
            text=f"  {icon} {self.artifact_name}",
            font=typography.FONT_HEADING,
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(side="left", padx=(0, 10))

        if self.resolved_path and os.path.exists(self.resolved_path):
            try:
                sz = _format_size(os.path.getsize(self.resolved_path))
                tk.Label(
                    main_row,
                    text=sz,
                    font=typography.FONT_MONO,
                    fg=self.FG_MUTED,
                    bg=self.BG_CARD
                ).pack(side="left", padx=(0, 10))
            except Exception:
                pass

        btn_open = tk.Button(
            main_row,
            text="↗ Открыть",
            font=typography.FONT_CAPTION,
            fg=self.FG_WHITE,
            bg="#162238",
            bd=0,
            padx=8,
            pady=2,
            cursor="hand2",
            command=self.on_open_file
        )
        btn_open.pack(side="right")
        _bind_btn_hover(btn_open, "#162238", "#233658")

    def on_open_file(self) -> None:
        if not self.resolved_path or not os.path.exists(self.resolved_path):
            messagebox.showwarning("Файл не найден", f"Файл не найден на диске:\n{self.resolved_path or self.raw_path}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(self.resolved_path)
            else:
                import subprocess
                cmd = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([cmd, self.resolved_path])
        except Exception as ex:
            messagebox.showerror("Ошибка открытия", f"Не удалось открыть файл:\n{ex}")


def create_artifact_card(
    master: tk.Widget,
    artifact: Union[Artifact, Dict[str, Any], str],
    compact: bool = False,
    **kwargs
) -> tk.Widget:
    """
    Фабрика карточек артефактов.
    Определяет тип артефакта через единую систему ArtifactType и создаёт
    соответствующий компонент (ImageArtifactCard или FileArtifactCard).
    """
    if isinstance(artifact, str):
        art_type = ArtifactType.guess_type(artifact)
        art_obj: Union[Artifact, Dict[str, Any], str] = Artifact(
            name=Path(artifact).name,
            type=art_type,
            path=artifact
        )
    elif isinstance(artifact, dict):
        art_type = artifact.get("type") or ArtifactType.guess_type(
            artifact.get("path") or artifact.get("name") or ""
        )
        art_obj = artifact
    else:
        art_type = getattr(artifact, "type", ArtifactType.FILE)
        art_obj = artifact

    is_image = (art_type == ArtifactType.IMAGE) or (
        isinstance(art_obj, Artifact) and art_obj.is_image
    )

    if is_image:
        return ImageArtifactCard(master, art_obj, compact=compact, **kwargs)
    return FileArtifactCard(master, art_obj, compact=compact, **kwargs)
