from pathlib import Path
import re

LAUNCHER = Path("src/launcher.c")
RUNTIME = Path("src/runtime.c")
launcher = LAUNCHER.read_text(encoding="utf-8")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"setup cleanup v33 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, new: str, label: str) -> str:
    updated, count = re.subn(pattern, lambda _m: new, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"setup cleanup v33 {label}: expected exactly one match, found {count}")
    return updated


# ---------------------------------------------------------------------------
# Launcher/setup hardening
# ---------------------------------------------------------------------------
# The previous setup path worked on the development machine but had two weak
# spots for a real clean install:
#   * a 32-bit launcher can be UAC-virtualized when writing under Program Files,
#     making a write appear successful even though the real game directory was
#     untouched;
#   * dgVoodoo copy failures were reported as a bad package even when the actual
#     problem was permissions.
#
# v33 disables file virtualization for this process, probes the real game folder,
# and automatically launches a narrowly-scoped elevated dgVoodoo repair worker
# only when the selected install directory actually needs administrator rights.
# SafeDiscShim keeps using its own verified official installer/UAC path.

# Track UAC cancellation explicitly so the user gets an actionable message.
launcher = replace_once(
    launcher,
    'static int run_elevated_installer(HWND hwnd, const char *path, const char *parameters)\n',
    'static DWORD setup_last_elevation_error;\n\nstatic int run_elevated_installer(HWND hwnd, const char *path, const char *parameters)\n',
    "elevation error global",
)
launcher = replace_once(
    launcher,
    '    if (!ShellExecuteExA(&sei) || !sei.hProcess) return 0;\n',
    '''    setup_last_elevation_error = ERROR_SUCCESS;\n    if (!ShellExecuteExA(&sei) || !sei.hProcess) {\n        setup_last_elevation_error = GetLastError();\n        return 0;\n    }\n''',
    "capture installer elevation error",
)
launcher = replace_once(
    launcher,
    '    GetExitCodeProcess(sei.hProcess, &exit_code);\n    CloseHandle(sei.hProcess);\n    return exit_code == 0;\n',
    '''    GetExitCodeProcess(sei.hProcess, &exit_code);\n    CloseHandle(sei.hProcess);\n    if (exit_code != 0) setup_last_elevation_error = exit_code;\n    return exit_code == 0;\n''',
    "capture installer exit code",
)

launcher = replace_once(
    launcher,
    '''        DeleteFileA(installer);\n        MessageBoxA(hwnd, "SafeDiscShim installation did not complete successfully.",\n            "MVP Baseball 2005 Modern", MB_ICONERROR);\n        return 0;\n''',
    '''        DeleteFileA(installer);\n        if (setup_last_elevation_error == ERROR_CANCELLED)\n            MessageBoxA(hwnd,\n                "SafeDiscShim setup was canceled at the Windows UAC prompt. Nothing was changed.\\n\\nRun Verify / Repair again when you are ready to approve the administrator prompt.",\n                "MVP Baseball 2005 Modern", MB_ICONINFORMATION);\n        else\n            MessageBoxA(hwnd,\n                "SafeDiscShim installation did not complete successfully. Verify that Windows allowed the installer to run, then try Verify / Repair again.",\n                "MVP Baseball 2005 Modern", MB_ICONERROR);\n        return 0;\n''',
    "specific SafeDisc UAC message",
)

# Insert real-directory write probing + health checks before dgVoodoo configuration.
marker = 'static int configure_dgvoodoo(const char *game_dir)\n'
if launcher.count(marker) != 1:
    raise SystemExit(f"setup cleanup v33 setup helper marker: found {launcher.count(marker)}")

