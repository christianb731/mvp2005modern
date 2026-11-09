/* Only included by the local QA launcher. The normal launcher remains borderless. */
static int apply_smoke_display_mode(HWND hwnd, const char *exe_path, const char *game_dir)
{
    char ini[MAX_PATH], conf[MAX_PATH], app_dir[MAX_PATH], relative[MAX_PATH];
    char expected[MAX_PATH], selected[MAX_PATH], mode[24];
    DWORD expected_len, selected_len;
    int borderless, fullscreen, relative_len;

    get_ini_path(ini, sizeof(ini));
    if (!GetPrivateProfileStringA("DisplayTest", "Mode", "", mode, sizeof(mode), ini))
        return 1;
    borderless = !_stricmp(mode, "borderless");
    fullscreen = !_stricmp(mode, "fullscreen");
    if (!borderless && !fullscreen && _stricmp(mode, "windowed")) goto failed;

    get_app_dir(app_dir, sizeof(app_dir));
    relative_len = snprintf(relative, sizeof(relative), "%s\\..\\..\\smoke-game\\MVP2005Smoke.exe", app_dir);
    if (relative_len < 0 || relative_len >= (int)sizeof(relative)) goto failed;
    expected_len = GetFullPathNameA(relative, sizeof(expected), expected, NULL);
    selected_len = GetFullPathNameA(exe_path, sizeof(selected), selected, NULL);
    if (!expected_len || expected_len >= sizeof(expected) || !selected_len ||
        selected_len >= sizeof(selected) || _stricmp(expected, selected)) goto failed;
    join_path(conf, sizeof(conf), game_dir, "dgVoodoo.conf");
    if (!file_exists(conf)) goto failed;

    if (WritePrivateProfileStringA("General", "FullScreenMode", fullscreen ? "true" : "false", conf) &&
        WritePrivateProfileStringA("DirectX", "AppControlledScreenMode", (!borderless && !fullscreen) ? "true" : "false", conf) &&
        WritePrivateProfileStringA("GeneralExt", "WindowedAttributes",
            borderless ? "borderless, fullscreensize" : "", conf) &&
        WritePrivateProfileStringA("GeneralExt", "FullscreenAttributes", "", conf) &&
        WritePrivateProfileStringA("Borderless", "Enabled", borderless ? "1" : "0", ini))
        return 1;
failed:
    MessageBoxA(hwnd, "Could not apply the isolated display test mode. Check the smoke launcher layout and configuration.",
        "MVP Baseball 2005 Modern", MB_ICONERROR);
    return 0;
}
