from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# v12 is applied after v11. With dgVoodoo AppControlledScreenMode=false the
# actual HWND stays monitor-sized, but gameplay mouse input is still wrong.
# The initial 640x480 decorated-window setup can request 2566x1469, so the old
# generic non-monitor-size detector is too broad. The real gameplay transition
# is the later large 4:3 request (1920x1440 in the observed 2560x1440 setup).
replace_once(
'''static volatile LONG gameplay_window_transition_seen;\nstatic LONG present_guard_log_count;\n''',
'''static volatile LONG gameplay_window_transition_seen;\nstatic volatile LONG gameplay_input_phase;\nstatic LONG present_guard_log_count;\n''',
"gameplay input phase global",
)

replace_once(
'''    if (GetForegroundWindow() != borderless_window) return;\n    if (!GetClientRect(borderless_window, &rc)) return;\n''',
'''    if (GetForegroundWindow() != borderless_window) return;\n\n    /* Front-end menus need physical client coordinates mapped into MVP's\n     * logical 800x600 UI. After the characteristic large 4:3 gameplay request,\n     * leave queued mouse coordinates untouched as a direct gameplay test. */\n    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0) {\n        if (InterlockedIncrement(&message_scale_log_count) <= 40) {\n            char buf[224];\n            wsprintfA(buf,\n                "%s gameplay passthrough msg=%04x lparam=%d,%d pt=%ld,%ld logical=%lux%lu\\n",\n                source, (unsigned int)msg->message,\n                (int)(SHORT)LOWORD(msg->lParam),\n                (int)(SHORT)HIWORD(msg->lParam),\n                msg->pt.x, msg->pt.y,\n                (unsigned long)borderless_logical_width,\n                (unsigned long)borderless_logical_height);\n            log_line(buf);\n        }\n        return;\n    }\n\n    if (!GetClientRect(borderless_window, &rc)) return;\n''',
"gameplay queued-message passthrough",
)

# v10 inserted this detector into fake_SetWindowPos_guard. Match it by code
# structure instead of an exact log-string representation; earlier patch stages
# may leave either escaped or double-escaped newline text in that C string.
transition_re = re.compile(
    r'''(?P<indent>\s*)if \(cx > 0 && cy > 0 &&\s*\n'''
    r'''\s*\(cx != monitor_width \|\| cy != monitor_height\) &&\s*\n'''
    r'''\s*InterlockedCompareExchange\(&gameplay_window_transition_seen, 1, 0\) == 0\) \{\s*\n'''
    r'''\s*InterlockedExchange\(&input_probe_log_count, 0\);\s*\n'''
    r'''\s*InterlockedExchange\(&geometry_probe_log_count, 0\);\s*\n'''
    r'''\s*InterlockedExchange\(&message_scale_log_count, 0\);\s*\n'''
    r'''\s*log_line\("gameplay window-size transition detected; input diagnostics reset(?:\\+n)?"\);\s*\n'''
    r'''\s*\}''',
    re.MULTILINE,
)

matches = list(transition_re.finditer(text))
if len(matches) != 1:
    anchor = 'InterlockedCompareExchange(&gameplay_window_transition_seen, 1, 0) == 0) {'
    pos = text.find(anchor)
    if pos < 0 or text.find(anchor, pos + 1) >= 0:
        raise SystemExit(
            f"precise gameplay phase detector: structural match={len(matches)} anchor_pos={pos}"
        )
    start = text.rfind('            if (cx > 0 && cy > 0 &&', 0, pos)
    if start < 0:
        raise SystemExit("precise gameplay phase detector: could not find detector start")
    end_marker = '            }\n'
    end = text.find(end_marker, pos)
    if end < 0:
        raise SystemExit("precise gameplay phase detector: could not find detector end")
    end += len(end_marker)
else:
    start, end = matches[0].span()

new_transition = '''            /* The raw requested size is the stable phase signal. Do not depend\n             * on MonitorFromWindow geometry because dgVoodoo can virtualize the\n             * host window while still forwarding MVP's 4:3 gameplay request. */\n            if (borderless_logical_width == 800 &&\n                borderless_logical_height == 600 &&\n                cx > (int)borderless_logical_width &&\n                cy > (int)borderless_logical_height &&\n                cx * 3 == cy * 4) {\n                LONG was_gameplay = InterlockedExchange(&gameplay_input_phase, 1);\n                if (!was_gameplay) {\n                    InterlockedExchange(&gameplay_window_transition_seen, 1);\n                    InterlockedExchange(&input_probe_log_count, 0);\n                    InterlockedExchange(&geometry_probe_log_count, 0);\n                    InterlockedExchange(&message_scale_log_count, 0);\n                    InterlockedExchange(&setcursor_probe_log_count, 0);\n                    log_line("gameplay 4:3 request detected; raw mouse passthrough enabled\\n");\n                }\n            }\n'''
text = text[:start] + new_transition + text[end:]

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern robust phase-aware gameplay mouse passthrough v12")