helpers = r'''static void disable_uac_file_virtualization(void)
{
    HANDLE token = NULL;
    DWORD disabled = 0;
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY | TOKEN_ADJUST_DEFAULT, &token)) {
        SetTokenInformation(token, TokenVirtualizationEnabled, &disabled, sizeof(disabled));
        CloseHandle(token);
    }
}

static int game_dir_is_writable(const char *game_dir)
{
    char path[MAX_PATH];
    HANDLE file;
    if (!game_dir || !game_dir[0]) return 0;
    snprintf(path, sizeof(path), "%s\\MVP2005Modern.write-test-%08lx.tmp",
        game_dir, (unsigned long)GetCurrentProcessId());
    file = CreateFileA(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
        FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;
    CloseHandle(file);
    DeleteFileA(path);
    return 1;
}

static int dgvoodoo_config_valid(const char *game_dir)
{
    char conf[MAX_PATH];
    char value[64];
    join_path(conf, sizeof(conf), game_dir, "dgVoodoo.conf");
    if (!file_exists(conf)) return 0;

    GetPrivateProfileStringA("General", "FullScreenMode", "", value, sizeof(value), conf);
    if (_stricmp(value, "false") != 0) return 0;
    GetPrivateProfileStringA("DirectX", "AppControlledScreenMode", "", value, sizeof(value), conf);
    if (_stricmp(value, "false") != 0) return 0;
    GetPrivateProfileStringA("DirectX", "DisableAltEnterToToggleScreenMode", "", value, sizeof(value), conf);
    if (_stricmp(value, "true") != 0) return 0;
    return 1;
}

static int run_elevated_local_repair(HWND hwnd, const char *game_dir, int force_repair)
{
    SHELLEXECUTEINFOA sei;
    char self[MAX_PATH];
    char parameters[MAX_PATH * 2 + 96];
    DWORD exit_code = 1;

    if (!GetModuleFileNameA(NULL, self, sizeof(self))) return 0;
    snprintf(parameters, sizeof(parameters),
        "--mvpmodern-dgvoodoo-repair \"%s\" %d", game_dir, force_repair ? 1 : 0);

    ZeroMemory(&sei, sizeof(sei));
    sei.cbSize = sizeof(sei);
    sei.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_FLAG_NO_UI;
    sei.hwnd = hwnd;
    sei.lpVerb = "runas";
    sei.lpFile = self;
    sei.lpParameters = parameters;
    sei.nShow = SW_HIDE;
    setup_last_elevation_error = ERROR_SUCCESS;
    if (!ShellExecuteExA(&sei) || !sei.hProcess) {
        setup_last_elevation_error = GetLastError();
        if (setup_last_elevation_error == ERROR_CANCELLED)
            MessageBoxA(hwnd,
                "Local compatibility setup was canceled at the Windows UAC prompt. Nothing was changed in the game folder.",
                "MVP Baseball 2005 Modern", MB_ICONINFORMATION);
        else
            MessageBoxA(hwnd,
                "Windows could not start the elevated compatibility repair helper.",
                "MVP Baseball 2005 Modern", MB_ICONERROR);
        return 0;
    }
    WaitForSingleObject(sei.hProcess, INFINITE);
    GetExitCodeProcess(sei.hProcess, &exit_code);
    CloseHandle(sei.hProcess);
    if (exit_code != 0) {
        MessageBoxA(hwnd,
            "The elevated dgVoodoo2 repair did not complete successfully. No MVP game executable was modified.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return 0;
    }
    return 1;
}

'''
launcher = launcher.replace(marker, helpers + marker, 1)

# Avoid silently attempting game-directory writes from Save Settings when the
# game lives under Program Files. Verify/Repair or Launch owns the elevated path.
launcher = replace_once(
    launcher,
    '''    WritePrivateProfileStringA("Borderless", "Enabled", "1", ini);\n    configure_dgvoodoo(game_dir);\n''',
    '''    WritePrivateProfileStringA("Borderless", "Enabled", "1", ini);\n    if (game_dir_is_writable(game_dir)) configure_dgvoodoo(game_dir);\n''',
    "avoid unelevated configure write",
)

# The intro experiment is disabled; normal settings saves should no longer touch
# the game tree just to restore/migrate old experimental movie backups.
launcher = launcher.replace(
    '    if (!apply_intro_setting(hwnd, game_dir, skip_intro)) return 0;\n',
    '    (void)hwnd;\n    (void)game_dir;\n    (void)skip_intro;\n',
    1,
)

