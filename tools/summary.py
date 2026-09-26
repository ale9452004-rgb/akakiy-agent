"""
Модуль формирования отчётов и сводок о выполнении задач Акакия.
"""


def format_task_summary(plan_data, exec_result, research_info=None):
    """
    Формирует агрегированный отчёт о выполнении комплексной задачи:
    ## Исследование
    ## План
    ## Изменения
    ## Проверка
    ## Результат
    """
    lines = []

    # 1. Исследование
    lines.append("## Исследование")
    res_lines = []
    if research_info:
        if isinstance(research_info, str):
            for item in research_info.splitlines():
                if item.strip():
                    res_lines.append(f"- {item}")
        else:
            for item in research_info:
                res_lines.append(f"- {item}")

    step_results = exec_result.get("results", []) if (isinstance(exec_result, dict) or hasattr(exec_result, "get")) else []
    for r in step_results:
        action = r.get("action")
        if action in ("search", "read", "analyze"):
            target = r.get("target") or r.get("query") or ""
            desc = r.get("details") or f"Действие {action}"
            status = "успешно" if r.get("success") else "не выполнено"
            res_lines.append(f"- {action} ({target}): {desc} — {status}")

    if res_lines:
        lines.extend(res_lines)
    else:
        lines.append("- Предварительное исследование не требовалось.")
    lines.append("")

    # 2. План
    lines.append("## План")
    steps = plan_data.get("steps", []) if isinstance(plan_data, dict) else []
    if steps:
        for s in steps:
            s_id = s.get("id")
            s_desc = s.get("description") or s.get("details", "")
            lines.append(f"{s_id}. {s_desc}")
    else:
        lines.append("План не содержит отдельных шагов.")
    lines.append("")

    # 3. Изменения
    lines.append("## Изменения")
    edits_found = False
    for r in step_results:
        action = r.get("action")
        if action in ("edit", "write"):
            edits_found = True
            target = r.get("target", "")
            if r.get("success"):
                lines.append(f"- Изменён файл: {target}")
            else:
                err = r.get("result", {}).get("error", "действие отменено или не выполнено")
                lines.append(f"- Изменение файла {target} НЕ выполнено ({err})")
    if not edits_found:
        lines.append("- Изменения файлов не производились.")
    lines.append("")

    # 4. Проверка
    lines.append("## Проверка")
    val_steps = [r for r in step_results if r.get("action") == "validate"]
    if val_steps:
        for v in val_steps:
            if v.get("success"):
                healing_info = ""
                if v.get("self_healing", {}).get("success"):
                    healing_info = " (исправлено через self-healing)"
                lines.append(f"- validate_project: проверка пройдена, ошибок синтаксиса: 0{healing_info}")
            else:
                lines.append("- validate_project: обнаружены синтаксические ошибки")
    else:
        lines.append("- Проверка проекта не запускалась.")
    lines.append("")

    # 5. Результат
    lines.append("## Результат")
    if (isinstance(exec_result, dict) or hasattr(exec_result, "get")) and exec_result.get("success"):
        lines.append(exec_result.get("message", "Задача выполнена успешно."))
    elif isinstance(exec_result, dict) or hasattr(exec_result, "get"):
        lines.append(exec_result.get("message", "Выполнение задачи остановлено."))
    else:
        lines.append("Выполнение задачи остановлено.")

    return "\n".join(lines)
