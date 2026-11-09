"""Map borderless mouse input when gameplay renders below the window size."""

from pathlib import Path


runtime = Path("src/runtime.c")
source = runtime.read_text(encoding="utf-8")


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise SystemExit(f"Expected one gameplay mouse patch anchor: {old!r}")
    return source.replace(old, new, 1)


old = """    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0)
        return;

    if (!GetClientRect(borderless_window, &rc)) return;"""
new = """    int gameplay = InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0;

    if (!GetClientRect(borderless_window, &rc)) return;"""
source = replace_once(source, old, new)

old = """    if (client_width <= 0 || client_height <= 0) return;

    physical_x = (SHORT)LOWORD(msg->lParam);"""
new = r"""    if (client_width <= 0 || client_height <= 0) return;

    /* At native resolution, gameplay already receives coordinates in the
     * same space as the backbuffer. Smaller renders need the window-to-render
     * transform used by the frontend. */
    if (gameplay && (UINT)client_width == borderless_logical_width &&
        (UINT)client_height == borderless_logical_height) return;

    if (debug_logging && gameplay && msg->message == WM_LBUTTONDOWN &&
        InterlockedIncrement(&message_scale_log_count) <= 12) {
        char line[160];
        snprintf(line, sizeof(line),
            "gameplay mouse mapping input=%d,%d client=%dx%d render=%lux%lu\n",
            (SHORT)LOWORD(msg->lParam), (SHORT)HIWORD(msg->lParam),
            client_width, client_height, (unsigned long)borderless_logical_width,
            (unsigned long)borderless_logical_height);
        log_line(line);
    }

    physical_x = (SHORT)LOWORD(msg->lParam);"""
source = replace_once(source, old, new)

source = source.replace("raw mouse passthrough enabled", "gameplay mouse mode enabled")
runtime.write_text(source, encoding="utf-8")
print("Applied MVP2005 Modern borderless gameplay mouse mapping")
