from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
CONTROLLER = Path("src/controller_config.c")
runtime = RUNTIME.read_text(encoding="utf-8")
controller = CONTROLLER.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller canonical xbox v15 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"controller canonical xbox v15 {label}: expected exactly one match, found {count}")
    return updated


# ---------------------------------------------------------------------------
# Controller profile: write one canonical Xbox 360-style logical device.
# ---------------------------------------------------------------------------
# v14 correctly learned the Flydigi trigger's physical DirectInput direction, but
# writing those physical directions straight into controller.cfg means MVP still
# has to understand the modern device's raw axis semantics. Instead keep the
# learned bindings only as *runtime source metadata* and always present MVP with
# the long-established Xbox 360 logical trigger layout: LT=axis-3, RT=axis+3.
controller = replace_once(
    controller,
    '    const char *l2 = generic_layout ? "button 7" : learned_l2_binding;\n'
    '    const char *r2 = generic_layout ? "button 8" : learned_r2_binding;\n',
    '    const char *l2 = generic_layout ? "button 7" : "axis- 3";\n'
    '    const char *r2 = generic_layout ? "button 8" : "axis+ 3";\n',
    "canonical trigger bindings",
)

# Use the complete, historically working MVP Xbox action layout instead of
# inventing new shoulder/trigger semantics. With the v13 runtime button shift and
# the trigger normalization below, these become stable logical controls no matter
# how the physical modern pad exposes itself.
controller = replace_once(
    controller,
    '    write_binding(file, "VPAD_FIELD_FAKE_RUNDOWN_THROW", select);\n',
    '    write_binding(file, "VPAD_FIELD_FAKE_RUNDOWN_THROW", r1);\n',
    "fake rundown on RB",
)
controller = replace_once(
    controller,
    '    write_binding(file, "VPAD_BASERUNNER_ADVANCEALL", l2);\n',
    '    write_binding(file, "VPAD_BASERUNNER_ADVANCEALL", l1);\n',
    "advance all on LB",
)
controller = replace_once(
    controller,
    '    write_binding(file, "VPAD_BASERUNNER_RETREATALL", r2);\n',
    '    write_binding(file, "VPAD_BASERUNNER_RETREATALL", r1);\n',
    "retreat all on RB",
)

# Keep the UI descriptions in sync with the canonical profile.
controller = replace_once(
    controller,
    '        create_binding_row(hwnd, "LB / L1", "Fielder switch", 424, IDC_L1, 4);\n',
    '        create_binding_row(hwnd, "LB / L1", "Fielder switch; advance all runners", 424, IDC_L1, 4);\n',
    "LB UI",
)
controller = replace_once(
    controller,
    '        create_binding_row(hwnd, "RB / R1", "Pitch 5", 452, IDC_R1, 5);\n',
    '        create_binding_row(hwnd, "RB / R1", "Pitch 5; retreat all runners; fake rundown throw", 452, IDC_R1, 5);\n',
    "RB UI",
)
controller = replace_once(
    controller,
    '        create_binding_row(hwnd, "View / Back", "Select; fake rundown throw", 480, IDC_SELECT, 6);\n',
    '        create_binding_row(hwnd, "View / Back", "Select", 480, IDC_SELECT, 6);\n',
    "View UI",
)
controller = replace_once(
    controller,
    '            "Xbox-style triggers are calibrated too. LT advances all runners; RT handles relay/cutoff throws and retreats all runners. L3 opens pitch history; R3 bunts.",\n',
    '            "MVP Modern learns the physical triggers, then presents MVP with a canonical Xbox layout. LB switches fielders / advances runners; RB is pitch 5 / retreat; RT is relay/cutoff; L3 is pitch history; R3 bunts.",\n',
    "canonical help UI",
)

CONTROLLER.write_text(controller, encoding="utf-8")


# ---------------------------------------------------------------------------
# Runtime trigger-axis normalization.
# ---------------------------------------------------------------------------
# The uploaded v14 config established this Flydigi exposes LT as axis+3 and RT as
# axis-3, the opposite direction from the canonical Xbox 360 MVP profile. v13
# already normalizes button indices. Normalize the physical trigger axis in the
# same place so MVP always receives LT on canonical axis-3 and RT on axis+3.
runtime = replace_once(
    runtime,
    'static int controller_remap_enabled;\n'
    'static int controller_button_sources[10] = {0,1,2,3,4,5,6,7,8,9};\n',
    'static int controller_remap_enabled;\n'
    'static int controller_button_sources[10] = {0,1,2,3,4,5,6,7,8,9};\n'
    'static int controller_lt_axis = 2;\n'
    'static int controller_lt_dir = -1;\n'
    'static int controller_rt_axis = 2;\n'
    'static int controller_rt_dir = 1;\n',
    "trigger globals",
)

load_marker = 'static void load_config(void)\n'
if runtime.count(load_marker) != 1:
    raise SystemExit(f"controller canonical xbox v15 load_config marker: found {runtime.count(load_marker)}")
