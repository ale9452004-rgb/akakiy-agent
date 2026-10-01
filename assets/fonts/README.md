# Typography Architecture & Local Fonts for Akakiy 2.0

## Шрифтовая система

В Akakiy 2.0 Desktop Hub утверждена следующая шрифтовая система:
- **Display / Hero**: `Manrope` (SemiBold / Bold / ExtraBold) — органичный, современный, мягкий геометрический гротеск с нативной кириллицей.
- **UI / Content**: `Inter` (Regular / Medium / SemiBold) — отраслевой стандарт экранной типографики с безупречной читаемостью в мелких кеглях (8–10pt).
- **Technical / Mono**: `JetBrains Mono` / `Cascadia Code` (Regular / Medium) — моноширинный шрифт для логов, артефактов, ID и метрик.

## Способ подключения в Windows Desktop (Tkinter & Win32)

Шрифты загружаются динамически в память процесса во время запуска приложения через Win32 GDI API:
```python
ctypes.windll.gdi32.AddFontResourceExW(str(font_file), 0x10, 0)  # FR_PRIVATE
```

### Преимущества:
1. **Без прав администратора**: не требуется установка в `C:\Windows\Fonts`.
2. **Изоляция**: шрифты видны только процессу приложения и автоматически выгружаются при завершении.
3. **Кросс-машинная консистентность**: интерфейс выглядит одинаково на Windows 10 и Windows 11.
4. **Надёжные fallback-шрифты**: если файлы `.ttf` отсутствуют, система автоматически переключается на `Segoe UI Variable` (Windows 11) / `Segoe UI` (Windows 10) и `Cascadia Code` / `Consolas`.

## Структура папок

- `assets/fonts/Manrope/` — файлы `Manrope-VariableFont_wght.ttf` или статические начертания.
- `assets/fonts/Inter/` — файлы `Inter-VariableFont_opsz,wght.ttf` или статические начертания.
- `assets/fonts/JetBrainsMono/` — моноширинные начертания.

> **Лицензирование**: Все три шрифта распространяются под свободной лицензией **SIL Open Font License (OFL 1.1)**, разрешающей коммерческое и некоммерческое использование, встраивание и распространение.
