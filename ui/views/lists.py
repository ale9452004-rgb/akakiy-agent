"""
Модульный экран управления списками (ListsView) для Desktop Hub Акакия 2.0.
"""

import tkinter as tk
from tkinter import messagebox
from typing import Any, Dict, List, Optional

from ui.pagination import PagedListController, PaginationBar
from ui.views.base import BaseView, _bind_hover


class ListsView(BaseView):
    """
    Экран управления именованными списками (Lists).
    Обеспечивает создание списка, поиск/фильтрацию списков, пагинацию,
    выбор списка, добавление/выполнение/удаление пунктов и удаление списка целиком.
    """

    def __init__(self, master: tk.Widget, shell: Any = None, **kwargs):
        super().__init__(master, shell=shell, **kwargs)
        self.entry_new_list: Optional[tk.Entry] = None
        self.entry_list_search: Optional[tk.Entry] = None
        self.list_names_box: Optional[tk.Frame] = None
        self.right_items_pane: Optional[tk.Frame] = None
        self.entry_item_text: Optional[tk.Entry] = None
        self.current_selected_list: str = ""
        self.pagination_bar: Optional[PaginationBar] = None
        self.paged_controller: Optional[PagedListController] = None
        self.render()

    def render(self) -> None:
        """Построение двухпанельного интерфейса списков."""
        for w in self.winfo_children():
            w.destroy()

        header_row = tk.Frame(self, bg=self.BG_MAIN)
        header_row.pack(fill="x", pady=(0, 16))

        tk.Label(
            header_row,
            text="СПИСКИ (LISTS)",
            font=("Segoe UI", 14, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_MAIN
        ).pack(side="left")

        # Поиск списков
        search_box = tk.Frame(header_row, bg=self.BG_MAIN)
        search_box.pack(side="right")

        tk.Label(
            search_box,
            text="Поиск:",
            font=("Segoe UI", 9),
            fg=self.FG_MUTED,
            bg=self.BG_MAIN
        ).pack(side="left", padx=4)

        self.entry_list_search = tk.Entry(
            search_box,
            font=("Segoe UI", 10),
            bg=self.BG_CARD,
            fg=self.FG_WHITE,
            width=20,
            bd=1,
            relief="solid"
        )
        self.entry_list_search.pack(side="left", padx=4)
        self.entry_list_search.bind("<KeyRelease>", lambda e: self._on_search_changed())

        body_split = tk.Frame(self, bg=self.BG_MAIN)
        body_split.pack(fill="both", expand=True)

        # Левая часть: перечень списков + добавление списка
        left_pane = tk.Frame(body_split, bg=self.BG_CARD, bd=1, relief="solid", width=300)
        left_pane.pack(side="left", fill="y", padx=(0, 14))
        left_pane.pack_propagate(False)

        tk.Label(
            left_pane,
            text="ВАШИ СПИСКИ",
            font=("Segoe UI", 10, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=14, pady=12)

        new_l_box = tk.Frame(left_pane, bg=self.BG_CARD)
        new_l_box.pack(fill="x", padx=14, pady=(0, 10))

        self.entry_new_list = tk.Entry(
            new_l_box,
            font=("Segoe UI", 9),
            bg="#13171f",
            fg=self.FG_WHITE,
            bd=1,
            relief="solid"
        )
        self.entry_new_list.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.entry_new_list.bind("<Return>", lambda e: self.ui_create_list())

        btn_create_l = tk.Button(
            new_l_box,
            text="+",
            font=("Segoe UI", 9, "bold"),
            bg=self.ACCENT_GREEN,
            fg="#0d1117",
            bd=0,
            padx=8,
            cursor="hand2",
            command=self.ui_create_list
        )
        btn_create_l.pack(side="left")
        _bind_hover(btn_create_l, self.ACCENT_GREEN, "#56d364", "#0d1117", "#0d1117")

        # Панель пагинации списков внизу левой панели
        self.pagination_bar = PaginationBar(left_pane, bg=self.BG_CARD)
        self.pagination_bar.pack(side="bottom", fill="x", pady=(4, 8))

        self.list_names_box = tk.Frame(left_pane, bg=self.BG_CARD)
        self.list_names_box.pack(fill="both", expand=True, padx=8, pady=4)

        # Контроллер пагинации списков
        self.paged_controller = PagedListController[Dict[str, Any]](
            content_frame=self.list_names_box,
            pagination_bar=self.pagination_bar,
            render_item=self._render_list_item,
            filter_fn=self._filter_list,
            page_size=8,
            empty_text="Нет списков.",
            no_results_text="Списков не найдено.",
            empty_bg=self.BG_CARD,
            empty_fg=self.FG_MUTED,
        )

        # Правая часть: элементы выбранного списка
        self.right_items_pane = tk.Frame(body_split, bg=self.BG_CARD, bd=1, relief="solid")
        self.right_items_pane.pack(side="left", fill="both", expand=True)
        self.list_items_box = self.right_items_pane

        self.refresh()

    def _filter_list(self, list_info: Dict[str, Any], query: str) -> bool:
        """Предикат фильтрации списка по названию, ID или содержимому пунктов."""
        q = query.strip().lower()
        if not q:
            return True
        clean_q = q.lstrip("#")
        name = str(list_info.get("name", "")).lower()
        list_id = str(list_info.get("id", ""))
        if q in name or clean_q == list_id or f"#{list_id}" == q:
            return True
        for it in list_info.get("items", []):
            it_id = str(it.get("id", ""))
            it_text = str(it.get("text", "")).lower()
            if clean_q == it_id or f"#{it_id}" == q or q in it_text:
                return True
        return False

    def _on_search_changed(self) -> None:
        """Обработка ввода в строку поиска."""
        if not self.paged_controller:
            return
        query = self.entry_list_search.get().strip() if self.entry_list_search else ""
        self.paged_controller.set_filter(query)

    def _render_list_item(self, parent: tk.Widget, list_info: Dict[str, Any]) -> None:
        """Отрисовка одной кнопки списка в боковой панели."""
        l_name = list_info["name"]
        l_id = list_info.get("id")
        cnt = list_info.get("count", 0)
        is_active = (l_name == self.current_selected_list)
        btn_bg = self.BG_ACTIVE if is_active else "#13171f"
        btn_fg = self.ACCENT_CYAN if is_active else self.FG_MAIN

        id_prefix = f"#{l_id} " if l_id is not None else ""
        b = tk.Button(
            parent,
            text=f"• {id_prefix}{l_name} ({cnt})",
            font=("Segoe UI", 9, "bold" if is_active else "normal"),
            fg=btn_fg,
            bg=btn_bg,
            bd=0,
            anchor="w",
            padx=10,
            pady=6,
            cursor="hand2",
            command=lambda name=l_name: self.select_list(name)
        )
        b.pack(fill="x", pady=2)
        _bind_hover(b, btn_bg, self.BG_HOVER)

    def ui_create_list(self) -> None:
        """Создание нового списка."""
        if not self.entry_new_list:
            return
        name = self.entry_new_list.get().strip().lower()
        if name and self.household:
            self.household.create_list(name)
            self.entry_new_list.delete(0, tk.END)
            self.current_selected_list = name
            if self.shell:
                self.shell.current_selected_list = name
            self.refresh()

    def refresh(self) -> None:
        """Реактивное обновление меню списков и содержимого выбранного списка."""
        if not self.list_names_box or not self.list_names_box.winfo_exists():
            return

        if not self.household:
            for w in self.list_names_box.winfo_children():
                w.destroy()
            tk.Label(
                self.list_names_box,
                text="Сервис списков недоступен.",
                font=("Segoe UI", 9),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(pady=10)
            if self.pagination_bar and self.paged_controller:
                self.pagination_bar.update_state(self.paged_controller.model)
            self.render_selected_list_items("")
            return

        lists = list(self.household.lists.keys())
        if not lists:
            self.current_selected_list = ""
            if self.shell:
                self.shell.current_selected_list = ""
            if self.paged_controller:
                self.paged_controller.set_items([])
            self.render_selected_list_items("")
            return

        if not self.current_selected_list or self.current_selected_list not in lists:
            self.current_selected_list = lists[0]
            if self.shell:
                self.shell.current_selected_list = lists[0]

        list_data = []
        for idx, (l_name, items) in enumerate(self.household.lists.items(), start=1):
            list_data.append({
                "id": idx,
                "name": l_name,
                "count": len(items),
                "items": items
            })

        query = self.entry_list_search.get().strip() if self.entry_list_search else ""
        if self.paged_controller:
            self.paged_controller.model.set_filter(query)
            self.paged_controller.set_items(list_data)

        self.render_selected_list_items(self.current_selected_list)

    def select_list(self, name: str) -> None:
        """Выбор активного списка."""
        self.current_selected_list = name
        if self.shell:
            self.shell.current_selected_list = name
        self.render_selected_list_items(self.current_selected_list)
        if self.paged_controller:
            self.paged_controller.render()

    def render_selected_list_items(self, list_name: str) -> None:
        """Отрисовка содержимого выбранного списка."""
        if not self.right_items_pane or not self.right_items_pane.winfo_exists():
            return

        for w in self.right_items_pane.winfo_children():
            w.destroy()

        if not self.household or not list_name or list_name not in self.household.lists:
            tk.Label(
                self.right_items_pane,
                text="Выберите или создайте список слева.",
                font=("Segoe UI", 11),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(pady=40)
            return

        header = tk.Frame(self.right_items_pane, bg=self.BG_CARD)
        header.pack(fill="x", padx=16, pady=12)

        tk.Label(
            header,
            text=f"СПИСОК: {list_name.upper()}",
            font=("Segoe UI", 12, "bold"),
            fg=self.ACCENT_GREEN,
            bg=self.BG_CARD
        ).pack(side="left")

        btn_del_list = tk.Button(
            header,
            text="Удалить список целиком",
            font=("Segoe UI", 8),
            fg=self.ACCENT_RED,
            bg="#21262d",
            bd=0,
            padx=8,
            pady=4,
            cursor="hand2",
            command=lambda: self.ui_delete_entire_list(list_name)
        )
        btn_del_list.pack(side="right")
        _bind_hover(btn_del_list, "#21262d", "#30363d")

        # Форма добавления пункта
        add_item_box = tk.Frame(self.right_items_pane, bg=self.BG_CARD)
        add_item_box.pack(fill="x", padx=16, pady=(0, 12))

        self.entry_item_text = tk.Entry(
            add_item_box,
            font=("Segoe UI", 10),
            bg="#13171f",
            fg=self.FG_WHITE,
            bd=1,
            relief="solid"
        )
        self.entry_item_text.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_item_text.bind("<Return>", lambda e: self.ui_add_item(list_name))

        btn_add_item = tk.Button(
            add_item_box,
            text="Добавить пункт",
            font=("Segoe UI", 9, "bold"),
            bg=self.ACCENT_GREEN,
            fg="#0d1117",
            bd=0,
            padx=12,
            pady=5,
            cursor="hand2",
            command=lambda: self.ui_add_item(list_name)
        )
        btn_add_item.pack(side="left")
        _bind_hover(btn_add_item, self.ACCENT_GREEN, "#56d364", "#0d1117", "#0d1117")

        # Пункты списка
        items = self.household.lists[list_name]
        items_scroll = tk.Frame(self.right_items_pane, bg=self.BG_CARD)
        items_scroll.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        if not items:
            tk.Label(
                items_scroll,
                text="Список пуст.",
                font=("Segoe UI", 10),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(anchor="w", pady=10)
        else:
            for it in items:
                row = tk.Frame(items_scroll, bg="#13171f", bd=1, relief="solid")
                row.pack(fill="x", pady=2)

                is_done = it.get("completed", False)
                btn_txt = "☑" if is_done else "☐"
                chk = tk.Button(
                    row,
                    text=btn_txt,
                    font=("Segoe UI", 11),
                    fg=self.ACCENT_GREEN if is_done else self.FG_MUTED,
                    bg="#13171f",
                    bd=0,
                    cursor="hand2",
                    command=lambda iid=it["id"]: self.ui_toggle_item(list_name, iid)
                )
                chk.pack(side="left", padx=8, pady=4)

                tk.Label(
                    row,
                    text=it["text"],
                    font=("Segoe UI", 9),
                    fg=self.FG_MUTED if is_done else self.FG_WHITE,
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
                    command=lambda iid=it["id"]: self.ui_delete_item(list_name, iid)
                )
                btn_del.pack(side="right", padx=8)

    def ui_add_item(self, list_name: str) -> None:
        """Добавление пункта в список."""
        if not self.entry_item_text:
            return
        txt = self.entry_item_text.get().strip()
        if txt and self.household:
            self.household.add_list_item(list_name, txt)
            self.refresh()

    def ui_toggle_item(self, list_name: str, item_id: int) -> None:
        """Переключение отметки пункта списка."""
        if self.household:
            self.household.complete_list_item(list_name, item_id)
            self.render_selected_list_items(list_name)

    def ui_delete_item(self, list_name: str, item_id: int) -> None:
        """Удаление пункта из списка."""
        if self.household:
            self.household.delete_list_item(list_name, item_id)
            self.refresh()

    def ui_delete_entire_list(self, list_name: str) -> None:
        """Удаление списка целиком с подтверждением пользователя."""
        if messagebox.askyesno("Подтверждение", f"Удалить весь список '{list_name}'?"):
            if self.household:
                self.household.delete_list(list_name)
                self.current_selected_list = ""
                if self.shell:
                    self.shell.current_selected_list = ""
                self.refresh()
