"""
Модуль переиспользуемой фильтрации и пагинации UI для Desktop Hub Акакия.

Обеспечивает:
1. PaginationModel — чистая модель состояния пагинации и поиска (не зависит от Tkinter и источников данных).
2. PaginationBar — визуальная панель навигации по страницам (кнопки «←» / «→», счетчик страниц).
3. PagedListController — переиспользуемый контроллер рендеринга списков с поддержкой фильтрации и пагинации.
"""

import math
import tkinter as tk
from typing import Any, Callable, Generic, List, Optional, TypeVar

def _bind_hover(
    widget: tk.Widget,
    normal_bg: str,
    hover_bg: str,
    normal_fg: Optional[str] = None,
    hover_fg: Optional[str] = None
) -> None:
    """Добавляет hover-эффект при наведении курсора на виджет."""
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
T = TypeVar("T")


class PaginationModel(Generic[T]):
    """
    Чистая модель данных для управления пагинацией и текстовой фильтрацией.
    Не привязана к GUI или конкретным моделям базы данных.
    """

    def __init__(
        self,
        items: Optional[List[T]] = None,
        page_size: int = 8,
        filter_fn: Optional[Callable[[T, str], bool]] = None
    ):
        self._raw_items: List[T] = list(items) if items is not None else []
        self._page_size: int = max(1, page_size)
        self._current_page: int = 1
        self._filter_query: str = ""
        self._filter_fn: Optional[Callable[[T, str], bool]] = filter_fn

    @property
    def page_size(self) -> int:
        return self._page_size

    @page_size.setter
    def page_size(self, value: int) -> None:
        self._page_size = max(1, value)
        self._adjust_page_bounds()

    @property
    def filter_query(self) -> str:
        return self._filter_query

    @property
    def current_page(self) -> int:
        return self._current_page

    @property
    def filtered_items(self) -> List[T]:
        """Возвращает отфильтрованный список элементов."""
        if not self._filter_query:
            return list(self._raw_items)
        q = self._filter_query.strip().lower()
        if not self._filter_fn:
            return [it for it in self._raw_items if q in str(it).lower()]
        return [it for it in self._raw_items if self._filter_fn(it, q)]

    @property
    def total_items(self) -> int:
        """Общее количество отфильтрованных элементов."""
        return len(self.filtered_items)

    @property
    def total_pages(self) -> int:
        """Общее количество страниц для текущих отфильтрованных элементов."""
        count = self.total_items
        if count == 0:
            return 1
        return math.ceil(count / self._page_size)

    @property
    def page_items(self) -> List[T]:
        """Элементы для отображения на текущей странице."""
        items = self.filtered_items
        if not items:
            return []
        start = (self._current_page - 1) * self._page_size
        end = start + self._page_size
        return items[start:end]

    @property
    def has_prev(self) -> bool:
        return self._current_page > 1

    @property
    def has_next(self) -> bool:
        return self._current_page < self.total_pages

    def set_items(self, items: List[T]) -> None:
        """
        Обновляет исходную коллекцию элементов.
        Сохраняет исходный список без мутации переданного объекта.
        Автоматически корректирует current_page при удалении элементов.
        """
        self._raw_items = list(items)
        self._adjust_page_bounds()

    def set_filter(self, query: str) -> None:
        """
        Устанавливает поисковый запрос.
        При изменении фильтра всегда сбрасывает страницу на 1-ю.
        """
        new_q = query.strip()
        if new_q != self._filter_query:
            self._filter_query = new_q
            self._current_page = 1
        self._adjust_page_bounds()

    def next_page(self) -> bool:
        """Переход на следующую страницу. Возвращает True, если страница изменилась."""
        if self.has_next:
            self._current_page += 1
            return True
        return False

    def prev_page(self) -> bool:
        """Переход на предыдущую страницу. Возвращает True, если страница изменилась."""
        if self.has_prev:
            self._current_page -= 1
            return True
        return False

    def go_to_page(self, page: int) -> bool:
        """Переход на заданную страницу. Возвращает True, если страница изменилась."""
        target = max(1, min(page, self.total_pages))
        if target != self._current_page:
            self._current_page = target
            return True
        return False

    def reset(self) -> None:
        """Сброс пагинации и фильтрации к исходному состоянию."""
        self._current_page = 1
        self._filter_query = ""

    def _adjust_page_bounds(self) -> None:
        """Корректирует current_page в пределах [1, total_pages]."""
        max_p = self.total_pages
        if self._current_page > max_p:
            self._current_page = max(1, max_p)
        elif self._current_page < 1:
            self._current_page = 1