trigger_parser = r'''static int parse_controller_axis_binding(const char *text, int *axis, int *direction)
{
    int parsed_axis;
    if (!text || _strnicmp(text, "axis", 4) != 0) return 0;
    if (text[4] != '+' && text[4] != '-') return 0;
    parsed_axis = atoi(text + 5) - 1;
    if (parsed_axis < 0 || parsed_axis >= 6) return 0;
    if (axis) *axis = parsed_axis;
    if (direction) *direction = text[4] == '-' ? -1 : 1;
    return 1;
}

'''
runtime = runtime.replace(load_marker, trigger_parser + load_marker, 1)

runtime = replace_once(
    runtime,
    '''        for (i = 0; i < 10; i++) {\n            int source = GetPrivateProfileIntA("Controller", keys[i], i, ini);\n            if (source >= 0 && source < 32) controller_button_sources[i] = source;\n        }\n    }\n''',
    '''        for (i = 0; i < 10; i++) {\n            int source = GetPrivateProfileIntA("Controller", keys[i], i, ini);\n            if (source >= 0 && source < 32) controller_button_sources[i] = source;\n        }\n        {\n            char binding[32];\n            if (GetPrivateProfileStringA("Controller", "LTBinding", "axis- 3",\n                    binding, sizeof(binding), ini) > 0)\n                parse_controller_axis_binding(binding, &controller_lt_axis, &controller_lt_dir);\n            if (GetPrivateProfileStringA("Controller", "RTBinding", "axis+ 3",\n                    binding, sizeof(binding), ini) > 0)\n                parse_controller_axis_binding(binding, &controller_rt_axis, &controller_rt_dir);\n        }\n    }\n''',
    "load trigger sources",
)

# Replace the v13 button-only normalizer with a canonical controller state
# normalizer. It preserves both analog sticks and POV, remaps the ten buttons, and
# synthesizes canonical Z/axis-3 trigger state from the calibrated physical axis.
runtime = replace_regex_once(
    runtime,
    r'''static void normalize_controller_buttons\(DWORD data_size, void \*data\)\n\{.*?\n\}\n\nstatic HRESULT WINAPI controller_fake_GetDeviceState''',
    r'''static LONG controller_clamp_axis(LONG value)
{
    if (value < 0) return 0;
    if (value > 65535) return 65535;
    return value;
}

static LONG controller_axis_amount(LONG value, int direction)
{
    const LONG center = 32767;
    LONG delta = direction < 0 ? center - value : value - center;
    return delta > 0 ? delta : 0;
}

static void normalize_controller_buttons(DWORD data_size, void *data)
{
    BYTE original_buttons[32];
    LONG original_axes[6];
    BYTE *bytes = (BYTE *)data;
    LONG *axes = (LONG *)data;
    int i;

    /* Classic DIJOYSTATE is 80 bytes: six primary LONG axes first, rgbButtons
     * begins at byte 48. Keep the physical state before rewriting anything. */
    if (!controller_remap_enabled || !data || data_size != 80) return;
    memcpy(original_axes, axes, sizeof(original_axes));
    memcpy(original_buttons, bytes + 48, sizeof(original_buttons));

    /* MVP's modern-device mismatch is avoided by presenting a stable logical
     * one-based controller: slots 1..10 are A,B,X,Y,LB,RB,View,Start,L3,R3. */
    ZeroMemory(bytes + 48, sizeof(original_buttons));
    for (i = 0; i < 10; i++) {
        int source = controller_button_sources[i];
        if (source >= 0 && source < 32)
            bytes[48 + (i + 1)] = original_buttons[source];
    }

    /* Present a canonical Xbox 360 trigger axis to MVP: LT drives axis-3 and RT
     * drives axis+3. This is deliberately independent from the physical device's
     * sign/direction. When both triggers share one axis (the Flydigi case), this
     * is just a possible inversion. Separate-axis devices are combined around the
     * normal DirectInput center value. */
    if (controller_lt_axis >= 0 && controller_lt_axis < 6 &&
        controller_rt_axis >= 0 && controller_rt_axis < 6) {
        LONG canonical = 32767;
        if (controller_lt_axis == controller_rt_axis &&
            controller_lt_dir == -controller_rt_dir) {
            LONG physical = original_axes[controller_lt_axis];
            canonical = controller_lt_dir < 0 ? physical : 65535 - physical;
        } else {
            LONG lt_amount = controller_axis_amount(original_axes[controller_lt_axis], controller_lt_dir);
            LONG rt_amount = controller_axis_amount(original_axes[controller_rt_axis], controller_rt_dir);
            if (lt_amount > rt_amount)
                canonical = 32767 - (lt_amount > 32767 ? 32767 : lt_amount);
            else if (rt_amount > 0)
                canonical = 32767 + (rt_amount > 32768 ? 32768 : rt_amount);
        }
        axes[2] = controller_clamp_axis(canonical);
    }
}

static HRESULT WINAPI controller_fake_GetDeviceState''',
    "canonical state normalizer",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern canonical Xbox controller state v15")
