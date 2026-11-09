from pathlib import Path
import re

SOURCE = Path("src/controller_config.c")
text = SOURCE.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller configurator v6 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


def replace_regex_once(pattern: str, replacement: str, label: str) -> None:
    global text
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"controller configurator v6 {label}: expected exactly one match, found {count}")
    text = updated


# v4/v5 generated an older community action layout. Keep the learned physical
# button IDs, but use the better-established Xbox-style MVP action assignments:
# LB switches fielders/advances runners, RB is pitch 5/retreat, L3 opens pitch
# history, R3 bunts, and the right trigger handles relay/cutoff throws.
replace_once('''    write_binding(file, "VPAD_PITCH_HISTORY_OPEN", l2);\n''',
             '''    write_binding(file, "VPAD_PITCH_HISTORY_OPEN", l3);\n''',
             "pitch history")
replace_once('''    write_binding(file, "VPAD_SWING_BUNT", square);\n''',
             '''    write_binding(file, "VPAD_SWING_BUNT", r3);\n''',
             "bunt")
replace_once('''    write_binding(file, "VPAD_FIELD_SWITCH", r1);\n''',
             '''    write_binding(file, "VPAD_FIELD_SWITCH", l1);\n''',
             "fielder switch")
replace_once('''    write_binding(file, "VPAD_FIELD_RELAY_THROW", l1);\n''',
             '''    write_binding(file, "VPAD_FIELD_RELAY_THROW", r2);\n''',
             "relay throw")
replace_once('''    write_binding(file, "VPAD_FIELD_CUTOFF_THROW", square);\n''',
             '''    write_binding(file, "VPAD_FIELD_CUTOFF_THROW", r2);\n''',
             "cutoff throw")
replace_once('''    write_binding(file, "VPAD_FIELD_FAKE_RUNDOWN_THROW", r1);\n''',
             '''    write_binding(file, "VPAD_FIELD_FAKE_RUNDOWN_THROW", generic_layout ? r1 : select);\n''',
             "fake rundown")
replace_once('''    write_binding(file, "VPAD_BASERUNNER_ADVANCEALL", l2);\n''',
             '''    write_binding(file, "VPAD_BASERUNNER_ADVANCEALL", l1);\n''',
             "advance all")
replace_once('''    write_binding(file, "VPAD_BASERUNNER_RETREATALL", r2);\n''',
             '''    write_binding(file, "VPAD_BASERUNNER_RETREATALL", r1);\n''',
             "retreat all")


# MVP can leave more than one controller profile marked as Player 1. That makes
# it possible for the game to continue using its old auto-generated mapping even
# after MVP2005 Modern writes a new profile. Prefer MVP's existing non-keyboard
# Player 1 profile name when one exists, then demote other gamepad Player 1 blocks
# to player 0 while preserving them for multiplayer/recovery.
marker = '''static void write_binding(FILE *file, const char *name, const char *value)\n'''
if text.count(marker) != 1:
    raise SystemExit(f"controller configurator v6 profile helper marker: expected one match, found {text.count(marker)}")

