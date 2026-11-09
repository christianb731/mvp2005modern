from pathlib import Path

LAUNCHER = Path("src/launcher.c")
text = LAUNCHER.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"modern launcher {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# Add persistent UI loading plus the MVP2005 Modern compatibility configuration
# immediately after the upstream runtime settings writer. We deliberately touch
# only the dgVoodoo keys proven necessary for the final RC1 setup and preserve
# every other user/wrapper setting already present in dgVoodoo.conf.
marker = '''static void do_browse(HWND hwnd)\n'''
if text.count(marker) != 1:
    raise SystemExit(f"modern launcher helper marker: expected exactly one match, found {text.count(marker)}")

helpers = r'''static void load_runtime_controls(void)
{
    char ini[MAX_PATH];
    char value[32];
    DWORD width;
    DWORD height;
    int custom_idx = custom_resolution_index();
    int selected_idx = -1;
    int i;

    get_ini_path(ini, sizeof(ini));
    width = GetPrivateProfileIntA("Resolution", "Width", 0, ini);
    height = GetPrivateProfileIntA("Resolution", "Height", 0, ini);
    if (width >= 640 && height >= 480) {
        selected_idx = custom_idx;
        for (i = 0; i < custom_idx; i++) {
            if (resolutions[i].width == width && resolutions[i].height == height) {
                selected_idx = i;
                break;
            }
        }
        SendMessageA(res_combo, CB_SETCURSEL, selected_idx, 0);
        if (selected_idx == custom_idx) {
            wsprintfA(value, "%lu", (unsigned long)width);
            SetWindowTextA(custom_width_edit, value);
            wsprintfA(value, "%lu", (unsigned long)height);
            SetWindowTextA(custom_height_edit, value);
        }
        update_custom_resolution_controls();
    }

    Button_SetCheck(aspect_check,
        GetPrivateProfileIntA("Aspect", "Enabled", 1, ini) ? BST_CHECKED : BST_UNCHECKED);
    Button_SetCheck(save_check,
        GetPrivateProfileIntA("SaveFix", "Enabled", 1, ini) ? BST_CHECKED : BST_UNCHECKED);
}

static int configure_dgvoodoo(const char *game_dir)
{
    char conf[MAX_PATH];

    join_path(conf, sizeof(conf), game_dir, "dgVoodoo.conf");
    if (!file_exists(conf)) return 0;

    /* Final validated true-borderless settings. Leave every unrelated
     * dgVoodoo option exactly as the user already has it. */
    WritePrivateProfileStringA("General", "FullScreenMode", "false", conf);
    WritePrivateProfileStringA("DirectX", "AppControlledScreenMode", "false", conf);
    WritePrivateProfileStringA("DirectX", "DisableAltEnterToToggleScreenMode", "true", conf);
    return 1;
}

static void configure_modern_runtime(const char *game_dir)
{
    char ini[MAX_PATH];

    get_ini_path(ini, sizeof(ini));
    WritePrivateProfileStringA("Borderless", "Enabled", "1", ini);
    configure_dgvoodoo(game_dir);
}

static int compatibility_stack_present(const char *game_dir)
{
    char path[MAX_PATH];

    join_path(path, sizeof(path), game_dir, "dgVoodoo.conf");
    if (!file_exists(path)) return 0;
    join_path(path, sizeof(path), game_dir, "D3D8.dll");
    if (!file_exists(path)) return 0;
    join_path(path, sizeof(path), game_dir, "DDraw.dll");
    if (!file_exists(path)) return 0;
    return 1;
}

'''
text = text.replace(marker, helpers + marker, 1)

# Saving through the launcher now owns the runtime borderless switch and the two
# dgVoodoo presentation settings that were verified during the v15/v16 tests.
replace_once(
'''    (void)game_dir;\n    write_config(width, height, aspect_enabled, save_enabled);\n    return 1;\n''',
'''    write_config(width, height, aspect_enabled, save_enabled);\n    configure_modern_runtime(game_dir);\n    return 1;\n''',
"write compatibility settings",
)

# Give Save useful health feedback without refusing to write the runtime config.
replace_once(
'''static void do_save(HWND hwnd)\n{\n    if (write_selected_config(hwnd)) {\n        set_status("Saved config. No game files were modified.");\n    }\n}\n''',
'''static void do_save(HWND hwnd)\n{\n    if (write_selected_config(hwnd)) {\n        char exe_path[MAX_PATH];\n        char game_dir[MAX_PATH];\n        GetWindowTextA(exe_edit, exe_path, sizeof(exe_path));\n        path_dirname(exe_path, game_dir, sizeof(game_dir));\n        if (compatibility_stack_present(game_dir))\n            set_status("Settings saved. Borderless + dgVoodoo compatibility is configured.");\n        else\n            set_status("Settings saved. dgVoodoo files were not all found in the game folder.");\n    }\n}\n''',
"save status",
)

# Apply the compatibility keys again immediately before launch, then warn if the
# expected dgVoodoo wrapper files are not beside the selected game executable.
replace_once(
'''    path_dirname(exe_path, game_dir, sizeof(game_dir));\n    if (write_ui_config) {\n''',
'''    path_dirname(exe_path, game_dir, sizeof(game_dir));\n    configure_modern_runtime(game_dir);\n    if (!compatibility_stack_present(game_dir)) {\n        if (MessageBoxA(hwnd,\n            "The validated dgVoodoo2 files were not all found next to mvp2005.exe.\\n\\n"\n            "Expected: dgVoodoo.conf, D3D8.dll and DDraw.dll.\\n\\n"\n            "Launch anyway?",\n            "MVP Baseball 2005 Modern", MB_ICONWARNING | MB_YESNO) != IDYES)\n            return 0;\n    }\n    if (write_ui_config) {\n''',
"pre-launch compatibility validation",
)

