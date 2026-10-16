from pathlib import Path
import re

SOURCE = Path("src/controller_config.c")
text = SOURCE.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller configurator v5 {label}: expected one match, found {count}")
    text = text.replace(old, new, 1)


def replace_regex_once(pattern: str, replacement: str, label: str) -> None:
    global text
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"controller configurator v5 {label}: expected one match, found {count}")
    text = updated


replace_once(
'''#define IDC_R3 2129\n''',
'''#define IDC_R3 2129\n#define IDC_CALIBRATE_BUTTONS 2130\n#define IDC_REFRESH_CONTROLLERS 2131\n''',
"control ids",
)

# Capture the user's actual DirectInput button order instead of assuming every
# modern Xbox-compatible device exposes A/B/X/Y/Start in the same sequence.
# MVP controller.cfg is one-based, whereas DIJOYSTATE2.rgbButtons is zero-based.
marker = '''static void apply_layout_preset(int preset)\n'''
if text.count(marker) != 1:
    raise SystemExit(f"controller configurator v5 calibration marker: expected one match, found {text.count(marker)}")

helpers = r'''static int read_capture_state(LPDIRECTINPUTDEVICE8A device, DIJOYSTATE2 *state)
{
    HRESULT hr;
    ZeroMemory(state, sizeof(*state));
    hr = IDirectInputDevice8_Poll(device);
    if (FAILED(hr)) {
        IDirectInputDevice8_Acquire(device);
        hr = IDirectInputDevice8_Poll(device);
    }
    hr = IDirectInputDevice8_GetDeviceState(device, sizeof(*state), state);
    if (hr == DIERR_INPUTLOST || hr == DIERR_NOTACQUIRED) {
        IDirectInputDevice8_Acquire(device);
        hr = IDirectInputDevice8_GetDeviceState(device, sizeof(*state), state);
    }
    return SUCCEEDED(hr);
}

static int any_capture_button_down(const DIJOYSTATE2 *state, DWORD count)
{
    DWORD i;
    if (count > 128) count = 128;
    for (i = 0; i < count; i++)
        if (state->rgbButtons[i] & 0x80) return 1;
    return 0;
}

static int calibration_cancel_requested(void)
{
    MSG msg;
    if (GetAsyncKeyState(VK_ESCAPE) & 0x8000) return 1;
    while (PeekMessageA(&msg, NULL, 0, 0, PM_REMOVE)) {
        if (msg.message == WM_QUIT) return 1;
        TranslateMessage(&msg);
        DispatchMessageA(&msg);
    }
    return (GetAsyncKeyState(VK_ESCAPE) & 0x8000) != 0;
}

static int wait_for_all_buttons_released(LPDIRECTINPUTDEVICE8A device, DWORD button_count,
    DWORD timeout_ms)
{
    DWORD start = GetTickCount();
    DIJOYSTATE2 state;
    while (GetTickCount() - start < timeout_ms) {
        if (calibration_cancel_requested()) return 0;
        if (read_capture_state(device, &state) && !any_capture_button_down(&state, button_count))
            return 1;
        Sleep(15);
    }
    return 0;
}

static int capture_physical_button(LPDIRECTINPUTDEVICE8A device, DWORD button_count,
    const char *friendly_name, int step, int total)
{
    char status[384];
    DWORD start;
    DIJOYSTATE2 state;
    DWORD i;

    snprintf(status, sizeof(status),
        "Step %d of %d: press %s. Release the button after it is detected. Press Esc to cancel.",
        step, total, friendly_name);
    controller_status(status);
    if (cfg_status) UpdateWindow(cfg_status);

    if (!wait_for_all_buttons_released(device, button_count, 5000)) return -1;
    start = GetTickCount();
    while (GetTickCount() - start < 30000) {
        if (calibration_cancel_requested()) return -1;
        if (read_capture_state(device, &state)) {
            DWORD limit = button_count > 128 ? 128 : button_count;
            for (i = 0; i < limit; i++) {
                if (state.rgbButtons[i] & 0x80) {
                    MessageBeep(MB_OK);
                    wait_for_all_buttons_released(device, button_count, 5000);
                    return (int)i + 1;
                }
            }
        }
        Sleep(15);
    }
    return -1;
}

static int open_selected_capture_device(HWND hwnd, LPDIRECTINPUT8A *di_out,
    LPDIRECTINPUTDEVICE8A *device_out)
{
    int idx = (int)SendMessageA(device_combo, CB_GETCURSEL, 0, 0);
    LPDIRECTINPUT8A di = NULL;
    LPDIRECTINPUTDEVICE8A device = NULL;
    HRESULT hr;

    *di_out = NULL;
    *device_out = NULL;
    if (idx < 0 || idx >= controller_count) return 0;

    hr = DirectInput8Create(GetModuleHandleA(NULL), DIRECTINPUT_VERSION,
        &IID_IDirectInput8A, (void **)&di, NULL);
    if (FAILED(hr) || !di) goto failed;
    hr = IDirectInput8_CreateDevice(di, &controllers[idx].guid, &device, NULL);
    if (FAILED(hr) || !device) goto failed;
    hr = IDirectInputDevice8_SetDataFormat(device, &c_dfDIJoystick2);
    if (FAILED(hr)) goto failed;
    hr = IDirectInputDevice8_SetCooperativeLevel(device, hwnd,
        DISCL_NONEXCLUSIVE | DISCL_BACKGROUND);
    if (FAILED(hr)) goto failed;
    IDirectInputDevice8_Acquire(device);

    *di_out = di;
    *device_out = device;
    return 1;

failed:
    if (device) IDirectInputDevice8_Release(device);
    if (di) IDirectInput8_Release(di);
    return 0;
}

static void calibrate_physical_buttons(HWND hwnd)
{
    static const char *friendly_names[10] = {
        "A / Cross (confirm, normal swing, pitch 1, throw home)",
        "B / Circle (back, pitch 2, throw first)",
        "X / Square (bunt, pitch 3, throw third)",
        "Y / Triangle (pitch 4, throw second)",
        "LB / L1 (relay / shoulder action)",
        "RB / R1 (fielder switch / pitch 5)",
        "View / Back / Select",
        "Menu / Start (pause/menu)",
        "Left Stick Click / L3",
        "Right Stick Click / R3"
    };
    LPDIRECTINPUT8A di = NULL;
    LPDIRECTINPUTDEVICE8A device = NULL;
    int values[10];
    int idx;
    int i;
    DWORD buttons;

    idx = (int)SendMessageA(device_combo, CB_GETCURSEL, 0, 0);
    if (idx < 0 || idx >= controller_count) {
        MessageBoxA(hwnd, "Select a connected controller first.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return;
    }
    buttons = controllers[idx].buttons;
    if (!buttons) {
        MessageBoxA(hwnd, "The selected DirectInput device reports no buttons.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return;
    }

    if (MessageBoxA(hwnd,
        "Recommended setup:\n\n"
        "The launcher will ask you to press the physical A, B, X, Y, shoulder, menu, and stick-click buttons one at a time. This learns the controller's real DirectInput numbering instead of guessing it.\n\n"
        "Keep this window focused. Release each button after pressing it. Press Esc at any time to cancel.\n\n"
        "Start calibration?",
        "MVP Baseball 2005 Modern - Controller Calibration",
        MB_ICONINFORMATION | MB_OKCANCEL) != IDOK) return;

    if (!open_selected_capture_device(hwnd, &di, &device)) {
        MessageBoxA(hwnd,
            "Could not open the selected controller for live button detection. Close other controller tools and try again.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return;
    }

    EnableWindow(device_combo, FALSE);
    EnableWindow(layout_combo, FALSE);
    for (i = 0; i < 10; i++) {
        values[i] = capture_physical_button(device, buttons, friendly_names[i], i + 1, 10);
        if (values[i] < 1) {
            controller_status("Calibration cancelled or timed out. Existing assignments were left unchanged.");
            EnableWindow(device_combo, TRUE);
            EnableWindow(layout_combo, TRUE);
            IDirectInputDevice8_Unacquire(device);
            IDirectInputDevice8_Release(device);
            IDirectInput8_Release(di);
            return;
        }
    }

    for (i = 0; i < 10; i++) set_edit_number(edits[i], values[i]);
    EnableWindow(device_combo, TRUE);
    EnableWindow(layout_combo, TRUE);
    IDirectInputDevice8_Unacquire(device);
    IDirectInputDevice8_Release(device);
    IDirectInput8_Release(di);
    controller_status("Calibration complete. The fields now match the buttons you actually pressed. Click Save to MVP to install this mapping.");
}

'''
text = text.replace(marker, helpers + marker, 1)

