from pathlib import Path

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller live learner v32 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# v32 is deliberately different from the previous controller builds: no more
# compile/test cycles for individual button guesses.  Keep every currently proven
# control untouched and add a live, persistent learner for ONLY the unresolved
# physical controls (LB, LT, RT, Back).  The user can cycle every plausible MVP
# input representation in one running game, lock the first one that performs the
# desired action, and that choice is written to mvp2005fix.ini for future runs.
#
# Ctrl+F1 = learn LB
# Ctrl+F2 = learn LT
# Ctrl+F3 = learn RT
# Ctrl+F4 = learn Back/View
# Press the selected controller control repeatedly; every press advances to the
# next candidate representation.  When the desired in-game action happens,
# Ctrl+Enter locks and persists it. Ctrl+Backspace clears the selected mapping.
#
# Candidate sets contain the directly observed/legacy possibilities: nearby DI
# button slots, both trigger-axis directions, and (for field-switch/relay probes)
# the exact keyboard scancodes already present in the user's controller.cfg.
# This means one binary can finish calibration without another rebuild.

runtime = replace_once(
    runtime,
    'static int controller_diag_face_bank_split = 0;\n',
    '''static int controller_diag_face_bank_split = 0;\n\n'''
    '''enum { CONTROLLER_PROBE_NONE=0, CONTROLLER_PROBE_LB=1, CONTROLLER_PROBE_LT=2, CONTROLLER_PROBE_RT=3, CONTROLLER_PROBE_BACK=4 };\n'''
    '''static int controller_probe_target;\n'''
    '''static int controller_probe_index = -1;\n'''
    '''static int controller_probe_current_code = -1;\n'''
    '''static int controller_probe_saved[5] = {-1,-1,-1,-1,-1};\n'''
    '''static BYTE controller_probe_prev_down[5];\n'''
    '''static BYTE controller_probe_key_down[5];\n'''
    '''static WORD controller_probe_key_scan[5];\n'''
    '''static LONG controller_probe_loaded;\n''',
    "probe globals",
)

# Insert the learner helpers immediately before the existing diagnostic hotkey
# handler so all later controller-state code can call them.
marker = 'static void controller_diag_update_hotkeys(void)\n'
if runtime.count(marker) != 1:
    raise SystemExit(f"controller live learner v32 helper marker: found {runtime.count(marker)}")

