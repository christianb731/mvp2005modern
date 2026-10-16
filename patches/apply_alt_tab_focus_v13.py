from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# v13 is deliberately narrow: v12 is the known-good rendering/input baseline.
# The remaining problem is Alt-Tab/focus behavior. Logs show Present observing the
# standard minimized/off-screen HWND rectangle (-32000,-32000, tiny client) and
# immediately reasserting 2560x1440, which can fight Windows deactivation and
# make the game appear to steal focus back.
#
# Track WM_ACTIVATEAPP and make all persistent geometry/style guards stand down
# while the app is inactive/minimized. On reactivation, normal Present/window
# enforcement resumes without changing the v12 menu/gameplay mouse behavior.
replace_once(
'''static volatile LONG gameplay_input_phase;\nstatic LONG present_guard_log_count;\n''',
'''static volatile LONG gameplay_input_phase;\nstatic volatile LONG borderless_app_active = 1;\nstatic LONG present_guard_log_count;\n''',
"Alt-Tab active-state global",
)

# Window/style guard API hooks: do not rewrite geometry/style while Windows is
# deactivating or the game is minimized. The original API call is allowed through.
replace_once(
'''    if (borderless_enabled && hwnd == borderless_window) {\n        LONG original = value;\n''',
'''    if (borderless_enabled && hwnd == borderless_window &&\n        InterlockedCompareExchange(&borderless_app_active, 0, 0) != 0 &&\n        GetForegroundWindow() == hwnd && !IsIconic(hwnd)) {\n        LONG original = value;\n''',
"focus-aware SetWindowLongA guard",
)

replace_once(
'''    if (borderless_enabled && hwnd == borderless_window) {\n        RECT monitor;\n        if (get_borderless_monitor_rect(hwnd, &monitor)) {\n            int monitor_width = monitor.right - monitor.left;\n''',
'''    if (borderless_enabled && hwnd == borderless_window &&\n        InterlockedCompareExchange(&borderless_app_active, 0, 0) != 0 &&\n        GetForegroundWindow() == hwnd && !IsIconic(hwnd) &&\n        !(flags & SWP_HIDEWINDOW) && x > -30000 && y > -30000) {\n        RECT monitor;\n        if (get_borderless_monitor_rect(hwnd, &monitor)) {\n            int monitor_width = monitor.right - monitor.left;\n''',
"focus-aware SetWindowPos guard",
)

replace_once(
'''    if (borderless_enabled && hwnd == borderless_window) {\n        RECT monitor;\n        if (get_borderless_monitor_rect(hwnd, &monitor)) {\n            log_window_guard("MoveWindow", x, y, width, height);\n''',
'''    if (borderless_enabled && hwnd == borderless_window &&\n        InterlockedCompareExchange(&borderless_app_active, 0, 0) != 0 &&\n        GetForegroundWindow() == hwnd && !IsIconic(hwnd) &&\n        x > -30000 && y > -30000) {\n        RECT monitor;\n        if (get_borderless_monitor_rect(hwnd, &monitor)) {\n            log_window_guard("MoveWindow", x, y, width, height);\n''',
"focus-aware MoveWindow guard",
)

replace_once(
'''    if (borderless_enabled && hwnd == borderless_window && placement &&\n        get_borderless_monitor_rect(hwnd, &monitor)) {\n''',
'''    if (borderless_enabled && hwnd == borderless_window && placement &&\n        InterlockedCompareExchange(&borderless_app_active, 0, 0) != 0 &&\n        GetForegroundWindow() == hwnd && !IsIconic(hwnd) &&\n        get_borderless_monitor_rect(hwnd, &monitor)) {\n''',
"focus-aware SetWindowPlacement guard",
)

# Present-time enforcement is the clearest source of the Alt-Tab fight. Never
# reassert the game HWND while it is inactive, not foreground, or iconic.
replace_once(
'''    if (!borderless_enabled || !borderless_window || !IsWindow(borderless_window)) return;\n    if (borderless_window_matches_monitor(borderless_window,\n''',
'''    if (!borderless_enabled || !borderless_window || !IsWindow(borderless_window)) return;\n    if (InterlockedCompareExchange(&borderless_app_active, 0, 0) == 0 ||\n        GetForegroundWindow() != borderless_window || IsIconic(borderless_window)) return;\n    if (borderless_window_matches_monitor(borderless_window,\n''',
"focus-aware Present guard",
)

# Track activation in the final HWND subclass. Do this after the previous proc so
# Windows/dgVoodoo still receives its normal activation message. We only update
# our guard state and log it; no focus-stealing API is called here.
needle = '''    result = previous ? CallWindowProcA(previous, hwnd, msg, wparam, lparam) :\n        DefWindowProcA(hwnd, msg, wparam, lparam);\n\n    if (!borderless_enabled || hwnd != borderless_window ||\n        GetForegroundWindow() != hwnd) return result;\n'''
replacement = '''    result = previous ? CallWindowProcA(previous, hwnd, msg, wparam, lparam) :\n        DefWindowProcA(hwnd, msg, wparam, lparam);\n\n    if (borderless_enabled && hwnd == borderless_window && msg == WM_ACTIVATEAPP) {\n        InterlockedExchange(&borderless_app_active, wparam ? 1 : 0);\n        if (InterlockedIncrement(&borderless_geometry_guard_log_count) <= 32) {\n            char buf[160];\n            wsprintfA(buf, "borderless WM_ACTIVATEAPP active=%lu\\n",\n                (unsigned long)(wparam ? 1 : 0));\n            log_line(buf);\n        }\n        return result;\n    }\n\n    if (!borderless_enabled || hwnd != borderless_window ||\n        InterlockedCompareExchange(&borderless_app_active, 0, 0) == 0 ||\n        GetForegroundWindow() != hwnd || IsIconic(hwnd)) return result;\n'''
replace_once(needle, replacement, "WM_ACTIVATEAPP tracking")

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern focus-aware Alt-Tab borderless guard v13")
