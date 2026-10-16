from pathlib import Path
import re

PATCH_DIR = Path(__file__).resolve().parent
RUNTIME = Path("src/runtime.c")


def run_patch(name: str, transform=None) -> None:
    path = PATCH_DIR / name
    source = path.read_text(encoding="utf-8")
    if transform:
        source = transform(source)
    namespace = {
        "__name__": "__main__",
        "__file__": str(path),
    }
    exec(compile(source, str(path), "exec"), namespace, namespace)


def failsafe_compat(source: str) -> str:
    """Accept either normal or double-escaped C log newlines in fail-safe patching."""
    old = '''    count = text.count(old)\n    if count != 1:\n        raise SystemExit(f"{label}: expected exactly one match, found {count}")\n    text = text.replace(old, new, 1)\n'''
    new = '''    count = text.count(old)\n    if count == 1:\n        text = text.replace(old, new, 1)\n        return\n\n    alt_old = old.replace("\\\\n", "\\\\\\\\n")\n    alt_new = new.replace("\\\\n", "\\\\\\\\n")\n    alt_count = text.count(alt_old)\n    if alt_count == 1:\n        text = text.replace(alt_old, alt_new, 1)\n        return\n\n    raise SystemExit(f"{label}: expected exactly one match, found {count} (escaped form {alt_count})")\n'''
    if old not in source:
        raise SystemExit("RC1: could not make apply_failsafe.py escape-tolerant")
    return source.replace(old, new, 1)


def normalize_windowed_interval() -> None:
    text = RUNTIME.read_text(encoding="utf-8")
    needle = "    pp->FullScreen_RefreshRateInHz = 0;\n"
    replacement = needle + "    pp->FullScreen_PresentationInterval = 0;\n"
    count = text.count(needle)
    if count < 2:
        raise SystemExit(f"RC1: expected at least 2 refresh assignments, found {count}")
    text = text.replace(needle, replacement)
    RUNTIME.write_text(text, encoding="utf-8")


def replace_regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"RC1 cleanup {label}: expected one match, found {count}")
    return updated