helpers = r'''static int block_profile_name(const char *start, const char *end, char *out, DWORD out_size)
{
    const char *p;
    const char *line_end;
    size_t len;
    if (!start || !end || start >= end || strncmp(start, "profile=", 8) != 0 || !out_size)
        return 0;
    p = start + 8;
    while (p < end && (*p == ' ' || *p == '\t')) p++;
    line_end = p;
    while (line_end < end && *line_end != '\r' && *line_end != '\n') line_end++;
    len = (size_t)(line_end - p);
    if (!len) return 0;
    if (len >= out_size) len = out_size - 1;
    memcpy(out, p, len);
    out[len] = 0;
    return 1;
}

static int profile_is_keyboard(const char *profile)
{
    return profile && _strnicmp(profile, "Keyboard_Profile_", 17) == 0;
}

static int block_player_value(const char *start, const char *end)
{
    const char *p = start;
    while (p < end) {
        const char *line_end = p;
        while (line_end < end && *line_end != '\r' && *line_end != '\n') line_end++;
        if ((size_t)(line_end - p) >= 7 && _strnicmp(p, "player=", 7) == 0) {
            const char *v = p + 7;
            while (v < line_end && (*v == ' ' || *v == '\t')) v++;
            if (v < line_end && *v >= '0' && *v <= '9') return *v - '0';
        }
        p = line_end;
        while (p < end && (*p == '\r' || *p == '\n')) p++;
    }
    return -1;
}

static int find_existing_player1_controller_profile(const char *data, DWORD size,
    char *profile, DWORD profile_size)
{
    const char *block;
    if (!data || !size) return 0;
    block = find_next_profile(data, data);
    while (block) {
        const char *next = find_next_profile(data, block + 1);
        const char *end = next ? next : data + size;
        char name[MAX_PATH];
        if (block_profile_name(block, end, name, sizeof(name)) &&
            !profile_is_keyboard(name) && block_player_value(block, end) == 1) {
            lstrcpynA(profile, name, profile_size);
            return 1;
        }
        block = next;
    }
    return 0;
}

static void write_profile_block_with_player(FILE *file, const char *start,
    const char *end, int new_player)
{
    const char *p = start;
    int replaced = 0;
    while (p < end) {
        const char *line_end = p;
        const char *after;
        while (line_end < end && *line_end != '\r' && *line_end != '\n') line_end++;
        after = line_end;
        while (after < end && (*after == '\r' || *after == '\n')) after++;
        if (!replaced && (size_t)(line_end - p) >= 7 && _strnicmp(p, "player=", 7) == 0) {
            fprintf(file, "player= %d\r\n", new_player);
            replaced = 1;
        } else {
            fwrite(p, 1, (size_t)(after - p), file);
        }
        p = after;
    }
}

static int block_is_other_player1_controller(const char *start, const char *end,
    const char *selected_profile)
{
    char name[MAX_PATH];
    if (!block_profile_name(start, end, name, sizeof(name))) return 0;
    if (profile_is_keyboard(name)) return 0;
    if (_stricmp(name, selected_profile) == 0) return 0;
    return block_player_value(start, end) == 1;
}

'''
text = text.replace(marker, helpers + marker, 1)

# Determine the profile after reading controller.cfg so we can reuse the exact
# profile name MVP already assigned to Player 1 when available.
replace_once(
'''    normalize_mvp_device_name(controllers[idx].name, profile, sizeof(profile));\n    if (!get_controller_cfg_path(cfg, sizeof(cfg), 1)) {\n        MessageBoxA(hwnd, "Could not locate your Documents\\\\MVP Baseball 2005 folder.",\n            "MVP Baseball 2005 Modern", MB_ICONERROR);\n        return 0;\n    }\n\n    old_data = read_entire_file(cfg, &old_size);\n''',
'''    if (!get_controller_cfg_path(cfg, sizeof(cfg), 1)) {\n        MessageBoxA(hwnd, "Could not locate your Documents\\\\MVP Baseball 2005 folder.",\n            "MVP Baseball 2005 Modern", MB_ICONERROR);\n        return 0;\n    }\n\n    old_data = read_entire_file(cfg, &old_size);\n    if (!find_existing_player1_controller_profile(old_data, old_size, profile, sizeof(profile)))\n        normalize_mvp_device_name(controllers[idx].name, profile, sizeof(profile));\n''',
"reuse active MVP profile name",
)

replace_once(
'''            if (!profile_block_matches(block, end, profile))\n                fwrite(block, 1, (size_t)(end - block), file);\n''',
'''            if (profile_block_matches(block, end, profile)) {\n                /* Replaced by the freshly generated selected profile above. */\n            } else if (block_is_other_player1_controller(block, end, profile)) {\n                write_profile_block_with_player(file, block, end, 0);\n            } else {\n                fwrite(block, 1, (size_t)(end - block), file);\n            }\n''',
"deactivate conflicting player1 profiles",
)

replace_once(
'''    controller_status("Saved controller.cfg. Existing config was preserved and the selected controller profile was replaced/added.");\n''',
'''    controller_status("Saved controller.cfg. This controller is now MVP Player 1; other gamepad Player 1 profiles were left intact but deactivated.");\n''',
"save status",
)

