from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# v12 is applied after v11. With dgVoodoo AppControlledScreenMode=false the
# actual HWND now remains monitor-sized, but gameplay mouse input is still
# wrong. The clean trace also showed that v10's generic "non-monitor resize"
# phase detector fires too early during the initial decorated 640x480 window
# setup (2566x1469 on a 2560x1440 monitor). The real gameplay transition is the
# later 4:3 same-height request: 1920x1440 on a 2560x1440 monitor.
#
# Treat only that 4:3 request, while MVP's logical front end is 800x600, as the
# gameplay phase marker. Once gameplay begins, stop applying v8's physical ->
# 800x600 queued-message transform. This is both a direct behavioral test and a
# diagnostic: the bounded raw-message/geometry/SetCursorPos counters are reset
# at the real transition, so the next log contains gameplay evidence.
replace_once(
'''static volatile LONG gameplay_window_transition_seen;\nstatic LONG present_guard_log_count;\n''',
'''static volatile LONG gameplay_window_transition_seen;\nstatic volatile LONG gameplay_input_phase;\nstatic LONG present_guard_log_count;\n''',
"gameplay input phase global",
)

replace_once(
'''    if (GetForegroundWindow() != borderless_window) return;\n    if (!GetClientRect(borderless_window, &rc)) return;\n''',
'''    if (GetForegroundWindow() != borderless_window) return;\n\n    /* The front end needs physical client coordinates mapped into MVP's\n     * logical 800x600 UI. Gameplay uses a different mouse interpretation.\n     * Once the characteristic 4:3 gameplay resize request is observed, leave\n     * queued mouse coordinates untouched and let MVP consume physical client\n     * coordinates directly. */\n    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0) {\n        if (InterlockedIncrement(&message_scale_log_count) <= 40) {\n            char buf[224];\n            wsprintfA(buf,\n                "%s gameplay passthrough msg=%04x lparam=%d,%d pt=%ld,%ld logical=%lux%lu\\\\n",\n                source, (unsigned int)msg->message,\n                (int)(SHORT)LOWORD(msg->lParam),\n                (int)(SHORT)HIWORD(msg->lParam),\n                msg->pt.x, msg->pt.y,\n                (unsigned long)borderless_logical_width,\n                (unsigned long)borderless_logical_height);\n            log_line(buf);\n        }\n        return;\n    }\n\n    if (!GetClientRect(borderless_window, &rc)) return;\n''',
"gameplay queued-message passthrough",
)

old_transition = '''            if (cx > 0 && cy > 0 &&\n                (cx != monitor_width || cy != monitor_height) &&\n                InterlockedCompareExchange(&gameplay_window_transition_seen, 1, 0) == 0) {\n                InterlockedExchange(&input_probe_log_count, 0);\n                InterlockedExchange(&geometry_probe_log_count, 0);\n                InterlockedExchange(&message_scale_log_count, 0);\n                log_line("gameplay window-size transition detected; input diagnostics reset\\\\n");\n            }\n'''
new_transition = '''            if (borderless_logical_width == 800 &&\n                borderless_logical_height == 600 &&\n                cx > 0 && cy > 0 &&\n                cy == monitor_height && cx < monitor_width &&\n                cx * 3 == cy * 4 &&\n                InterlockedCompareExchange(&gameplay_window_transition_seen, 1, 0) == 0) {\n                InterlockedExchange(&gameplay_input_phase, 1);\n                InterlockedExchange(&input_probe_log_count, 0);\n                InterlockedExchange(&geometry_probe_log_count, 0);\n                InterlockedExchange(&message_scale_log_count, 0);\n                InterlockedExchange(&setcursor_probe_log_count, 0);\n                log_line("gameplay 4:3 transition detected; mouse scaling disabled and diagnostics reset\\\\n");\n            }\n'''
replace_once(old_transition, new_transition, "precise gameplay phase detector")

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern phase-aware gameplay mouse passthrough v12")
