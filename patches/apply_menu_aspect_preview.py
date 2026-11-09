"""Fit the native menu using dgVoodoo's windowed presentation profile."""

from pathlib import Path


def replace_once(source: str, old: str, new: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"Expected one menu aspect patch anchor, found {count}: {old!r}")
    return source.replace(old, new, 1)


launcher = Path("src/launcher.c")
launch_source = launcher.read_text(encoding="utf-8")
launch_source = replace_once(
    launch_source,
    "static HWND aspect_check;",
    "static HWND aspect_check;\nstatic HWND fill_menu_check;",
)
launch_source = replace_once(
    launch_source,
    '    Button_SetCheck(aspect_check,\n        GetPrivateProfileIntA("Aspect", "Enabled", 1, ini) ? BST_CHECKED : BST_UNCHECKED);',
    '''    Button_SetCheck(aspect_check,
        GetPrivateProfileIntA("Aspect", "Enabled", 1, ini) ? BST_CHECKED : BST_UNCHECKED);
    Button_SetCheck(fill_menu_check,
        GetPrivateProfileIntA("MenuScale", "PreserveAspect", 0, ini) ? BST_UNCHECKED : BST_CHECKED);''',
)
launch_source = replace_once(
    launch_source,
    '        WritePrivateProfileStringA("Modern", "SkipIntro", skip_intro ? "1" : "0", ini);',
    '''        if (fill_menu_check &&
            !WritePrivateProfileStringA("MenuScale", "PreserveAspect",
                Button_GetCheck(fill_menu_check) == BST_CHECKED ? "0" : "1", ini)) {
            MessageBoxA(hwnd, "Could not save the menu size setting.", "MVP Baseball 2005 Modern", MB_ICONERROR);
            return 0;
        }
        WritePrivateProfileStringA("Modern", "SkipIntro", skip_intro ? "1" : "0", ini);''',
)
launch_source = replace_once(
    launch_source,
    "        load_runtime_controls();",
    '''        fill_menu_check = CreateWindowA("BUTTON", "Fill screen with menus",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_AUTOCHECKBOX,
            96, 180, 300, 22, hwnd, NULL, NULL, NULL);
        load_runtime_controls();''',
)
for old_position, new_position in (
    ("12, 180, 492, 20", "12, 206, 492, 20"),
    ("96, 206, 108, 26", "96, 232, 108, 26"),
    ("214, 206, 108, 26", "214, 232, 108, 26"),
    ("332, 206, 108, 26", "332, 232, 108, 26"),
    ("12, 246, 492, 20", "12, 272, 492, 20"),
    ("window_rect.bottom = 282;", "window_rect.bottom = 308;"),
):
    launch_source = replace_once(launch_source, old_position, new_position)

launch_source = replace_once(
    launch_source,
    'static int configure_dgvoodoo(const char *game_dir)\n{\n    char conf[MAX_PATH];',
    '''static int configure_dgvoodoo(const char *game_dir)
{
    char conf[MAX_PATH];
    char ini[MAX_PATH];
    char attributes[128];
    int menu_aspect = 0;''',
)
launch_source = replace_once(
    launch_source,
    '    WritePrivateProfileStringA("General", "ScalingMode", "stretched", conf);',
    '''    get_ini_path(ini, sizeof(ini));
    if (GetPrivateProfileIntA("MenuScale", "PreserveAspect", 0, ini)) {
        GetPrivateProfileStringA("GeneralExt", "WindowedAttributes", "",
            attributes, sizeof(attributes), conf);
        menu_aspect = strstr(_strlwr(attributes), "fullscreensize") != NULL;
    }
    WritePrivateProfileStringA("General", "ScalingMode",
        menu_aspect ? "stretched_ar" : "stretched", conf);''',
)
launch_source = replace_once(
    launch_source,
    '    WritePrivateProfileStringA("GeneralExt", "FreeMouse", "false", conf);',
    '''    WritePrivateProfileStringA("GeneralExt", "FreeMouse",
        menu_aspect ? "true" : "false", conf);''',
)

