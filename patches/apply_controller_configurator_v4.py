from pathlib import Path
import re

LAUNCHER = Path("src/launcher.c")
MAKEFILE = Path("Makefile")
HEADER = Path("src/controller_config.h")
SOURCE = Path("src/controller_config.c")

launcher = LAUNCHER.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global launcher
    count = launcher.count(old)
    if count != 1:
        raise SystemExit(f"controller configurator v4 {label}: expected one match, found {count}")
    launcher = launcher.replace(old, new, 1)


def replace_regex_once(pattern: str, new: str, label: str) -> None:
    global launcher
    updated, count = re.subn(pattern, lambda _m: new, launcher, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"controller configurator v4 {label}: expected one match, found {count}")
    launcher = updated


HEADER.write_text(r'''#ifndef MVP2005MODERN_CONTROLLER_CONFIG_H
#define MVP2005MODERN_CONTROLLER_CONFIG_H

#include <windows.h>

void show_controller_configurator(HWND owner);

#endif
''', encoding="utf-8")

SOURCE.write_text(r'''#define DIRECTINPUT_VERSION 0x0800
#include <windows.h>
#include <windowsx.h>
#include <dinput.h>
#include <shlobj.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "controller_config.h"

#define IDC_DEVICE 2101
#define IDC_LAYOUT 2102
#define IDC_SAVE_CONTROLLER 2103
#define IDC_OPEN_CFG 2104
#define IDC_CLOSE_CONTROLLER 2105
#define IDC_STATUS_CONTROLLER 2106
#define IDC_PROFILE 2107
#define IDC_CAPS 2108
#define IDC_CROSS 2120
#define IDC_CIRCLE 2121
#define IDC_SQUARE 2122
#define IDC_TRIANGLE 2123
#define IDC_L1 2124
#define IDC_R1 2125
#define IDC_SELECT 2126
#define IDC_START 2127
#define IDC_L3 2128
#define IDC_R3 2129

#define MAX_CONTROLLERS 16

typedef struct ControllerInfo {
    GUID guid;
    char name[MAX_PATH];
    DWORD buttons;
    DWORD axes;
    DWORD povs;
} ControllerInfo;

typedef struct ButtonMap {
    int cross;
    int circle;
    int square;
    int triangle;
    int l1;
    int r1;
    int select;
    int start;
    int l3;
    int r3;
} ButtonMap;

static ControllerInfo controllers[MAX_CONTROLLERS];
static int controller_count;
static LPDIRECTINPUT8A enum_di;
static HWND device_combo;
static HWND layout_combo;
static HWND profile_text;
static HWND caps_text;
static HWND cfg_status;
static HWND edits[10];
static HWND controller_window;
static HWND controller_owner;

static void set_all_child_fonts(HWND hwnd)
{
    HWND child;
    HFONT font = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    for (child = GetWindow(hwnd, GW_CHILD); child; child = GetWindow(child, GW_HWNDNEXT))
        SendMessageA(child, WM_SETFONT, (WPARAM)font, TRUE);
}

static void controller_status(const char *text)
{
    if (cfg_status) SetWindowTextA(cfg_status, text);
}

static void normalize_mvp_device_name(const char *input, char *output, DWORD output_size)
{
    DWORD pos = 0;
    if (!output_size) return;
    while (*input && pos + 1 < output_size) {
        unsigned char ch = (unsigned char)*input++;
        if (ch == ' ' || ch == '\t') ch = '_';
        output[pos++] = (char)ch;
    }
    output[pos] = 0;
}

static BOOL CALLBACK enum_controller_cb(const DIDEVICEINSTANCEA *instance, VOID *context)
{
    LPDIRECTINPUTDEVICE8A device = NULL;
    DIDEVCAPS caps;
    ControllerInfo *info;
    (void)context;

    if (controller_count >= MAX_CONTROLLERS) return DIENUM_STOP;
    info = &controllers[controller_count];
    ZeroMemory(info, sizeof(*info));
    info->guid = instance->guidInstance;
    lstrcpynA(info->name, instance->tszProductName, sizeof(info->name));

    ZeroMemory(&caps, sizeof(caps));
    caps.dwSize = sizeof(caps);
    if (SUCCEEDED(IDirectInput8_CreateDevice(enum_di, &instance->guidInstance, &device, NULL))) {
        if (SUCCEEDED(IDirectInputDevice8_GetCapabilities(device, &caps))) {
            info->buttons = caps.dwButtons;
            info->axes = caps.dwAxes;
            info->povs = caps.dwPOVs;
        }
        IDirectInputDevice8_Release(device);
    }
    controller_count++;
    return DIENUM_CONTINUE;
}

static void enumerate_controllers(void)
{
    HRESULT hr;
    controller_count = 0;
    ZeroMemory(controllers, sizeof(controllers));
    if (enum_di) {
        IDirectInput8_Release(enum_di);
        enum_di = NULL;
    }

    hr = DirectInput8Create(GetModuleHandleA(NULL), DIRECTINPUT_VERSION,
        &IID_IDirectInput8A, (void **)&enum_di, NULL);
    if (FAILED(hr) || !enum_di) return;
    IDirectInput8_EnumDevices(enum_di, DI8DEVCLASS_GAMECTRL,
        enum_controller_cb, NULL, DIEDFL_ATTACHEDONLY);
    IDirectInput8_Release(enum_di);
    enum_di = NULL;
}

static void fill_device_combo(void)
{
    int i;
    SendMessageA(device_combo, CB_RESETCONTENT, 0, 0);
    enumerate_controllers();
    for (i = 0; i < controller_count; i++)
        SendMessageA(device_combo, CB_ADDSTRING, 0, (LPARAM)controllers[i].name);
    if (controller_count > 0) SendMessageA(device_combo, CB_SETCURSEL, 0, 0);
}

static void set_edit_number(HWND edit, int value)
{
    char text[16];
    wsprintfA(text, "%d", value);
    SetWindowTextA(edit, text);
}

static int read_edit_number(HWND edit, int min_value, int max_value)
{
    char text[16];
    char *end;
    long value;
    GetWindowTextA(edit, text, sizeof(text));
    value = strtol(text, &end, 10);
    if (!text[0] || *end || value < min_value || value > max_value) return -1;
    return (int)value;
}

static void apply_layout_preset(int preset)
{
    ButtonMap map;
    if (preset == 1) {
        /* Common 12-button DirectInput layout used by older PC pads. */
        map.cross = 2;
        map.circle = 3;
        map.square = 1;
        map.triangle = 4;
        map.l1 = 5;
        map.r1 = 6;
        map.select = 9;
        map.start = 10;
        map.l3 = 11;
        map.r3 = 12;
    } else {
        /* Xbox 360 / modern XInput DirectInput exposure. */
        map.cross = 1;
        map.circle = 2;
        map.square = 3;
        map.triangle = 4;
        map.l1 = 5;
        map.r1 = 6;
        map.select = 7;
        map.start = 8;
        map.l3 = 9;
        map.r3 = 10;
    }
    set_edit_number(edits[0], map.cross);
    set_edit_number(edits[1], map.circle);
    set_edit_number(edits[2], map.square);
    set_edit_number(edits[3], map.triangle);
    set_edit_number(edits[4], map.l1);
    set_edit_number(edits[5], map.r1);
    set_edit_number(edits[6], map.select);
    set_edit_number(edits[7], map.start);
    set_edit_number(edits[8], map.l3);
    set_edit_number(edits[9], map.r3);
}

static void update_selected_device_info(void)
{
    int idx = (int)SendMessageA(device_combo, CB_GETCURSEL, 0, 0);
    char profile[MAX_PATH];
    char caps[192];
    if (idx < 0 || idx >= controller_count) {
        SetWindowTextA(profile_text, "No DirectInput controller detected");
        SetWindowTextA(caps_text, "Connect a controller, close this window, and open Controller Setup again.");
        return;
    }
    normalize_mvp_device_name(controllers[idx].name, profile, sizeof(profile));
    SetWindowTextA(profile_text, profile);
    wsprintfA(caps, "%lu buttons, %lu axes, %lu POV hats. MVP profile name is derived from this DirectInput device name.",
        (unsigned long)controllers[idx].buttons,
        (unsigned long)controllers[idx].axes,
        (unsigned long)controllers[idx].povs);
    SetWindowTextA(caps_text, caps);
}

static int get_controller_cfg_path(char *path, DWORD path_size, int create_dir)
{
    char docs[MAX_PATH];
    char dir[MAX_PATH];
    if (FAILED(SHGetFolderPathA(NULL, CSIDL_PERSONAL | (create_dir ? CSIDL_FLAG_CREATE : 0),
            NULL, SHGFP_TYPE_CURRENT, docs))) return 0;
    snprintf(dir, sizeof(dir), "%s\\MVP Baseball 2005", docs);
    if (create_dir && !CreateDirectoryA(dir, NULL) && GetLastError() != ERROR_ALREADY_EXISTS)
        return 0;
    snprintf(path, path_size, "%s\\controller.cfg", dir);
    return 1;
}

static char *read_entire_file(const char *path, DWORD *size_out)
{
    HANDLE file;
    DWORD size;
    DWORD read;
    char *buffer;
    *size_out = 0;
    file = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return NULL;
    size = GetFileSize(file, NULL);
    if (size == INVALID_FILE_SIZE || size > 1024 * 1024) {
        CloseHandle(file);
        return NULL;
    }
    buffer = (char *)malloc(size + 1);
    if (!buffer) {
        CloseHandle(file);
        return NULL;
    }
    if (!ReadFile(file, buffer, size, &read, NULL) || read != size) {
        free(buffer);
        CloseHandle(file);
        return NULL;
    }
    CloseHandle(file);
    buffer[size] = 0;
    *size_out = size;
    return buffer;
}

static int line_starts_profile(const char *base, const char *p)
{
    if (p != base && p[-1] != '\n' && p[-1] != '\r') return 0;
    return strncmp(p, "profile=", 8) == 0;
}

static const char *find_next_profile(const char *base, const char *start)
{
    const char *p;
    for (p = start; *p; p++) {
        if (*p == 'p' && line_starts_profile(base, p)) return p;
    }
    return NULL;
}

static int profile_block_matches(const char *start, const char *end, const char *profile)
{
    const char *p = start + 8;
    const char *line_end;
    size_t len;
    while (p < end && (*p == ' ' || *p == '\t')) p++;
    line_end = p;
    while (line_end < end && *line_end != '\r' && *line_end != '\n') line_end++;
    len = (size_t)(line_end - p);
    return strlen(profile) == len && _strnicmp(p, profile, len) == 0;
}

static void write_binding(FILE *file, const char *name, const char *value)
{
    fprintf(file, "%s= %s\r\n", name, value);
}

static void button_value(char *out, DWORD out_size, int button)
{
    snprintf(out, out_size, "button %d", button);
}

static int write_controller_profile(FILE *file, const char *profile, const ButtonMap *m,
    int generic_layout, DWORD buttons, DWORD axes, DWORD povs)
{
    char cross[32], circle[32], square[32], triangle[32];
    char l1[32], r1[32], select[32], start[32], l3[32], r3[32];
    const char *l2 = generic_layout ? "button 7" : "axis- 3";
    const char *r2 = generic_layout ? "button 8" : "axis+ 3";
    const char *right_right = generic_layout ? "axis- 3" : "axis- 4";
    const char *right_left = generic_layout ? "axis+ 3" : "axis+ 4";
    const char *right_up = generic_layout ? "axis+ 4" : "axis+ 5";
    const char *right_down = generic_layout ? "axis- 4" : "axis- 5";

    button_value(cross, sizeof(cross), m->cross);
    button_value(circle, sizeof(circle), m->circle);
    button_value(square, sizeof(square), m->square);
    button_value(triangle, sizeof(triangle), m->triangle);
    button_value(l1, sizeof(l1), m->l1);
    button_value(r1, sizeof(r1), m->r1);
    button_value(select, sizeof(select), m->select);
    button_value(start, sizeof(start), m->start);
    button_value(l3, sizeof(l3), m->l3);
    button_value(r3, sizeof(r3), m->r3);

    fprintf(file, "profile= %s\r\ndevice= %s\r\nplayer= 1\r\n", profile, profile);
    fprintf(file, "number_of_buttons= %lu\r\nnumber_of_povs= %lu\r\nnumber_of_axis= %lu\r\n",
        (unsigned long)(buttons ? buttons : (generic_layout ? 12 : 10)),
        (unsigned long)(povs ? povs : 1),
        (unsigned long)(axes ? axes : (generic_layout ? 4 : 5)));

    write_binding(file, "VPAD_VIRTUAL_BUTTON_START", start);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_SELECT", select);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_CROSS", cross);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_CIRCLE", circle);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_SQUARE", square);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_TRIANGLE", triangle);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_L1", l1);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_R1", r1);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_L2", l2);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_R2", r2);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_L3", l3);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_R3", r3);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_DPAD_UP", "pov0 1");
    write_binding(file, "VPAD_VIRTUAL_BUTTON_DPAD_DOWN", "pov180 1");
    write_binding(file, "VPAD_VIRTUAL_BUTTON_DPAD_LEFT", "pov270 1");
    write_binding(file, "VPAD_VIRTUAL_BUTTON_DPAD_RIGHT", "pov90 1");
    write_binding(file, "VPAD_VIRTUAL_BUTTON_L_STICK_RIGHT", "axis- 1");
    write_binding(file, "VPAD_VIRTUAL_BUTTON_L_STICK_LEFT", "axis+ 1");
    write_binding(file, "VPAD_VIRTUAL_BUTTON_L_STICK_UP", "axis+ 2");
    write_binding(file, "VPAD_VIRTUAL_BUTTON_L_STICK_DOWN", "axis- 2");
    write_binding(file, "VPAD_VIRTUAL_BUTTON_R_STICK_RIGHT", right_right);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_R_STICK_LEFT", right_left);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_R_STICK_UP", right_up);
    write_binding(file, "VPAD_VIRTUAL_BUTTON_R_STICK_DOWN", right_down);

    write_binding(file, "VPAD_PITCH_1", cross);
    write_binding(file, "VPAD_PITCH_2", circle);
    write_binding(file, "VPAD_PITCH_3", square);
    write_binding(file, "VPAD_PITCH_4", triangle);
    write_binding(file, "VPAD_PITCH_5", r1);
    write_binding(file, "VPAD_FIELD_PICK_OFF_THROW_FIRST", circle);
    write_binding(file, "VPAD_FIELD_PICK_OFF_THROW_SECOND", triangle);
    write_binding(file, "VPAD_FIELD_PICK_OFF_THROW_THIRD", square);
    write_binding(file, "VPAD_PITCH_OUT", cross);
    write_binding(file, "VPAD_THROW_BALL", "not_assigned -1");
    write_binding(file, "VPAD_INTENTIONAL_WALK", r3);
    write_binding(file, "VPAD_INTENTIONAL_HITBATTER", l3);
    write_binding(file, "VPAD_PITCH_HISTORY_OPEN", l2);
    write_binding(file, "VPAD_SWING_NORMAL", cross);
    write_binding(file, "VPAD_SWING_BUNT", square);
    write_binding(file, "VPAD_CHARGE_MOUND", triangle);
    write_binding(file, "VPAD_FIELD_THROW_FIRST", circle);
    write_binding(file, "VPAD_FIELD_THROW_SECOND", triangle);
    write_binding(file, "VPAD_FIELD_THROW_THIRD", square);
    write_binding(file, "VPAD_FIELD_THROW_HOME", cross);
    write_binding(file, "VPAD_FIELD_SWITCH", r1);
    write_binding(file, "VPAD_FIELD_RELAY_THROW", l1);
    write_binding(file, "VPAD_FIELD_CUTOFF_THROW", square);
    write_binding(file, "VPAD_FIELD_FAKE_RUNDOWN_THROW", r1);
    write_binding(file, "VPAD_RUNNER_FIRST_SELECT", circle);
    write_binding(file, "VPAD_RUNNER_SECOND_SELECT", triangle);
    write_binding(file, "VPAD_RUNNER_THIRD_SELECT", square);
    write_binding(file, "VPAD_RUNNER_RUNFIRST", "pov90 1");
    write_binding(file, "VPAD_RUNNER_RUNSECOND", "pov0 1");
    write_binding(file, "VPAD_RUNNER_RUNTHIRD", "pov270 1");
    write_binding(file, "VPAD_RUNNER_RUNHOME2SCORE", "pov180 1");
    write_binding(file, "VPAD_BASERUNNER_ADVANCEALL", l2);
    write_binding(file, "VPAD_BASERUNNER_RETREATALL", r2);
    fprintf(file, "\r\n");
    return 1;
}

static int save_controller_cfg(HWND hwnd)
{
    int idx = (int)SendMessageA(device_combo, CB_GETCURSEL, 0, 0);
    int preset = (int)SendMessageA(layout_combo, CB_GETCURSEL, 0, 0);
    ButtonMap map;
    char profile[MAX_PATH];
    char cfg[MAX_PATH];
    char backup[MAX_PATH];
    char *old_data = NULL;
    DWORD old_size = 0;
    FILE *file;
    const char *first;
    const char *block;

    if (idx < 0 || idx >= controller_count) {
        MessageBoxA(hwnd, "No connected DirectInput controller is selected.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return 0;
    }
    if (preset < 0) preset = 0;

    map.cross = read_edit_number(edits[0], 1, 64);
    map.circle = read_edit_number(edits[1], 1, 64);
    map.square = read_edit_number(edits[2], 1, 64);
    map.triangle = read_edit_number(edits[3], 1, 64);
    map.l1 = read_edit_number(edits[4], 1, 64);
    map.r1 = read_edit_number(edits[5], 1, 64);
    map.select = read_edit_number(edits[6], 1, 64);
    map.start = read_edit_number(edits[7], 1, 64);
    map.l3 = read_edit_number(edits[8], 1, 64);
    map.r3 = read_edit_number(edits[9], 1, 64);
    if (map.cross < 0 || map.circle < 0 || map.square < 0 || map.triangle < 0 ||
        map.l1 < 0 || map.r1 < 0 || map.select < 0 || map.start < 0 ||
        map.l3 < 0 || map.r3 < 0) {
        MessageBoxA(hwnd, "Button assignments must be numbers from 1 to 64.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return 0;
    }

    normalize_mvp_device_name(controllers[idx].name, profile, sizeof(profile));
    if (!get_controller_cfg_path(cfg, sizeof(cfg), 1)) {
        MessageBoxA(hwnd, "Could not locate your Documents\\MVP Baseball 2005 folder.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return 0;
    }

    old_data = read_entire_file(cfg, &old_size);
    if (old_data) {
        snprintf(backup, sizeof(backup), "%s.mvp2005modern.bak", cfg);
        if (GetFileAttributesA(backup) == INVALID_FILE_ATTRIBUTES)
            CopyFileA(cfg, backup, TRUE);
    }

    file = fopen(cfg, "wb");
    if (!file) {
        free(old_data);
        MessageBoxA(hwnd, "Could not write controller.cfg. Close MVP Baseball 2005 and try again.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return 0;
    }

    write_controller_profile(file, profile, &map, preset == 1,
        controllers[idx].buttons, controllers[idx].axes, controllers[idx].povs);

    if (old_data) {
        first = find_next_profile(old_data, old_data);
        if (first && first > old_data) fwrite(old_data, 1, (size_t)(first - old_data), file);
        block = first;
        while (block) {
            const char *next = find_next_profile(old_data, block + 1);
            const char *end = next ? next : old_data + old_size;
            if (!profile_block_matches(block, end, profile))
                fwrite(block, 1, (size_t)(end - block), file);
            block = next;
        }
        free(old_data);
    }

    fclose(file);
    controller_status("Saved controller.cfg. Existing config was preserved and the selected controller profile was replaced/added.");
    return 1;
}

static void open_controller_cfg(HWND hwnd)
{
    char cfg[MAX_PATH];
    if (!get_controller_cfg_path(cfg, sizeof(cfg), 0) ||
        GetFileAttributesA(cfg) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxA(hwnd, "controller.cfg does not exist yet. Save a controller profile first.",
            "MVP Baseball 2005 Modern", MB_ICONINFORMATION);
        return;
    }
    ShellExecuteA(hwnd, "open", cfg, NULL, NULL, SW_SHOWNORMAL);
}

static void create_label_and_edit(HWND hwnd, const char *label, int x, int y, int edit_id, int edit_index)
{
    CreateWindowA("STATIC", label, WS_CHILD | WS_VISIBLE, x, y + 3, 62, 20, hwnd, NULL, NULL, NULL);
    edits[edit_index] = CreateWindowA("EDIT", "", WS_CHILD | WS_VISIBLE | WS_BORDER | ES_NUMBER,
        x + 64, y, 42, 22, hwnd, (HMENU)(INT_PTR)edit_id, NULL, NULL);
}

static LRESULT CALLBACK controller_proc(HWND hwnd, UINT msg, WPARAM wparam, LPARAM lparam)
{
    (void)lparam;
    switch (msg) {
    case WM_CREATE:
        CreateWindowA("STATIC", "Detected controller", WS_CHILD | WS_VISIBLE,
            12, 14, 106, 20, hwnd, NULL, NULL, NULL);
        device_combo = CreateWindowA("COMBOBOX", "", WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST | WS_VSCROLL,
            122, 10, 356, 240, hwnd, (HMENU)IDC_DEVICE, NULL, NULL);
        CreateWindowA("STATIC", "MVP profile", WS_CHILD | WS_VISIBLE,
            12, 44, 106, 20, hwnd, NULL, NULL, NULL);
        profile_text = CreateWindowA("STATIC", "", WS_CHILD | WS_VISIBLE | SS_LEFT,
            122, 44, 356, 20, hwnd, (HMENU)IDC_PROFILE, NULL, NULL);
        caps_text = CreateWindowA("STATIC", "", WS_CHILD | WS_VISIBLE | SS_LEFT,
            12, 70, 466, 34, hwnd, (HMENU)IDC_CAPS, NULL, NULL);

        CreateWindowA("STATIC", "Controller layout", WS_CHILD | WS_VISIBLE,
            12, 112, 106, 20, hwnd, NULL, NULL, NULL);
        layout_combo = CreateWindowA("COMBOBOX", "", WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST | WS_VSCROLL,
            122, 108, 356, 160, hwnd, (HMENU)IDC_LAYOUT, NULL, NULL);
        SendMessageA(layout_combo, CB_ADDSTRING, 0, (LPARAM)"Xbox / XInput-style (10 buttons, trigger axis, 5 axes)");
        SendMessageA(layout_combo, CB_ADDSTRING, 0, (LPARAM)"Generic 12-button / 4-axis DirectInput pad");
        SendMessageA(layout_combo, CB_SETCURSEL, 0, 0);

        CreateWindowA("STATIC", "Button numbers (1-based)", WS_CHILD | WS_VISIBLE,
            12, 142, 180, 20, hwnd, NULL, NULL, NULL);
        create_label_and_edit(hwnd, "A/Cross", 12, 166, IDC_CROSS, 0);
        create_label_and_edit(hwnd, "B/Circle", 132, 166, IDC_CIRCLE, 1);
        create_label_and_edit(hwnd, "X/Square", 252, 166, IDC_SQUARE, 2);
        create_label_and_edit(hwnd, "Y/Tri", 372, 166, IDC_TRIANGLE, 3);
        create_label_and_edit(hwnd, "LB/L1", 12, 196, IDC_L1, 4);
        create_label_and_edit(hwnd, "RB/R1", 132, 196, IDC_R1, 5);
        create_label_and_edit(hwnd, "Back", 252, 196, IDC_SELECT, 6);
        create_label_and_edit(hwnd, "Start", 372, 196, IDC_START, 7);
        create_label_and_edit(hwnd, "L3", 12, 226, IDC_L3, 8);
        create_label_and_edit(hwnd, "R3", 132, 226, IDC_R3, 9);

        CreateWindowA("STATIC",
            "Stick axes, D-pad and trigger representation follow the selected layout. The gameplay actions are generated from these logical buttons.",
            WS_CHILD | WS_VISIBLE, 12, 258, 466, 34, hwnd, NULL, NULL, NULL);
        CreateWindowA("BUTTON", "Save to MVP", WS_CHILD | WS_VISIBLE,
            122, 300, 106, 28, hwnd, (HMENU)IDC_SAVE_CONTROLLER, NULL, NULL);
        CreateWindowA("BUTTON", "Open controller.cfg", WS_CHILD | WS_VISIBLE,
            238, 300, 126, 28, hwnd, (HMENU)IDC_OPEN_CFG, NULL, NULL);
        CreateWindowA("BUTTON", "Close", WS_CHILD | WS_VISIBLE,
            374, 300, 80, 28, hwnd, (HMENU)IDC_CLOSE_CONTROLLER, NULL, NULL);
        cfg_status = CreateWindowA("STATIC", "Choose your controller and layout, then Save to MVP.",
            WS_CHILD | WS_VISIBLE, 12, 340, 466, 36, hwnd, (HMENU)IDC_STATUS_CONTROLLER, NULL, NULL);

        set_all_child_fonts(hwnd);
        fill_device_combo();
        apply_layout_preset(0);
        update_selected_device_info();
        return 0;

    case WM_COMMAND:
        switch (LOWORD(wparam)) {
        case IDC_DEVICE:
            if (HIWORD(wparam) == CBN_SELCHANGE) update_selected_device_info();
            return 0;
        case IDC_LAYOUT:
            if (HIWORD(wparam) == CBN_SELCHANGE) {
                int preset = (int)SendMessageA(layout_combo, CB_GETCURSEL, 0, 0);
                apply_layout_preset(preset);
            }
            return 0;
        case IDC_SAVE_CONTROLLER:
            save_controller_cfg(hwnd);
            return 0;
        case IDC_OPEN_CFG:
            open_controller_cfg(hwnd);
            return 0;
        case IDC_CLOSE_CONTROLLER:
            DestroyWindow(hwnd);
            return 0;
        }
        break;

    case WM_CLOSE:
        DestroyWindow(hwnd);
        return 0;
    case WM_DESTROY:
        controller_window = NULL;
        if (controller_owner) EnableWindow(controller_owner, TRUE);
        if (controller_owner) SetForegroundWindow(controller_owner);
        return 0;
    }
    return DefWindowProcA(hwnd, msg, wparam, lparam);
}

void show_controller_configurator(HWND owner)
{
    static int class_registered;
    WNDCLASSA wc;
    MSG msg;
    RECT rect = {0, 0, 500, 390};
    int x;
    int y;

    if (controller_window) {
        SetForegroundWindow(controller_window);
        return;
    }
    if (!class_registered) {
        ZeroMemory(&wc, sizeof(wc));
        wc.lpfnWndProc = controller_proc;
        wc.hInstance = GetModuleHandleA(NULL);
        wc.hCursor = LoadCursor(NULL, IDC_ARROW);
        wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
        wc.lpszClassName = "MVP2005ModernControllerConfig";
        if (!RegisterClassA(&wc) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS) {
            MessageBoxA(owner, "Could not register the controller configuration window.",
                "MVP Baseball 2005 Modern", MB_ICONERROR);
            return;
        }
        class_registered = 1;
    }

    AdjustWindowRect(&rect, WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU, FALSE);
    x = (GetSystemMetrics(SM_CXSCREEN) - (rect.right - rect.left)) / 2;
    y = (GetSystemMetrics(SM_CYSCREEN) - (rect.bottom - rect.top)) / 2;
    controller_owner = owner;
    if (owner) EnableWindow(owner, FALSE);
    controller_window = CreateWindowA("MVP2005ModernControllerConfig",
        "MVP Baseball 2005 Modern - Controller Setup",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU,
        x, y, rect.right - rect.left, rect.bottom - rect.top,
        owner, NULL, GetModuleHandleA(NULL), NULL);
    if (!controller_window) {
        if (owner) EnableWindow(owner, TRUE);
        return;
    }
    ShowWindow(controller_window, SW_SHOW);
    UpdateWindow(controller_window);

    while (IsWindow(controller_window) && GetMessageA(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageA(&msg);
    }
}
''', encoding="utf-8")

