from pathlib import Path

LAUNCHER = Path("src/launcher.c")
MAKEFILE = Path("Makefile")
text = LAUNCHER.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"modern launcher v2 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# Native helpers used by the all-in-one setup layer.
replace_once(
'''#include <commdlg.h>\n#include <stdio.h>\n''',
'''#include <commdlg.h>\n#include <shellapi.h>\n#include <urlmon.h>\n#include <wincrypt.h>\n#include <ctype.h>\n#include <stdio.h>\n''',
"setup includes",
)

replace_once(
'''#define ID_CUSTOM_HEIGHT 1011\n#define WM_AUTOLAUNCH (WM_APP + 1)\n''',
'''#define ID_CUSTOM_HEIGHT 1011\n#define ID_SKIP_INTRO 1012\n#define ID_SETUP_REPAIR 1013\n#define WM_AUTOLAUNCH (WM_APP + 1)\n''',
"control ids",
)

replace_once(
'''static HWND custom_height_edit;\n''',
'''static HWND custom_height_edit;\nstatic HWND skip_intro_check;\n''',
"skip intro control",
)

# Find a normal installed copy even when the launcher is not already in the game
# directory. The retail installer uses this EA SPORTS registry key.
replace_once(
'''static int find_default_game_exe(char *exe_path, DWORD exe_size)\n{\n    char app_dir[MAX_PATH];\n    get_app_dir(app_dir, sizeof(app_dir));\n    join_path(exe_path, exe_size, app_dir, "mvp2005.exe");\n    return exe_path[0] && file_exists(exe_path);\n}\n''',
'''static int find_registry_game_exe(char *exe_path, DWORD exe_size)\n{\n    HKEY key;\n    char install_dir[MAX_PATH];\n    DWORD type = 0;\n    DWORD size = sizeof(install_dir);\n    LONG rc;\n\n    rc = RegOpenKeyExA(HKEY_LOCAL_MACHINE,\n        "SOFTWARE\\\\EA SPORTS\\\\MVP Baseball 2005", 0,\n        KEY_QUERY_VALUE | KEY_WOW64_32KEY, &key);\n    if (rc != ERROR_SUCCESS)\n        rc = RegOpenKeyExA(HKEY_LOCAL_MACHINE,\n            "SOFTWARE\\\\EA SPORTS\\\\MVP Baseball 2005", 0, KEY_QUERY_VALUE, &key);\n    if (rc != ERROR_SUCCESS) return 0;\n\n    rc = RegQueryValueExA(key, "Install Dir", NULL, &type, (BYTE *)install_dir, &size);\n    RegCloseKey(key);\n    if (rc != ERROR_SUCCESS || (type != REG_SZ && type != REG_EXPAND_SZ)) return 0;\n    install_dir[sizeof(install_dir) - 1] = 0;\n    join_path(exe_path, exe_size, install_dir, "mvp2005.exe");\n    return exe_path[0] && file_exists(exe_path);\n}\n\nstatic int find_default_game_exe(char *exe_path, DWORD exe_size)\n{\n    char app_dir[MAX_PATH];\n    char program_files[MAX_PATH];\n\n    get_app_dir(app_dir, sizeof(app_dir));\n    join_path(exe_path, exe_size, app_dir, "mvp2005.exe");\n    if (exe_path[0] && file_exists(exe_path)) return 1;\n\n    if (find_registry_game_exe(exe_path, exe_size)) return 1;\n\n    if (GetEnvironmentVariableA("ProgramFiles(x86)", program_files, sizeof(program_files))) {\n        join_path(exe_path, exe_size, program_files,\n            "EA SPORTS\\\\MVP Baseball 2005\\\\mvp2005.exe");\n        if (exe_path[0] && file_exists(exe_path)) return 1;\n    }\n    if (GetEnvironmentVariableA("ProgramFiles", program_files, sizeof(program_files))) {\n        join_path(exe_path, exe_size, program_files,\n            "EA SPORTS\\\\MVP Baseball 2005\\\\mvp2005.exe");\n        if (exe_path[0] && file_exists(exe_path)) return 1;\n    }\n    exe_path[0] = 0;\n    return 0;\n}\n''',
"installed game detection",
)