runtime = Path("src/runtime.c")
runtime_source = runtime.read_text(encoding="utf-8")
runtime_source = replace_once(
    runtime_source,
    'static int borderless_enabled;',
    'static int borderless_enabled;\nstatic int menu_aspect_enabled;',
)
runtime_source = replace_once(
    runtime_source,
    '    borderless_enabled = GetPrivateProfileIntA("Borderless", "Enabled", 0, ini) != 0;',
    '''    borderless_enabled = GetPrivateProfileIntA("Borderless", "Enabled", 0, ini) != 0;
    if (borderless_enabled && GetPrivateProfileIntA("MenuScale", "PreserveAspect", 0, ini)) {
        char conf[MAX_PATH];
        char attributes[128];
        char scale_mode[32];
        char free_mouse[16];

        /* The launcher starts MVP with the game directory as its working directory. */
        DWORD length = GetFullPathNameA("dgVoodoo.conf", sizeof(conf), conf, NULL);
        if (length && length < sizeof(conf)) {
            GetPrivateProfileStringA("GeneralExt", "WindowedAttributes", "",
                attributes, sizeof(attributes), conf);
            GetPrivateProfileStringA("General", "ScalingMode", "",
                scale_mode, sizeof(scale_mode), conf);
            GetPrivateProfileStringA("GeneralExt", "FreeMouse", "",
                free_mouse, sizeof(free_mouse), conf);
            menu_aspect_enabled = strstr(_strlwr(attributes), "fullscreensize") &&
                _stricmp(scale_mode, "stretched_ar") == 0 && _stricmp(free_mouse, "true") == 0;
        }
        log_line(menu_aspect_enabled ? "aspect-fit menu mouse mapping enabled\\n" :
            "aspect-fit menu requested but the dgVoodoo profile is unavailable\\n");
    }''',
)
runtime_source = replace_once(
    runtime_source,
    'static void scale_queued_mouse_message(MSG *msg)',
    '''static int map_fitted_mouse_axis(int position, int offset, int extent, int logical_extent)
{
    if (position < offset) return -1;
    if (position >= offset + extent) return logical_extent;
    return menu_scale_clamp_int(MulDiv(position - offset, logical_extent, extent),
        0, logical_extent - 1);
}

static void scale_queued_mouse_message(MSG *msg)''',
)
runtime_source = replace_once(
    runtime_source,
    '    physical_y = (SHORT)HIWORD(msg->lParam);\n    logical_x = MulDiv',
    '''    physical_y = (SHORT)HIWORD(msg->lParam);
    if (menu_aspect_enabled) {
        int width = (int)borderless_logical_width;
        int height = (int)borderless_logical_height;
        int fit_width = client_width;
        int fit_height = client_height;
        int left;
        int top;

        if ((LONGLONG)client_width * height > (LONGLONG)client_height * width)
            fit_width = MulDiv(client_height, width, height);
        else
            fit_height = MulDiv(client_width, height, width);

        if (fit_width > 0 && fit_height > 0) {
            left = (client_width - fit_width) / 2;
            top = (client_height - fit_height) / 2;
            logical_x = map_fitted_mouse_axis(physical_x, left, fit_width, width);
            logical_y = map_fitted_mouse_axis(physical_y, top, fit_height, height);
            origin.x = 0;
            origin.y = 0;
            if (ClientToScreen(borderless_window, &origin)) {
                msg->pt.x = origin.x + map_fitted_mouse_axis(msg->pt.x - origin.x,
                    left, fit_width, width);
                msg->pt.y = origin.y + map_fitted_mouse_axis(msg->pt.y - origin.y,
                    top, fit_height, height);
            }
            msg->lParam = MAKELPARAM((WORD)(SHORT)logical_x, (WORD)(SHORT)logical_y);
            return;
        }
    }
    logical_x = MulDiv''',
)

launcher.write_text(launch_source, encoding="utf-8")
runtime.write_text(runtime_source, encoding="utf-8")
print("Applied MVP2005 Modern aspect-fit menu preview")
