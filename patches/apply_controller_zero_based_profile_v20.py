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
# In other words, the modern DirectInput path is consuming controller.cfg button
# numbers as zero-based DI slots. Our configurator had been writing learned
# one-based labels (1..10), while the v17 F8 bridge deliberately exposes the
# canonical physical controls as slots 0..9. Make those two layers agree.
#
# Keep the UI/capture values human-friendly and one-based; only the Xbox-style
# controller.cfg output is converted to zero-based values. Generic DirectInput is
# untouched.
old_values = '''    button_value(cross, sizeof(cross), m->cross);\n    button_value(circle, sizeof(circle), m->circle);\n    button_value(square, sizeof(square), m->square);\n    button_value(triangle, sizeof(triangle), m->triangle);\n    button_value(l1, sizeof(l1), m->l1);\n    button_value(r1, sizeof(r1), m->r1);\n    button_value(select, sizeof(select), m->select);\n    button_value(start, sizeof(start), m->start);\n    button_value(l3, sizeof(l3), m->l3);\n    button_value(r3, sizeof(r3), m->r3);\n'''
new_values = '''    button_value(cross, sizeof(cross), generic_layout ? m->cross : m->cross - 1);\n    button_value(circle, sizeof(circle), generic_layout ? m->circle : m->circle - 1);\n    button_value(square, sizeof(square), generic_layout ? m->square : m->square - 1);\n    button_value(triangle, sizeof(triangle), generic_layout ? m->triangle : m->triangle - 1);\n    button_value(l1, sizeof(l1), generic_layout ? m->l1 : m->l1 - 1);\n    button_value(r1, sizeof(r1), generic_layout ? m->r1 : m->r1 - 1);\n    button_value(select, sizeof(select), generic_layout ? m->select : m->select - 1);\n    button_value(start, sizeof(start), generic_layout ? m->start : m->start - 1);\n    button_value(l3, sizeof(l3), generic_layout ? m->l3 : m->l3 - 1);\n    button_value(r3, sizeof(r3), generic_layout ? m->r3 : m->r3 - 1);\n'''
controller = replace_once(controller, old_values, new_values, "logical button values")

# v18's separate frontend face bank is runtime slots 10..13. Match those slot
# numbers directly instead of the previous one-based 11..14 labels.
for name, old_button, new_button in [
    ("CROSS", 11, 10),
    ("CIRCLE", 12, 11),
    ("SQUARE", 13, 12),
    ("TRIANGLE", 14, 13),
]:
    controller = replace_once(
        controller,
        f'    write_binding(file, "VPAD_VIRTUAL_BUTTON_{name}", generic_layout ? {name.lower() if name != "CROSS" else "cross"} : "button {old_button}");\n',
        f'    write_binding(file, "VPAD_VIRTUAL_BUTTON_{name}", generic_layout ? {name.lower() if name != "CROSS" else "cross"} : "button {new_button}");\n',
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