helpers = r'''static const char *controller_probe_target_name(int target)
{
    switch (target) {
    case CONTROLLER_PROBE_LB: return "LB";
    case CONTROLLER_PROBE_LT: return "LT";
    case CONTROLLER_PROBE_RT: return "RT";
    case CONTROLLER_PROBE_BACK: return "BACK";
    default: return "NONE";
    }
}

static const int *controller_probe_candidates(int target, int *count)
{
    /* Ordered by evidence from the user's previous runs, then exhaustive nearby
     * slots.  100/101 are axis-/axis+, 200 is keyboard Numpad0 (field switch),
     * 201 is keyboard Backslash (relay/cutoff). */
    static const int field_candidates[] = {
        5,4,6,7,8,9,10,11,12,0,1,2,3,13,14,15,200,100,101
    };
    static const int relay_candidates[] = {
        101,8,7,12,5,6,4,9,10,11,0,1,2,3,13,14,15,201,100
    };
    static const int back_candidates[] = {
        2,7,101,8,12,5,6,4,9,10,11,0,1,3,13,14,15,100
    };
    if (target == CONTROLLER_PROBE_RT) {
        if (count) *count = (int)(sizeof(relay_candidates) / sizeof(relay_candidates[0]));
        return relay_candidates;
    }
    if (target == CONTROLLER_PROBE_BACK) {
        if (count) *count = (int)(sizeof(back_candidates) / sizeof(back_candidates[0]));
        return back_candidates;
    }
    if (count) *count = (int)(sizeof(field_candidates) / sizeof(field_candidates[0]));
    return field_candidates;
}

static void controller_probe_load_saved(void)
{
    char ini[MAX_PATH];
    if (InterlockedCompareExchange(&controller_probe_loaded, 1, 0) != 0) return;
    if (!get_ini_path(ini, sizeof(ini))) return;
    controller_probe_saved[CONTROLLER_PROBE_LB] = GetPrivateProfileIntA("ControllerLearned", "LB", -1, ini);
    controller_probe_saved[CONTROLLER_PROBE_LT] = GetPrivateProfileIntA("ControllerLearned", "LT", -1, ini);
    controller_probe_saved[CONTROLLER_PROBE_RT] = GetPrivateProfileIntA("ControllerLearned", "RT", -1, ini);
    controller_probe_saved[CONTROLLER_PROBE_BACK] = GetPrivateProfileIntA("ControllerLearned", "Back", -1, ini);
    controller_diag_logf("LEARN loaded LB=%d LT=%d RT=%d Back=%d",
        controller_probe_saved[1], controller_probe_saved[2],
        controller_probe_saved[3], controller_probe_saved[4]);
}

static void controller_probe_write_saved(int target, int code)
{
    static const char *keys[5] = {"", "LB", "LT", "RT", "Back"};
    char ini[MAX_PATH];
    char value[32];
    if (target < 1 || target > 4 || !get_ini_path(ini, sizeof(ini))) return;
    wsprintfA(value, "%d", code);
    WritePrivateProfileStringA("ControllerLearned", keys[target], value, ini);
}

static const char *controller_probe_code_name(int code)
{
    if (code >= 0 && code <= 15) return "DI button slot";
    if (code == 100) return "trigger axis -";
    if (code == 101) return "trigger axis +";
    if (code == 200) return "keyboard Numpad0 / FIELD_SWITCH";
    if (code == 201) return "keyboard Backslash / RELAY_CUTOFF";
    return "baseline/no override";
}

static void controller_probe_select(int target)
{
    controller_probe_load_saved();
    controller_probe_target = target;
    controller_probe_index = -1;
    controller_probe_current_code = -1;
    controller_diag_logf("LEARN SELECT %s: press that controller control repeatedly; Ctrl+Enter locks the first correct action",
        controller_probe_target_name(target));
}

static void controller_probe_next(int target)
{
    int count = 0;
    const int *candidates = controller_probe_candidates(target, &count);
    if (!candidates || count <= 0) return;
    controller_probe_index++;
    if (controller_probe_index >= count) controller_probe_index = 0;
    controller_probe_current_code = candidates[controller_probe_index];
    controller_diag_logf("LEARN %s candidate %d/%d code=%d (%s)",
        controller_probe_target_name(target), controller_probe_index + 1, count,
        controller_probe_current_code, controller_probe_code_name(controller_probe_current_code));
}

static void controller_probe_lock(void)
{
    int target = controller_probe_target;
    if (target < 1 || target > 4 || controller_probe_current_code < 0) {
        controller_diag_logf("LEARN LOCK ignored: select F1-F4 and test at least one candidate first");
        return;
    }
    controller_probe_saved[target] = controller_probe_current_code;
    controller_probe_write_saved(target, controller_probe_current_code);
    controller_diag_logf("LEARN LOCKED %s code=%d (%s); persists in mvp2005fix.ini",
        controller_probe_target_name(target), controller_probe_current_code,
        controller_probe_code_name(controller_probe_current_code));
    controller_probe_target = CONTROLLER_PROBE_NONE;
    controller_probe_index = -1;
    controller_probe_current_code = -1;
}

static void controller_probe_clear(void)
{
    int target = controller_probe_target;
    if (target < 1 || target > 4) return;
    controller_probe_saved[target] = -1;
    controller_probe_write_saved(target, -1);
    controller_probe_index = -1;
    controller_probe_current_code = -1;
    controller_diag_logf("LEARN CLEARED %s; baseline behavior restored",
        controller_probe_target_name(target));
}

static void controller_probe_send_scan(int target, WORD scan, int down)
{
    INPUT input;
    if (target < 1 || target > 4) return;
    if (down) {
        if (controller_probe_key_down[target] && controller_probe_key_scan[target] == scan) return;
        if (controller_probe_key_down[target]) {
            ZeroMemory(&input, sizeof(input));
            input.type = INPUT_KEYBOARD;
            input.ki.wScan = controller_probe_key_scan[target];
            input.ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP;
            SendInput(1, &input, sizeof(input));
        }
        ZeroMemory(&input, sizeof(input));
        input.type = INPUT_KEYBOARD;
        input.ki.wScan = scan;
        input.ki.dwFlags = KEYEVENTF_SCANCODE;
        SendInput(1, &input, sizeof(input));
        controller_probe_key_down[target] = 1;
        controller_probe_key_scan[target] = scan;
    } else if (controller_probe_key_down[target]) {
        ZeroMemory(&input, sizeof(input));
        input.type = INPUT_KEYBOARD;
        input.ki.wScan = controller_probe_key_scan[target];
        input.ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP;
        SendInput(1, &input, sizeof(input));
        controller_probe_key_down[target] = 0;
        controller_probe_key_scan[target] = 0;
    }
}

static int controller_probe_effective_code(int target)
{
    controller_probe_load_saved();
    if (controller_probe_target == target && controller_probe_current_code >= 0)
        return controller_probe_current_code;
    if (target >= 1 && target <= 4) return controller_probe_saved[target];
    return -1;
}

static void controller_probe_press_edge(int target, int down)
{
    if (target < 1 || target > 4) return;
    if (controller_probe_target == target && down && !controller_probe_prev_down[target])
        controller_probe_next(target);
    controller_probe_prev_down[target] = (BYTE)(down != 0);
}

static void controller_probe_apply(int target, int code, int down, BYTE *bytes, LONG *axes)
{
    if (!bytes || !axes || target < 1 || target > 4) return;
    if (code >= 0 && code <= 15) {
        controller_probe_send_scan(target, 0, 0);
        if (down) bytes[48 + code] = 0x80;
    } else if (code == 100) {
        controller_probe_send_scan(target, 0, 0);
        if (down) axes[2] = 127;
    } else if (code == 101) {
        controller_probe_send_scan(target, 0, 0);
        if (down) axes[2] = 65407;
    } else if (code == 200) {
        /* DIK_NUMPAD0 / scan code 0x52. The user's own controller.cfg maps this
         * keyboard input to VPAD_FIELD_SWITCH. */
        controller_probe_send_scan(target, 0x52, down);
    } else if (code == 201) {
        /* DIK_BACKSLASH / scan code 0x2B. The user's own controller.cfg maps this
         * keyboard input to both VPAD_FIELD_RELAY_THROW and CUTOFF_THROW. */
        controller_probe_send_scan(target, 0x2B, down);
    } else {
        controller_probe_send_scan(target, 0, 0);
    }
}

'''
runtime = runtime.replace(marker, helpers + marker, 1)

