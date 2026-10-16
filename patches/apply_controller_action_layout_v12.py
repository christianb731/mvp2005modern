from pathlib import Path

SOURCE = Path("src/controller_config.c")
text = SOURCE.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller action layout v12 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# v11 proved that the launcher learns the physical Flydigi buttons correctly and
# that MVP polls exactly the expected DirectInput device. The remaining problem is
# therefore the *action layout* written by our v6 generator.
#
# Restore the long-standing known-good MVP/Xbox controller action assignments used
# by the community fixes. These differ materially from the v6 experiment:
#   LT = pitch history / advance all runners
#   X  = bunt / cutoff throw
#   RB = fielder switch / pitch 5 / fake rundown throw
#   LB = relay throw
#   RT = retreat all runners
#   L3/R3 remain intentional HBP / intentional walk only.
replace_once(
    '    write_binding(file, "VPAD_PITCH_HISTORY_OPEN", l3);\n',
    '    write_binding(file, "VPAD_PITCH_HISTORY_OPEN", l2);\n',
    "pitch history on LT",
)
replace_once(
    '    write_binding(file, "VPAD_SWING_BUNT", r3);\n',
    '    write_binding(file, "VPAD_SWING_BUNT", square);\n',
    "bunt on X",
)
replace_once(
    '    write_binding(file, "VPAD_FIELD_SWITCH", l1);\n',
    '    write_binding(file, "VPAD_FIELD_SWITCH", r1);\n',
    "fielder switch on RB",
)
replace_once(
    '    write_binding(file, "VPAD_FIELD_RELAY_THROW", r2);\n',
    '    write_binding(file, "VPAD_FIELD_RELAY_THROW", l1);\n',
    "relay throw on LB",
)
replace_once(
    '    write_binding(file, "VPAD_FIELD_CUTOFF_THROW", r2);\n',
    '    write_binding(file, "VPAD_FIELD_CUTOFF_THROW", square);\n',
    "cutoff throw on X",
)
replace_once(
    '    write_binding(file, "VPAD_FIELD_FAKE_RUNDOWN_THROW", generic_layout ? r1 : select);\n',
    '    write_binding(file, "VPAD_FIELD_FAKE_RUNDOWN_THROW", r1);\n',
    "fake rundown on RB",
)
replace_once(
    '    write_binding(file, "VPAD_BASERUNNER_ADVANCEALL", l1);\n',
    '    write_binding(file, "VPAD_BASERUNNER_ADVANCEALL", l2);\n',
    "advance all on LT",
)
replace_once(
    '    write_binding(file, "VPAD_BASERUNNER_RETREATALL", r1);\n',
    '    write_binding(file, "VPAD_BASERUNNER_RETREATALL", r2);\n',
    "retreat all on RT",
)

# Update the readable UI so it describes the bindings we actually write.
replace_once(
    '        create_binding_row(hwnd, "X / Square", "Pitch 3; throw third", 368, IDC_SQUARE, 2);\n',
    '        create_binding_row(hwnd, "X / Square", "Pitch 3; bunt; throw third; cutoff throw", 368, IDC_SQUARE, 2);\n',
    "X usage text",
)
replace_once(
    '        create_binding_row(hwnd, "LB / L1", "Fielder switch; advance all runners", 424, IDC_L1, 4);\n',
    '        create_binding_row(hwnd, "LB / L1", "Relay throw", 424, IDC_L1, 4);\n',
    "LB usage text",
)
replace_once(
    '        create_binding_row(hwnd, "RB / R1", "Pitch 5; retreat all runners", 452, IDC_R1, 5);\n',
    '        create_binding_row(hwnd, "RB / R1", "Pitch 5; fielder switch; fake rundown throw", 452, IDC_R1, 5);\n',
    "RB usage text",
)
replace_once(
    '        create_binding_row(hwnd, "View / Back", "Select; fake rundown throw (Xbox layout)", 480, IDC_SELECT, 6);\n',
    '        create_binding_row(hwnd, "View / Back", "Select", 480, IDC_SELECT, 6);\n',
    "View usage text",
)
replace_once(
    '        create_binding_row(hwnd, "L3", "Pitch history; intentional hit batter", 536, IDC_L3, 8);\n',
    '        create_binding_row(hwnd, "L3", "Intentional hit batter", 536, IDC_L3, 8);\n',
    "L3 usage text",
)
replace_once(
    '        create_binding_row(hwnd, "R3", "Bunt; intentional walk", 564, IDC_R3, 9);\n',
    '        create_binding_row(hwnd, "R3", "Intentional walk", 564, IDC_R3, 9);\n',
    "R3 usage text",
)
replace_once(
    '            "If the physical buttons above are learned correctly but MVP performs different actions, Save to MVP again. v0.6 also makes this the active Player 1 gamepad profile so an older auto-generated mapping cannot remain selected.",\n',
    '            "Xbox-style trigger actions: LT opens pitch history / advances all runners; RT retreats all runners. Physical button learning is now verified against MVP itself.",\n',
    "trigger help text",
)

SOURCE.write_text(text, encoding="utf-8")
print("Applied known-good MVP Xbox controller action layout v12")
