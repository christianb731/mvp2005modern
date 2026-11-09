from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# With dgVoodoo FullScreenMode=false, gameplay is borderless immediately and
# no longer produces the 1920x1440 SetWindowPos request used by v12 to enter
# gameplay mouse mode. In every trace the gameplay transition still contains a
# MoveWindow request for the monitor-sized 2560x1440 window immediately before
# gameplay shader activity. Use that as a second phase signal while preserving
# the existing large-4:3 detector for other dgVoodoo configurations.
replace_once(
'''        if (get_borderless_monitor_rect(hwnd, &monitor)) {\n            log_window_guard("MoveWindow", x, y, width, height);\n            x = monitor.left;\n            y = monitor.top;\n            width = monitor.right - monitor.left;\n            height = monitor.bottom - monitor.top;\n        }\n''',
'''        if (get_borderless_monitor_rect(hwnd, &monitor)) {\n            int monitor_width = monitor.right - monitor.left;\n            int monitor_height = monitor.bottom - monitor.top;\n            log_window_guard("MoveWindow", x, y, width, height);\n\n            /* In true dgVoodoo windowed/borderless mode MVP's gameplay switch\n             * asks to MoveWindow to the full monitor instead of requesting the\n             * old 1920x1440 4:3 size. Front-end startup does not issue this\n             * MoveWindow while logical size is 800x600 in the observed traces. */\n            if (borderless_logical_width == 800 &&\n                borderless_logical_height == 600 &&\n                width == monitor_width && height == monitor_height) {\n                LONG was_gameplay = InterlockedExchange(&gameplay_input_phase, 1);\n                if (!was_gameplay) {\n                    InterlockedExchange(&gameplay_window_transition_seen, 1);\n                    InterlockedExchange(&input_probe_log_count, 0);\n                    InterlockedExchange(&geometry_probe_log_count, 0);\n                    InterlockedExchange(&message_scale_log_count, 0);\n                    InterlockedExchange(&setcursor_probe_log_count, 0);\n                    log_line("gameplay monitor-sized MoveWindow detected; raw mouse passthrough enabled\\n");\n                }\n            }\n\n            x = monitor.left;\n            y = monitor.top;\n            width = monitor_width;\n            height = monitor_height;\n        }\n''',
"true-borderless gameplay MoveWindow detector",
)


# The v14 focus trace shows Alt-Tab legitimately minimizing/deactivating the
# window (-32000,-32000, 160x28) while the Present guard is still running and
# immediately calling make_borderless_window(). That can pull the game back into
# the foreground. Never reassert geometry from Present while the game is not the
# foreground window, is minimized, or is hidden. The normal guard resumes after
# Windows restores/reactivates MVP.
replace_once(
'''    if (!borderless_enabled || !borderless_window || !IsWindow(borderless_window)) return;\n    if (borderless_window_matches_monitor(borderless_window,\n''',
'''    if (!borderless_enabled || !borderless_window || !IsWindow(borderless_window)) return;\n    if (GetForegroundWindow() != borderless_window ||\n        IsIconic(borderless_window) || !IsWindowVisible(borderless_window)) return;\n    if (borderless_window_matches_monitor(borderless_window,\n''',
"inactive/minimized Present guard bypass",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern true-borderless gameplay/focus fix v15")
