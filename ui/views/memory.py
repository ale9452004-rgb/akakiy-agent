"""
Модульный экран долговременной памяти (MemoryView) для Desktop Hub Акакия 2.0.
"""

import tkinter as tk
from tkinter import messagebox
from typing import Any, Dict, Optional

from ui.pagination import PagedListController, PaginationBar
from ui.views.base import BaseView, _bind_hover


class MemoryView(BaseView):
    """
    Экран управления долговременной памятью (Memory).
    Обеспечивает сохранение фактов, текстовый поиск/фильтрацию, пагинацию,
    просмотр всех записей и удаление фактов (забывание).
    """

    def __init__(self, master: tk.Widget, shell: Any = None, **kwargs):
        super().__init__(master, shell=shell, **kwargs)
        self.entry_mem: Optional[tk.Entry] = None
        self.entry_mem_search: Optional[tk.Entry] = None
        self.mem_list_frame: Optional[tk.Frame] = None
        self.pagination_bar: Optional[PaginationBar] = None
        self.paged_controller: Optional[PagedListController] = None
        self.render()

    def render(self) -> None:
        """Построение интерфейса управления долговременной памятью."""
        for w in self.winfo_children():
            w.destroy()

        header_row = tk.Frame(self, bg=self.BG_MAIN)
        header_row.pack(fill="x", pady=(0, 16))

        tk.Label(
            header_row,
            text="ДОЛГОВРЕМЕННАЯ ПАМЯТЬ (MEMORY)",
            font=("Segoe UI", 14, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_MAIN
        ).pack(side="left")

        # Поиск записей памяти
        search_box = tk.Frame(header_row, bg=self.BG_MAIN)
        search_box.pack(side="right")

        tk.Label(
            search_box,
            text="Поиск:",
            font=("Segoe UI", 9),
            fg=self.FG_MUTED,
            bg=self.BG_MAIN
        ).pack(side="left", padx=4)

        self.entry_mem_search = tk.Entry(
            search_box,
            font=("Segoe UI", 10),
            bg=self.BG_CARD,
            fg=self.FG_WHITE,
            width=20,
            bd=1,
            relief="solid"
        )
        self.entry_mem_search.pack(side="left", padx=4)
        self.entry_mem_search.bind("<KeyRelease>", lambda e: self._on_search_changed())

        # Форма добавления факта
        add_box = tk.Frame(self, bg=self.BG_CARD, bd=1, relief="solid")
        add_box.pack(fill="x", pady=(0, 16), ipady=4)

        tk.Label(
            add_box,
            text="Запомнить факт:",
            font=("Segoe UI", 9, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(side="left", padx=12)

        self.entry_mem = tk.Entry(
            add_box,
            font=("Segoe UI", 10),
            bg="#13171f",
            fg=self.FG_WHITE,
            bd=1,
            relief="solid"
        )
        self.entry_mem.pack(side="left", fill="x", expand=True, padx=6, pady=8)
        self.entry_mem.bind("<Return>", lambda e: self.ui_remember())

        btn_add = tk.Button(
            add_box,
            text="Запомнить",
            font=("Segoe UI", 9, "bold"),
            bg=self.ACCENT_CYAN,
            fg="#0d1117",
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self.ui_remember
        )
        btn_add.pack(side="left", padx=12)
        _bind_hover(btn_add, self.ACCENT_CYAN, "#7dd3fc", "#0d1117", "#0d1117")

        # Контейнер списка памяти
        self.mem_list_frame = tk.Frame(self, bg=self.BG_CARD, bd=1, relief="solid")
        self.mem_list_frame.pack(fill="both", expand=True)

        # Панель пагинации
        self.pagination_bar = PaginationBar(self, bg=self.BG_MAIN)
        self.pagination_bar.pack(fill="x", pady=(8, 0))

        # Контроллер пагинации и поиска
        self.paged_controller = PagedListController[Dict[str, Any]](
            content_frame=self.mem_list_frame,
            pagination_bar=self.pagination_bar,
            render_item=self._render_mem_item,
            filter_fn=self._filter_memory,
            page_size=8,
            empty_text="Долговременная память пуста.",
            no_results_text="Записей памяти по запросу не найдено.",
            empty_bg=self.BG_CARD,
            empty_fg=self.FG_MUTED,
        )

        self.refresh()

    def _filter_memory(self, mem: Dict[str, Any], query: str) -> bool:
        """Предикат фильтрации записи памяти по тексту или номеру #id."""
        q = query.strip().lower()
        if not q:
            return True
        clean_q = q.lstrip("#")
        text = str(mem.get("text", "")).lower()
        mem_id = str(mem.get("id", ""))
        return q in text or clean_q == mem_id or f"#{mem_id}" == q

    def _on_search_changed(self) -> None:
        """Обработка ввода в строку поиска."""
        if not self.paged_controller:
            return
        query = self.entry_mem_search.get().strip() if self.entry_mem_search else ""
        self.paged_controller.set_filter(query)

    def _render_mem_item(self, parent: tk.Widget, m: Dict[str, Any]) -> None:
        """Отрисовка одной строки долговременной памяти."""
        row = tk.Frame(parent, bg="#13171f", bd=1, relief="solid")
        row.pack(fill="x", padx=16, pady=4)

        tk.Label(
            row,
            text="🧠",
            font=("Segoe UI", 10),
            fg=self.ACCENT_CYAN,
            bg="#13171f"
        ).pack(side="left", padx=10, pady=8)

        tk.Label(
            row,
            text=f"#{m['id']} {m['text']}",
            font=("Segoe UI", 9),
            fg=self.FG_WHITE,
            bg="#13171f"
        ).pack(side="left", padx=4)

        btn_del = tk.Button(
            row,
            text="✕",
            font=("Segoe UI", 8),
            fg=self.ACCENT_RED,
            bg="#13171f",
            bd=0,
            cursor="hand2",
            command=lambda mid=m["id"]: self.ui_forget(mid)
        )
        btn_del.pack(side="right", padx=8)

        tk.Label(
            row,
            text=m.get("created_at", ""),
            font=("Consolas", 8),
            fg=self.FG_DIM,
            bg="#13171f"
        ).pack(side="right", padx=8)

    def ui_remember(self) -> None:
        """Сохранение нового факта из поля ввода."""
        if not self.entry_mem:
            return
        txt = self.entry_mem.get().strip()
        if txt and self.memory:
            ok, msg, _ = self.memory.remember(txt)
            if not ok:
                messagebox.showwarning("Память", msg)
            self.entry_mem.delete(0, tk.END)
            self.refresh()

    def refresh(self) -> None:
        """Реактивное обновление списка фактов памяти."""
        if not self.mem_list_frame or not self.mem_list_frame.winfo_exists():
            return

        if not self.memory:
            for w in self.mem_list_frame.winfo_children():
                w.destroy()
            tk.Label(
                self.mem_list_frame,
                text="Сервис памяти недоступен.",
                font=("Segoe UI", 11),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(pady=40)
            if self.pagination_bar and self.paged_controller:
                self.pagination_bar.update_state(self.paged_controller.model)
            return

        memories = self.memory.get_all()
        query = self.entry_mem_search.get().strip() if self.entry_mem_search else ""
        if self.paged_controller:
            self.paged_controller.model.set_filter(query)
            self.paged_controller.set_items(list(reversed(memories)))

    def ui_forget(self, mem_id: int) -> None:
        """Удаление факта из памяти с запросом подтверждения."""
        if not self.memory:
            return
        if messagebox.askyesno("Подтверждение", f"Забыть запись #{mem_id}?"):
            self.memory.forget(mem_id)
            self.refresh()
