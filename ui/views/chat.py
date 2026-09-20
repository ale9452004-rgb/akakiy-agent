"""
Модульный экран чата и логов (ChatView) для Desktop Hub Акакия 2.0.
"""

import time
import tkinter as tk
from typing import Any, List, Tuple

from ui.views.base import BaseView, _bind_hover


class ChatView(BaseView):
    """
    Экран интерактивного диалога с ассистентом (Chat) и системного лога.
    Обеспечивает отображение переписки, подсветку сообщений, вывод системных логов инструментов
    и очистку сессии.
    """

    def __init__(self, master: tk.Widget, shell: Any = None, **kwargs):
        super().__init__(master, shell=shell, **kwargs)
        self.chat_text: tk.Text = None
        self.log_text: tk.Text = None
        self._local_chat_messages: List[Tuple[str, str, str]] = []
        self._local_log_messages: List[Tuple[str, str, str]] = []
        self.render()

    @property
    def chat_messages(self) -> List[Tuple[str, str, str]]:
        if self.shell and hasattr(self.shell, "chat_messages"):
            return self.shell.chat_messages
        return self._local_chat_messages

    @property
    def log_messages(self) -> List[Tuple[str, str, str]]:
        if self.shell and hasattr(self.shell, "log_messages"):
            return self.shell.log_messages
        return self._local_log_messages

    def render(self) -> None:
        """Построение двухколоночного интерфейса диалога и системного лога."""
        for w in self.winfo_children():
            w.destroy()

        chat_split = tk.Frame(self, bg=self.BG_MAIN)
        chat_split.pack(fill="both", expand=True)

        # Левая колонка: Лента диалога
        left_chat = tk.Frame(chat_split, bg=self.BG_CARD, bd=1, relief="solid")
        left_chat.pack(side="left", fill="both", expand=True, padx=(0, 14))

        chat_header = tk.Frame(left_chat, bg=self.BG_CARD)
        chat_header.pack(fill="x", padx=16, pady=12)

        tk.Label(
            chat_header,
            text="ДИАЛОГ С АКАКИЕМ",
            font=("Segoe UI", 11, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(side="left")

        btn_clear = tk.Button(
            chat_header,
            text="Очистить",
            font=("Segoe UI", 8),
            fg=self.FG_MUTED,
            bg="#21262d",
            bd=0,
            cursor="hand2",
            command=self.clear_chat
        )
        btn_clear.pack(side="right")
        _bind_hover(btn_clear, "#21262d", "#30363d")

        self.chat_text = tk.Text(
            left_chat,
            bg="#0d1117",
            fg=self.FG_MAIN,
            font=("Segoe UI", 10),
            wrap="word",
            bd=0,
            padx=14,
            pady=14
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
            right_log,
            text="СИСТЕМНЫЙ ЛОГ И ИНСТРУМЕНТЫ",
            font=("Segoe UI", 10, "bold"),
            fg=self.FG_MUTED,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=16, pady=12)

        self.log_text = tk.Text(
            right_log,
            bg="#0d1117",
            fg=self.FG_MUTED,
            font=("Consolas", 8),
            wrap="word",
            bd=0,
            padx=10,
            pady=10
        )
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log_text.tag_config("info", foreground=self.ACCENT_CYAN)
        self.log_text.tag_config("tool", foreground=self.ACCENT_PURPLE)
        self.log_text.tag_config("done", foreground=self.ACCENT_GREEN)
        self.log_text.tag_config("err", foreground=self.ACCENT_RED)

        # Синхронизация виджетов с Shell
        if self.shell:
            self.shell.chat_text = self.chat_text
            self.shell.log_text = self.log_text

        # Восстановление сохранённых сообщений сессии
        if not self.chat_messages:
            self.append_chat("Акакий", "Привет! Чем я могу помочь? Задавай вопросы, управляй делами или работай с проектом.")
        else:
            for author, message, t_str in list(self.chat_messages):
                self.insert_chat_ui(author, message, t_str)

        for prefix, text, t_str in list(self.log_messages):
            self.insert_log_ui(prefix, text, t_str)

    def insert_chat_ui(self, author: str, message: str, t_str: str) -> None:
        """Вставка отформатированного сообщения в ленту чата."""
        if not self.chat_text or not self.chat_text.winfo_exists():
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

    def append_chat(self, author: str, message: str) -> None:
        """Добавление сообщения в историю и отображение в интерфейсе."""
        t_str = time.strftime("%H:%M:%S")
        self.chat_messages.append((author, message, t_str))
        self.insert_chat_ui(author, message, t_str)

    def insert_log_ui(self, prefix: str, text: str, t_str: str) -> None:
        """Вставка строки лога в системную панель."""
        if not self.log_text or not self.log_text.winfo_exists():
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

    def append_log(self, prefix: str, text: str) -> None:
        """Добавление записи лога в историю и отображение в интерфейсе."""
        t_str = time.strftime("%H:%M:%S")
        self.log_messages.append((prefix, text, t_str))
        self.insert_log_ui(prefix, text, t_str)

    def clear_chat(self) -> None:
        """Очистка диалога, системного лога и контекстной истории агента."""
        self.chat_messages.clear()
        self.log_messages.clear()
        if self.chat_text and self.chat_text.winfo_exists():
            self.chat_text.delete("1.0", tk.END)
        if self.log_text and self.log_text.winfo_exists():
            self.log_text.delete("1.0", tk.END)
        if self.agent and hasattr(self.agent, "context_mgr") and hasattr(self.agent.context_mgr, "clear_history"):
            self.agent.context_mgr.clear_history()

    def refresh(self) -> None:
        """Реактивное обновление ленты чата (контракт BaseView)."""
        pass
