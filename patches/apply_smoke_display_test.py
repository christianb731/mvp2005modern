"""Add a display-mode override to the QA launcher only."""

from pathlib import Path


launcher = Path("src/launcher.c")
source = launcher.read_text(encoding="utf-8")
anchor = "static int launch_target(HWND hwnd, const char *exe_path, int write_ui_config)"
launch = """    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    if (CreateProcessA(exe_path, NULL, NULL, NULL, FALSE, CREATE_SUSPENDED"""
if source.count(anchor) != 1 or source.count(launch) != 1:
    raise SystemExit("Expected one modern launcher target and process creation")

fixture = Path(__file__).resolve().parent.parent / "src" / "smoke_display_test.inc"
Path("src/smoke_display_test.inc").write_bytes(fixture.read_bytes())
source = source.replace(anchor, '#include "smoke_display_test.inc"\n\n' + anchor)
source = source.replace(launch, "    if (!apply_smoke_display_mode(hwnd, exe_path, game_dir)) return 0;\n\n" + launch)
launcher.write_text(source, encoding="utf-8")

runtime = Path("src/runtime.c")
source = runtime.read_text(encoding="utf-8")
Path("src/smoke_display_runtime.inc").write_bytes(fixture.with_name("smoke_display_runtime.inc").read_bytes())
anchors = {
    "static void load_config(void)": '#include "smoke_display_runtime.inc"\n\nstatic void load_config(void)',
    '    borderless_enabled = GetPrivateProfileIntA("Borderless", "Enabled", 0, ini) != 0;':
        '    borderless_enabled = GetPrivateProfileIntA("Borderless", "Enabled", 0, ini) != 0;\n'
        '    load_smoke_display_mode(ini);',
    '\n    hr = real_CreateDevice(self, adapter, device_type, focus_window, behavior_flags,\n'
    '        presentation_parameters, returned_device);':
        '\n    prepare_smoke_windowed(self, adapter, focus_window, presentation_parameters);\n'
        '    hr = real_CreateDevice(self, adapter, device_type, focus_window, behavior_flags,\n'
        '        presentation_parameters, returned_device);\n'
        '    finish_smoke_windowed(hr, presentation_parameters, "CreateDevice");',
    '\n    hr = real_Reset ? real_Reset(self, presentation_parameters) : E_FAIL;':
        '\n    prepare_smoke_windowed(NULL, 0, NULL, presentation_parameters);\n'
        '    hr = real_Reset ? real_Reset(self, presentation_parameters) : E_FAIL;\n'
        '    finish_smoke_windowed(hr, presentation_parameters, "Reset");',
}
for original, replacement in anchors.items():
    if source.count(original) != 1:
        raise SystemExit(f"Expected one runtime anchor: {original.strip()}")
    source = source.replace(original, replacement)
runtime.write_text(source, encoding="utf-8")
print("Applied the isolated MVP display test launcher and runtime")
