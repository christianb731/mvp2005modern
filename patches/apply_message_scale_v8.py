from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# v8 is applied after apply_input_probe_v7.py. The v7 probe proved that MVP's
# front end receives raw physical WM_MOUSEMOVE coordinates directly from
# PeekMessageA while its logical D3D8 front-end remains 800x600. Transform the
# MSG returned to MVP before it can inspect or dispatch it.
replace_once(
'''static LONG setcursor_probe_log_count;\nstatic UINT borderless_logical_width;\n''',
'''static LONG setcursor_probe_log_count;\nstatic LONG message_scale_log_count;\nstatic UINT borderless_logical_width;\n''',
"message scaling log counter",
)

marker = '''static BOOL WINAPI fake_PeekMessageA_probe(LPMSG msg, HWND hwnd, UINT min_msg, UINT max_msg, UINT remove_msg)\n'''
if text.count(marker) != 1:
    raise SystemExit(f"PeekMessage marker: expected exactly one match, found {text.count(marker)}")

helper = r'''static int is_client_coordinate_mouse_message(UINT msg)
{
    switch (msg) {
    case WM_MOUSEMOVE:
    case WM_LBUTTONDOWN:
    case WM_LBUTTONUP:
    case WM_LBUTTONDBLCLK:
    case WM_RBUTTONDOWN:
    case WM_RBUTTONUP:
    case WM_RBUTTONDBLCLK:
    case WM_MBUTTONDOWN:
    case WM_MBUTTONUP:
    case WM_MBUTTONDBLCLK:
    case WM_XBUTTONDOWN:
    case WM_XBUTTONUP:
    case WM_XBUTTONDBLCLK:
        return 1;
    default:
        return 0;
    }
}

static void scale_queued_mouse_message(MSG *msg, const char *source)
{
    RECT rc;
    POINT origin;
    int client_width;
    int client_height;
    int physical_x;
    int physical_y;
    int logical_x;
    int logical_y;
    LONG old_pt_x;
    LONG old_pt_y;

    if (!msg || msg->hwnd != borderless_window ||
        !is_client_coordinate_mouse_message(msg->message) ||
        !borderless_logical_width || !borderless_logical_height) return;
    if (GetForegroundWindow() != borderless_window) return;
    if (!GetClientRect(borderless_window, &rc)) return;

    client_width = rc.right - rc.left;
    client_height = rc.bottom - rc.top;
    if (client_width <= 0 || client_height <= 0) return;
    if (client_width == (int)borderless_logical_width &&
        client_height == (int)borderless_logical_height) return;

    physical_x = (SHORT)LOWORD(msg->lParam);
    physical_y = (SHORT)HIWORD(msg->lParam);
    logical_x = MulDiv(physical_x, (int)borderless_logical_width, client_width);
    logical_y = MulDiv(physical_y, (int)borderless_logical_height, client_height);

    old_pt_x = msg->pt.x;
    old_pt_y = msg->pt.y;
    origin.x = 0;
    origin.y = 0;
    if (ClientToScreen(borderless_window, &origin)) {
        LONG local_pt_x = msg->pt.x - origin.x;
        LONG local_pt_y = msg->pt.y - origin.y;
        msg->pt.x = origin.x + MulDiv(local_pt_x,
            (int)borderless_logical_width, client_width);
        msg->pt.y = origin.y + MulDiv(local_pt_y,
            (int)borderless_logical_height, client_height);
    }

    msg->lParam = MAKELPARAM((WORD)(SHORT)logical_x, (WORD)(SHORT)logical_y);

    if (InterlockedIncrement(&message_scale_log_count) <= 40) {
        char buf[288];
        wsprintfA(buf,
            "%s scaled msg=%04x lparam=%d,%d -> %d,%d pt=%ld,%ld -> %ld,%ld client=%dx%d logical=%lux%lu\\n",
            source, (unsigned int)msg->message,
            physical_x, physical_y, logical_x, logical_y,
            old_pt_x, old_pt_y, msg->pt.x, msg->pt.y,
            client_width, client_height,
            (unsigned long)borderless_logical_width,
            (unsigned long)borderless_logical_height);
        log_line(buf);
    }
}

'''
text = text.replace(marker, helper + marker, 1)

replace_once(
'''    ok = fn(msg, hwnd, min_msg, max_msg, remove_msg);\n    if (ok && borderless_enabled) log_mouse_msg("probe PeekMessageA", msg);\n    return ok;\n}\n''',
'''    ok = fn(msg, hwnd, min_msg, max_msg, remove_msg);\n    if (ok && borderless_enabled) {\n        log_mouse_msg("probe PeekMessageA raw", msg);\n        scale_queued_mouse_message(msg, "PeekMessageA");\n    }\n    return ok;\n}\n''',
"scale PeekMessageA result",
)

replace_once(
'''    ok = fn(msg, hwnd, min_msg, max_msg);\n    if (ok > 0 && borderless_enabled) log_mouse_msg("probe GetMessageA", msg);\n    return ok;\n}\n''',
'''    ok = fn(msg, hwnd, min_msg, max_msg);\n    if (ok > 0 && borderless_enabled) {\n        log_mouse_msg("probe GetMessageA raw", msg);\n        scale_queued_mouse_message(msg, "GetMessageA");\n    }\n    return ok;\n}\n''',
"scale GetMessageA result",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern queued Win32 mouse scaling v8")