# The v1 launcher already has runtime/dgVoodoo helpers. Insert first-run setup,
# verified downloads, backups and intro-video management directly before the
# dgVoodoo configuration function.
marker = '''static int configure_dgvoodoo(const char *game_dir)\n'''
if text.count(marker) != 1:
    raise SystemExit(f"modern launcher v2 helper marker: expected one match, found {text.count(marker)}")

helpers = r'''static const char *SAFEDISCSHIM_URL =
    "https://github.com/RibShark/SafeDiscShim/releases/download/v0.9.0/SafeDiscShim_Setup_0.9.0.exe";
static const char *SAFEDISCSHIM_SHA256 =
    "b4c355ec63047a09c20c286c083fcad1031d47a2c17eac0de12b96d377ec369f";
static const char *DGVOODOO_URL =
    "https://github.com/dege-diosg/dgVoodoo2/releases/download/v2.87.5/dgVoodoo2_87_5.zip";
static const char *DGVOODOO_SHA256 =
    "5ffde6927f7355ca3fdd5d785b581256a8e6539fa13e395a891ade6ba1040850";

static int contains_ascii_ci(const char *haystack, const char *needle)
{
    const char *h;
    const char *n;
    if (!haystack || !needle || !needle[0]) return 0;
    for (; *haystack; haystack++) {
        h = haystack;
        n = needle;
        while (*h && *n &&
            tolower((unsigned char)*h) == tolower((unsigned char)*n)) {
            h++;
            n++;
        }
        if (!*n) return 1;
    }
    return 0;
}

static int sha256_file_matches(const char *path, const char *expected_hex)
{
    HCRYPTPROV provider = 0;
    HCRYPTHASH hash = 0;
    HANDLE file = INVALID_HANDLE_VALUE;
    BYTE buffer[65536];
    BYTE digest[32];
    DWORD read = 0;
    DWORD digest_size = sizeof(digest);
    int ok = 0;
    int i;

    if (!CryptAcquireContextA(&provider, NULL, NULL, PROV_RSA_AES, CRYPT_VERIFYCONTEXT))
        goto done;
    if (!CryptCreateHash(provider, CALG_SHA_256, 0, 0, &hash)) goto done;
    file = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) goto done;

    for (;;) {
        if (!ReadFile(file, buffer, sizeof(buffer), &read, NULL)) goto done;
        if (!read) break;
        if (!CryptHashData(hash, buffer, read, 0)) goto done;
    }
    if (!CryptGetHashParam(hash, HP_HASHVAL, digest, &digest_size, 0) ||
        digest_size != sizeof(digest)) goto done;

    for (i = 0; i < 32; i++) {
        char pair[3];
        char *end = NULL;
        unsigned long expected;
        pair[0] = expected_hex[i * 2];
        pair[1] = expected_hex[i * 2 + 1];
        pair[2] = 0;
        expected = strtoul(pair, &end, 16);
        if (!end || *end || digest[i] != (BYTE)expected) goto done;
    }
    ok = 1;

done:
    if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
    if (hash) CryptDestroyHash(hash);
    if (provider) CryptReleaseContext(provider, 0);
    return ok;
}

static void temp_named_path(char *out, DWORD out_size, const char *name)
{
    char temp[MAX_PATH];
    DWORD len = GetTempPathA(sizeof(temp), temp);
    if (!len || len >= sizeof(temp)) {
        out[0] = 0;
        return;
    }
    join_path(out, out_size, temp, name);
}

static int download_verified(HWND hwnd, const char *label, const char *url,
    const char *expected_hash, const char *path)
{
    HRESULT hr;
    char message[512];

    if (file_exists(path) && sha256_file_matches(path, expected_hash)) return 1;
    DeleteFileA(path);
    wsprintfA(message, "Downloading %s...", label);
    set_status(message);
    if (status_text) UpdateWindow(status_text);

    hr = URLDownloadToFileA(NULL, url, path, 0, NULL);
    if (FAILED(hr)) {
        wsprintfA(message, "Could not download %s (HRESULT %08lx).", label,
            (unsigned long)hr);
        MessageBoxA(hwnd, message, "MVP Baseball 2005 Modern", MB_ICONERROR);
        DeleteFileA(path);
        return 0;
    }
    if (!sha256_file_matches(path, expected_hash)) {
        wsprintfA(message, "%s failed its SHA-256 verification. The download was deleted.", label);
        MessageBoxA(hwnd, message, "MVP Baseball 2005 Modern", MB_ICONERROR);
        DeleteFileA(path);
        return 0;
    }
    return 1;
}

static int run_elevated_installer(HWND hwnd, const char *path, const char *parameters)
{
    SHELLEXECUTEINFOA sei;
    DWORD exit_code = 1;

    ZeroMemory(&sei, sizeof(sei));
    sei.cbSize = sizeof(sei);
    sei.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_FLAG_NO_UI;
    sei.hwnd = hwnd;
    sei.lpVerb = "runas";
    sei.lpFile = path;
    sei.lpParameters = parameters;
    sei.nShow = SW_SHOWNORMAL;
    if (!ShellExecuteExA(&sei) || !sei.hProcess) return 0;
    WaitForSingleObject(sei.hProcess, INFINITE);
    GetExitCodeProcess(sei.hProcess, &exit_code);
    CloseHandle(sei.hProcess);
    return exit_code == 0;
}

static int run_hidden_command(char *command)
{
    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    DWORD exit_code = 1;

    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    if (!CreateProcessA(NULL, command, NULL, NULL, FALSE, CREATE_NO_WINDOW,
        NULL, NULL, &si, &pi)) return 0;
    WaitForSingleObject(pi.hProcess, INFINITE);
    GetExitCodeProcess(pi.hProcess, &exit_code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return exit_code == 0;
}

static void powershell_single_quote(const char *src, char *dst, DWORD dst_size)
{
    DWORD pos = 0;
    if (!dst_size) return;
    if (pos + 1 < dst_size) dst[pos++] = '\'';
    while (*src && pos + 2 < dst_size) {
        if (*src == '\'') dst[pos++] = '\'';
        dst[pos++] = *src++;
    }
    if (pos + 1 < dst_size) dst[pos++] = '\'';
    dst[pos < dst_size ? pos : dst_size - 1] = 0;
}

static int create_temp_work_dir(char *out, DWORD out_size)
{
    char temp[MAX_PATH];
    DWORD len = GetTempPathA(sizeof(temp), temp);
    if (!len || len >= sizeof(temp)) return 0;
    snprintf(out, out_size, "%sMVP2005Modern-%08lx-%08lx",
        temp, (unsigned long)GetCurrentProcessId(), (unsigned long)GetTickCount());
    return CreateDirectoryA(out, NULL) || GetLastError() == ERROR_ALREADY_EXISTS;
}

static int expand_zip_with_powershell(const char *zip_path, const char *dest_dir)
{
    char qzip[MAX_PATH * 2];
    char qdest[MAX_PATH * 2];
    char command[2048];
    powershell_single_quote(zip_path, qzip, sizeof(qzip));
    powershell_single_quote(dest_dir, qdest, sizeof(qdest));
    snprintf(command, sizeof(command),
        "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command \"Expand-Archive -LiteralPath %s -DestinationPath %s -Force\"",
        qzip, qdest);
    return run_hidden_command(command);
}

static void remove_temp_tree(const char *path)
{
    char qpath[MAX_PATH * 2];
    char command[1536];
    powershell_single_quote(path, qpath, sizeof(qpath));
    snprintf(command, sizeof(command),
        "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command \"Remove-Item -LiteralPath %s -Recurse -Force -ErrorAction SilentlyContinue\"",
        qpath);
    run_hidden_command(command);
}

static int ensure_backup_subdir(const char *game_dir, const char *subdir,
    char *out, DWORD out_size)
{
    char root[MAX_PATH];
    join_path(root, sizeof(root), game_dir, "MVP2005Modern.Backup");
    if (!CreateDirectoryA(root, NULL) && GetLastError() != ERROR_ALREADY_EXISTS) return 0;
    join_path(out, out_size, root, subdir);
    if (!CreateDirectoryA(out, NULL) && GetLastError() != ERROR_ALREADY_EXISTS) return 0;
    return 1;
}

static void backup_root_file_once(const char *game_dir, const char *name)
{
    char source[MAX_PATH];
    char backup_dir[MAX_PATH];
    char backup[MAX_PATH];
    join_path(source, sizeof(source), game_dir, name);
    if (!file_exists(source)) return;
    if (!ensure_backup_subdir(game_dir, "compatibility", backup_dir, sizeof(backup_dir))) return;
    join_path(backup, sizeof(backup), backup_dir, name);
    if (!file_exists(backup)) CopyFileA(source, backup, TRUE);
}

static int safediscshim_installed(void)
{
    char system_dir[MAX_PATH];
    char dll_path[MAX_PATH];
    char layer[1024];
    DWORD type = 0;
    DWORD size = sizeof(layer);
    HKEY key;
    LONG rc;

    if (!GetSystemDirectoryA(system_dir, sizeof(system_dir))) return 0;
    join_path(dll_path, sizeof(dll_path), system_dir, "drvmgt.dll");
    if (!file_exists(dll_path)) return 0;

    rc = RegOpenKeyExA(HKEY_LOCAL_MACHINE,
        "SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment",
        0, KEY_QUERY_VALUE, &key);
    if (rc != ERROR_SUCCESS) return 0;
    rc = RegQueryValueExA(key, "__COMPAT_LAYER", NULL, &type, (BYTE *)layer, &size);
    RegCloseKey(key);
    if (rc != ERROR_SUCCESS || (type != REG_SZ && type != REG_EXPAND_SZ)) return 0;
    layer[sizeof(layer) - 1] = 0;
    return contains_ascii_ci(layer, "RedirectDrvMgt");
}

static void ensure_safedisc_environment(void)
{
    char current[2048];
    char combined[2048];
    DWORD len = GetEnvironmentVariableA("__COMPAT_LAYER", current, sizeof(current));
    if (len && len < sizeof(current) && contains_ascii_ci(current, "RedirectDrvMgt")) return;
    if (!len || len >= sizeof(current)) {
        SetEnvironmentVariableA("__COMPAT_LAYER", "RedirectDrvMgt");
        return;
    }
    snprintf(combined, sizeof(combined), "%s RedirectDrvMgt", current);
    SetEnvironmentVariableA("__COMPAT_LAYER", combined);
}

static int ensure_safediscshim(HWND hwnd)
{
    char installer[MAX_PATH];

    if (safediscshim_installed()) {
        ensure_safedisc_environment();
        return 1;
    }

    if (MessageBoxA(hwnd,
        "SafeDiscShim is not installed. MVP Baseball 2005 Modern will download the official SafeDiscShim v0.9.0 installer, verify it, and install it system-wide.\\n\\n"
        "Windows will show one Administrator/UAC prompt. The original game disc verification is still required.\\n\\nContinue?",
        "MVP Baseball 2005 Modern", MB_ICONINFORMATION | MB_OKCANCEL) != IDOK)
        return 0;

    temp_named_path(installer, sizeof(installer), "MVP2005Modern-SafeDiscShim-0.9.0.exe");
    if (!installer[0] || !download_verified(hwnd, "SafeDiscShim v0.9.0",
        SAFEDISCSHIM_URL, SAFEDISCSHIM_SHA256, installer)) return 0;

    set_status("Installing SafeDiscShim (approve the Windows UAC prompt)...");
    if (!run_elevated_installer(hwnd, installer,
        "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-")) {
        DeleteFileA(installer);
        MessageBoxA(hwnd, "SafeDiscShim installation did not complete successfully.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return 0;
    }
    DeleteFileA(installer);
    if (!safediscshim_installed()) {
        MessageBoxA(hwnd,
            "SafeDiscShim finished but MVP Baseball 2005 Modern could not verify the installation.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return 0;
    }
    ensure_safedisc_environment();
    return 1;
}

static int copy_dgvoodoo_component(const char *game_dir, const char *extract_dir,
    const char *source_relative, const char *target_name)
{
    char source[MAX_PATH];
    char target[MAX_PATH];
    join_path(source, sizeof(source), extract_dir, source_relative);
    join_path(target, sizeof(target), game_dir, target_name);
    if (!file_exists(source)) return 0;
    backup_root_file_once(game_dir, target_name);
    return CopyFileA(source, target, FALSE) != 0;
}

static int dgvoodoo_local_files_present(const char *game_dir)
{
    char path[MAX_PATH];
    const char *names[] = {"dgVoodoo.conf", "D3D8.dll", "DDraw.dll", "D3DImm.dll"};
    int i;
    for (i = 0; i < 4; i++) {
        join_path(path, sizeof(path), game_dir, names[i]);
        if (!file_exists(path)) return 0;
    }
    return 1;
}

static int ensure_dgvoodoo(HWND hwnd, const char *game_dir, int force_repair)
{
    char zip_path[MAX_PATH];
    char extract_dir[MAX_PATH];
    char source_conf[MAX_PATH];
    char target_conf[MAX_PATH];
    int ok = 0;

    if (!force_repair && dgvoodoo_local_files_present(game_dir)) return 1;

    temp_named_path(zip_path, sizeof(zip_path), "MVP2005Modern-dgVoodoo2_87_5.zip");
    if (!zip_path[0] || !download_verified(hwnd, "dgVoodoo2 v2.87.5",
        DGVOODOO_URL, DGVOODOO_SHA256, zip_path)) return 0;
    if (!create_temp_work_dir(extract_dir, sizeof(extract_dir))) {
        MessageBoxA(hwnd, "Could not create a temporary folder for dgVoodoo2 setup.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        DeleteFileA(zip_path);
        return 0;
    }

    set_status("Installing verified dgVoodoo2 v2.87.5 files...");
    if (!expand_zip_with_powershell(zip_path, extract_dir)) {
        MessageBoxA(hwnd, "Could not extract the dgVoodoo2 package.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        goto done;
    }

    if (!copy_dgvoodoo_component(game_dir, extract_dir, "MS\\x86\\D3D8.dll", "D3D8.dll") ||
        !copy_dgvoodoo_component(game_dir, extract_dir, "MS\\x86\\DDraw.dll", "DDraw.dll") ||
        !copy_dgvoodoo_component(game_dir, extract_dir, "MS\\x86\\D3DImm.dll", "D3DImm.dll")) {
        MessageBoxA(hwnd, "The dgVoodoo2 package did not contain the expected x86 DirectX files.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        goto done;
    }

    join_path(target_conf, sizeof(target_conf), game_dir, "dgVoodoo.conf");
    if (!file_exists(target_conf)) {
        join_path(source_conf, sizeof(source_conf), extract_dir, "dgVoodoo.conf");
        if (!file_exists(source_conf) || !CopyFileA(source_conf, target_conf, FALSE)) {
            MessageBoxA(hwnd, "Could not install dgVoodoo.conf.",
                "MVP Baseball 2005 Modern", MB_ICONERROR);
            goto done;
        }
    } else {
        backup_root_file_once(game_dir, "dgVoodoo.conf");
    }
    ok = dgvoodoo_local_files_present(game_dir);

done:
    DeleteFileA(zip_path);
    remove_temp_tree(extract_dir);
    return ok;
}

static int write_empty_file(const char *path)
{
    HANDLE file = CreateFileA(path, GENERIC_WRITE, FILE_SHARE_READ, NULL,
        CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;
    CloseHandle(file);
    return 1;
}

static int apply_intro_setting(HWND hwnd, const char *game_dir, int skip)
{
    const char *names[] = {"easports.vp6", "mvpintro.vp6"};
    char movies_dir[MAX_PATH];
    char backup_dir[MAX_PATH];
    char original[MAX_PATH];
    char backup[MAX_PATH];
    int i;

    join_path(movies_dir, sizeof(movies_dir), game_dir, "data\\frontend\\movies");
    if (!ensure_backup_subdir(game_dir, "intro", backup_dir, sizeof(backup_dir))) {
        MessageBoxA(hwnd, "Could not create the MVP2005Modern.Backup folder.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return 0;
    }

    for (i = 0; i < 2; i++) {
        join_path(original, sizeof(original), movies_dir, names[i]);
        join_path(backup, sizeof(backup), backup_dir, names[i]);
        if (skip) {
            if (!file_exists(original) && !file_exists(backup)) continue;
            if (file_exists(original) && !file_exists(backup) &&
                !CopyFileA(original, backup, TRUE)) {
                MessageBoxA(hwnd, "Could not back up an intro movie before disabling it.",
                    "MVP Baseball 2005 Modern", MB_ICONERROR);
                return 0;
            }
            if (!write_empty_file(original)) {
                MessageBoxA(hwnd, "Could not create the blank intro movie file.",
                    "MVP Baseball 2005 Modern", MB_ICONERROR);
                return 0;
            }
        } else if (file_exists(backup)) {
            if (!CopyFileA(backup, original, FALSE)) {
                MessageBoxA(hwnd, "Could not restore a backed-up intro movie.",
                    "MVP Baseball 2005 Modern", MB_ICONERROR);
                return 0;
            }
        }
    }
    return 1;
}

'''
text = text.replace(marker, helpers + marker, 1)

