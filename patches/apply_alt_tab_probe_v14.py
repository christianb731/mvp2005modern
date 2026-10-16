from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")

marker = '''    result = previous ? CallWindowProcA(previous, hwnd, msg, wparam, lparam) :\n        DefWindowProcA(hwnd, msg, wparam, lparam);\n\n'''
if text.count(marker) != 1:
    raise SystemExit(f"Alt-Tab probe insertion marker: expected exactly one match, found {text.count(marker)}")

probe = r'''    if (borderless_enabled && hwnd == borderless_window) {
        int interesting =
            msg == WM_ACTIVATEAPP || msg == WM_ACTIVATE ||
            msg == WM_SETFOCUS || msg == WM_KILLFOCUS ||
            msg == WM_SYSCOMMAND || msg == WM_SIZE ||
            msg == WM_SHOWWINDOW || msg == WM_WINDOWPOSCHANGED;
        if (interesting && InterlockedIncrement(&borderless_geometry_guard_log_count) <= 96) {
            RECT wr;
            RECT cr;
            int have_wr = GetWindowRect(hwnd, &wr);
            int have_cr = GetClientRect(hwnd, &cr);
            char buf[384];
            wsprintfA(buf,
                "focus probe msg=%04x wp=%08lx lp=%08lx fg=%d iconic=%d visible=%d "
                "window=%ld,%ld %ldx%ld client=%ldx%ld style=%08lx exstyle=%08lx\\n",
                (unsigned int)msg,
                (unsigned long)wparam,
                (unsigned long)lparam,
                GetForegroundWindow() == hwnd ? 1 : 0,
                IsIconic(hwnd) ? 1 : 0,
                IsWindowVisible(hwnd) ? 1 : 0,
                have_wr ? wr.left : -1,
                have_wr ? wr.top : -1,
                have_wr ? (wr.right - wr.left) : -1,
                have_wr ? (wr.bottom - wr.top) : -1,
                have_cr ? (cr.right - cr.left) : -1,
                have_cr ? (cr.bottom - cr.top) : -1,
                (unsigned long)GetWindowLongA(hwnd, GWL_STYLE),
                (unsigned long)GetWindowLongA(hwnd, GWL_EXSTYLE));
            log_line(buf);
        }
    }

'''

text = text.replace(marker, marker + probe, 1)
RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern Alt-Tab/focus diagnostic probe v14")