# Replace stack verification with a permissions-aware path. SafeDisc is checked
# first; local dgVoodoo work elevates only when the real game folder is not
# writable. After an elevated worker returns, the parent verifies actual files
# and the required known-good configuration instead of trusting an exit code.
launcher = replace_regex_once(
    launcher,
    r'''static int ensure_compatibility_stack\(HWND hwnd, const char \*game_dir, int force_repair\)\n\{.*?\n\}\n''',
    r'''static int ensure_compatibility_stack(HWND hwnd, const char *game_dir, int force_repair)
{
    int local_ready;

    if (!ensure_safediscshim(hwnd)) return 0;

    local_ready = dgvoodoo_local_files_present(game_dir) && dgvoodoo_config_valid(game_dir);
    if (!force_repair && local_ready) return 1;

    if (game_dir_is_writable(game_dir)) {
        if (!ensure_dgvoodoo(hwnd, game_dir, force_repair)) return 0;
        if (!configure_dgvoodoo(game_dir)) return 0;
    } else {
        set_status("Game folder needs administrator access. Waiting for Windows UAC...");
        if (!run_elevated_local_repair(hwnd, game_dir, force_repair)) return 0;
    }

    if (!dgvoodoo_local_files_present(game_dir) || !dgvoodoo_config_valid(game_dir)) {
        MessageBoxA(hwnd,
            "Compatibility setup finished, but the validated dgVoodoo2 files/configuration are still not present in the real MVP Baseball 2005 folder.\\n\\nIf the game is under Program Files, make sure the administrator prompt was approved.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return 0;
    }
    return 1;
}
''',
    "permissions-aware compatibility stack",
)

# Make the old package error describe what can actually fail.
launcher = launcher.replace(
    '"The dgVoodoo2 package did not contain the expected x86 DirectX files."',
    '"Could not install the verified dgVoodoo2 x86 DirectX files into the game folder. Check folder permissions and security software, then try Verify / Repair again."',
    1,
)

# Worker command: same signed/built launcher, elevated only for the local wrapper
# copy/configuration. It never launches the game and never touches SafeDisc.
worker_marker = 'static void do_setup_repair(HWND hwnd)\n'
if launcher.count(worker_marker) != 1:
    raise SystemExit(f"setup cleanup v33 worker insertion marker: found {launcher.count(worker_marker)}")
worker = r'''static int run_setup_worker_if_requested(void)
{
    int argc = 0;
    LPWSTR *argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    int result = -1;
    if (!argv) return -1;

    if (argc >= 3 && lstrcmpW(argv[1], L"--mvpmodern-dgvoodoo-repair") == 0) {
        char game_dir[MAX_PATH];
        int force_repair = argc >= 4 ? _wtoi(argv[3]) != 0 : 1;
        game_dir[0] = 0;
        WideCharToMultiByte(CP_ACP, 0, argv[2], -1, game_dir, sizeof(game_dir), NULL, NULL);
        game_dir[sizeof(game_dir) - 1] = 0;
        if (game_dir[0] && ensure_dgvoodoo(NULL, game_dir, force_repair) &&
            configure_dgvoodoo(game_dir) && dgvoodoo_local_files_present(game_dir) &&
            dgvoodoo_config_valid(game_dir))
            result = 0;
        else
            result = 12;
    }
    LocalFree(argv);
    return result;
}

static void refresh_setup_status(void)
{
    char exe_path[MAX_PATH];
    char game_dir[MAX_PATH];
    if (!status_text || !exe_edit) return;
    GetWindowTextA(exe_edit, exe_path, sizeof(exe_path));
    if (!file_exists(exe_path)) {
        set_status("Select mvp2005.exe. Verify / Repair will configure the compatibility stack.");
        return;
    }
    path_dirname(exe_path, game_dir, sizeof(game_dir));
    if (!safediscshim_installed()) {
        set_status("Setup needed: SafeDiscShim 0.9.0 is not installed.");
        return;
    }
    if (!dgvoodoo_local_files_present(game_dir)) {
        set_status("Setup needed: dgVoodoo2 wrapper files are missing from the game folder.");
        return;
    }
    if (!dgvoodoo_config_valid(game_dir)) {
        set_status("Repair recommended: dgVoodoo2 is present but not on the validated MVP profile.");
        return;
    }
    set_status("Ready: SafeDiscShim, dgVoodoo2 and MVP2005 Modern runtime are configured.");
}

'''
launcher = launcher.replace(worker_marker, worker + worker_marker, 1)