class PaginationBar(tk.Frame):
    """
    Визуальный компонент панели пагинации: кнопки «←» и «→», счетчик страниц.
    Стилизован под темную тему Akakiy Hub 2.0.
    """

    BG_PANEL = "#161b22"
    BG_CARD = "#1b212a"
    BG_BTN = "#21262d"
    BG_BTN_HOVER = "#30363d"
    FG_WHITE = "#f0f6fc"
    FG_MUTED = "#8b949e"
    FG_DIM = "#484f58"
    ACCENT_CYAN = "#38bdf8"

    def __init__(
        self,
        master: tk.Widget,
        on_prev: Optional[Callable[[], None]] = None,
        on_next: Optional[Callable[[], None]] = None,
        **kwargs
    ):
        if "bg" not in kwargs:
            kwargs["bg"] = self.BG_PANEL
        super().__init__(master, **kwargs)

        self.on_prev = on_prev
        self.on_next = on_next

        self._build_ui()

    def _build_ui(self) -> None:
        """Построение кнопок и текстовой метки пагинатора."""
        # Центрирующий контейнер
        center_box = tk.Frame(self, bg=self.cget("bg"))
        center_box.pack(anchor="center", pady=6)

        # Кнопка «Назад»
        self.btn_prev = tk.Button(
            center_box,
            text="←",
            font=("Segoe UI", 10, "bold"),
            bg=self.BG_BTN,
            fg=self.FG_WHITE,
            bd=1,
            relief="solid",
            padx=12,
            pady=3,
            cursor="hand2",
            command=self._handle_prev
        )
        self.btn_prev.pack(side="left", padx=(0, 12))
        _bind_hover(self.btn_prev, self.BG_BTN, self.BG_BTN_HOVER, self.FG_WHITE, self.FG_WHITE)

        # Метка информации о странице
        self.lbl_info = tk.Label(
            center_box,
            text="Страница 1 из 1",
            font=("Segoe UI", 9),
            fg=self.FG_MUTED,
            bg=self.cget("bg")
        )
        self.lbl_info.pack(side="left", padx=8)

        # Кнопка «Вперёд»
        self.btn_next = tk.Button(
            center_box,
            text="→",
            font=("Segoe UI", 10, "bold"),
            bg=self.BG_BTN,
            fg=self.FG_WHITE,
            bd=1,
            relief="solid",
            padx=12,
            pady=3,
            cursor="hand2",
            command=self._handle_next
        )
        self.btn_next.pack(side="left", padx=(12, 0))
        _bind_hover(self.btn_next, self.BG_BTN, self.BG_BTN_HOVER, self.FG_WHITE, self.FG_WHITE)

    def _handle_prev(self) -> None:
        if self.on_prev:
            self.on_prev()

    def _handle_next(self) -> None:
        if self.on_next:
            self.on_next()

    def update_state(self, model: PaginationModel) -> None:
        """
        Обновляет текст метки и активность кнопок в соответствии с состоянием модели.
        """
        curr = model.current_page
        total = model.total_pages
        items_cnt = model.total_items

        self.lbl_info.config(text=f"Страница {curr} из {total}  •  Всего: {items_cnt}")

        if model.has_prev:
            self.btn_prev.config(state="normal", fg=self.FG_WHITE, cursor="hand2")
        else:
            self.btn_prev.config(state="disabled", fg=self.FG_DIM, cursor="arrow")

        if model.has_next:
            self.btn_next.config(state="normal", fg=self.FG_WHITE, cursor="hand2")
        else:
            self.btn_next.config(state="disabled", fg=self.FG_DIM, cursor="arrow")


class PagedListController(Generic[T]):
    """
    Контроллер для связи списка элементов, поисковой строки, контейнера рендеринга
    и панели пагинации.
    """

    def __init__(
        self,
        content_frame: tk.Widget,
        pagination_bar: PaginationBar,
        render_item: Callable[[tk.Widget, T], None],
        filter_fn: Optional[Callable[[T, str], bool]] = None,
        page_size: int = 8,
        empty_text: str = "Записей пока нет.",
        no_results_text: str = "Ничего не найдено.",
        empty_bg: str = "#1b212a",
        empty_fg: str = "#8b949e",
    ):
        self.content_frame = content_frame
        self.pagination_bar = pagination_bar
        self.render_item = render_item
        self.empty_text = empty_text
        self.no_results_text = no_results_text
        self.empty_bg = empty_bg
        self.empty_fg = empty_fg

        self.model = PaginationModel[T](
            items=[],
            page_size=page_size,
            filter_fn=filter_fn
        )

        # Подключаем коллбэки пагинатора
        self.pagination_bar.on_prev = self._on_prev_page
        self.pagination_bar.on_next = self._on_next_page

    def set_items(self, items: List[T]) -> None:
        """Устанавливает новые исходные элементы и выполняет отрисовку."""
        self.model.set_items(items)
        self.render()

    def set_filter(self, query: str) -> None:
        """Устанавливает фильтр поиска и выполняет отрисовку."""
        self.model.set_filter(query)
        self.render()

    def go_to_page(self, page: int) -> bool:
        """Переход на заданную страницу с перерисовкой."""
        if self.model.go_to_page(page):
            self.render()
            return True
        return False

    def next_page(self) -> bool:
        """Переход на следующую страницу с перерисовкой."""
        if self.model.next_page():
            self.render()
            return True
        return False

    def prev_page(self) -> bool:
        """Переход на предыдущую страницу с перерисовкой."""
        if self.model.prev_page():
            self.render()
            return True
        return False

    def _on_prev_page(self) -> None:
        self.prev_page()

    def _on_next_page(self) -> None:
        self.next_page()

    def render(self) -> None:
        """Очищает контейнер и отрисовывает элементы текущей страницы."""
        if not self.content_frame or not self.content_frame.winfo_exists():
            return

        for w in self.content_frame.winfo_children():
            w.destroy()

        # 1. Если исходных элементов вообще нет
        if len(self.model._raw_items) == 0:
            tk.Label(
                self.content_frame,
                text=self.empty_text,
                font=("Segoe UI", 11),
                fg=self.empty_fg,
                bg=self.empty_bg
            ).pack(pady=40)
            self.pagination_bar.update_state(self.model)
            return

        # 2. Если после фильтрации ничего не найдено
        if self.model.total_items == 0:
            tk.Label(
                self.content_frame,
                text=self.no_results_text,
                font=("Segoe UI", 11),
                fg=self.empty_fg,
                bg=self.empty_bg
            ).pack(pady=40)
            self.pagination_bar.update_state(self.model)
            return

        # 3. Отрисовка элементов страницы
        page_items = self.model.page_items
        for item in page_items:
            self.render_item(self.content_frame, item)

        # 4. Обновление состояния панели пагинации
        self.pagination_bar.update_state(self.model)
