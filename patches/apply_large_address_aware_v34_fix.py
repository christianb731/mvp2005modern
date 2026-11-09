from pathlib import Path

LAUNCHER = Path("src/launcher.c")
text = LAUNCHER.read_text(encoding="utf-8")

old = "static int write_selected_config(HWND hwnd)\n"
new = "static int apply_laa_setting(HWND hwnd, const char *exe_path, int enable);\n\nstatic int write_selected_config(HWND hwnd)\n"
count = text.count(old)
if count != 1:
    raise SystemExit(f"LAA v34 compile fix: expected one write_selected_config marker, found {count}")

text = text.replace(old, new, 1)
LAUNCHER.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern LAA v34 forward-declaration compile fix")