# Keep the historic community Xbox 360 mapping as a fallback preset, but stop
# presenting it as guaranteed for every current Xbox/Steam/Bluetooth stack.
text = text.replace(
    '"Xbox / XInput-style (10 buttons, trigger axis, 5 axes)"',
    '"Legacy Xbox 360 preset (quick start; button order can vary)"',
    1,
)
text = text.replace(
    '"Generic 12-button / 4-axis DirectInput pad"',
    '"Generic DirectInput preset (quick start)"',
    1,
)

# Replace the number-centric UI with a calibration-first UI. Numeric IDs remain
# visible as an Advanced reference because controller.cfg itself stores them, but
# users no longer need to know or guess those values.
replace_regex_once(
    r'''    case WM_CREATE:\n.*?        return 0;\n\n    case WM_COMMAND:''',
    r'''    case WM_CREATE:
        CreateWindowA("STATIC", "1. Choose the controller you want MVP Baseball 2005 to use", WS_CHILD | WS_VISIBLE,
            12, 12, 470, 20, hwnd, NULL, NULL, NULL);
        device_combo = CreateWindowA("COMBOBOX", "", WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST | WS_VSCROLL,
            12, 34, 390, 240, hwnd, (HMENU)IDC_DEVICE, NULL, NULL);
        CreateWindowA("BUTTON", "Refresh", WS_CHILD | WS_VISIBLE,
            410, 33, 76, 24, hwnd, (HMENU)IDC_REFRESH_CONTROLLERS, NULL, NULL);
        profile_text = CreateWindowA("STATIC", "", WS_CHILD | WS_VISIBLE | SS_LEFT,
            12, 62, 474, 20, hwnd, (HMENU)IDC_PROFILE, NULL, NULL);
        caps_text = CreateWindowA("STATIC", "", WS_CHILD | WS_VISIBLE | SS_LEFT,
            12, 84, 474, 34, hwnd, (HMENU)IDC_CAPS, NULL, NULL);

        CreateWindowA("STATIC", "2. Choose how the sticks/triggers are represented", WS_CHILD | WS_VISIBLE,
            12, 124, 470, 20, hwnd, NULL, NULL, NULL);
        layout_combo = CreateWindowA("COMBOBOX", "", WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST | WS_VSCROLL,
            12, 146, 474, 160, hwnd, (HMENU)IDC_LAYOUT, NULL, NULL);
        SendMessageA(layout_combo, CB_ADDSTRING, 0, (LPARAM)"Legacy Xbox 360 preset (quick start; button order can vary)");
        SendMessageA(layout_combo, CB_ADDSTRING, 0, (LPARAM)"Generic DirectInput preset (quick start)");
        SendMessageA(layout_combo, CB_SETCURSEL, 0, 0);

        CreateWindowA("STATIC", "3. Recommended: let the launcher learn your physical buttons", WS_CHILD | WS_VISIBLE,
            12, 178, 470, 20, hwnd, NULL, NULL, NULL);
        CreateWindowA("STATIC",
            "This avoids guessing DirectInput button numbers. You will simply press A, B, X, Y, LB, RB, View/Back, Menu/Start, L3 and R3 when prompted.",
            WS_CHILD | WS_VISIBLE, 12, 200, 474, 36, hwnd, NULL, NULL, NULL);
        CreateWindowA("BUTTON", "Calibrate by pressing buttons...", WS_CHILD | WS_VISIBLE | BS_DEFPUSHBUTTON,
            12, 240, 218, 30, hwnd, (HMENU)IDC_CALIBRATE_BUTTONS, NULL, NULL);

        CreateWindowA("STATIC", "Advanced / learned DirectInput IDs", WS_CHILD | WS_VISIBLE,
            12, 280, 220, 20, hwnd, NULL, NULL, NULL);
        CreateWindowA("STATIC", "Normally you do not need to edit these. They show what MVP will store in controller.cfg.",
            WS_CHILD | WS_VISIBLE, 232, 280, 254, 32, hwnd, NULL, NULL, NULL);
        create_label_and_edit(hwnd, "A", 12, 314, IDC_CROSS, 0);
        create_label_and_edit(hwnd, "B", 106, 314, IDC_CIRCLE, 1);
        create_label_and_edit(hwnd, "X", 200, 314, IDC_SQUARE, 2);
        create_label_and_edit(hwnd, "Y", 294, 314, IDC_TRIANGLE, 3);
        create_label_and_edit(hwnd, "LB", 388, 314, IDC_L1, 4);
        create_label_and_edit(hwnd, "RB", 12, 344, IDC_R1, 5);
        create_label_and_edit(hwnd, "View", 106, 344, IDC_SELECT, 6);
        create_label_and_edit(hwnd, "Menu", 200, 344, IDC_START, 7);
        create_label_and_edit(hwnd, "L3", 294, 344, IDC_L3, 8);
        create_label_and_edit(hwnd, "R3", 388, 344, IDC_R3, 9);

        CreateWindowA("STATIC",
            "MVP actions generated from these controls include pitches, swings, base throws, fielder switch, baserunning, pause/menu and stick clicks.",
            WS_CHILD | WS_VISIBLE, 12, 380, 474, 34, hwnd, NULL, NULL, NULL);
        CreateWindowA("BUTTON", "Save to MVP", WS_CHILD | WS_VISIBLE,
            12, 420, 106, 28, hwnd, (HMENU)IDC_SAVE_CONTROLLER, NULL, NULL);
        CreateWindowA("BUTTON", "Open controller.cfg", WS_CHILD | WS_VISIBLE,
            128, 420, 126, 28, hwnd, (HMENU)IDC_OPEN_CFG, NULL, NULL);
        CreateWindowA("BUTTON", "Close", WS_CHILD | WS_VISIBLE,
            406, 420, 80, 28, hwnd, (HMENU)IDC_CLOSE_CONTROLLER, NULL, NULL);
        cfg_status = CreateWindowA("STATIC", "Recommended: Calibrate by pressing buttons, then Save to MVP.",
            WS_CHILD | WS_VISIBLE, 12, 458, 474, 42, hwnd, (HMENU)IDC_STATUS_CONTROLLER, NULL, NULL);

        set_all_child_fonts(hwnd);
        fill_device_combo();
        apply_layout_preset(0);
        update_selected_device_info();
        return 0;

    case WM_COMMAND:''',
    "calibration-first UI",
)

