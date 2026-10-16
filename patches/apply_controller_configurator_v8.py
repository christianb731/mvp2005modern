from pathlib import Path
import re

SOURCE = Path("src/controller_config.c")
MAKEFILE = Path("Makefile")
text = SOURCE.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller configurator v8 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


def replace_regex_once(pattern: str, replacement: str, label: str) -> None:
    global text
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"controller configurator v8 {label}: expected exactly one match, found {count}")
    text = updated


# MVP Baseball 2005 imports DirectInputCreateA and uses the legacy DirectInput 7
# path. The v0.5-v0.7 configurator calibrated with DirectInput8 instead. On some
# modern controller stacks those two compatibility paths can expose different
# logical button orderings. Calibrate through the same API family as the game.
replace_once("#define DIRECTINPUT_VERSION 0x0800\n", "#define DIRECTINPUT_VERSION 0x0700\n", "DirectInput version")

replace_once(
'''    hr = DirectInput8Create(GetModuleHandleA(NULL), DIRECTINPUT_VERSION,\n        &IID_IDirectInput8A, (void **)&enum_di, NULL);\n''',
'''    hr = DirectInputCreateA(GetModuleHandleA(NULL), DIRECTINPUT_VERSION,\n        &enum_di, NULL);\n''',
"enumeration DirectInputCreateA",
)
replace_once(
'''    hr = DirectInput8Create(GetModuleHandleA(NULL), DIRECTINPUT_VERSION,\n        &IID_IDirectInput8A, (void **)&di, NULL);\n''',
'''    hr = DirectInputCreateA(GetModuleHandleA(NULL), DIRECTINPUT_VERSION,\n        &di, NULL);\n''',
"capture DirectInputCreateA",
)

# Switch interface types/macros from DirectInput8 to the interface returned by
# DirectInputCreateA. GetDeviceState/Acquire/SetDataFormat are all available here.
for old, new in [
    ("LPDIRECTINPUT8A", "LPDIRECTINPUTA"),
    ("LPDIRECTINPUTDEVICE8A", "LPDIRECTINPUTDEVICEA"),
    ("IDirectInput8_", "IDirectInput_"),
    ("IDirectInputDevice8_", "IDirectInputDevice_"),
]:
    text = text.replace(old, new)

# DirectInputCreateA enumeration uses the legacy joystick device type rather than
# DI8's device-class constant.
replace_once(
'''    IDirectInput_EnumDevices(enum_di, DI8DEVCLASS_GAMECTRL,\n        enum_controller_cb, NULL, DIEDFL_ATTACHEDONLY);\n''',
'''    IDirectInput_EnumDevices(enum_di, DIDEVTYPE_JOYSTICK,\n        enum_controller_cb, NULL, DIEDFL_ATTACHEDONLY);\n''',
"legacy controller enumeration",
)

# Use the classic DIJOYSTATE data format, which is the format-era MVP was written
# against and is sufficient for MVP's 10/12-button controller.cfg layouts.
text = text.replace("DIJOYSTATE2", "DIJOYSTATE")
text = text.replace("c_dfDIJoystick2", "c_dfDIJoystick")
text = text.replace("if (count > 128) count = 128;", "if (count > 32) count = 32;")
text = text.replace("DWORD limit = button_count > 128 ? 128 : button_count;",
                    "DWORD limit = button_count > 32 ? 32 : button_count;")

# IDirectInputDeviceA does not expose the DI8 Poll method. GetDeviceState on an
# acquired nonexclusive device is enough for this short calibration loop.
replace_regex_once(
    r'''static int read_capture_state\(LPDIRECTINPUTDEVICEA device, DIJOYSTATE \*state\)\n\{.*?\n\}\n\n(?=static int any_capture_button_down)''',
    '''static int read_capture_state(LPDIRECTINPUTDEVICEA device, DIJOYSTATE *state)\n{
    HRESULT hr;
    ZeroMemory(state, sizeof(*state));
    hr = IDirectInputDevice_GetDeviceState(device, sizeof(*state), state);
    if (hr == DIERR_INPUTLOST || hr == DIERR_NOTACQUIRED) {
        IDirectInputDevice_Acquire(device);
        hr = IDirectInputDevice_GetDeviceState(device, sizeof(*state), state);
    }
    return SUCCEEDED(hr);
}

''',
    "legacy capture state",
)

# v0.7's zero-based controller.cfg experiment is intentionally NOT part of this
# build. Community/known-good MVP controller.cfg files use one-based button values
# (button 1 through button 10 for the standard Xbox layout), while the underlying
# DirectInput rgbButtons array is zero-based. The v0.6 capture already adds +1.
# Clarify this in the UI instead of exposing the implementation detail.
text = text.replace(
    '"Recommended: press each named button when prompted. The launcher learns what Windows actually calls it, so you do not need to understand DirectInput numbering."',
    '"Recommended: press each named button when prompted. Calibration now uses the same legacy DirectInput path as MVP Baseball 2005, then writes MVP-compatible button numbers automatically."',
    1,
)
text = text.replace('"Learned input"', '"MVP button"', 1)

SOURCE.write_text(text, encoding="utf-8")

# The launcher no longer needs dinput8.lib; link the legacy dinput import library
# so DirectInputCreateA resolves exactly as it does for MVP Baseball 2005.
make = MAKEFILE.read_text(encoding="utf-8")
old = "-ladvapi32 -ldinput8 -ldxguid"
new = "-ladvapi32 -ldinput -ldxguid"
if make.count(old) != 1:
    raise SystemExit(f"controller configurator v8 Makefile dinput link: expected one match, found {make.count(old)}")
MAKEFILE.write_text(make.replace(old, new, 1), encoding="utf-8")

# Hard checks: do not accidentally leave the DI8 calibration path behind.
final = SOURCE.read_text(encoding="utf-8")
for forbidden in ["DirectInput8Create", "LPDIRECTINPUT8A", "LPDIRECTINPUTDEVICE8A", "DIJOYSTATE2", "DI8DEVCLASS_GAMECTRL"]:
    if forbidden in final:
        raise SystemExit("controller configurator v8 still contains " + forbidden)
for required in ["DirectInputCreateA", "DIRECTINPUT_VERSION 0x0700", "c_dfDIJoystick", "return (int)i + 1;"]:
    if required not in final:
        raise SystemExit("controller configurator v8 missing " + required)

print("Applied MVP2005 Modern DirectInput 7-matched controller calibration v8")
