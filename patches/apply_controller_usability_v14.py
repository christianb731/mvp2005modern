from pathlib import Path

SOURCE = Path("src/controller_config.c")
text = SOURCE.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller usability v14 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Persisted trigger bindings
# ---------------------------------------------------------------------------
replace_once(
'''static HWND edits[10];\nstatic HWND controller_window;\n''',
'''static HWND edits[10];\nstatic char learned_l2_binding[32] = "axis- 3";\nstatic char learned_r2_binding[32] = "axis+ 3";\nstatic HWND controller_window;\n''',
"trigger binding globals",
)

# The Xbox-style path should use calibrated trigger axes instead of assuming every
# modern controller exposes LT/RT as opposite halves of axis 3.
replace_once(
'''    const char *l2 = generic_layout ? "button 7" : "axis- 3";\n    const char *r2 = generic_layout ? "button 8" : "axis+ 3";\n''',
'''    const char *l2 = generic_layout ? "button 7" : learned_l2_binding;\n    const char *r2 = generic_layout ? "button 8" : learned_r2_binding;\n''',
"use calibrated triggers",
)

# Save trigger bindings next to the runtime button-remap settings so reopening the
# launcher does not lose a successful trigger calibration.
replace_once(
'''    WritePrivateProfileStringA("Controller", "RemapEnabled",\n        generic_layout ? "0" : "1", ini);\n    if (generic_layout) return;\n\n''',
'''    WritePrivateProfileStringA("Controller", "RemapEnabled",\n        generic_layout ? "0" : "1", ini);\n    if (generic_layout) return;\n    WritePrivateProfileStringA("Controller", "LTBinding", learned_l2_binding, ini);\n    WritePrivateProfileStringA("Controller", "RTBinding", learned_r2_binding, ini);\n\n''',
"persist trigger bindings",
)

# Add a small loader alongside the v13 INI helper.
marker = '''static void write_controller_source_index(const char *ini, const char *key, int one_based_value)\n'''
if text.count(marker) != 1:
    raise SystemExit("controller usability v14: runtime INI helper marker not found")
loader = r'''static void load_saved_trigger_bindings(void)
{
    char ini[MAX_PATH];
    char value[32];
    if (!get_controller_runtime_ini_path(ini, sizeof(ini))) return;
    if (GetPrivateProfileStringA("Controller", "LTBinding", "", value, sizeof(value), ini) > 0)
        lstrcpynA(learned_l2_binding, value, sizeof(learned_l2_binding));
    if (GetPrivateProfileStringA("Controller", "RTBinding", "", value, sizeof(value), ini) > 0)
        lstrcpynA(learned_r2_binding, value, sizeof(learned_r2_binding));
}

'''
text = text.replace(marker, loader + marker, 1)

# ---------------------------------------------------------------------------
# Trigger-axis calibration through the same legacy DirectInput state used by MVP
# ---------------------------------------------------------------------------
marker = '''static int capture_physical_button(LPDIRECTINPUTDEVICEA device, DWORD button_count,\n'''
if text.count(marker) != 1:
    raise SystemExit("controller usability v14: capture button marker not found")
trigger_helpers = r'''static LONG controller_axis_value(const DIJOYSTATE *state, int axis)
{
    switch (axis) {
    case 0: return state->lX;
    case 1: return state->lY;
    case 2: return state->lZ;
    case 3: return state->lRx;
    case 4: return state->lRy;
    case 5: return state->lRz;
    default: return 0;
    }
}

static int capture_trigger_axis(LPDIRECTINPUTDEVICEA device, const DIJOYSTATE *baseline,
    DWORD axis_count, const char *friendly_name, char *binding, DWORD binding_size)
{
    DWORD start = GetTickCount();
    DIJOYSTATE state;
    int axis_limit = axis_count > 6 ? 6 : (int)axis_count;
    char status[320];

    if (axis_limit <= 0) return 0;
    snprintf(status, sizeof(status),
        "Press and hold %s fully. MVP Modern will detect its axis and direction. Press Esc to cancel.",
        friendly_name);
    controller_status(status);
    if (cfg_status) UpdateWindow(cfg_status);

    while (GetTickCount() - start < 30000) {
        int best_axis = -1;
        LONG best_delta = 0;
        int i;
        if (calibration_cancel_requested()) return 0;
        if (read_capture_state(device, &state)) {
            for (i = 0; i < axis_limit; i++) {
                LONG delta = controller_axis_value(&state, i) - controller_axis_value(baseline, i);
                LONG mag = delta < 0 ? -delta : delta;
                if (mag > (best_delta < 0 ? -best_delta : best_delta)) {
                    best_delta = delta;
                    best_axis = i;
                }
            }
            if (best_axis >= 0 && (best_delta > 7000 || best_delta < -7000)) {
                snprintf(binding, binding_size, "axis%c %d", best_delta < 0 ? '-' : '+', best_axis + 1);
                MessageBeep(MB_OK);
                Sleep(250);
                return 1;
            }
        }
        Sleep(15);
    }
    return 0;
}

'''
text = text.replace(marker, trigger_helpers + marker, 1)