replace_once(
'''        case IDC_DEVICE:\n            if (HIWORD(wparam) == CBN_SELCHANGE) update_selected_device_info();\n            return 0;\n''',
'''        case IDC_DEVICE:\n            if (HIWORD(wparam) == CBN_SELCHANGE) {\n                update_selected_device_info();\n                controller_status("Controller changed. Use Calibrate by pressing buttons for the safest mapping.");\n            }\n            return 0;\n        case IDC_REFRESH_CONTROLLERS:\n            fill_device_combo();\n            update_selected_device_info();\n            controller_status(controller_count ?\n                "Controller list refreshed. Use Calibrate by pressing buttons for the safest mapping." :\n                "No DirectInput controller detected. Connect one and click Refresh.");\n            return 0;\n        case IDC_CALIBRATE_BUTTONS:\n            calibrate_physical_buttons(hwnd);\n            return 0;\n''',
"calibration commands",
)

# The configurator now needs more room for plain-language guidance.
replace_once(
'''    RECT rect = {0, 0, 500, 390};\n''',
'''    RECT rect = {0, 0, 510, 515};\n''',
"larger controller window",
)

# Clarify why the fallback values can differ. The values themselves intentionally
# stay at the widely used legacy Xbox 360 mapping; calibration overrides them.
replace_once(
'''        /* Xbox 360 / modern XInput DirectInput exposure. */\n''',
'''        /* Widely used legacy Xbox 360 controller.cfg mapping. Modern Bluetooth,\n         * Steam Input and vendor layers can expose a different DirectInput order,\n         * so the UI recommends live calibration instead of assuming this is exact. */\n''',
"preset comment",
)

SOURCE.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern press-to-bind controller configurator v5")