# Preserve the user's existing wrapper configuration, but make a one-time backup
# before MVP2005 Modern owns the known-good compatibility keys. Fresh installs
# get the full tested MVP-specific baseline.
replace_once(
'''static int configure_dgvoodoo(const char *game_dir)\n{\n    char conf[MAX_PATH];\n\n    join_path(conf, sizeof(conf), game_dir, "dgVoodoo.conf");\n    if (!file_exists(conf)) return 0;\n\n    /* Final validated true-borderless settings. Leave every unrelated\n     * dgVoodoo option exactly as the user already has it. */\n    WritePrivateProfileStringA("General", "FullScreenMode", "false", conf);\n    WritePrivateProfileStringA("DirectX", "AppControlledScreenMode", "false", conf);\n    WritePrivateProfileStringA("DirectX", "DisableAltEnterToToggleScreenMode", "true", conf);\n    return 1;\n}\n''',
'''static int configure_dgvoodoo(const char *game_dir)\n{\n    char conf[MAX_PATH];\n\n    join_path(conf, sizeof(conf), game_dir, "dgVoodoo.conf");\n    if (!file_exists(conf)) return 0;\n    backup_root_file_once(game_dir, "dgVoodoo.conf");\n\n    WritePrivateProfileStringA("General", "OutputAPI", "bestavailable", conf);\n    WritePrivateProfileStringA("General", "FullScreenMode", "false", conf);\n    WritePrivateProfileStringA("General", "ScalingMode", "stretched", conf);\n    WritePrivateProfileStringA("General", "KeepWindowAspectRatio", "false", conf);\n    WritePrivateProfileStringA("General", "CaptureMouse", "false", conf);\n    WritePrivateProfileStringA("General", "CenterAppWindow", "false", conf);\n    WritePrivateProfileStringA("GeneralExt", "FreeMouse", "false", conf);\n    WritePrivateProfileStringA("DirectX", "DisableAndPassThru", "false", conf);\n    WritePrivateProfileStringA("DirectX", "VideoCard", "geforce_9800_gt", conf);\n    WritePrivateProfileStringA("DirectX", "VRAM", "1024", conf);\n    WritePrivateProfileStringA("DirectX", "Resolution", "unforced", conf);\n    WritePrivateProfileStringA("DirectX", "AppControlledScreenMode", "false", conf);\n    WritePrivateProfileStringA("DirectX", "DisableAltEnterToToggleScreenMode", "true", conf);\n    WritePrivateProfileStringA("DirectX", "ForceVerticalSync", "false", conf);\n    WritePrivateProfileStringA("DirectX", "dgVoodooWatermark", "false", conf);\n    WritePrivateProfileStringA("DirectXExt", "DefaultEnumeratedResolutions", "all", conf);\n    return 1;\n}\n''',
"validated dgVoodoo profile",
)