# Rebrand the visible launcher and keep it interactive on every run. The upstream
# launcher normally auto-launches as soon as mvp2005fix.ini is complete, which is
# undesirable once this becomes the central configuration/profile UI.
text = text.replace('"mvp2005fix", MB_ICONERROR', '"MVP Baseball 2005 Modern", MB_ICONERROR')
text = text.replace('"mvp2005fix", MB_ICONWARNING', '"MVP Baseball 2005 Modern", MB_ICONWARNING')
text = text.replace('"mvp2005fix", MB_ICONINFORMATION', '"MVP Baseball 2005 Modern", MB_ICONINFORMATION')

replace_once(
'''        aspect_check = CreateWindowA("BUTTON", "True widescreen 3D aspect fix", WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,\n            96, 72, 260, 22, hwnd, (HMENU)ID_ASPECT_FIX, NULL, NULL);\n        Button_SetCheck(aspect_check, BST_CHECKED);\n        save_check = CreateWindowA("BUTTON", "Save-game disk-space fixer", WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,\n            96, 98, 260, 22, hwnd, (HMENU)ID_SAVE_FIX, NULL, NULL);\n        Button_SetCheck(save_check, BST_CHECKED);\n\n        CreateWindowA("BUTTON", "Save", WS_CHILD | WS_VISIBLE, 96, 130, 82, 26, hwnd, (HMENU)ID_SAVE, NULL, NULL);\n        CreateWindowA("BUTTON", "Launch", WS_CHILD | WS_VISIBLE, 186, 130, 82, 26, hwnd, (HMENU)ID_LAUNCH, NULL, NULL);\n        status_text = CreateWindowA("STATIC", "Select mvp2005.exe, choose settings, then Launch.", WS_CHILD | WS_VISIBLE,\n            12, 168, 420, 20, hwnd, (HMENU)ID_STATUS, NULL, NULL);\n''',
'''        aspect_check = CreateWindowA("BUTTON", "True widescreen 3D aspect fix", WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,\n            96, 72, 260, 22, hwnd, (HMENU)ID_ASPECT_FIX, NULL, NULL);\n        Button_SetCheck(aspect_check, BST_CHECKED);\n        save_check = CreateWindowA("BUTTON", "Save-game disk-space fixer", WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,\n            96, 98, 260, 22, hwnd, (HMENU)ID_SAVE_FIX, NULL, NULL);\n        Button_SetCheck(save_check, BST_CHECKED);\n        load_runtime_controls();\n\n        CreateWindowA("BUTTON", "Save Settings", WS_CHILD | WS_VISIBLE, 96, 130, 108, 26, hwnd, (HMENU)ID_SAVE, NULL, NULL);\n        CreateWindowA("BUTTON", "Launch Game", WS_CHILD | WS_VISIBLE, 214, 130, 108, 26, hwnd, (HMENU)ID_LAUNCH, NULL, NULL);\n        status_text = CreateWindowA("STATIC", "Borderless and dgVoodoo compatibility are managed automatically.", WS_CHILD | WS_VISIBLE,\n            12, 168, 424, 20, hwnd, (HMENU)ID_STATUS, NULL, NULL);\n''',
"launcher controls",
)

replace_once(
'''            if (load_launcher_settings(remembered, sizeof(remembered))) {\n                SetWindowTextA(exe_edit, remembered);\n                if (config_is_complete()) {\n                    set_status("Launching with existing config...");\n                    PostMessageA(hwnd, WM_AUTOLAUNCH, 0, 0);\n                } else {\n                    set_status("Loaded previous mvp2005.exe path. Choose settings, then Launch.");\n                }\n''',
'''            if (load_launcher_settings(remembered, sizeof(remembered))) {\n                SetWindowTextA(exe_edit, remembered);\n                set_status("Loaded previous game path. Review settings or launch.");\n''',
"disable WM_CREATE autolaunch",
)

replace_once(
'''    char remembered[MAX_PATH];\n    char remembered_dir[MAX_PATH];\n    (void)prev;\n    (void)cmd;\n\n    if (load_launcher_settings(remembered, sizeof(remembered))) {\n        path_dirname(remembered, remembered_dir, sizeof(remembered_dir));\n        if (config_is_complete()) {\n            return launch_target(NULL, remembered, 0) ? 0 : 1;\n        }\n    }\n\n''',
'''    (void)prev;\n    (void)cmd;\n\n''',
"disable WinMain autolaunch",
)

replace_once(
'''    hwnd = CreateWindowA("mvp2005fixWindow", "mvp2005fix", window_style,\n''',
'''    hwnd = CreateWindowA("mvp2005fixWindow", "MVP Baseball 2005 Modern", window_style,\n''',
"window title",
)

# The executable is renamed in packaging, but the injected DLL intentionally
# keeps its upstream-compatible filename.
text = text.replace(
    '"mvp2005fix.dll was not found next to mvp2005fix.exe."',
    '"mvp2005fix.dll was not found next to MVP2005Modern.exe."',
)

LAUNCHER.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern launcher/configuration layer v1")
