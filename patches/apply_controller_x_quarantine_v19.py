from pathlib import Path

RUNTIME = Path("src/runtime.c")
CONTROLLER = Path("src/controller_config.c")
runtime = RUNTIME.read_text(encoding="utf-8")
controller = CONTROLLER.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller X quarantine v19 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# v18 proved the frontend/gameplay face-bank collision theory was incomplete:
# in gameplay phase, physical X is still the *only* reported DI slot (slot 2),
# yet MVP opens the manager menu. This matches a documented historical X360/MVP
# symptom. Treat DI slot 2 itself as unsafe during gameplay and move only X's
# baseball actions to a completely unused logical slot.

# Xbox-style profile now exposes button 15 for gameplay X. Existing frontend
# virtual face buttons remain 11..14, and the already-working A/B/Y gameplay
# actions remain 1/2/4. Generic DirectInput profiles are unchanged.
controller = replace_once(
    controller,
    '        (unsigned long)(generic_layout ? (buttons ? buttons : 12) : 14),\n',
    '        (unsigned long)(generic_layout ? (buttons ? buttons : 12) : 15),\n',
    "logical button count 15",
)

for action in [
    "VPAD_PITCH_3",
    "VPAD_FIELD_PICK_OFF_THROW_THIRD",
    "VPAD_FIELD_THROW_THIRD",
    "VPAD_RUNNER_THIRD_SELECT",
]:
    old = f'    write_binding(file, "{action}", square);\n'
    new = f'    write_binding(file, "{action}", generic_layout ? square : "button 15");\n'
    controller = replace_once(controller, old, new, action)

CONTROLLER.write_text(controller, encoding="utf-8")

# Runtime: in zero-based F8 mode, v18 already leaves A/B/X/Y in low slots during
# gameplay and sends them to the frontend high bank outside gameplay. Keep that
# behavior for A/B/Y, but when gameplay is active, remove X from unsafe slot 2
# and place it in slot 14 (controller.cfg button 15).
old_block = '''                if (controller_diag_face_bank_split &&\n                    InterlockedCompareExchange(&gameplay_input_phase, 0, 0) == 0) {\n                    for (i = 0; i < 4; i++) face[i] = bytes[48 + i];\n                    for (i = 0; i < 4; i++) bytes[48 + i] = 0;\n                    for (i = 0; i < 4; i++) bytes[48 + 10 + i] = face[i];\n                }\n'''
new_block = '''                if (controller_diag_face_bank_split &&\n                    InterlockedCompareExchange(&gameplay_input_phase, 0, 0) == 0) {\n                    for (i = 0; i < 4; i++) face[i] = bytes[48 + i];\n                    for (i = 0; i < 4; i++) bytes[48 + i] = 0;\n                    for (i = 0; i < 4; i++) bytes[48 + 10 + i] = face[i];\n                } else if (controller_diag_face_bank_split &&\n                    InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0) {\n                    /* Slot 2 is independently associated with MVP's manager-menu\n                     * behavior on X360-style input. Quarantine physical X to an\n                     * otherwise-unused gameplay slot so only explicit VPAD action\n                     * bindings can see it. */\n                    bytes[48 + 14] = bytes[48 + 2];\n                    bytes[48 + 2] = 0;\n                }\n'''
runtime = replace_once(runtime, old_block, new_block, "gameplay X quarantine")

# Make the diagnostic file self-identifying. The existing STATE line already
# prints slots 0..15, so slot 14 will be visible without more logging code.
runtime = replace_once(
    runtime,
    'MVP2005 Modern controller diagnostics + phase split v18\\r\\n',
    'MVP2005 Modern controller diagnostics + X quarantine v19\\r\\n',
    "diagnostic banner",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern gameplay X quarantine v19")