replace_once(
'''    join_path(path, sizeof(path), game_dir, "DDraw.dll");\n    if (!file_exists(path)) return 0;\n    return 1;\n}\n''',
'''    join_path(path, sizeof(path), game_dir, "DDraw.dll");\n    if (!file_exists(path)) return 0;\n    join_path(path, sizeof(path), game_dir, "D3DImm.dll");\n    if (!file_exists(path)) return 0;\n    return 1;\n}\n\nstatic int ensure_compatibility_stack(HWND hwnd, const char *game_dir, int force_repair)\n{\n    if (!ensure_safediscshim(hwnd)) return 0;\n    if (!ensure_dgvoodoo(hwnd, game_dir, force_repair)) return 0;\n    if (!configure_dgvoodoo(game_dir)) return 0;\n    return 1;\n}\n''',
"all-in-one compatibility stack",
)

# Persist and apply the reversible intro-video switch. Established MVP fixes use
# blank easports.vp6/mvpintro.vp6 files; we always retain originals first.
replace_once(
'''    Button_SetCheck(save_check,\n        GetPrivateProfileIntA("SaveFix", "Enabled", 1, ini) ? BST_CHECKED : BST_UNCHECKED);\n}\n''',
'''    Button_SetCheck(save_check,\n        GetPrivateProfileIntA("SaveFix", "Enabled", 1, ini) ? BST_CHECKED : BST_UNCHECKED);\n    if (skip_intro_check)\n        Button_SetCheck(skip_intro_check,\n            GetPrivateProfileIntA("Modern", "SkipIntro", 0, ini) ? BST_CHECKED : BST_UNCHECKED);\n}\n''',
"load intro setting",
)

