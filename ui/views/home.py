"""
Модульный главный экран дашборда (HomeView) для Desktop Hub Акакия 2.0 (Visual Direction 2.0).

Реализует органическую визуальную композицию:
1. Атмосферный Hero-блок: живое органическое ядро Akakiy Core в центре;
2. Состояние Акакия: минималистичный pill-бейдж и тонкое описание;
3. Ключевое состояние дня: лёгкая горизонтальная полоса метрик без тяжёлых рамок;
4. Пространство рабочих данных (2 сбалансированные воздушные колонки):
   • Слева: активные задачи, ближайшие события и списки дел;
   • Справа: живая активность субагентов, артефакты и последние заметки.
"""

from pathlib import Path
import tkinter as tk
from typing import Any, Optional, Union

from tools.agents.result import ArtifactType
from ui.native_visual_core import NativeGPUVisualCore
from ui.akakiy_core import AkakiyCore
from ui.views.base import BaseView, bind_hover


class HomeView(BaseView):
    """
    Главный экран рабочего пространства Desktop Hub 2.0.
    Фокусирует визуальное внимание на живом ядре и ключевом состоянии дня.
    """

    def __init__(self, master: tk.Widget, shell: Any = None, **kwargs):
        super().__init__(master, shell=shell, **kwargs)
        self.neural_core: Optional[Union[NativeGPUVisualCore, AkakiyCore]] = None
        self.core: Optional[Union[NativeGPUVisualCore, AkakiyCore]] = None
        self.lbl_status_badge: Optional[tk.Label] = None
        self.lbl_status_desc: Optional[tk.Label] = None
        self.render()

    def render(self) -> None:
        """Построение интерфейса главного экрана с органическим Hero-блоком."""
        for w in self.winfo_children():
            w.destroy()

        # =====================================================================
        # 1. АТМОСФЕРНЫЙ HERO-БЛОК: ЖИВОЕ ОРГАНИЧЕСКОЕ ЯДРО
        # =====================================================================
        hero_frame = tk.Frame(
            self,
            bg=self.BG_HERO,
            bd=0,
            highlightbackground=self.BORDER_SUBTLE,
            highlightthickness=1
        )
        hero_frame.pack(fill="x", pady=(0, 16))

        # 1.1. Живой аппаратный арт-объект Akakiy Core (нативный WGL / OpenGL / GLSL)
        self.neural_core = NativeGPUVisualCore(
            hero_frame,
            width=520,
            height=210,
            bg=self.BG_HERO,
        )
        self.neural_core.pack(pady=(12, 2))
        self.core = self.neural_core

        if self.shell:
            self.shell.neural_core = self.neural_core
            cur_state = getattr(self.shell, "current_state", "idle")
            self.neural_core.set_state(cur_state)

        # 1.2. Статусный pill-бейдж и описание
        status_row = tk.Frame(hero_frame, bg=self.BG_HERO)
        status_row.pack(pady=(0, 4))

        pill_frame = tk.Frame(
            status_row,
            bg="#0e1624",
            bd=0,
            highlightbackground=self.BORDER_LIGHT,
            highlightthickness=1,
            padx=14,
            pady=3
        )
        pill_frame.pack()

        cur_palette = self.neural_core.color_scheme
        badge_txt = cur_palette.get("status", "СИСТЕМА В РАВНОВЕСИИ")
        badge_fg = cur_palette.get("text", self.ACCENT_CYAN)

        self.lbl_status_badge = tk.Label(
            pill_frame,
            text=f"● {badge_txt}",
            font=self.FONT_HEADING,
            fg=badge_fg,
            bg="#0e1624"
        )
        self.lbl_status_badge.pack()

        desc_txt = self.neural_core.state_description or "Акакий 2.0 • Органическое ядро в спокойном равновесии"
        self.lbl_status_desc = tk.Label(
            hero_frame,
            text=desc_txt,
            font=self.FONT_BODY,
            fg=self.FG_MUTED,
            bg=self.BG_HERO
        )
        self.lbl_status_desc.pack(pady=(0, 10))

        # 1.3. Ключевое состояние дня (Day State Strip)
        day_bar = tk.Frame(
            hero_frame,
            bg=self.BG_CARD_INNER,
            bd=0,
            highlightbackground=self.BORDER_SUBTLE,
            highlightthickness=1
        )
        day_bar.pack(fill="x", padx=20, pady=(0, 12))

        # Сбор метрик дня
        pending_tasks = len(self.household.list_tasks(status="pending")["tasks"]) if self.household else 0
        due_dict = self.household.check_due_reminders() if self.household and hasattr(self.household, "check_due_reminders") else {}
        due_count = due_dict.get("due_count", 0) if isinstance(due_dict, dict) else 0
        total_lists = len(self.household.lists) if self.household and hasattr(self.household, "lists") else 0
        total_notes = len(self.household.notes) if self.household and hasattr(self.household, "notes") else 0

        metrics_frame = tk.Frame(day_bar, bg=self.BG_CARD_INNER)
        metrics_frame.pack(side="left", padx=16, pady=7)

        # Метка задач
        tk.Label(
            metrics_frame,
            text=f"⚡ Задачи: {pending_tasks}",
            font=self.FONT_HEADING,
            fg=self.ACCENT_CYAN,
            bg=self.BG_CARD_INNER
        ).pack(side="left", padx=(0, 18))

        # Метка напоминаний (акцент при наличии наступивших)
        rem_fg = self.ACCENT_RED if due_count > 0 else self.ACCENT_PURPLE
        rem_icon = "🔔" if due_count > 0 else "⏰"
        rem_label = f"{rem_icon} События: {due_count} наступило" if due_count > 0 else f"{rem_icon} События: активно"
        tk.Label(
            metrics_frame,
            text=rem_label,
            font=self.FONT_HEADING,
            fg=rem_fg,
            bg=self.BG_CARD_INNER
        ).pack(side="left", padx=(0, 18))

        # Метка списков
        tk.Label(
            metrics_frame,
            text=f"📋 Списки: {total_lists}",
            font=self.FONT_BODY,
            fg=self.FG_MAIN,
            bg=self.BG_CARD_INNER
        ).pack(side="left", padx=(0, 18))

        # Метка заметок
        tk.Label(
            metrics_frame,
            text=f"📝 Заметки: {total_notes}",
            font=self.FONT_BODY,
            fg=self.FG_MUTED,
            bg=self.BG_CARD_INNER
        ).pack(side="left")

        # Кнопка экспресс-сводки дня
        btn_brief = tk.Button(
            day_bar,
            text="⚡ Сводка дня",
            font=self.FONT_CAPTION,
            bg="#131c2c",
            fg=self.ACCENT_AMBER,
            activebackground="#1e2c45",
            activeforeground="#ffffff",
            bd=0,
            highlightbackground=self.BORDER_LIGHT,
            highlightthickness=1,
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=3,
            command=self.ui_show_daily_briefing
        )
        btn_brief.pack(side="right", padx=14, pady=5)
        bind_hover(btn_brief, "#131c2c", "#1e2c45")

        # =====================================================================
        # 2. РАБОЧИЕ СЕКЦИИ (2 ВОЗДУШНЫЕ КОЛОНКИ С ТОНКИМИ ПОВЕРХНОСТЯМИ)
        # =====================================================================
        workspace_row = tk.Frame(self, bg=self.BG_MAIN)
        workspace_row.pack(fill="both", expand=True)

        # ---------------------------------------------------------------------
        # ЛЕВАЯ КОЛОНКА (50%): Задачи, События, Списки
        # ---------------------------------------------------------------------
        col_left = tk.Frame(workspace_row, bg=self.BG_MAIN)
        col_left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        # 2.1. Задачи
        card_tasks = tk.Frame(
            col_left,
            bg=self.BG_CARD,
            bd=0,
            highlightbackground=self.BORDER_SUBTLE,
            highlightthickness=1
        )
        card_tasks.pack(fill="x", pady=(0, 10))

        tasks_header = tk.Frame(card_tasks, bg=self.BG_CARD)
        tasks_header.pack(fill="x", padx=16, pady=(10, 6))

        tk.Label(
            tasks_header,
            text="✓  АКТИВНЫЕ ЗАДАЧИ",
            font=self.FONT_HEADING,
            fg=self.ACCENT_CYAN,
            bg=self.BG_CARD
        ).pack(side="left")

        btn_all_t = tk.Button(
            tasks_header,
            text="Все задачи →",
            font=self.FONT_CAPTION,
            fg=self.ACCENT_BLUE,
            bg=self.BG_CARD,
            bd=0,
            cursor="hand2",
            command=lambda: self.switch_section("tasks")
        )
        btn_all_t.pack(side="right")

        tasks = self.household.list_tasks(status="pending")["tasks"][:3] if self.household else []
        if not tasks:
            tk.Label(
                card_tasks,
                text="Нет активных задач.",
                font=self.FONT_BODY,
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(anchor="w", padx=16, pady=(2, 10))
        else:
            for t in tasks:
                t_row = tk.Frame(card_tasks, bg=self.BG_CARD)
                t_row.pack(fill="x", padx=16, pady=2)

                chk = tk.Button(
                    t_row,
                    text="☐",
                    font=self.FONT_BODY,
                    bg=self.BG_CARD,
                    fg=self.FG_MUTED,
                    bd=0,
                    cursor="hand2",
                    command=lambda tid=t["id"]: self.quick_complete_task(tid)
                )
                chk.pack(side="left")

                title_clean = t["title"] if len(t["title"]) <= 38 else t["title"][:35] + "..."
                tk.Label(
                    t_row,
                    text=title_clean,
                    font=self.FONT_BODY,
                    fg=self.FG_MAIN,
                    bg=self.BG_CARD
                ).pack(side="left", padx=4)

            tk.Frame(card_tasks, bg=self.BG_CARD, height=6).pack()

        # 2.2. Ближайшие события
        card_rems = tk.Frame(
            col_left,
            bg=self.BG_CARD,
            bd=0,
            highlightbackground=self.BORDER_SUBTLE,
            highlightthickness=1
        )
        card_rems.pack(fill="x", pady=(0, 10))

        rems_header = tk.Frame(card_rems, bg=self.BG_CARD)
        rems_header.pack(fill="x", padx=16, pady=(10, 6))

        tk.Label(
            rems_header,
            text="🔔  БЛИЖАЙШИЕ СОБЫТИЯ",
            font=self.FONT_HEADING,
            fg=self.ACCENT_PURPLE,
            bg=self.BG_CARD
        ).pack(side="left")

        btn_all_r = tk.Button(
            rems_header,
            text="Все напоминания →",
            font=self.FONT_CAPTION,
            fg=self.ACCENT_PURPLE,
            bg=self.BG_CARD,
            bd=0,
            cursor="hand2",
            command=lambda: self.switch_section("reminders")
        )
        btn_all_r.pack(side="right")

        rems_dict = self.household.list_reminders() if self.household and hasattr(self.household, "list_reminders") else {}
        rems = rems_dict.get("reminders", []) if isinstance(rems_dict, dict) else []
        due_ids = {r.get("id") for r in due_dict.get("due_reminders", [])} if isinstance(due_dict, dict) else set()

        if not rems:
            tk.Label(
                card_rems,
                text="Ближайших событий нет.",
                font=self.FONT_BODY,
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(anchor="w", padx=16, pady=(2, 10))
        else:
            for r in rems[:3]:
                is_due = r.get("id") in due_ids
                r_row = tk.Frame(card_rems, bg=self.BG_CARD)
                r_row.pack(fill="x", padx=16, pady=2)

                icon = "⏰" if not is_due else "🔔"
                tag_fg = self.ACCENT_RED if is_due else self.ACCENT_PURPLE
                tk.Label(
                    r_row,
                    text=icon,
                    font=self.FONT_BODY,
                    fg=tag_fg,
                    bg=self.BG_CARD
                ).pack(side="left")

                t_snip = r["text"][:32] + ("..." if len(r["text"]) > 32 else "")
                tk.Label(
                    r_row,
                    text=f" {t_snip}",
                    font=self.FONT_BODY,
                    fg=self.FG_MAIN,
                    bg=self.BG_CARD
                ).pack(side="left")

                time_badge = "Наступило!" if is_due else r.get("remind_at", "")[:10]
                tk.Label(
                    r_row,
                    text=f"({time_badge})",
                    font=self.FONT_CAPTION,
                    fg=tag_fg if is_due else self.FG_DIM,
                    bg=self.BG_CARD
                ).pack(side="right")

            tk.Frame(card_rems, bg=self.BG_CARD, height=6).pack()

        # 2.3. Списки дел
        card_lists = tk.Frame(
            col_left,
            bg=self.BG_CARD,
            bd=0,
            highlightbackground=self.BORDER_SUBTLE,
            highlightthickness=1
        )
        card_lists.pack(fill="x")

        lists_header = tk.Frame(card_lists, bg=self.BG_CARD)
        lists_header.pack(fill="x", padx=16, pady=(10, 6))

        tk.Label(
            lists_header,
            text="📋  СПИСКИ ДЕЛ",
            font=self.FONT_HEADING,
            fg=self.ACCENT_GREEN,
            bg=self.BG_CARD
        ).pack(side="left")

        btn_all_l = tk.Button(
            lists_header,
            text="Все списки →",
            font=self.FONT_CAPTION,
            fg=self.ACCENT_GREEN,
            bg=self.BG_CARD,
            bd=0,
            cursor="hand2",
            command=lambda: self.switch_section("lists")
        )
        btn_all_l.pack(side="right")

        lists_keys = list(self.household.lists.keys())[:3] if self.household and hasattr(self.household, "lists") else []
        if not lists_keys:
            tk.Label(
                card_lists,
                text="Списков пока нет.",
                font=self.FONT_BODY,
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(anchor="w", padx=16, pady=(2, 10))
        else:
            for l_name in lists_keys:
                cnt = len(self.household.lists[l_name])
                tk.Label(
                    card_lists,
                    text=f"• {l_name} ({cnt} эл.)",
                    font=self.FONT_BODY,
                    fg=self.FG_MAIN,
                    bg=self.BG_CARD
                ).pack(anchor="w", padx=16, pady=2)
            tk.Frame(card_lists, bg=self.BG_CARD, height=6).pack()

        # ---------------------------------------------------------------------
        # ПРАВАЯ КОЛОНКА (50%): Активность и результаты, Заметки
        # ---------------------------------------------------------------------
        col_right = tk.Frame(workspace_row, bg=self.BG_MAIN)
        col_right.pack(side="right", fill="both", expand=True, padx=(8, 0))

        # 2.4. Активность и результаты
        act_box = tk.Frame(
            col_right,
            bg=self.BG_CARD,
            bd=0,
            highlightbackground=self.BORDER_SUBTLE,
            highlightthickness=1
        )
        act_box.pack(fill="both", expand=True, pady=(0, 10))

        act_header = tk.Frame(act_box, bg=self.BG_CARD)
        act_header.pack(fill="x", padx=16, pady=(10, 6))

        tk.Label(
            act_header,
            text="⚡  АКТИВНОСТЬ И РЕЗУЛЬТАТЫ",
            font=self.FONT_HEADING,
            fg=self.ACCENT_AMBER,
            bg=self.BG_CARD
        ).pack(side="left")

        btn_to_chat = tk.Button(
            act_header,
            text="Открыть Чат →",
            font=self.FONT_CAPTION,
            fg=self.ACCENT_BLUE,
            bg=self.BG_CARD,
            bd=0,
            cursor="hand2",
            command=lambda: self.switch_section("chat")
        )
        btn_to_chat.pack(side="right")

        recent_results = []
        if self.shell and hasattr(self.shell, "recent_work_results"):
            raw_w = getattr(self.shell, "recent_work_results")
            if isinstance(raw_w, list):
                recent_results = list(raw_w)[-3:]

        if not recent_results and self.shell and hasattr(self.shell, "log_messages"):
            raw_logs = getattr(self.shell, "log_messages")
            if isinstance(raw_logs, list) and raw_logs:
                recent_results = [
                    {
                        "type": p.lower(),
                        "title": f"Событие [{p}]",
                        "message": txt,
                        "time": tm,
                        "success": p not in ("ERR", "FAIL"),
                        "created_files": []
                    }
                    for p, txt, tm in raw_logs[-3:]
                ]

        if not recent_results:
            tk.Label(
                act_box,
                text="Акакий готов к работе. Начните диалог или введите задачу в нижней строке.",
                font=self.FONT_BODY,
                fg=self.FG_MUTED,
                bg=self.BG_CARD,
                justify="left",
                wraplength=420
            ).pack(anchor="w", padx=16, pady=10)
        else:
            for item in reversed(recent_results):
                row = tk.Frame(
                    act_box,
                    bg=self.BG_CARD_INNER,
                    bd=0,
                    highlightbackground=self.BORDER_SUBTLE,
                    highlightthickness=1
                )
                row.pack(fill="x", padx=14, pady=3)

                top_l = tk.Frame(row, bg=self.BG_CARD_INNER)
                top_l.pack(fill="x", padx=10, pady=(6, 2))

                is_ok = item.get("success", True)
                b_color = self.ACCENT_GREEN if is_ok else self.ACCENT_RED
                raw_type = str(item.get("type", "ДЕЙСТВИЕ")).upper()
                d_badge = item.get("domain_badge")
                if d_badge:
                    badge_label = str(d_badge).upper()
                else:
                    domain_title_map = {
                        "HOUSEHOLD": "🏠 ДОМАШНИЕ ДЕЛА",
                        "TASKS": "🏠 ДОМАШНИЕ ДЕЛА",
                        "REMINDERS": "🔔 НАПОМИНАНИЯ",
                        "NOTES": "📝 ЗАМЕТКИ",
                        "LISTS": "📋 СПИСКИ",
                        "RESEARCH": "🔍 ИССЛЕДОВАНИЯ",
                        "IMAGE": "🎨 ИЗОБРАЖЕНИЕ",
                        "PRESENTATION": "📊 ПРЕЗЕНТАЦИЯ",
                        "DOCUMENT": "📄 ДОКУМЕНТ",
                        "CODING": "💻 КОД",
                        "FILE": "📁 ФАЙЛ",
                        "PLAN": "📋 ПЛАН",
                        "CHAT": "💬 ДИАЛОГ",
                    }
                    badge_label = domain_title_map.get(raw_type, raw_type)

                tk.Label(
                    top_l,
                    text=f"[{badge_label}]",
                    font=self.FONT_MONO,
                    fg=b_color,
                    bg="#101824",
                    padx=4,
                    pady=1
                ).pack(side="left")

                title_txt = str(item.get("title", "") or item.get("query", ""))
                if len(title_txt) > 38:
                    title_txt = title_txt[:35] + "..."
                tk.Label(
                    top_l,
                    text=f"  {title_txt}",
                    font=self.FONT_HEADING,
                    fg=self.FG_WHITE,
                    bg=self.BG_CARD_INNER
                ).pack(side="left")

                tk.Label(
                    top_l,
                    text=str(item.get("time", "")),
                    font=self.FONT_MONO,
                    fg=self.FG_DIM,
                    bg=self.BG_CARD_INNER
                ).pack(side="right")

                msg_snip = str(item.get("message", ""))
                if msg_snip:
                    if len(msg_snip) > 105:
                        msg_snip = msg_snip[:102] + "..."
                    tk.Label(
                        row,
                        text=msg_snip,
                        font=self.FONT_BODY,
                        fg=self.FG_MAIN,
                        bg=self.BG_CARD_INNER,
                        justify="left",
                        anchor="w"
                    ).pack(fill="x", padx=10, pady=(0, 4))

                artifacts = item.get("artifacts") or []
                c_files = item.get("created_files") or []
                if not artifacts and c_files:
                    artifacts = [{"name": Path(str(f)).name, "path": str(f)} for f in c_files]

                image_arts = []
                other_arts = []
                for a in artifacts:
                    if isinstance(a, dict):
                        is_img = (a.get("type") == "image") or (ArtifactType.guess_type(a.get("path") or a.get("name") or "") == ArtifactType.IMAGE)
                    elif hasattr(a, "is_image"):
                        is_img = a.is_image
                    else:
                        is_img = ArtifactType.guess_type(str(a)) == ArtifactType.IMAGE
                    if is_img:
                        image_arts.append(a)
                    else:
                        other_arts.append(a)

                # Отрисовка интерактивных карточек IMAGE Artifact с preview
                if image_arts:
                    from ui.artifact_card import create_artifact_card
                    for img_art in image_arts[:2]:
                        try:
                            card = create_artifact_card(row, img_art, compact=True)
                            card.pack(fill="x", padx=10, pady=(2, 6))
                        except Exception:
                            pass

                # Отрисовка неграфических артефактов (документы, файлы)
                if other_arts:
                    art_row = tk.Frame(row, bg=self.BG_CARD_INNER)
                    art_row.pack(fill="x", padx=10, pady=(0, 6))
                    tk.Label(
                        art_row,
                        text="Артефакты: ",
                        font=self.FONT_CAPTION,
                        fg=self.ACCENT_CYAN,
                        bg=self.BG_CARD_INNER
                    ).pack(side="left")
                    for a in other_arts[:2]:
                        fname = a.get("name") if isinstance(a, dict) else (getattr(a, "name", None) or Path(str(a)).name)
                        tk.Label(
                            art_row,
                            text=f"📁 {fname}",
                            font=self.FONT_MONO,
                            fg=self.ACCENT_CYAN,
                            bg="#142236",
                            padx=4,
                            pady=1
                        ).pack(side="left", padx=2)

        # 2.5. Последние заметки
        notes_box = tk.Frame(
            col_right,
            bg=self.BG_CARD,
            bd=0,
            highlightbackground=self.BORDER_SUBTLE,
            highlightthickness=1
        )
        notes_box.pack(fill="x")

        n_hdr = tk.Frame(notes_box, bg=self.BG_CARD)
        n_hdr.pack(fill="x", padx=16, pady=(10, 6))

        tk.Label(
            n_hdr,
            text="📝  ПОСЛЕДНИЕ ЗАМЕТКИ",
            font=self.FONT_HEADING,
            fg=self.ACCENT_CYAN,
            bg=self.BG_CARD
        ).pack(side="left")

        btn_all_n = tk.Button(
            n_hdr,
            text="Все заметки →",
            font=self.FONT_CAPTION,
            fg=self.ACCENT_CYAN,
            bg=self.BG_CARD,
            bd=0,
            cursor="hand2",
            command=lambda: self.switch_section("notes")
        )
        btn_all_n.pack(side="right")

        notes = self.household.notes[-2:] if self.household and self.household.notes else []
        if not notes:
            tk.Label(
                notes_box,
                text="Заметок пока нет.",
                font=self.FONT_BODY,
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(anchor="w", padx=16, pady=(2, 10))
        else:
            for n in reversed(notes):
                item_card = tk.Frame(
                    notes_box,
                    bg=self.BG_CARD_INNER,
                    bd=0,
                    highlightbackground=self.BORDER_SUBTLE,
                    highlightthickness=1
                )
                item_card.pack(fill="x", padx=14, pady=3)

                tk.Label(
                    item_card,
                    text=n.get("title", ""),
                    font=self.FONT_HEADING,
                    fg=self.FG_WHITE,
                    bg=self.BG_CARD_INNER
                ).pack(anchor="w", padx=10, pady=(6, 2))

                c_prev = n.get("content", "")[:75] + ("..." if len(n.get("content", "")) > 75 else "")
                tk.Label(
                    item_card,
                    text=c_prev,
                    font=self.FONT_BODY,
                    fg=self.FG_MUTED,
                    bg=self.BG_CARD_INNER,
                    justify="left",
                    wraplength=380
                ).pack(anchor="w", padx=10, pady=(0, 6))

            tk.Frame(notes_box, bg=self.BG_CARD, height=6).pack()

    # -------------------------------------------------------------------------
    # Реактивные методы синхронизации и обновления
    # -------------------------------------------------------------------------

    def update_state_display(
        self,
        state_name: str,
        active_agent: Optional[str] = None,
        active_step: Optional[str] = None
    ) -> None:
        """Реактивно обновляет текстовые бейджи состояния ядра и Domain Agent."""
        if not self.neural_core:
            return

        palette = self.neural_core.COLOR_PALETTES.get(state_name, self.neural_core.COLOR_PALETTES["idle"])
        if self.lbl_status_badge and self.lbl_status_badge.winfo_exists():
            if active_agent and state_name == "working":
                agent_lower = active_agent.lower()
                clean_name = active_agent.strip()
                if clean_name.startswith("🏠") or clean_name.startswith("🔍"):
                    badge_txt = clean_name.upper()
                else:
                    icon = "🏠 " if ("домашн" in agent_lower or "household" in agent_lower) else ("🔍 " if ("исследован" in agent_lower or "research" in agent_lower) else "")
                    badge_txt = f"{icon}{clean_name.upper()}"
            else:
                badge_txt = palette.get("status", state_name.upper())
            badge_fg = palette.get("text", self.ACCENT_CYAN)
            self.lbl_status_badge.config(text=f"● {badge_txt}", fg=badge_fg)

        if self.lbl_status_desc and self.lbl_status_desc.winfo_exists():
            if active_step and state_name == "working":
                desc_txt = active_step
            elif active_agent and state_name == "working":
                desc_txt = f"{active_agent} • Исполнение задачи…"
            else:
                desc_txt = palette.get("description", "")
            self.lbl_status_desc.config(text=desc_txt)

    def quick_complete_task(self, task_id: int) -> None:
        """Быстрое завершение задачи из сводки главной страницы."""
        if self.household:
            self.household.complete_task(task_id)
        self.refresh()

    def ui_show_daily_briefing(self) -> None:
        """Отображает структурированную сводку дня в окне и озвучивает при активном голосе."""
        from tkinter import messagebox
        from tools.daily_briefing import get_daily_briefing

        briefing = get_daily_briefing(self.household)
        text = briefing.get("text", "")

        if self.voice and hasattr(self.voice, "speak_phrase") and getattr(self.voice, "is_running", False):
            try:
                self.voice.speak_phrase(text)
            except Exception:
                pass

        messagebox.showinfo("⚡ Сводка дня", text)

    def refresh(self) -> None:
        """Реактивное обновление дашборда."""
        self.render()
