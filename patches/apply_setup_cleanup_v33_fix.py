from pathlib import Path

LAUNCHER = Path("src/launcher.c")
text = LAUNCHER.read_text(encoding="utf-8")
old = "static void do_browse(HWND hwnd)\n"
new = "static void refresh_setup_status(void);\n\nstatic void do_browse(HWND hwnd)\n"
count = text.count(old)
if count != 1:
    raise SystemExit(f"setup cleanup v33 forward declaration: expected one match, found {count}")
LAUNCHER.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Applied MVP2005 Modern setup cleanup v33 compile fix")