# Setup/Repair now reports health from actual post-repair state.
launcher = replace_regex_once(
    launcher,
    r'''static void do_setup_repair\(HWND hwnd\)\n\{.*?\n\}\n\nstatic LRESULT CALLBACK window_proc''',
    r'''static void do_setup_repair(HWND hwnd)
{
    char exe_path[MAX_PATH];
    char game_dir[MAX_PATH];
    const ResolutionOption *res;

    if (!get_selected(hwnd, exe_path, sizeof(exe_path), game_dir, sizeof(game_dir), &res)) return;
    (void)res;
    set_status("Verifying SafeDiscShim and the local dgVoodoo2 compatibility files...");
    if (ensure_compatibility_stack(hwnd, game_dir, 1)) {
        configure_modern_runtime(game_dir);
        refresh_setup_status();
    } else {
        refresh_setup_status();
    }
}

static LRESULT CALLBACK window_proc''',
    "clean repair handler",
)

# Update status immediately after browsing/detection so Setup is self-explanatory.
launcher = replace_once(
    launcher,
    '''    if (GetOpenFileNameA(&ofn)) {\n        SetWindowTextA(exe_edit, path);\n        save_launcher_settings(path);\n    }\n''',
    '''    if (GetOpenFileNameA(&ofn)) {\n        SetWindowTextA(exe_edit, path);\n        save_launcher_settings(path);\n        refresh_setup_status();\n    }\n''',
    "browse health refresh",
)
launcher = launcher.replace(
    'set_status("Loaded previous game path. Launch will verify the complete compatibility stack.");',
    'refresh_setup_status();',
    1,
)
launcher = launcher.replace(
    'set_status("Found mvp2005.exe next to the launcher. Choose settings, then Launch.");',
    'refresh_setup_status();',
    1,
)

# Cleaner production wording. Controller setup remains available but is no longer
# the headline of the launcher.
launcher = launcher.replace(
    '"Compatibility setup is automatic: SafeDiscShim + dgVoodoo2 2.87.5 + RC1 runtime"',
    '"Compatibility: SafeDiscShim 0.9.0 + dgVoodoo2 2.87.5 + MVP2005 Modern runtime"',
    1,
)
launcher = launcher.replace('"Setup / Repair"', '"Verify / Repair"', 1)
launcher = launcher.replace(
    '"Launch will verify/install missing compatibility components automatically."',
    '"Select mvp2005.exe. Verify / Repair will configure the compatibility stack."',
    1,
)

# Disable WOW64/UAC file virtualization and service an elevated repair worker
# before the normal window is created.
launcher = replace_once(
    launcher,
    '''    (void)prev;\n    (void)cmd;\n\n''',
    '''    int setup_worker_result;\n    (void)prev;\n    (void)cmd;\n\n    disable_uac_file_virtualization();\n    setup_worker_result = run_setup_worker_if_requested();\n    if (setup_worker_result >= 0) return setup_worker_result;\n\n''',
    "WinMain setup worker",
)

LAUNCHER.write_text(launcher, encoding="utf-8")


# ---------------------------------------------------------------------------
# Runtime production cleanup
# ---------------------------------------------------------------------------
# Keep the successful v32 learner and persisted mappings, but stop creating a
# 50k-line controller diagnostic file during ordinary play. Diagnostics remain
# opt-in with [ControllerDebug] Logging=1 in mvp2005fix.ini.
runtime = replace_once(
    runtime,
    '''static void controller_diag_open_log(void)\n{\n    char path[MAX_PATH];\n''',
    '''static void controller_diag_open_log(void)\n{\n    char path[MAX_PATH];\n    char ini[MAX_PATH];\n    if (!get_ini_path(ini, sizeof(ini)) ||\n        !GetPrivateProfileIntA("ControllerDebug", "Logging", 0, ini))\n        return;\n''',
    "opt-in controller diagnostic file",
)
runtime = replace_once(
    runtime,
    '''static void controller_diag_logf(const char *fmt, ...)\n{\n    char buf[2048];\n''',
    '''static void controller_diag_logf(const char *fmt, ...)\n{\n    char buf[2048];\n    if (controller_diag_log_handle == INVALID_HANDLE_VALUE) return;\n''',
    "skip disabled diagnostic formatting",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern setup hardening + production cleanup v33")
