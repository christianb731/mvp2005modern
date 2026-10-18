from pathlib import Path

RUNTIME = Path("src/runtime.c")
CONTROLLER = Path("src/controller_config.c")
runtime = RUNTIME.read_text(encoding="utf-8")
controller = CONTROLLER.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller frontend/gameplay split v18 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Evidence from v0.17
# ---------------------------------------------------------------------------
# F8 / XINPUT_ZERO_BASED is the first mode where physical B reliably becomes
# MVP's Throw First action. The diagnostic log also proves physical X (XInput
# 0x4000) becomes only DI button slot 2 with neutral triggers and no Esc/Enter,
# yet MVP opens a menu. controller.cfg simultaneously maps button 3 both to the
# gameplay X/Square actions and to VPAD_VIRTUAL_BUTTON_SQUARE.
#
# Therefore separate the menu/navigation face-button bank from the gameplay
# action bank instead of forcing one DI slot to serve both systems.
#
# Gameplay bank (zero-based DI slots):
#   A/B/X/Y -> slots 0/1/2/3, matching controller.cfg buttons 1/2/3/4.
# Frontend/menu bank:
#   A/B/X/Y -> slots 10/11/12/13, matching controller.cfg buttons 11/12/13/14.
#
# RC1 already has a proven gameplay_input_phase signal, so the runtime can choose
# the bank without another input API or heuristic.

# Make the generated Xbox-style profile advertise enough logical buttons for the
# separate frontend bank. Generic DirectInput profiles are left unchanged.
controller = replace_once(
    controller,
    '''        (unsigned long)(buttons ? buttons : (generic_layout ? 12 : 10)),\n''',
    '''        (unsigned long)(generic_layout ? (buttons ? buttons : 12) : 14),\n''',
    "logical button count",
)

# Move only the four virtual/menu face buttons to the high bank. Gameplay actions
# below this block continue to use cross/circle/square/triangle = buttons 1..4.
for name, variable, logical_button in [
    ("CROSS", "cross", 11),
    ("CIRCLE", "circle", 12),
    ("SQUARE", "square", 13),
    ("TRIANGLE", "triangle", 14),
]:
    controller = replace_once(
        controller,
        f'    write_binding(file, "VPAD_VIRTUAL_BUTTON_{name}", {variable});\n',
        f'    write_binding(file, "VPAD_VIRTUAL_BUTTON_{name}", generic_layout ? {variable} : "button {logical_button}");\n',
        f"virtual {name} frontend bank",
    )

CONTROLLER.write_text(controller, encoding="utf-8")


# ---------------------------------------------------------------------------
# Runtime: corrected native XInput axes + zero-based gameplay / high-bank menus
# ---------------------------------------------------------------------------
# v0.16's synthesized sticks were visibly reversed. The v0.17 log lets us compare
# raw DI and XInput simultaneously and shows the signs are opposite. Match the raw
# DI convention used by the working MVP profile.
runtime = replace_once(
    runtime,
    '''static LONG controller_xinput_axis_x(SHORT value)\n{\n    LONG result = 32767 - (LONG)value;\n''',
    '''static LONG controller_xinput_axis_x(SHORT value)\n{\n    LONG result = 32767 + (LONG)value;\n''',
    "X axis sign",
)
runtime = replace_once(
    runtime,
    '''static LONG controller_xinput_axis_y(SHORT value)\n{\n    LONG result = 32767 + (LONG)value;\n''',
    '''static LONG controller_xinput_axis_y(SHORT value)\n{\n    LONG result = 32767 - (LONG)value;\n''',
    "Y axis sign",
)

# Start the diagnostic build in the now-proven zero-based mode rather than v13's
# one-based compatibility experiment.
runtime = replace_once(
    runtime,
    '''static int controller_diag_mode = 1;\n''',
    '''static int controller_diag_mode = 3;\nstatic int controller_diag_face_bank_split = 1;\n''',
    "default diagnostic mode",
)