replace_once(
'''    int save_enabled;\n    int aspect_enabled;\n''',
'''    int save_enabled;\n    int aspect_enabled;\n    int skip_intro;\n''',
"intro local",
)

replace_once(
'''    save_enabled = Button_GetCheck(save_check) == BST_CHECKED;\n    aspect_enabled = Button_GetCheck(aspect_check) == BST_CHECKED;\n    write_config(width, height, aspect_enabled, save_enabled);\n    configure_modern_runtime(game_dir);\n    return 1;\n''',
'''    save_enabled = Button_GetCheck(save_check) == BST_CHECKED;\n    aspect_enabled = Button_GetCheck(aspect_check) == BST_CHECKED;\n    skip_intro = skip_intro_check && Button_GetCheck(skip_intro_check) == BST_CHECKED;\n    write_config(width, height, aspect_enabled, save_enabled);\n    {\n        char ini[MAX_PATH];\n        get_ini_path(ini, sizeof(ini));\n        WritePrivateProfileStringA("Modern", "SkipIntro", skip_intro ? "1" : "0", ini);\n    }\n    configure_modern_runtime(game_dir);\n    if (!apply_intro_setting(hwnd, game_dir, skip_intro)) return 0;\n    return 1;\n''',
"apply intro setting",
)

# Launch now performs the missing-system setup automatically instead of warning
# the user to install dependencies manually.
replace_once(
'''    path_dirname(exe_path, game_dir, sizeof(game_dir));\n    configure_modern_runtime(game_dir);\n    if (!compatibility_stack_present(game_dir)) {\n        if (MessageBoxA(hwnd,\n            "The validated dgVoodoo2 files were not all found next to mvp2005.exe.\\n\\n"\n            "Expected: dgVoodoo.conf, D3D8.dll and DDraw.dll.\\n\\n"\n            "Launch anyway?",\n            "MVP Baseball 2005 Modern", MB_ICONWARNING | MB_YESNO) != IDYES)\n            return 0;\n    }\n    if (write_ui_config) {\n''',
'''    path_dirname(exe_path, game_dir, sizeof(game_dir));\n    if (!ensure_compatibility_stack(hwnd, game_dir, 0)) return 0;\n    configure_modern_runtime(game_dir);\n    if (write_ui_config) {\n''',
"automatic compatibility setup before launch",
)