# Extend the existing button wizard with LT/RT calibration for Xbox-style mode.
replace_once(
'''    int idx;\n    int i;\n    DWORD buttons;\n''',
'''    int idx;\n    int i;\n    int preset;\n    DWORD buttons;\n    DIJOYSTATE trigger_baseline;\n    char lt_binding[32];\n    char rt_binding[32];\n''',
"calibration locals",
)

replace_once(
'''    idx = (int)SendMessageA(device_combo, CB_GETCURSEL, 0, 0);\n''',
'''    idx = (int)SendMessageA(device_combo, CB_GETCURSEL, 0, 0);\n    preset = (int)SendMessageA(layout_combo, CB_GETCURSEL, 0, 0);\n''',
"read layout during calibration",
)

replace_once(
'''        "The launcher will ask you to press the physical A, B, X, Y, shoulder, menu, and stick-click buttons one at a time. This learns the controller's real DirectInput numbering instead of guessing it.\\n\\n"\n''',
'''        "The launcher will ask you to press A, B, X, Y, LB, RB, View, Start, L3 and R3 one at a time. For Xbox-style controllers it will then learn LT and RT from their actual DirectInput axes.\\n\\n"\n''',
"calibration intro",
)

replace_once(
'''    for (i = 0; i < 10; i++) set_edit_number(edits[i], values[i]);\n    EnableWindow(device_combo, TRUE);\n''',
'''    for (i = 0; i < 10; i++) set_edit_number(edits[i], values[i]);\n\n    if (preset != 1) {\n        if (MessageBoxA(hwnd,\n                "Button learning is complete.\\n\\nRelease both triggers and center both sticks, then click OK. The next two steps will learn LT and RT.",\n                "MVP Baseball 2005 Modern - Trigger Calibration",\n                MB_ICONINFORMATION | MB_OKCANCEL) != IDOK ||\n            !read_capture_state(device, &trigger_baseline) ||\n            !capture_trigger_axis(device, &trigger_baseline, controllers[idx].axes,\n                "LT / Left Trigger", lt_binding, sizeof(lt_binding)) ||\n            !capture_trigger_axis(device, &trigger_baseline, controllers[idx].axes,\n                "RT / Right Trigger", rt_binding, sizeof(rt_binding))) {\n            controller_status("Button calibration succeeded, but trigger calibration was cancelled or timed out. Existing trigger bindings were kept.");\n        } else {\n            lstrcpynA(learned_l2_binding, lt_binding, sizeof(learned_l2_binding));\n            lstrcpynA(learned_r2_binding, rt_binding, sizeof(learned_r2_binding));\n        }\n    }\n\n    EnableWindow(device_combo, TRUE);\n''',
"calibrate triggers after buttons",
)

replace_once(
'''    controller_status("Calibration complete. The fields now match the buttons you actually pressed. Click Save to MVP to install this mapping.");\n''',
'''    {\n        char done[256];\n        snprintf(done, sizeof(done),\n            "Calibration complete. LT=%s, RT=%s. Click Save to MVP to install the mapping.",\n            learned_l2_binding, learned_r2_binding);\n        controller_status(done);\n    }\n''',
"calibration completion status",
)

