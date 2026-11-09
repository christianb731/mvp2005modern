from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller XInput bridge v16 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"controller XInput bridge v16 {label}: expected exactly one match, found {count}")
    return updated


# The controller has been in XInput mode throughout. Stop using the legacy
# DirectInput representation as the source of truth. MVP still calls DirectInput,
# but when a real XInput controller is connected we synthesize the exact classic
# 80-byte DIJOYSTATE layout that MVP's long-established Xbox profile expects.
# If no XInput controller is available, retain v15's calibrated DirectInput
# normalizer as a fallback for generic pads.

runtime = replace_once(
    runtime,
    '''static int controller_rt_dir = 1;\n''',
    '''static int controller_rt_dir = 1;\nstatic LONG controller_xinput_logged;\n''',
    "XInput logging global",
)

marker = '''static LONG controller_clamp_axis(LONG value)\n'''
if runtime.count(marker) != 1:
    raise SystemExit(f"controller XInput bridge v16 helper marker: found {runtime.count(marker)}")

helpers = r'''typedef struct ControllerXInputGamepad {
    WORD wButtons;
    BYTE bLeftTrigger;
    BYTE bRightTrigger;
    SHORT sThumbLX;
    SHORT sThumbLY;
    SHORT sThumbRX;
    SHORT sThumbRY;
} ControllerXInputGamepad;

typedef struct ControllerXInputState {
    DWORD dwPacketNumber;
    ControllerXInputGamepad Gamepad;
} ControllerXInputState;

typedef DWORD (WINAPI *ControllerXInputGetStateFn)(DWORD, ControllerXInputState *);

#define CXINPUT_DPAD_UP        0x0001
#define CXINPUT_DPAD_DOWN      0x0002
#define CXINPUT_DPAD_LEFT      0x0004
#define CXINPUT_DPAD_RIGHT     0x0008
#define CXINPUT_START          0x0010
#define CXINPUT_BACK           0x0020
#define CXINPUT_LEFT_THUMB     0x0040
#define CXINPUT_RIGHT_THUMB    0x0080
#define CXINPUT_LEFT_SHOULDER  0x0100
#define CXINPUT_RIGHT_SHOULDER 0x0200
#define CXINPUT_A              0x1000
#define CXINPUT_B              0x2000
#define CXINPUT_X              0x4000
#define CXINPUT_Y              0x8000

static ControllerXInputGetStateFn controller_load_xinput_get_state(void)
{
    static ControllerXInputGetStateFn fn;
    static LONG tried;
    static const char *dlls[] = {
        "xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"
    };
    int i;
    if (InterlockedCompareExchange(&tried, 1, 0) != 0) return fn;
    for (i = 0; i < (int)(sizeof(dlls) / sizeof(dlls[0])); i++) {
        HMODULE mod = LoadLibraryA(dlls[i]);
        if (mod) {
            FARPROC proc = GetProcAddress(mod, "XInputGetState");
            if (proc) {
                memcpy(&fn, &proc, sizeof(fn));
                break;
            }
        }
    }
    return fn;
}

static LONG controller_xinput_axis_x(SHORT value)
{
    LONG result = 32767 - (LONG)value;
    if (result < 0) result = 0;
    if (result > 65535) result = 65535;
    return result;
}

static LONG controller_xinput_axis_y(SHORT value)
{
    LONG result = 32767 + (LONG)value;
    if (result < 0) result = 0;
    if (result > 65535) result = 65535;
    return result;
}

static DWORD controller_xinput_pov(WORD buttons)
{
    int up = (buttons & CXINPUT_DPAD_UP) != 0;
    int down = (buttons & CXINPUT_DPAD_DOWN) != 0;
    int left = (buttons & CXINPUT_DPAD_LEFT) != 0;
    int right = (buttons & CXINPUT_DPAD_RIGHT) != 0;
    if (up && right) return 4500;
    if (down && right) return 13500;
    if (down && left) return 22500;
    if (up && left) return 31500;
    if (up) return 0;
    if (right) return 9000;
    if (down) return 18000;
    if (left) return 27000;
    return 0xFFFFFFFFu;
}

static int controller_write_xinput_state(DWORD data_size, void *data)
{
    ControllerXInputGetStateFn fn;
    ControllerXInputState state;
    BYTE *bytes;
    LONG *axes;
    DWORD *povs;
    DWORD user;
    WORD b;

    if (!controller_remap_enabled || !data || data_size != 80) return 0;
    fn = controller_load_xinput_get_state();
    if (!fn) return 0;

    ZeroMemory(&state, sizeof(state));
    for (user = 0; user < 4; user++) {
        if (fn(user, &state) == ERROR_SUCCESS) break;
    }
    if (user >= 4) return 0;

    bytes = (BYTE *)data;
    axes = (LONG *)data;
    povs = (DWORD *)(bytes + 32);
    b = state.Gamepad.wButtons;

    ZeroMemory(data, 80);
    axes[0] = controller_xinput_axis_x(state.Gamepad.sThumbLX);
    axes[1] = controller_xinput_axis_y(state.Gamepad.sThumbLY);
    axes[2] = 32767 - ((LONG)state.Gamepad.bLeftTrigger * 128) +
        ((LONG)state.Gamepad.bRightTrigger * 128);
    if (axes[2] < 0) axes[2] = 0;
    if (axes[2] > 65535) axes[2] = 65535;
    axes[3] = controller_xinput_axis_x(state.Gamepad.sThumbRX);
    axes[4] = controller_xinput_axis_y(state.Gamepad.sThumbRY);
    axes[5] = 32767;
    povs[0] = controller_xinput_pov(b);
    povs[1] = povs[2] = povs[3] = 0xFFFFFFFFu;

    /* Deliberately leave rgbButtons[0] unused. The historical MVP Xbox profile
     * uses controller.cfg buttons 1..10, and v13 proved those logical slots make
     * the face buttons and Start behave correctly on this system. */
    bytes[48 + 1]  = (b & CXINPUT_A) ? 0x80 : 0;
    bytes[48 + 2]  = (b & CXINPUT_B) ? 0x80 : 0;
    bytes[48 + 3]  = (b & CXINPUT_X) ? 0x80 : 0;
    bytes[48 + 4]  = (b & CXINPUT_Y) ? 0x80 : 0;
    bytes[48 + 5]  = (b & CXINPUT_LEFT_SHOULDER) ? 0x80 : 0;
    bytes[48 + 6]  = (b & CXINPUT_RIGHT_SHOULDER) ? 0x80 : 0;
    bytes[48 + 7]  = (b & CXINPUT_BACK) ? 0x80 : 0;
    bytes[48 + 8]  = (b & CXINPUT_START) ? 0x80 : 0;
    bytes[48 + 9]  = (b & CXINPUT_LEFT_THUMB) ? 0x80 : 0;
    bytes[48 + 10] = (b & CXINPUT_RIGHT_THUMB) ? 0x80 : 0;

    if (InterlockedCompareExchange(&controller_xinput_logged, 1, 0) == 0)
        log_line("controller source: native XInput -> canonical MVP DIJOYSTATE\n");
    return 1;
}

'''
runtime = runtime.replace(marker, helpers + marker, 1)

# Make XInput the primary source. The existing v15 remap remains unchanged below
# as a fallback only when no XInput controller is connected.
runtime = replace_once(
    runtime,
    '''static void normalize_controller_buttons(DWORD data_size, void *data)\n{\n    BYTE original_buttons[32];\n''',
    '''static void normalize_controller_buttons(DWORD data_size, void *data)\n{\n    BYTE original_buttons[32];\n''',
    "normalizer anchor",
)

runtime = replace_once(
    runtime,
    '''    if (!controller_remap_enabled || !data || data_size != 80) return;\n    memcpy(original_axes, axes, sizeof(original_axes));\n''',
    '''    if (!controller_remap_enabled || !data || data_size != 80) return;\n    if (controller_write_xinput_state(data_size, data)) return;\n    memcpy(original_axes, axes, sizeof(original_axes));\n''',
    "XInput first",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern native XInput controller bridge v16")