# Add the configurator to the launcher itself.
replace_once(
    '#include "injection.h"\n',
    '#include "injection.h"\n#include "controller_config.h"\n',
    "controller include",
)
replace_once(
    '#define ID_SETUP_REPAIR 1013\n',
    '#define ID_SETUP_REPAIR 1013\n#define ID_CONTROLLER_CONFIG 1014\n',
    "controller control id",
)

# The intro experiment is intentionally taken back out of the visible UI for now.
# Its setting is forced off whenever normal launcher settings are saved. This keeps
# v0.4 focused on the verified runtime plus controller setup.
replace_regex_once(
    r'''        skip_intro_check = CreateWindowA\("BUTTON", "Skip EA Sports / MVP intro videos \(safe runtime method\)",.*?Button_SetCheck\(skip_intro_check, BST_UNCHECKED\);\n        load_runtime_controls\(\);''',
    '''        skip_intro_check = NULL;\n        load_runtime_controls();''',
    "remove experimental intro checkbox",
)
replace_once(
    '    skip_intro = skip_intro_check && Button_GetCheck(skip_intro_check) == BST_CHECKED;\n',
    '    skip_intro = 0;\n',
    "disable experimental intro setting",
)

# Add Controller Setup on the main launcher and move the compatibility caption down
# slightly so the existing v0.3 layout stays uncluttered.
replace_once(
    '''        CreateWindowA("STATIC", "Compatibility setup is automatic: SafeDiscShim + dgVoodoo2 2.87.5 + RC1 runtime",\n            WS_CHILD | WS_VISIBLE, 12, 154, 492, 20, hwnd, NULL, NULL, NULL);\n        CreateWindowA("BUTTON", "Setup / Repair", WS_CHILD | WS_VISIBLE, 96, 180, 108, 26, hwnd, (HMENU)ID_SETUP_REPAIR, NULL, NULL);\n''',
    '''        CreateWindowA("BUTTON", "Controller Setup...", WS_CHILD | WS_VISIBLE, 96, 124, 140, 26, hwnd, (HMENU)ID_CONTROLLER_CONFIG, NULL, NULL);\n        CreateWindowA("STATIC", "Compatibility setup is automatic: SafeDiscShim + dgVoodoo2 2.87.5 + RC1 runtime",\n            WS_CHILD | WS_VISIBLE, 12, 154, 492, 20, hwnd, NULL, NULL, NULL);\n        CreateWindowA("BUTTON", "Setup / Repair", WS_CHILD | WS_VISIBLE, 96, 180, 108, 26, hwnd, (HMENU)ID_SETUP_REPAIR, NULL, NULL);\n''',
    "main controller button",
)
replace_once(
    '''        case ID_SETUP_REPAIR:\n            do_setup_repair(hwnd);\n            return 0;\n''',
    '''        case ID_CONTROLLER_CONFIG:\n            show_controller_configurator(hwnd);\n            return 0;\n        case ID_SETUP_REPAIR:\n            do_setup_repair(hwnd);\n            return 0;\n''',
    "controller command",
)

LAUNCHER.write_text(launcher, encoding="utf-8")

make = MAKEFILE.read_text(encoding="utf-8")
old = '-mwindows -o release/mvp2005fix.exe src/launcher.c src/injection.c -lcomdlg32 -lurlmon -lshell32 -ladvapi32'
new = '-mwindows -o release/mvp2005fix.exe src/launcher.c src/controller_config.c src/injection.c -lcomdlg32 -lurlmon -lshell32 -ladvapi32 -ldinput8 -ldxguid'
if make.count(old) != 1:
    raise SystemExit(f"controller configurator v4 Makefile link line: expected one match, found {make.count(old)}")
MAKEFILE.write_text(make.replace(old, new, 1), encoding="utf-8")

print("Applied MVP2005 Modern integrated controller configurator v4")