# Add an explicit repair button for users who want to refresh the local wrapper
# files without waiting for a missing-file check.
marker = '''static LRESULT CALLBACK window_proc(HWND hwnd, UINT msg, WPARAM wparam, LPARAM lparam)\n'''
if text.count(marker) != 1:
    raise SystemExit(f"modern launcher v2 repair marker: expected one match, found {text.count(marker)}")
repair = r'''static void do_setup_repair(HWND hwnd)
{
    char exe_path[MAX_PATH];
    char game_dir[MAX_PATH];
    const ResolutionOption *res;

    if (!get_selected(hwnd, exe_path, sizeof(exe_path), game_dir, sizeof(game_dir), &res)) return;
    (void)res;
    set_status("Checking SafeDiscShim and repairing dgVoodoo2...");
    if (ensure_compatibility_stack(hwnd, game_dir, 1)) {
        configure_modern_runtime(game_dir);
        set_status("Compatibility setup is ready: SafeDiscShim + dgVoodoo2 + RC1 runtime.");
    }
}

'''
text = text.replace(marker, repair + marker, 1)

# Grow the configuration UI to include the intro switch and one-click setup.
replace_once(
'''        save_check = CreateWindowA("BUTTON", "Save-game disk-space fixer", WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,\n            96, 98, 260, 22, hwnd, (HMENU)ID_SAVE_FIX, NULL, NULL);\n        Button_SetCheck(save_check, BST_CHECKED);\n        load_runtime_controls();\n\n        CreateWindowA("BUTTON", "Save Settings", WS_CHILD | WS_VISIBLE, 96, 130, 108, 26, hwnd, (HMENU)ID_SAVE, NULL, NULL);\n        CreateWindowA("BUTTON", "Launch Game", WS_CHILD | WS_VISIBLE, 214, 130, 108, 26, hwnd, (HMENU)ID_LAUNCH, NULL, NULL);\n        status_text = CreateWindowA("STATIC", "Borderless and dgVoodoo compatibility are managed automatically.", WS_CHILD | WS_VISIBLE,\n            12, 168, 424, 20, hwnd, (HMENU)ID_STATUS, NULL, NULL);\n''',
'''        save_check = CreateWindowA("BUTTON", "Save-game disk-space fixer", WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,\n            96, 98, 260, 22, hwnd, (HMENU)ID_SAVE_FIX, NULL, NULL);\n        Button_SetCheck(save_check, BST_CHECKED);\n        skip_intro_check = CreateWindowA("BUTTON", "Skip EA Sports / MVP intro videos", WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,\n            96, 124, 280, 22, hwnd, (HMENU)ID_SKIP_INTRO, NULL, NULL);\n        Button_SetCheck(skip_intro_check, BST_UNCHECKED);\n        load_runtime_controls();\n\n        CreateWindowA("STATIC", "Compatibility setup is automatic: SafeDiscShim + dgVoodoo2 2.87.5 + RC1 runtime",\n            WS_CHILD | WS_VISIBLE, 12, 154, 492, 20, hwnd, NULL, NULL, NULL);\n        CreateWindowA("BUTTON", "Setup / Repair", WS_CHILD | WS_VISIBLE, 96, 180, 108, 26, hwnd, (HMENU)ID_SETUP_REPAIR, NULL, NULL);\n        CreateWindowA("BUTTON", "Save Settings", WS_CHILD | WS_VISIBLE, 214, 180, 108, 26, hwnd, (HMENU)ID_SAVE, NULL, NULL);\n        CreateWindowA("BUTTON", "Launch Game", WS_CHILD | WS_VISIBLE, 332, 180, 108, 26, hwnd, (HMENU)ID_LAUNCH, NULL, NULL);\n        status_text = CreateWindowA("STATIC", "Launch will verify/install missing compatibility components automatically.", WS_CHILD | WS_VISIBLE,\n            12, 220, 492, 20, hwnd, (HMENU)ID_STATUS, NULL, NULL);\n''',
"all-in-one launcher controls",
)