def production_cleanup() -> None:
    """Keep proven behavior while removing experiment-only probes and log volume."""
    text = RUNTIME.read_text(encoding="utf-8")

    # The v7 experiment installed ten USER32 probes. Production only needs the
    # three hooks that have behavioral value: suppress MVP's cursor warps and
    # transform queued mouse messages. The other seven were diagnostics only.
    input_installer = r'''static void install_borderless_input_probe\(void\)\n\{.*?\n\}\n\n(?=typedef LONG \(WINAPI \*SetWindowLongAWinGuardFn\)'''
    input_replacement = '''static void install_borderless_input_probe(void)\n{
    HMODULE user32;
    int installed = 0;

    if (!borderless_enabled) return;
    user32 = GetModuleHandleA("user32.dll");
    if (!user32) {
        log_line("borderless input hooks unavailable: user32.dll not loaded\\n");
        return;
    }

    installed += install_probe_hook(user32, "SetCursorPos",
        fake_SetCursorPos_probe, &real_SetCursorPosPtr);
    installed += install_probe_hook(user32, "PeekMessageA",
        fake_PeekMessageA_probe, &real_PeekMessageAPtr);
    installed += install_probe_hook(user32, "GetMessageA",
        fake_GetMessageA_probe, &real_GetMessageAPtr);

    if (installed != 3)
        log_line("borderless input hook installation incomplete\\n");
}

'''
    text = replace_regex_once(text, input_installer, input_replacement,
        "production input hook set")

    # Raw message dumps were useful to discover MVP's input path, but are not
    # useful in a release build. Preserve the scaler/passthrough behavior.
    text = text.replace(
        '''    if (ok && borderless_enabled) {\n        log_mouse_msg("probe PeekMessageA raw", msg);\n        scale_queued_mouse_message(msg, "PeekMessageA");\n    }\n''',
        '''    if (ok && borderless_enabled)\n        scale_queued_mouse_message(msg, "PeekMessageA");\n''',
        1,
    )
    text = text.replace(
        '''    if (ok > 0 && borderless_enabled) {\n        log_mouse_msg("probe GetMessageA raw", msg);\n        scale_queued_mouse_message(msg, "GetMessageA");\n    }\n''',
        '''    if (ok > 0 && borderless_enabled)\n        scale_queued_mouse_message(msg, "GetMessageA");\n''',
        1,
    )

    # Gameplay raw passthrough is now proven. Drop its per-message trace.
    gameplay_trace = r'''    if \(InterlockedCompareExchange\(&gameplay_input_phase, 0, 0\) != 0\) \{\n        if \(InterlockedIncrement\(&message_scale_log_count\) <= 40\) \{.*?\n        \}\n        return;\n    \}'''
    text = replace_regex_once(
        text,
        gameplay_trace,
        '''    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0)\n        return;''',
        "gameplay per-message trace",
    )

    # Frontend coordinate conversion is also proven. Remove its bounded 40-line
    # message dump while leaving the actual lParam/MSG.pt conversion unchanged.
    frontend_trace = r'''\n    if \(InterlockedIncrement\(&message_scale_log_count\) <= 40\) \{\n        char buf\[288\];\n        wsprintfA\(buf,\n            "%s scaled msg=%04x.*?\n        log_line\(buf\);\n    \}\n'''
    text = replace_regex_once(text, frontend_trace, "\n", "frontend per-message trace")

    # Persistent window guards remain important, but their request-by-request
    # diagnostics are no longer necessary.
    window_log = r'''static void log_window_guard\(const char \*what, int x, int y, int w, int h\)\n\{.*?\n\}\n\n(?=static LONG WINAPI fake_SetWindowLongA_guard)'''
    window_log_replacement = '''static void log_window_guard(const char *what, int x, int y, int w, int h)\n{
    (void)what;
    (void)x;
    (void)y;
    (void)w;
    (void)h;
}

'''
    text = replace_regex_once(text, window_log, window_log_replacement,
        "window request logger")

    wndproc_log = r'''static void log_wndproc_geometry_guard\(const char \*what,.*?\n\}\n\n(?=static LRESULT CALLBACK borderless_geometry_wndproc)'''
    wndproc_log_replacement = '''static void log_wndproc_geometry_guard(const char *what,
    int old_x, int old_y, int old_w, int old_h,
    int new_x, int new_y, int new_w, int new_h)
{
    (void)what;
    (void)old_x;
    (void)old_y;
    (void)old_w;
    (void)old_h;
    (void)new_x;
    (void)new_y;
    (void)new_w;
    (void)new_h;
}

'''
    text = replace_regex_once(text, wndproc_log, wndproc_log_replacement,
        "WndProc geometry logger")

    # Keep a small amount of useful drift/suppression information when Debug=1.
    text = text.replace(
        "InterlockedIncrement(&present_guard_log_count) <= 24",
        "InterlockedIncrement(&present_guard_log_count) <= 4",
    )
    text = text.replace(
        "InterlockedIncrement(&window_guard_log_count) <= 48",
        "InterlockedIncrement(&window_guard_log_count) <= 4",
    )
    text = text.replace(
        "InterlockedIncrement(&borderless_geometry_guard_log_count) <= 96)\n            log_line(\"WndProc guard suppressed SC_MINIMIZE for borderless Alt-Tab",
        "InterlockedIncrement(&borderless_geometry_guard_log_count) <= 8)\n            log_line(\"WndProc guard suppressed SC_MINIMIZE for borderless Alt-Tab",
    )

    # Hard assertions for the compatibility behavior we are freezing in RC1.
    required = [
        "pp->FullScreen_PresentationInterval = 0;",
        "frontend render phase detected; 800x600 mouse scaling restored",
        "3D gameplay rendering resumed; raw mouse passthrough enabled",
        "gameplay monitor-sized MoveWindow detected; raw mouse passthrough enabled",
        "fake_ShowWindow_guard",
        "SC_MINIMIZE",
        "fake_Present",
        "borderless_geometry_wndproc",
    ]
    missing = [token for token in required if token not in text]
    if missing:
        raise SystemExit("RC1 verification failed; missing: " + ", ".join(missing))

    RUNTIME.write_text(text, encoding="utf-8")


# Build the exact behavior proven by the v16 test series. The individual scripts
# remain in the repository as development history/rollback points; this file is
# now the canonical production entry point.
run_patch("apply_borderless.py")
run_patch("apply_failsafe.py", failsafe_compat)
normalize_windowed_interval()
run_patch("apply_input_probe_v7.py")
run_patch("apply_message_scale_v8.py")
run_patch("apply_window_guard_v9.py")
run_patch("apply_present_guard_v10.py")
run_patch("apply_wndproc_geometry_guard_v11.py")
run_patch("apply_gameplay_input_phase_v12.py")
run_patch("apply_true_borderless_v15.py")
run_patch("apply_frontend_return_alt_tab_v16.py")
production_cleanup()

print("Applied MVP2005 Modern compatibility runtime RC1")