# ---------------------------------------------------------------------------
# Modern Xbox action defaults now that v13 fixed the physical/logical mismatch.
# The v12 community layout made several shoulder/stick controls appear dead in
# normal play. Give each modern control a useful, easy-to-test role.
# ---------------------------------------------------------------------------
replace_once(
'    write_binding(file, "VPAD_PITCH_HISTORY_OPEN", l2);\n',
'    write_binding(file, "VPAD_PITCH_HISTORY_OPEN", l3);\n',
"pitch history on L3",
)
replace_once(
'    write_binding(file, "VPAD_SWING_BUNT", square);\n',
'    write_binding(file, "VPAD_SWING_BUNT", r3);\n',
"bunt on R3",
)
replace_once(
'    write_binding(file, "VPAD_FIELD_SWITCH", r1);\n',
'    write_binding(file, "VPAD_FIELD_SWITCH", l1);\n',
"fielder switch on LB",
)
replace_once(
'    write_binding(file, "VPAD_FIELD_RELAY_THROW", l1);\n',
'    write_binding(file, "VPAD_FIELD_RELAY_THROW", r2);\n',
"relay on RT",
)
replace_once(
'    write_binding(file, "VPAD_FIELD_CUTOFF_THROW", square);\n',
'    write_binding(file, "VPAD_FIELD_CUTOFF_THROW", r2);\n',
"cutoff on RT",
)
replace_once(
'    write_binding(file, "VPAD_FIELD_FAKE_RUNDOWN_THROW", r1);\n',
'    write_binding(file, "VPAD_FIELD_FAKE_RUNDOWN_THROW", select);\n',
"fake rundown on View",
)
replace_once(
'    write_binding(file, "VPAD_BASERUNNER_ADVANCEALL", l2);\n',
'    write_binding(file, "VPAD_BASERUNNER_ADVANCEALL", l2);\n',
"advance all remains LT",
)
replace_once(
'    write_binding(file, "VPAD_BASERUNNER_RETREATALL", r2);\n',
'    write_binding(file, "VPAD_BASERUNNER_RETREATALL", r2);\n',
"retreat all remains RT",
)

# Update the readable rows to match the modern defaults.
replace_once(
'        create_binding_row(hwnd, "X / Square", "Pitch 3; bunt; throw third; cutoff throw", 368, IDC_SQUARE, 2);\n',
'        create_binding_row(hwnd, "X / Square", "Pitch 3; throw third", 368, IDC_SQUARE, 2);\n',
"X UI",
)
replace_once(
'        create_binding_row(hwnd, "LB / L1", "Relay throw", 424, IDC_L1, 4);\n',
'        create_binding_row(hwnd, "LB / L1", "Fielder switch", 424, IDC_L1, 4);\n',
"LB UI",
)
replace_once(
'        create_binding_row(hwnd, "RB / R1", "Pitch 5; fielder switch; fake rundown throw", 452, IDC_R1, 5);\n',
'        create_binding_row(hwnd, "RB / R1", "Pitch 5", 452, IDC_R1, 5);\n',
"RB UI",
)
replace_once(
'        create_binding_row(hwnd, "View / Back", "Select", 480, IDC_SELECT, 6);\n',
'        create_binding_row(hwnd, "View / Back", "Select; fake rundown throw", 480, IDC_SELECT, 6);\n',
"View UI",
)
replace_once(
'        create_binding_row(hwnd, "L3", "Intentional hit batter", 536, IDC_L3, 8);\n',
'        create_binding_row(hwnd, "L3", "Pitch history; intentional hit batter", 536, IDC_L3, 8);\n',
"L3 UI",
)
replace_once(
'        create_binding_row(hwnd, "R3", "Intentional walk", 564, IDC_R3, 9);\n',
'        create_binding_row(hwnd, "R3", "Bunt; intentional walk", 564, IDC_R3, 9);\n',
"R3 UI",
)
replace_once(
'            "Xbox-style trigger actions: LT opens pitch history / advances all runners; RT retreats all runners. Physical button learning is now verified against MVP itself.",\n',
'            "Xbox-style triggers are calibrated too. LT advances all runners; RT handles relay/cutoff throws and retreats all runners. L3 opens pitch history; R3 bunts.",\n',
"trigger help UI",
)

# Make the calibration button name reflect what it now learns.
text = text.replace('"Calibrate / relearn all buttons..."', '"Calibrate buttons + triggers..."', 1)

# Load saved trigger axes when the configurator opens.
replace_once(
'''        set_all_child_fonts(hwnd);\n        fill_device_combo();\n''',
'''        load_saved_trigger_bindings();\n        set_all_child_fonts(hwnd);\n        fill_device_combo();\n''',
"load triggers on window create",
)

SOURCE.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern controller usability and trigger calibration v14")
