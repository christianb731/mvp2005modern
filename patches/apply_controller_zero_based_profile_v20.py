from pathlib import Path

RUNTIME = Path("src/runtime.c")
CONTROLLER = Path("src/controller_config.c")
runtime = RUNTIME.read_text(encoding="utf-8")
controller = CONTROLLER.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller zero-based profile v20 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# v19 + the user's new observation finally gives us a consistent explanation for
# the old symptoms. In the gameplay stream, physical Y is DI slot 3 and MVP treats
# it as the action configured as "button 3" (Throw Third). Historically, physical
# L3 at slot 8 also fired the profile's "button 8" Start binding and paused, and
# physical LB at slot 4 behaved like the profile's button-4 face/pitch action.
#
# The modern DirectInput path is therefore consuming controller.cfg button numbers
# as zero-based DI slots. v13 intentionally generated a stable one-based logical
# profile (1..10), and v17's now-proven F8 mode shifts the synthesized XInput state
# back to slots 0..9. Correct the profile side to match the state the game really
# receives. The UI/capture values stay human-friendly; Generic DirectInput remains
# unchanged.
for variable, old_slot, new_slot in [
    ("cross", 1, 0),
    ("circle", 2, 1),
    ("square", 3, 2),
    ("triangle", 4, 3),
    ("l1", 5, 4),
    ("r1", 6, 5),
    ("select", 7, 6),
    ("start", 8, 7),
    ("l3", 9, 8),
    ("r3", 10, 9),
]:
    controller = replace_once(
        controller,
        f'    button_value({variable}, sizeof({variable}), generic_layout ? m->{variable} : {old_slot});\n',
        f'    button_value({variable}, sizeof({variable}), generic_layout ? m->{variable} : {new_slot});\n',
        f"{variable} logical slot",
    )

# v18's separate frontend face bank is runtime slots 10..13. Match those slot
# numbers directly instead of the previous one-based 11..14 labels.
for name, variable, old_button, new_button in [
    ("CROSS", "cross", 11, 10),
    ("CIRCLE", "circle", 12, 11),
    ("SQUARE", "square", 13, 12),
    ("TRIANGLE", "triangle", 14, 13),
]:
    controller = replace_once(
        controller,
        f'    write_binding(file, "VPAD_VIRTUAL_BUTTON_{name}", generic_layout ? {variable} : "button {old_button}");\n',
        f'    write_binding(file, "VPAD_VIRTUAL_BUTTON_{name}", generic_layout ? {variable} : "button {new_button}");\n',
        f"frontend {name} slot",
    )

# v19 quarantines gameplay X from unsafe slot 2 into DI slot 14. The gameplay
# action bindings must therefore say button 14, not button 15.
for action in [
    "VPAD_PITCH_3",
    "VPAD_FIELD_PICK_OFF_THROW_THIRD",
    "VPAD_FIELD_THROW_THIRD",
    "VPAD_RUNNER_THIRD_SELECT",
]:
    controller = replace_once(
        controller,
        f'    write_binding(file, "{action}", generic_layout ? square : "button 15");\n',
        f'    write_binding(file, "{action}", generic_layout ? square : "button 14");\n',
        f"{action} quarantine slot",
    )

CONTROLLER.write_text(controller, encoding="utf-8")

runtime = replace_once(
    runtime,
    'MVP2005 Modern controller diagnostics + X quarantine v19\\r\\n',
    'MVP2005 Modern controller diagnostics + zero-based profile v20\\r\\n',
    "diagnostic banner",
)
RUNTIME.write_text(runtime, encoding="utf-8")

print("Applied MVP2005 Modern zero-based controller profile v20")
