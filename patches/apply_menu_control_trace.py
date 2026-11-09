"""Trace the stock game's native control dispatch on the verified x86 build."""

from pathlib import Path


runtime = Path("src/runtime.c")
source = runtime.read_text(encoding="utf-8")

anchor = "static DWORD WINAPI init_worker_thread(LPVOID param)\n{"
if source.count(anchor) != 1:
    raise SystemExit("Expected one runtime startup anchor for the menu control trace")

trace = Path(__file__).resolve().parent.parent / "src" / "menu_control_trace.inc"
Path("src/menu_control_trace.inc").write_bytes(trace.read_bytes())
source = source.replace(anchor, '#include "menu_control_trace.inc"\n\n' + anchor, 1)

anchor = "static LRESULT CALLBACK borderless_geometry_wndproc(HWND hwnd, UINT msg,"
if source.count(anchor) != 1:
    raise SystemExit("Expected one borderless window procedure for the menu pointer signal")
source = source.replace(anchor, "static void menu_controller_pointer_message(HWND hwnd, UINT msg);\n\n" + anchor, 1)
anchor = "    WNDPROC previous = borderless_geometry_guard_original_proc;\n"
if source.count(anchor) != 1:
    raise SystemExit("Expected one borderless window procedure body for the menu pointer signal")
source = source.replace(anchor, anchor + "\n    menu_controller_pointer_message(hwnd, msg);\n", 1)

anchor = "static HANDLE WINAPI controller_diag_CreateFileA(LPCSTR name, DWORD access, DWORD share,"
if source.count(anchor) != 1:
    raise SystemExit("Expected one CreateFileA anchor for the menu archive trace")
source = source.replace(anchor, "static void trace_menu_archive_open(const char *path, HANDLE result);\n\n" + anchor, 1)
for suffix, argument in (("A", "name"), ("W", "path")):
    anchor = f'    if (intro_target)\n        intro_diag_logf("VP6 PASS {suffix}'
    if source.count(anchor) != 1:
        raise SystemExit(f"Expected one file-open completion anchor for {suffix}")
    source = source.replace(anchor, f"    trace_menu_archive_open({argument}, h);\n" + anchor, 1)

anchor = "    controller_diag_install_file_hooks();"
if source.count(anchor) != 1:
    raise SystemExit("Expected one hook installation anchor for the menu control trace")
source = source.replace(anchor, "    install_menu_control_trace();\n" + anchor, 1)
runtime.write_text(source, encoding="utf-8")
print("Applied MVP2005 Modern native menu control trace")
