from pathlib import Path

RUNTIME = Path("src/runtime.c")
CONTROLLER = Path("src/controller_config.c")
runtime = RUNTIME.read_text(encoding="utf-8")
controller = CONTROLLER.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller one-based final v21 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# v20's zero-based experiment produced the exact historic MVP/XInput offset:
# Y (raw slot 3) acted as X/Square/Throw Third, and L3 (raw slot 8) acted as
# Start/Pause. That is the classic symptom of feeding zero-based XInput button
# slots to MVP's one-based controller profile. v13 had already demonstrated that
# shifting XInput into logical slots 1..10 fixes the face buttons and Start.
#
# Return to the canonical one-based profile and make F7/XINPUT_ONE_BASED the
# production/default diagnostic mode. Keep all diagnostics and F5-F10 live modes
# so a single run can still compare theories if anything remains.

# Restore the advertised Xbox-style button count used by the long-established
# community profile. Generic DirectInput remains untouched.
controller = replace_once(
    controller,
    '        (unsigned long)(generic_layout ? (buttons ? buttons : 12) : 15),\n',
    '        (unsigned long)(generic_layout ? (buttons ? buttons : 12) : 10),\n',
    "logical button count 10",
)

# Restore the canonical one-based logical face/shoulder/menu/stick-click slots.
for variable, old_value, new_value in [
    ("cross", 0, 1),
    ("circle", 1, 2),
    ("square", 2, 3),
    ("triangle", 3, 4),
    ("l1", 4, 5),
    ("r1", 5, 6),
    ("select", 6, 7),
    ("start", 7, 8),
    ("l3", 8, 9),
    ("r3", 9, 10),
]:
    controller = replace_once(
        controller,
        f'button_value({variable}, sizeof({variable}), generic_layout ? m->{variable if variable not in ("cross", "circle", "square", "triangle") else variable} : {old_value});',
        f'button_value({variable}, sizeof({variable}), generic_layout ? m->{variable if variable not in ("cross", "circle", "square", "triangle") else variable} : {new_value});',
        f"{variable} one-based logical slot",
    )

# The v18/v20 separate frontend bank is not needed with a correctly synthesized
# one-based controller. Restore virtual A/B/X/Y to the same canonical buttons as
# gameplay, matching known working MVP 2005 Xbox 360 controller.cfg profiles.
for name, variable, old_button in [
    ("CROSS", "cross", 10),
    ("CIRCLE", "circle", 11),
    ("SQUARE", "square", 12),
    ("TRIANGLE", "triangle", 13),
]:
    controller = replace_once(
        controller,
        f'    write_binding(file, "VPAD_VIRTUAL_BUTTON_{name}", generic_layout ? {variable} : "button {old_button}");\n',
        f'    write_binding(file, "VPAD_VIRTUAL_BUTTON_{name}", {variable});\n',
        f"virtual {name} canonical slot",
    )

# Remove the v19 X quarantine. With one-based XInput synthesis, physical X is
# logical slot 3 and can use the normal Square/action binding again.
for action in [
    "VPAD_PITCH_3",
    "VPAD_FIELD_PICK_OFF_THROW_THIRD",
    "VPAD_FIELD_THROW_THIRD",
    "VPAD_RUNNER_THIRD_SELECT",
]:
    controller = replace_once(
        controller,
        f'    write_binding(file, "{action}", generic_layout ? square : "button 14");\n',
        f'    write_binding(file, "{action}", square);\n',
        f"{action} restore Square",
    )

# Match the common working Xbox 360 MVP profile for the remaining baseball
# actions: Select handles fake rundown; LB advances all; RB retreats all; RT is
# relay/cutoff; L3 pitch history; R3 bunt. Most of these are already in place.
controller = replace_once(
    controller,
    '    write_binding(file, "VPAD_FIELD_FAKE_RUNDOWN_THROW", r1);\n',
    '    write_binding(file, "VPAD_FIELD_FAKE_RUNDOWN_THROW", select);\n',
    "fake rundown on Select",
)

CONTROLLER.write_text(controller, encoding="utf-8")

# Default to the v17 F7 path: native XInput synthesized as a canonical one-based
# DIJOYSTATE. v18 already corrected the X/Y axis signs, so this path now carries
# the good stick conversion as well as the correct button numbering.
runtime = replace_once(
    runtime,
    'static int controller_diag_mode = 3;\n',
    'static int controller_diag_mode = 2;\n',
    "default F7 one-based mode",
)

# Keep the face-bank toggle code available for diagnostics, but default it off;
# mode 2 does not use it anyway.
runtime = replace_once(
    runtime,
    'static int controller_diag_face_bank_split = 1;\n',
    'static int controller_diag_face_bank_split = 0;\n',
    "disable split by default",
)

runtime = replace_once(
    runtime,
    'MVP2005 Modern controller diagnostics + zero-based profile v20\\r\\n',
    'MVP2005 Modern controller diagnostics + canonical one-based v21\\r\\n',
    "diagnostic banner",
)

runtime = replace_once(
    runtime,
    'controller hooks requested; default=F8 zero-based with frontend/gameplay face split; Ctrl+F4 toggles face split; F5 raw DI, F6 DI remap/raw axes, F7 XInput 1-based, F8 XInput 0-based, F9 DI remap+neutral trigger, F10 XInput+neutral trigger; Ctrl+1..0 B-slot test, Ctrl+F11 clear B-slot, Ctrl+F12 marker',
    'controller hooks requested; default=F7 canonical one-based XInput; Ctrl+F4 toggles legacy face split; F5 raw DI, F6 DI remap/raw axes, F7 XInput 1-based, F8 XInput 0-based, F9 DI remap+neutral trigger, F10 XInput+neutral trigger; Ctrl+1..0 B-slot test, Ctrl+F11 clear B-slot, Ctrl+F12 marker',
    "startup diagnostic text",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern canonical one-based controller profile v21")