# Replace the obsolete Ctrl+F4 face-bank diagnostic with the four live learner
# selectors, and add lock/clear controls. F5-F10 legacy diagnostics remain intact.
old_hotkeys = '''    if (ctrl) {\n        if (controller_diag_hotkey_edge(22, VK_F4)) {\n            controller_diag_face_bank_split = !controller_diag_face_bank_split;\n            controller_diag_logf("FACE BANK SPLIT -> %d (0=shared slots, 1=frontend high bank/gameplay low bank)",\n                controller_diag_face_bank_split);\n        }\n        static const int fkeys[6] = {VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10};\n'''
new_hotkeys = '''    if (ctrl) {\n        if (controller_diag_hotkey_edge(22, VK_F1)) controller_probe_select(CONTROLLER_PROBE_LB);\n        if (controller_diag_hotkey_edge(23, VK_F2)) controller_probe_select(CONTROLLER_PROBE_LT);\n        if (controller_diag_hotkey_edge(24, VK_F3)) controller_probe_select(CONTROLLER_PROBE_RT);\n        if (controller_diag_hotkey_edge(25, VK_F4)) controller_probe_select(CONTROLLER_PROBE_BACK);\n        if (controller_diag_hotkey_edge(26, VK_RETURN)) controller_probe_lock();\n        if (controller_diag_hotkey_edge(27, VK_BACK)) controller_probe_clear();\n        static const int fkeys[6] = {VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10};\n'''
runtime = replace_once(runtime, old_hotkeys, new_hotkeys, "learner hotkeys")