replace_once(
'''        case ID_SAVE:\n            do_save(hwnd);\n            return 0;\n        case ID_LAUNCH:\n''',
'''        case ID_SETUP_REPAIR:\n            do_setup_repair(hwnd);\n            return 0;\n        case ID_SAVE:\n            do_save(hwnd);\n            return 0;\n        case ID_LAUNCH:\n''',
"setup repair command",
)

replace_once(
'''                set_status("Loaded previous game path. Review settings or launch.");\n''',
'''                set_status("Loaded previous game path. Launch will verify the complete compatibility stack.");\n''',
"remembered path status",
)

replace_once(
'''    window_rect.right = 448;\n    window_rect.bottom = 200;\n''',
'''    window_rect.right = 520;\n    window_rect.bottom = 250;\n''',
"larger launcher window",
)

LAUNCHER.write_text(text, encoding="utf-8")

# URLDownloadToFile, ShellExecuteEx, registry/CryptoAPI calls are Windows system
# APIs; no additional runtime files are shipped with the launcher.
make = MAKEFILE.read_text(encoding="utf-8")
old = '''\t$(CC) $(CFLAGS) $(LDFLAGS) -mwindows -o release/mvp2005fix.exe src/launcher.c src/injection.c -lcomdlg32\n'''
new = '''\t$(CC) $(CFLAGS) $(LDFLAGS) -mwindows -o release/mvp2005fix.exe src/launcher.c src/injection.c -lcomdlg32 -lurlmon -lshell32 -ladvapi32\n'''
if make.count(old) != 1:
    raise SystemExit(f"modern launcher v2 Makefile link line: expected one match, found {make.count(old)}")
MAKEFILE.write_text(make.replace(old, new, 1), encoding="utf-8")

print("Applied MVP2005 Modern all-in-one launcher/setup layer v2")