# After v17 shifts XInput buttons down to zero-based slots in mode 3, route the
# four face buttons into the separate high bank whenever the proven RC1 gameplay
# phase detector says we are in the frontend/menu phase.
old_zero_based = '''            if (controller_diag_mode == 3) {\n                /* Compare the legacy zero-based hypothesis in the same run. */\n                for (i = 0; i < 10; i++) bytes[48 + i] = bytes[48 + i + 1];\n                bytes[48 + 10] = 0;\n            }\n'''
new_zero_based = '''            if (controller_diag_mode == 3) {\n                BYTE face[4];\n                /* v17 proved the gameplay convention is zero-based: physical B\n                 * at slot 1 activates controller.cfg button 2 / Throw First. */\n                for (i = 0; i < 10; i++) bytes[48 + i] = bytes[48 + i + 1];\n                bytes[48 + 10] = 0;\n\n                /* Do not let the same slot simultaneously drive MVP's virtual\n                 * frontend face command and its baseball action. In frontend\n                 * phase, move A/B/X/Y to logical buttons 11..14. In gameplay,\n                 * leave them at slots 0..3 for action bindings 1..4. */\n                if (controller_diag_face_bank_split &&\n                    InterlockedCompareExchange(&gameplay_input_phase, 0, 0) == 0) {\n                    for (i = 0; i < 4; i++) face[i] = bytes[48 + i];\n                    for (i = 0; i < 4; i++) bytes[48 + i] = 0;\n                    for (i = 0; i < 4; i++) bytes[48 + 10 + i] = face[i];\n                }\n            }\n'''
runtime = replace_once(runtime, old_zero_based, new_zero_based, "frontend/gameplay face bank")

# Add one in-session switch so, if needed, the user can compare split vs unsplit
# without another build. Ctrl+F4 toggles the split and logs the result.
old_hotkeys = '''    if (ctrl) {\n        static const int fkeys[6] = {VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10};\n'''
new_hotkeys = '''    if (ctrl) {\n        if (controller_diag_hotkey_edge(22, VK_F4)) {\n            controller_diag_face_bank_split = !controller_diag_face_bank_split;\n            controller_diag_logf("FACE BANK SPLIT -> %d (0=shared slots, 1=frontend high bank/gameplay low bank)",\n                controller_diag_face_bank_split);\n        }\n        static const int fkeys[6] = {VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10};\n'''
runtime = replace_once(runtime, old_hotkeys, new_hotkeys, "F4 face bank toggle")

runtime = replace_once(
    runtime,
    '''        for (i = 0; i < 22; i++) controller_diag_hotkey_prev[i] = 0;\n''',
    '''        for (i = 0; i < 23; i++) controller_diag_hotkey_prev[i] = 0;\n''',
    "hotkey reset size",
)

runtime = replace_once(
    runtime,
    '''controller hooks requested; hotkeys: Ctrl+F5 raw DI, F6 DI remap/raw axes, F7 XInput 1-based, F8 XInput 0-based, F9 DI remap+neutral trigger, F10 XInput+neutral trigger; Ctrl+1..0 B-slot test, Ctrl+F11 clear B-slot, Ctrl+F12 marker''',
    '''controller hooks requested; default=F8 zero-based with frontend/gameplay face split; Ctrl+F4 toggles face split; F5 raw DI, F6 DI remap/raw axes, F7 XInput 1-based, F8 XInput 0-based, F9 DI remap+neutral trigger, F10 XInput+neutral trigger; Ctrl+1..0 B-slot test, Ctrl+F11 clear B-slot, Ctrl+F12 marker''',
    "diagnostic banner",
)

runtime = replace_once(
    runtime,
    '''MVP2005 Modern full controller diagnostics v17\\r\\n''',
    '''MVP2005 Modern controller diagnostics + phase split v18\\r\\n''',
    "diagnostic version banner",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern controller frontend/gameplay split v18")
