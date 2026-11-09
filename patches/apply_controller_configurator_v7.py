from pathlib import Path

SOURCE = Path("src/controller_config.c")
text = SOURCE.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller configurator v7 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# DirectInput exposes rgbButtons as zero-based indices and MVP's controller.cfg
# uses that same zero-based numbering. v0.5/v0.6 incorrectly displayed/stored
# index+1. The resulting one-button shift exactly explains the verified symptoms:
# physical LB (DI index 4) hit config button 4 -> pitch 4, physical L3 (index 8)
# hit config button 8 -> Start/pause, and physical X (index 2) hit button 2 ->
# Circle/back behavior.
replace_once(
'''                    return (int)i + 1;\n''',
'''                    return (int)i;\n''',
"captured button numbering",
)

replace_once(
'''        if (values[i] < 1) {\n''',
'''        if (values[i] < 0) {\n''',
"allow zero button",
)

# Presets are also controller.cfg values, so shift the legacy one-based values
# down by one. Calibration remains the recommended path.
replace_once(
'''        map.cross = 2;\n        map.circle = 3;\n        map.square = 1;\n        map.triangle = 4;\n        map.l1 = 5;\n        map.r1 = 6;\n        map.select = 9;\n        map.start = 10;\n        map.l3 = 11;\n        map.r3 = 12;\n''',
'''        map.cross = 1;\n        map.circle = 2;\n        map.square = 0;\n        map.triangle = 3;\n        map.l1 = 4;\n        map.r1 = 5;\n        map.select = 8;\n        map.start = 9;\n        map.l3 = 10;\n        map.r3 = 11;\n''',
"generic preset zero based",
)

replace_once(
'''        map.cross = 1;\n        map.circle = 2;\n        map.square = 3;\n        map.triangle = 4;\n        map.l1 = 5;\n        map.r1 = 6;\n        map.select = 7;\n        map.start = 8;\n        map.l3 = 9;\n        map.r3 = 10;\n''',
'''        map.cross = 0;\n        map.circle = 1;\n        map.square = 2;\n        map.triangle = 3;\n        map.l1 = 4;\n        map.r1 = 5;\n        map.select = 6;\n        map.start = 7;\n        map.l3 = 8;\n        map.r3 = 9;\n''',
"xbox preset zero based",
)

# Generic DirectInput trigger buttons were hard-coded with the same old
# one-based convention.
replace_once(
'''    const char *l2 = generic_layout ? "button 7" : "axis- 3";\n    const char *r2 = generic_layout ? "button 8" : "axis+ 3";\n''',
'''    const char *l2 = generic_layout ? "button 6" : "axis- 3";\n    const char *r2 = generic_layout ? "button 7" : "axis+ 3";\n''',
"generic trigger button numbering",
)

# Numeric validation/editing must include controller.cfg button 0.
for old, new, label in [
    ('map.cross = read_edit_number(edits[0], 1, 64);', 'map.cross = read_edit_number(edits[0], 0, 63);', 'cross range'),
    ('map.circle = read_edit_number(edits[1], 1, 64);', 'map.circle = read_edit_number(edits[1], 0, 63);', 'circle range'),
    ('map.square = read_edit_number(edits[2], 1, 64);', 'map.square = read_edit_number(edits[2], 0, 63);', 'square range'),
    ('map.triangle = read_edit_number(edits[3], 1, 64);', 'map.triangle = read_edit_number(edits[3], 0, 63);', 'triangle range'),
    ('map.l1 = read_edit_number(edits[4], 1, 64);', 'map.l1 = read_edit_number(edits[4], 0, 63);', 'l1 range'),
    ('map.r1 = read_edit_number(edits[5], 1, 64);', 'map.r1 = read_edit_number(edits[5], 0, 63);', 'r1 range'),
    ('map.select = read_edit_number(edits[6], 1, 64);', 'map.select = read_edit_number(edits[6], 0, 63);', 'select range'),
    ('map.start = read_edit_number(edits[7], 1, 64);', 'map.start = read_edit_number(edits[7], 0, 63);', 'start range'),
    ('map.l3 = read_edit_number(edits[8], 1, 64);', 'map.l3 = read_edit_number(edits[8], 0, 63);', 'l3 range'),
    ('map.r3 = read_edit_number(edits[9], 1, 64);', 'map.r3 = read_edit_number(edits[9], 0, 63);', 'r3 range'),
]:
    replace_once(old, new, label)

replace_once(
'''        MessageBoxA(hwnd, "Button assignments must be numbers from 1 to 64.",\n''',
'''        MessageBoxA(hwnd, "Button assignments must be controller.cfg indices from 0 to 63.",\n''',
"validation message",
)

# Make the UI wording explicit so users do not interpret these as human-facing
# button ordinals. Calibration still means they never have to edit them.
text = text.replace('"Learned input"', '"MVP button index"', 1)
text = text.replace('"Button", WS_CHILD | WS_VISIBLE,', '"Index", WS_CHILD | WS_VISIBLE,', 1)
text = text.replace(
    '"Recommended: press each named button when prompted. The launcher learns what Windows actually calls it, so you do not need to understand DirectInput numbering."',
    '"Recommended: press each named button when prompted. The launcher learns the exact zero-based button index MVP stores, so you never need to type these numbers yourself."',
    1,
)

SOURCE.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern zero-based controller.cfg button fix v7")