runtime = replace_once(
    runtime,
    '        for (i = 0; i < 23; i++) controller_diag_hotkey_prev[i] = 0;\n',
    '        for (i = 0; i < 28; i++) controller_diag_hotkey_prev[i] = 0;\n',
    "hotkey reset count",
)

# Capture LB alongside the already-captured RB/Back/trigger state.
runtime = replace_once(
    runtime,
    '''                BYTE rb = bytes[48 + 6];\n                BYTE back = bytes[48 + 7];\n                LONG trigger_axis = ((LONG *)bytes)[2];\n''',
    '''                BYTE lb = bytes[48 + 5];\n                BYTE rb = bytes[48 + 6];\n                BYTE back = bytes[48 + 7];\n                LONG trigger_axis = ((LONG *)bytes)[2];\n''',
    "capture LB",
)

# Layer the learner after v31's stable face/RB/Start mapping. With no learned
# values this is a no-op and v31 behaves exactly as before. During learning (or
# after locking) only the selected physical control is removed from its baseline
# representation and re-emitted through the candidate representation.
old_tail = '''                bytes[48 + 11] = 0;\n                bytes[48 + 12] = (rt_virtual || back) ? 0x80 : 0;\n                ((LONG *)bytes)[2] = 32767;\n'''
new_tail = '''                bytes[48 + 11] = 0;\n                bytes[48 + 12] = (rt_virtual || back) ? 0x80 : 0;\n                ((LONG *)bytes)[2] = 32767;\n\n                {\n                    int lb_down = lb != 0;\n                    int lt_down = lt_virtual != 0;\n                    int rt_down = rt_virtual != 0;\n                    int back_down = back != 0;\n                    int lb_code, lt_code, rt_code, back_code;\n                    LONG *probe_axes = (LONG *)bytes;\n\n                    controller_probe_press_edge(CONTROLLER_PROBE_LB, lb_down);\n                    controller_probe_press_edge(CONTROLLER_PROBE_LT, lt_down);\n                    controller_probe_press_edge(CONTROLLER_PROBE_RT, rt_down);\n                    controller_probe_press_edge(CONTROLLER_PROBE_BACK, back_down);\n\n                    lb_code = controller_probe_effective_code(CONTROLLER_PROBE_LB);\n                    lt_code = controller_probe_effective_code(CONTROLLER_PROBE_LT);\n                    rt_code = controller_probe_effective_code(CONTROLLER_PROBE_RT);\n                    back_code = controller_probe_effective_code(CONTROLLER_PROBE_BACK);\n\n                    if (lb_code >= 0) bytes[48 + 5] = 0;\n                    if (rt_code >= 0) bytes[48 + 12] = 0;\n                    if (back_code >= 0) bytes[48 + 12] = rt_code >= 0 ? 0 : (rt_virtual ? 0x80 : 0);\n\n                    controller_probe_apply(CONTROLLER_PROBE_LB, lb_code, lb_down, bytes, probe_axes);\n                    controller_probe_apply(CONTROLLER_PROBE_LT, lt_code, lt_down, bytes, probe_axes);\n                    controller_probe_apply(CONTROLLER_PROBE_RT, rt_code, rt_down, bytes, probe_axes);\n                    controller_probe_apply(CONTROLLER_PROBE_BACK, back_code, back_down, bytes, probe_axes);\n                }\n'''
runtime = replace_once(runtime, old_tail, new_tail, "apply live learned mappings")

runtime = replace_once(
    runtime,
    'MVP2005 Modern controller diagnostics + native fielding controls v31\\r\\n',
    'MVP2005 Modern controller diagnostics + one-session live learner v32\\r\\n',
    "diagnostic banner",
)

runtime = replace_once(
    runtime,
    'controller hooks requested; stable A0/B1/X3/Y4 RB->7; LB->slot5 native field switch, RT/Back->slot12 native R2 relay/cutoff, LT unused; Start/L3 frozen',
    'controller hooks requested; stable controls frozen; LIVE LEARN: Ctrl+F1 LB, F2 LT, F3 RT, F4 Back; press selected control repeatedly to cycle candidates; Ctrl+Enter lock/persist, Ctrl+Backspace clear; no rebuild required',
    "startup diagnostic text",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern one-session persistent live controller learner v32")
