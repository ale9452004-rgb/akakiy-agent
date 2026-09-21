"""
Модульный экран настроек и диагностики (SettingsView) для Desktop Hub Акакия 2.0.
"""

import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Any, Callable, Optional

from tools.backup import export_data, import_data
from tools.validation import validate_project
from ui.views.base import BaseView, _bind_hover


class SettingsView(BaseView):
    """
    Экран настроек и системной диагностики (Settings).
    Обеспечивает отображение конфигурации бэкенда, хранилищ данных, резервное копирование и валидацию.
    """

    def __init__(self, master: tk.Widget, shell: Any = None, **kwargs):
        super().__init__(master, shell=shell, **kwargs)
        self.lbl_val_res: tk.Label = None
        self.lbl_backup_res: tk.Label = None
        self.btn_toggle_sound: tk.Button = None
        self.btn_toggle_tts: tk.Button = None
        self.render()

    def render(self) -> None:
        """Построение интерфейса настроек и диагностики."""
        for w in self.winfo_children():
            w.destroy()

        header_row = tk.Frame(self, bg=self.BG_MAIN)
        header_row.pack(fill="x", pady=(0, 16))

        tk.Label(
            header_row,
            text="НАСТРОЙКИ И ДИАГНОСТИКА СИСТЕМЫ",
            font=("Segoe UI", 14, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_MAIN
        ).pack(side="left")

        panel = tk.Frame(self, bg=self.BG_CARD, bd=1, relief="solid")
        panel.pack(fill="both", expand=True, padx=0, pady=0)

        # 1. Секция моделей
        tk.Label(
            panel,
            text="ИНТЕЛЛЕКТУАЛЬНЫЙ БЭКЕНД",
            font=("Segoe UI", 11, "bold"),
            fg=self.ACCENT_CYAN,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=20, pady=(20, 8))

        tk.Label(
            panel,
            text="• LLM Engine: Ollama Local Server (http://localhost:11434)\n"
                 "• Модель: qwen3:8b\n"
                 "• Skills Registry: project, memory, household\n"
                 "• Context Manager: Sliding Window + Data Injection Shield",
            font=("Segoe UI", 9),
            fg=self.FG_MAIN,
            bg=self.BG_CARD,
            justify="left"
        ).pack(anchor="w", padx=20, pady=(0, 16))

        # 2. Секция валидации
        tk.Label(
            panel,
            text="ПРОВЕРКА ЦЕЛОСТНОСТИ ПРОЕКТА",
            font=("Segoe UI", 11, "bold"),
            fg=self.ACCENT_GREEN,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=20, pady=(10, 8))

        btn_val = tk.Button(
            panel,
            text="Запустить validate_project()",
            font=("Segoe UI", 9, "bold"),
            bg=self.ACCENT_GREEN,
            fg="#0d1117",
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self.ui_run_validation
        )
        btn_val.pack(anchor="w", padx=20, pady=(0, 8))
        _bind_hover(btn_val, self.ACCENT_GREEN, "#56d364", "#0d1117", "#0d1117")

        self.lbl_val_res = tk.Label(
            panel,
            text="",
            font=("Consolas", 9),
            fg=self.FG_MUTED,
            bg=self.BG_CARD
        )
        self.lbl_val_res.pack(anchor="w", padx=20, pady=(0, 16))

        # 3. Секция хранилищ
        tk.Label(
            panel,
            text="ЛОКАЛЬНЫЕ ДАННЫЕ",
            font=("Segoe UI", 11, "bold"),
            fg=self.ACCENT_PURPLE,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=20, pady=(10, 8))

        tk.Label(
            panel,
            text="• Долговременная память: data/memory.json (изолировано)\n"
                 "• Бытовой слой: data/household.json (Tasks, Reminders, Notes, Lists)\n"
                 "• Резервное копирование: безопасный экспорт/импорт в JSON с валидацией",
            font=("Segoe UI", 9),
            fg=self.FG_MAIN,
            bg=self.BG_CARD,
            justify="left"
        ).pack(anchor="w", padx=20, pady=(0, 12))

        btn_box = tk.Frame(panel, bg=self.BG_CARD)
        btn_box.pack(anchor="w", padx=20, pady=(0, 10))

        btn_export = tk.Button(
            btn_box,
            text="⬆ Экспорт данных...",
            font=("Segoe UI", 9, "bold"),
            bg="#21262d",
            fg=self.FG_WHITE,
            bd=1,
            relief="solid",
            padx=14,
            pady=6,
            cursor="hand2",
            command=self.ui_export_data
        )
        btn_export.pack(side="left", padx=(0, 10))
        _bind_hover(btn_export, "#21262d", "#30363d", self.FG_WHITE, self.FG_WHITE)

        btn_import = tk.Button(
            btn_box,
            text="⬇ Импорт данных...",
            font=("Segoe UI", 9, "bold"),
            bg="#21262d",
            fg=self.FG_WHITE,
            bd=1,
            relief="solid",
            padx=14,
            pady=6,
            cursor="hand2",
            command=self.ui_import_data
        )
        btn_import.pack(side="left")
        _bind_hover(btn_import, "#21262d", "#30363d", self.FG_WHITE, self.FG_WHITE)

        self.lbl_backup_res = tk.Label(
            panel,
            text="",
            font=("Segoe UI", 9),
            fg=self.FG_MUTED,
            bg=self.BG_CARD
        )
        self.lbl_backup_res.pack(anchor="w", padx=20, pady=(0, 16))

        # 4. Секция уведомлений и звука
        tk.Label(
            panel,
            text="УВЕДОМЛЕНИЯ И ЗВУК",
            font=("Segoe UI", 11, "bold"),
            fg=self.ACCENT_AMBER,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=20, pady=(10, 8))

        # Ряд 1: Звук уведомлений
        row_sound = tk.Frame(panel, bg=self.BG_CARD)
        row_sound.pack(fill="x", padx=20, pady=(0, 10))

        sound_info = tk.Frame(row_sound, bg=self.BG_CARD)
        sound_info.pack(side="left", fill="x", expand=True)

        tk.Label(
            sound_info,
            text="Звук уведомлений",
            font=("Segoe UI", 10, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(anchor="w")

        tk.Label(
            sound_info,
            text="Воспроизведение системного звука Windows при появлении уведомлений",
            font=("Segoe UI", 9),
            fg=self.FG_MUTED,
            bg=self.BG_CARD
        ).pack(anchor="w")

        self.btn_toggle_sound = tk.Button(
            row_sound,
            text="",
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief="solid",
            padx=16,
            pady=4,
            cursor="hand2",
            command=self.toggle_notification_sound
        )
        self.btn_toggle_sound.pack(side="right", padx=(10, 0))

        # Ряд 2: Озвучивание напоминаний
        row_tts = tk.Frame(panel, bg=self.BG_CARD)
        row_tts.pack(fill="x", padx=20, pady=(0, 10))

        tts_info = tk.Frame(row_tts, bg=self.BG_CARD)
        tts_info.pack(side="left", fill="x", expand=True)

        tk.Label(
            tts_info,
            text="Озвучивать напоминания (TTS)",
            font=("Segoe UI", 10, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(anchor="w")

        tk.Label(
            tts_info,
            text="Произносить текст наступившего напоминания голосом через синтезатор речи",
            font=("Segoe UI", 9),
            fg=self.FG_MUTED,
            bg=self.BG_CARD
        ).pack(anchor="w")

        self.btn_toggle_tts = tk.Button(
            row_tts,
            text="",
            font=("Segoe UI", 9, "bold"),
            bd=1,
            relief="solid",
            padx=16,
            pady=4,
            cursor="hand2",
            command=self.toggle_speak_reminders
        )
        self.btn_toggle_tts.pack(side="right", padx=(10, 0))

        # Ряд 3: Кнопка проверки звука
        btn_test = tk.Button(
            panel,
            text="🔊 Проверить звук уведомления",
            font=("Segoe UI", 9, "bold"),
            bg="#21262d",
            fg=self.FG_WHITE,
            bd=1,
            relief="solid",
            padx=14,
            pady=5,
            cursor="hand2",
            command=self.test_notification_sound
        )
        btn_test.pack(anchor="w", padx=20, pady=(0, 20))
        _bind_hover(btn_test, "#21262d", "#30363d", self.FG_WHITE, self.FG_WHITE)

        self._update_sound_buttons()

    def _update_sound_buttons(self) -> None:
        """Обновляет визуальное состояние кнопок-тумблеров звука и TTS."""
        if not self.btn_toggle_sound or not self.btn_toggle_sound.winfo_exists():
            return

        sound_on = getattr(self.settings, "notification_sound", True)
        if sound_on:
            self.btn_toggle_sound.config(
                text="[ ВКЛ ]",
                bg="#112d1b",
                fg=self.ACCENT_GREEN,
                activebackground="#1b4d2e",
                activeforeground=self.ACCENT_GREEN
            )
        else:
            self.btn_toggle_sound.config(
                text="[ ВЫКЛ ]",
                bg="#21262d",
                fg=self.FG_MUTED,
                activebackground="#30363d",
                activeforeground=self.FG_MUTED
            )

        if not self.btn_toggle_tts or not self.btn_toggle_tts.winfo_exists():
            return

        tts_on = getattr(self.settings, "speak_reminders", True)
        if tts_on:
            self.btn_toggle_tts.config(
                text="[ ВКЛ ]",
                bg="#112d1b",
                fg=self.ACCENT_GREEN,
                activebackground="#1b4d2e",
                activeforeground=self.ACCENT_GREEN
            )
        else:
            self.btn_toggle_tts.config(
                text="[ ВЫКЛ ]",
                bg="#21262d",
                fg=self.FG_MUTED,
                activebackground="#30363d",
                activeforeground=self.FG_MUTED
            )

    def toggle_notification_sound(self) -> None:
        """Переключает настройку системного звука уведомлений."""
        cur = getattr(self.settings, "notification_sound", True)
        self.settings.notification_sound = not cur
        self.settings.save()
        self._update_sound_buttons()
        if self.shell and hasattr(self.shell, "_append_log"):
            status_str = "включён" if self.settings.notification_sound else "выключен"
            self.shell._append_log("SETTINGS", f"Звук уведомлений {status_str}.")

    def toggle_speak_reminders(self) -> None:
        """Переключает настройку озвучивания напоминаний через TTS."""
        cur = getattr(self.settings, "speak_reminders", True)
        self.settings.speak_reminders = not cur
        self.settings.save()
        self._update_sound_buttons()
        if self.shell and hasattr(self.shell, "_append_log"):
            status_str = "включено" if self.settings.speak_reminders else "выключено"
            self.shell._append_log("SETTINGS", f"Озвучивание напоминаний {status_str}.")

    def test_notification_sound(self) -> None:
        """Тестовое воспроизведение системного звука Windows."""
        from notifications.sound import play_system_sound
        play_system_sound()
        if self.shell and hasattr(self.shell, "_append_log"):
            self.shell._append_log("AUDIO", "Тестовый звуковой сигнал воспроизведён.")

    def refresh(self) -> None:
        """Реактивное обновление экрана настроек (контракт BaseView)."""
        self._update_sound_buttons()

    def ui_export_data(self) -> Optional[dict]:
        """Экспорт пользовательских данных в выбранный пользователем JSON-файл."""
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Backup", "*.json"), ("All Files", "*.*")],
            title="Сохранить резервную копию Акакия"
        )
        if not file_path:
            return None

        res = export_data(
            output_path=file_path,
            household=self.household,
            memory=self.memory
        )

        if not self.lbl_backup_res or not self.lbl_backup_res.winfo_exists():
            return res

        if res.get("success"):
            self.lbl_backup_res.config(
                text=f"✓ {res.get('message')}",
                fg=self.ACCENT_GREEN
            )
            if self.shell and hasattr(self.shell, "_append_log"):
                self.shell._append_log("BACKUP", res.get("message"))
        else:
            self.lbl_backup_res.config(
                text=f"✗ {res.get('error')}",
                fg=self.ACCENT_RED
            )
        return res

    def ui_import_data(self) -> Optional[dict]:
        """Импорт пользовательских данных из выбранного JSON-файла."""
        file_path = filedialog.askopenfilename(
            defaultextension=".json",
            filetypes=[("JSON Backup", "*.json"), ("All Files", "*.*")],
            title="Выберите файл резервной копии Акакия"
        )
        if not file_path:
            return None

        confirm = messagebox.askyesno(
            "Подтверждение импорта",
            f"Вы уверены, что хотите восстановить данные из файла:\n{file_path}?\n\n"
            "Текущие задачи, напоминания, заметки, списки и память будут заменены."
        )
        if not confirm:
            return None

        res = import_data(
            input_path=file_path,
            household=self.household,
            memory=self.memory
        )

        if not self.lbl_backup_res or not self.lbl_backup_res.winfo_exists():
            return res

        if res.get("success"):
            self.lbl_backup_res.config(
                text=f"✓ {res.get('message')}",
                fg=self.ACCENT_GREEN
            )
            if self.shell:
                if hasattr(self.shell, "_append_log"):
                    self.shell._append_log("BACKUP", res.get("message"))
                if hasattr(self.shell, "refresh_current_view"):
                    self.shell.refresh_current_view()
        else:
            self.lbl_backup_res.config(
                text=f"✗ {res.get('error')}",
                fg=self.ACCENT_RED
            )
        return res

    def ui_run_validation(self, val_func: Optional[Callable[[], dict]] = None) -> dict:
        """Запуск проверки целостности проекта и вывод статуса."""
        if val_func is None:
            gui_mod = sys.modules.get("gui")
            val_func = getattr(gui_mod, "validate_project", validate_project) if gui_mod else validate_project

        res = val_func()
        if not self.lbl_val_res or not self.lbl_val_res.winfo_exists():
            return res

        if res.get("success"):
            self.lbl_val_res.config(
                text=f"✓ Проект валиден: проверено {res.get('files_checked')} файлов, 0 синтаксических ошибок.",
                fg=self.ACCENT_GREEN
            )
        else:
            self.lbl_val_res.config(
                text=f"✗ Ошибки валидации: {res.get('errors')}",
                fg=self.ACCENT_RED
            )
        return res