# Replace the cramped five-column numeric grid with readable rows. The learned
# numeric value is still editable, but each row tells the user what that physical
# control will actually do in MVP.
replace_regex_once(
    r'''static void create_label_and_edit\(HWND hwnd, const char \*label, int x, int y, int edit_id, int edit_index\)\n\{.*?\n\}\n''',
    r'''static void create_binding_row(HWND hwnd, const char *label, const char *usage,
    int y, int edit_id, int edit_index)
{
    CreateWindowA("STATIC", label, WS_CHILD | WS_VISIBLE,
        16, y + 3, 100, 20, hwnd, NULL, NULL, NULL);
    CreateWindowA("STATIC", "Button", WS_CHILD | WS_VISIBLE,
        124, y + 3, 42, 20, hwnd, NULL, NULL, NULL);
    edits[edit_index] = CreateWindowA("EDIT", "", WS_CHILD | WS_VISIBLE | WS_BORDER | ES_NUMBER,
        168, y, 50, 22, hwnd, (HMENU)(INT_PTR)edit_id, NULL, NULL);
    CreateWindowA("STATIC", usage, WS_CHILD | WS_VISIBLE,
        236, y + 3, 438, 20, hwnd, NULL, NULL, NULL);
}
''',
    "readable binding row",
)

replace_regex_once(
    r'''    case WM_CREATE:\n.*?        return 0;\n\n    case WM_COMMAND:''',
    r'''    case WM_CREATE:
        CreateWindowA("STATIC", "1. Choose your controller", WS_CHILD | WS_VISIBLE,
            16, 12, 660, 20, hwnd, NULL, NULL, NULL);
        device_combo = CreateWindowA("COMBOBOX", "", WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST | WS_VSCROLL,
            16, 34, 566, 240, hwnd, (HMENU)IDC_DEVICE, NULL, NULL);
        CreateWindowA("BUTTON", "Refresh", WS_CHILD | WS_VISIBLE,
            592, 33, 82, 24, hwnd, (HMENU)IDC_REFRESH_CONTROLLERS, NULL, NULL);
        profile_text = CreateWindowA("STATIC", "", WS_CHILD | WS_VISIBLE | SS_LEFT,
            16, 64, 658, 20, hwnd, (HMENU)IDC_PROFILE, NULL, NULL);
        caps_text = CreateWindowA("STATIC", "", WS_CHILD | WS_VISIBLE | SS_LEFT,
            16, 86, 658, 34, hwnd, (HMENU)IDC_CAPS, NULL, NULL);

        CreateWindowA("STATIC", "2. Controller type", WS_CHILD | WS_VISIBLE,
            16, 126, 660, 20, hwnd, NULL, NULL, NULL);
        layout_combo = CreateWindowA("COMBOBOX", "", WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST | WS_VSCROLL,
            16, 148, 658, 160, hwnd, (HMENU)IDC_LAYOUT, NULL, NULL);
        SendMessageA(layout_combo, CB_ADDSTRING, 0, (LPARAM)"Xbox-style controller (combined trigger axis / 5 axes)");
        SendMessageA(layout_combo, CB_ADDSTRING, 0, (LPARAM)"Generic DirectInput controller (12 buttons / 4 axes)");
        SendMessageA(layout_combo, CB_SETCURSEL, 0, 0);

        CreateWindowA("STATIC", "3. Learn the physical buttons", WS_CHILD | WS_VISIBLE,
            16, 184, 660, 20, hwnd, NULL, NULL, NULL);
        CreateWindowA("STATIC",
            "Recommended: press each named button when prompted. The launcher learns what Windows actually calls it, so you do not need to understand DirectInput numbering.",
            WS_CHILD | WS_VISIBLE, 16, 206, 658, 34, hwnd, NULL, NULL, NULL);
        CreateWindowA("BUTTON", "Calibrate / relearn all buttons...", WS_CHILD | WS_VISIBLE | BS_DEFPUSHBUTTON,
            16, 244, 250, 30, hwnd, (HMENU)IDC_CALIBRATE_BUTTONS, NULL, NULL);

        CreateWindowA("STATIC", "Physical control", WS_CHILD | WS_VISIBLE,
            16, 288, 100, 20, hwnd, NULL, NULL, NULL);
        CreateWindowA("STATIC", "Learned input", WS_CHILD | WS_VISIBLE,
            124, 288, 94, 20, hwnd, NULL, NULL, NULL);
        CreateWindowA("STATIC", "Main MVP Baseball 2005 uses", WS_CHILD | WS_VISIBLE,
            236, 288, 438, 20, hwnd, NULL, NULL, NULL);

        create_binding_row(hwnd, "A / Cross", "Confirm; normal swing; pitch 1; throw home", 312, IDC_CROSS, 0);
        create_binding_row(hwnd, "B / Circle", "Back; pitch 2; throw first", 340, IDC_CIRCLE, 1);
        create_binding_row(hwnd, "X / Square", "Pitch 3; throw third", 368, IDC_SQUARE, 2);
        create_binding_row(hwnd, "Y / Triangle", "Pitch 4; throw second; charge mound", 396, IDC_TRIANGLE, 3);
        create_binding_row(hwnd, "LB / L1", "Fielder switch; advance all runners", 424, IDC_L1, 4);
        create_binding_row(hwnd, "RB / R1", "Pitch 5; retreat all runners", 452, IDC_R1, 5);
        create_binding_row(hwnd, "View / Back", "Select; fake rundown throw (Xbox layout)", 480, IDC_SELECT, 6);
        create_binding_row(hwnd, "Menu / Start", "Pause / menu", 508, IDC_START, 7);
        create_binding_row(hwnd, "L3", "Pitch history; intentional hit batter", 536, IDC_L3, 8);
        create_binding_row(hwnd, "R3", "Bunt; intentional walk", 564, IDC_R3, 9);

        CreateWindowA("STATIC",
            "If the physical buttons above are learned correctly but MVP performs different actions, Save to MVP again. v0.6 also makes this the active Player 1 gamepad profile so an older auto-generated mapping cannot remain selected.",
            WS_CHILD | WS_VISIBLE, 16, 598, 658, 44, hwnd, NULL, NULL, NULL);
        CreateWindowA("BUTTON", "Save to MVP", WS_CHILD | WS_VISIBLE,
            16, 648, 116, 28, hwnd, (HMENU)IDC_SAVE_CONTROLLER, NULL, NULL);
        CreateWindowA("BUTTON", "Open controller.cfg", WS_CHILD | WS_VISIBLE,
            142, 648, 136, 28, hwnd, (HMENU)IDC_OPEN_CFG, NULL, NULL);
        CreateWindowA("BUTTON", "Close", WS_CHILD | WS_VISIBLE,
            594, 648, 80, 28, hwnd, (HMENU)IDC_CLOSE_CONTROLLER, NULL, NULL);
        cfg_status = CreateWindowA("STATIC", "Recommended: Calibrate, review the plain-language actions above, then Save to MVP.",
            WS_CHILD | WS_VISIBLE, 16, 684, 658, 34, hwnd, (HMENU)IDC_STATUS_CONTROLLER, NULL, NULL);

        set_all_child_fonts(hwnd);
        fill_device_combo();
        apply_layout_preset(0);
        update_selected_device_info();
        return 0;

    case WM_COMMAND:''',
    "clear controller UI",
)

replace_once(
'''    RECT rect = {0, 0, 510, 515};\n''',
'''    RECT rect = {0, 0, 700, 730};\n''',
"larger readable controller window",
)

# Update calibration wording to match the corrected action layout.
text = text.replace(
    '"X / Square (bunt, pitch 3, throw third)"',
    '"X / Square (pitch 3, throw third)"',
    1,
)
text = text.replace(
    '"LB / L1 (relay / shoulder action)"',
    '"LB / L1 (fielder switch, advance all runners)"',
    1,
)
text = text.replace(
    '"RB / R1 (fielder switch / pitch 5)"',
    '"RB / R1 (pitch 5, retreat all runners)"',
    1,
)
text = text.replace(
    '"Left Stick Click / L3"',
    '"Left Stick Click / L3 (pitch history)"',
    1,
)
text = text.replace(
    '"Right Stick Click / R3"',
    '"Right Stick Click / R3 (bunt)"',
    1,
)

SOURCE.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern controller action/profile/UI fixes v6")
