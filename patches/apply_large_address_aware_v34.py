from pathlib import Path

LAUNCHER = Path("src/launcher.c")
RUNTIME = Path("src/runtime.c")
launcher = LAUNCHER.read_text(encoding="utf-8")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"large address aware v34 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Launcher: opt-in, reversible Large Address Aware PE-header toggle.
# ---------------------------------------------------------------------------
launcher = replace_once(
    launcher,
    '#include <stdlib.h>\n',
    '#include <stdlib.h>\n#include <stdarg.h>\n',
    'stdarg include',
)

launcher = replace_once(
    launcher,
    '#define ID_CONTROLLER_CONFIG 1014\n',
    '#define ID_CONTROLLER_CONFIG 1014\n#define ID_LARGE_ADDRESS_AWARE 1015\n',
    'LAA control id',
)

launcher = replace_once(
    launcher,
    'static HWND skip_intro_check;\n',
    'static HWND skip_intro_check;\nstatic HWND laa_check;\n',
    'LAA control global',
)

# v33 inserts this worker after all setup helpers, so every dependency used here
# (backup directory helper, write-permission probe, and setup elevation state)
# already exists at this point in the generated launcher source.
marker = 'static int run_setup_worker_if_requested(void)\n'
if launcher.count(marker) != 1:
    raise SystemExit(f"large address aware v34 helper marker: found {launcher.count(marker)}")

helpers = r'''typedef struct LaaPeInfo {
    ULONGLONG file_size;
    DWORD pe_offset;
    DWORD characteristics_offset;
    WORD machine;
    WORD optional_magic;
    WORD characteristics;
} LaaPeInfo;

static void laa_logf(const char *fmt, ...)
{
    char app_dir[MAX_PATH];
    char path[MAX_PATH];
    char message[2048];
    char line[2304];
    SYSTEMTIME st;
    HANDLE file;
    DWORD written;
    va_list ap;

    get_app_dir(app_dir, sizeof(app_dir));
    join_path(path, sizeof(path), app_dir, "MVP2005Modern-LAA.log");
    va_start(ap, fmt);
    vsnprintf(message, sizeof(message), fmt, ap);
    va_end(ap);
    message[sizeof(message) - 1] = 0;
    GetLocalTime(&st);
    snprintf(line, sizeof(line),
        "[%04u-%02u-%02u %02u:%02u:%02u.%03u] launcher pid=%lu %s\r\n",
        st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond,
        st.wMilliseconds, (unsigned long)GetCurrentProcessId(), message);
    line[sizeof(line) - 1] = 0;

    file = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
        NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return;
    WriteFile(file, line, (DWORD)lstrlenA(line), &written, NULL);
    CloseHandle(file);
}

static int sha256_file_hex(const char *path, char *hex, DWORD hex_size)
{
    HCRYPTPROV provider = 0;
    HCRYPTHASH hash = 0;
    HANDLE file = INVALID_HANDLE_VALUE;
    BYTE buffer[65536];
    BYTE digest[32];
    DWORD read = 0;
    DWORD digest_size = sizeof(digest);
    static const char digits[] = "0123456789abcdef";
    int ok = 0;
    int i;

    if (!hex || hex_size < 65) return 0;
    hex[0] = 0;
    if (!CryptAcquireContextA(&provider, NULL, NULL, PROV_RSA_AES, CRYPT_VERIFYCONTEXT))
        goto done;
    if (!CryptCreateHash(provider, CALG_SHA_256, 0, 0, &hash)) goto done;
    file = CreateFileA(path, GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) goto done;
    for (;;) {
        if (!ReadFile(file, buffer, sizeof(buffer), &read, NULL)) goto done;
        if (!read) break;
        if (!CryptHashData(hash, buffer, read, 0)) goto done;
    }
    if (!CryptGetHashParam(hash, HP_HASHVAL, digest, &digest_size, 0) || digest_size != 32)
        goto done;
    for (i = 0; i < 32; i++) {
        hex[i * 2] = digits[digest[i] >> 4];
        hex[i * 2 + 1] = digits[digest[i] & 15];
    }
    hex[64] = 0;
    ok = 1;

done:
    if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
    if (hash) CryptDestroyHash(hash);
    if (provider) CryptReleaseContext(provider, 0);
    return ok;
}

static int read_laa_pe_info(const char *exe_path, LaaPeInfo *info)
{
    HANDLE file = INVALID_HANDLE_VALUE;
    LARGE_INTEGER size;
    IMAGE_DOS_HEADER dos;
    IMAGE_NT_HEADERS32 nt;
    LARGE_INTEGER pos;
    DWORD read = 0;
    int result = -1;

    if (!info) return -1;
    ZeroMemory(info, sizeof(*info));
    file = CreateFileA(exe_path, GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) {
        laa_logf("read failed path=\"%s\" winerr=%lu", exe_path,
            (unsigned long)GetLastError());
        return -1;
    }
    if (!GetFileSizeEx(file, &size) || size.QuadPart < (LONGLONG)sizeof(IMAGE_DOS_HEADER))
        goto invalid;
    info->file_size = (ULONGLONG)size.QuadPart;

    if (!ReadFile(file, &dos, sizeof(dos), &read, NULL) || read != sizeof(dos) ||
        dos.e_magic != IMAGE_DOS_SIGNATURE)
        goto invalid;
    if (dos.e_lfanew < (LONG)sizeof(IMAGE_DOS_HEADER) ||
        (ULONGLONG)dos.e_lfanew + sizeof(nt) > info->file_size)
        goto invalid;

    pos.QuadPart = dos.e_lfanew;
    if (!SetFilePointerEx(file, pos, NULL, FILE_BEGIN)) goto invalid;
    if (!ReadFile(file, &nt, sizeof(nt), &read, NULL) || read != sizeof(nt)) goto invalid;
    if (nt.Signature != IMAGE_NT_SIGNATURE ||
        nt.FileHeader.Machine != IMAGE_FILE_MACHINE_I386 ||
        nt.OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR32_MAGIC)
        goto invalid;

    info->pe_offset = (DWORD)dos.e_lfanew;
    info->characteristics_offset = info->pe_offset +
        (DWORD)FIELD_OFFSET(IMAGE_NT_HEADERS32, FileHeader.Characteristics);
    info->machine = nt.FileHeader.Machine;
    info->optional_magic = nt.OptionalHeader.Magic;
    info->characteristics = nt.FileHeader.Characteristics;
    result = (info->characteristics & IMAGE_FILE_LARGE_ADDRESS_AWARE) ? 1 : 0;
    CloseHandle(file);
    return result;

invalid:
    laa_logf("invalid PE32/i386 image path=\"%s\" size=%llu", exe_path,
        (unsigned long long)info->file_size);
    CloseHandle(file);
    return -1;
}

static int ensure_laa_backup(const char *exe_path, char *backup_path, DWORD backup_size)
{
    char game_dir[MAX_PATH];
    char backup_dir[MAX_PATH];

    path_dirname(exe_path, game_dir, sizeof(game_dir));
    if (!ensure_backup_subdir(game_dir, "executable", backup_dir, sizeof(backup_dir))) {
        laa_logf("backup directory creation failed game_dir=\"%s\" winerr=%lu",
            game_dir, (unsigned long)GetLastError());
        return 0;
    }
    join_path(backup_path, backup_size, backup_dir, "mvp2005.exe.pre-laa.bak");
    if (!file_exists(backup_path)) {
        if (!CopyFileA(exe_path, backup_path, TRUE)) {
            laa_logf("backup copy failed source=\"%s\" dest=\"%s\" winerr=%lu",
                exe_path, backup_path, (unsigned long)GetLastError());
            return 0;
        }
        laa_logf("created executable backup path=\"%s\"", backup_path);
    } else {
        laa_logf("reusing existing executable backup path=\"%s\"", backup_path);
    }
    return 1;
}

static int write_laa_direct(const char *exe_path, int enable)
{
    LaaPeInfo before;
    LaaPeInfo after;
    HANDLE file = INVALID_HANDLE_VALUE;
    LARGE_INTEGER pos;
    WORD new_characteristics;
    DWORD written = 0;
    char backup[MAX_PATH];
    char hash_before[65];
    char hash_after[65];
    int state;

    hash_before[0] = 0;
    hash_after[0] = 0;
    state = read_laa_pe_info(exe_path, &before);
    if (state < 0) return 0;
    sha256_file_hex(exe_path, hash_before, sizeof(hash_before));
    laa_logf(
        "request=%s path=\"%s\" size=%llu pe=0x%08lx chars_off=0x%08lx machine=0x%04x magic=0x%04x chars_before=0x%04x laa_before=%d sha256_before=%s",
        enable ? "enable" : "disable", exe_path,
        (unsigned long long)before.file_size, (unsigned long)before.pe_offset,
        (unsigned long)before.characteristics_offset, before.machine,
        before.optional_magic, before.characteristics, state,
        hash_before[0] ? hash_before : "unavailable");

    if (state == (enable ? 1 : 0)) {
        laa_logf("no write required; executable already has requested LAA state");
        return 1;
    }
    if (!ensure_laa_backup(exe_path, backup, sizeof(backup))) return 0;

    file = CreateFileA(exe_path, GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) {
        laa_logf("write open failed path=\"%s\" winerr=%lu", exe_path,
            (unsigned long)GetLastError());
        return 0;
    }

    new_characteristics = enable
        ? (WORD)(before.characteristics | IMAGE_FILE_LARGE_ADDRESS_AWARE)
        : (WORD)(before.characteristics & ~IMAGE_FILE_LARGE_ADDRESS_AWARE);
    pos.QuadPart = before.characteristics_offset;
    if (!SetFilePointerEx(file, pos, NULL, FILE_BEGIN) ||
        !WriteFile(file, &new_characteristics, sizeof(new_characteristics), &written, NULL) ||
        written != sizeof(new_characteristics) || !FlushFileBuffers(file)) {
        DWORD err = GetLastError();
        CloseHandle(file);
        SetLastError(err);
        laa_logf("characteristics write failed offset=0x%08lx winerr=%lu",
            (unsigned long)before.characteristics_offset, (unsigned long)err);
        return 0;
    }
    CloseHandle(file);

    state = read_laa_pe_info(exe_path, &after);
    sha256_file_hex(exe_path, hash_after, sizeof(hash_after));
    if (state != (enable ? 1 : 0) ||
        after.characteristics != new_characteristics ||
        after.characteristics_offset != before.characteristics_offset ||
        after.file_size != before.file_size) {
        laa_logf(
            "verification FAILED state=%d chars_after=0x%04x expected=0x%04x size_after=%llu",
            state, after.characteristics, new_characteristics,
            (unsigned long long)after.file_size);
        SetLastError(ERROR_INVALID_DATA);
        return 0;
    }
    laa_logf(
        "verification PASS chars_after=0x%04x laa_after=%d changed_mask=0x%04x sha256_after=%s",
        after.characteristics, state,
        (WORD)(before.characteristics ^ after.characteristics),
        hash_after[0] ? hash_after : "unavailable");
    return 1;
}

static int run_elevated_laa(HWND hwnd, const char *exe_path, int enable)
{
    SHELLEXECUTEINFOA sei;
    char self[MAX_PATH];
    char parameters[MAX_PATH * 2 + 96];
    DWORD exit_code = 1;

    if (!GetModuleFileNameA(NULL, self, sizeof(self))) return 0;
    snprintf(parameters, sizeof(parameters),
        "--mvpmodern-laa \"%s\" %d", exe_path, enable ? 1 : 0);
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
        laa_logf("elevated worker start failed winerr=%lu",
            (unsigned long)setup_last_elevation_error);
        return 0;
    }
    WaitForSingleObject(sei.hProcess, INFINITE);
    GetExitCodeProcess(sei.hProcess, &exit_code);
    CloseHandle(sei.hProcess);
    if (exit_code != 0) {
        setup_last_elevation_error = exit_code;
        laa_logf("elevated worker failed exit=%lu", (unsigned long)exit_code);
        return 0;
    }
    return 1;
}

static int apply_laa_setting(HWND hwnd, const char *exe_path, int enable)
{
    char game_dir[MAX_PATH];
    LaaPeInfo info;
    int state;

    state = read_laa_pe_info(exe_path, &info);
    if (state < 0) {
        MessageBoxA(hwnd,
            "Large Address Aware could not validate the selected file as a 32-bit x86 PE executable. No change was made. See MVP2005Modern-LAA.log for details.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return 0;
    }
    if (state == (enable ? 1 : 0)) return 1;

    path_dirname(exe_path, game_dir, sizeof(game_dir));
    laa_logf("applying requested LAA state=%d game_dir_writable=%d",
        enable ? 1 : 0, game_dir_is_writable(game_dir));

    if (game_dir_is_writable(game_dir)) {
        if (write_laa_direct(exe_path, enable)) return 1;
        laa_logf("direct LAA update failed; retrying through narrowly scoped elevated worker");
    }

    set_status("Large Address Aware needs administrator access. Waiting for Windows UAC...");
    if (!run_elevated_laa(hwnd, exe_path, enable)) {
        if (setup_last_elevation_error == ERROR_CANCELLED)
            MessageBoxA(hwnd,
                "Large Address Aware was not changed because the Windows UAC prompt was canceled.",
                "MVP Baseball 2005 Modern", MB_ICONINFORMATION);
        else
            MessageBoxA(hwnd,
                "The elevated Large Address Aware update did not complete. No launch was attempted. See MVP2005Modern-LAA.log for details.",
                "MVP Baseball 2005 Modern", MB_ICONERROR);
        return 0;
    }

    state = read_laa_pe_info(exe_path, &info);
    if (state != (enable ? 1 : 0)) {
        laa_logf("parent verification FAILED after elevated worker state=%d", state);
        MessageBoxA(hwnd,
            "Windows reported that the Large Address Aware update completed, but verification of mvp2005.exe failed. No launch was attempted.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return 0;
    }
    laa_logf("parent verification PASS after elevated worker laa=%d", state);
    return 1;
}

static void refresh_laa_checkbox(const char *exe_path)
{
    LaaPeInfo info;
    int state;
    if (!laa_check) return;
    state = read_laa_pe_info(exe_path, &info);
    EnableWindow(laa_check, state >= 0);
    if (state >= 0)
        Button_SetCheck(laa_check, state ? BST_CHECKED : BST_UNCHECKED);
    else
        Button_SetCheck(laa_check, BST_UNCHECKED);
}

'''
launcher = launcher.replace(marker, helpers + marker, 1)

# Extend the v33 elevated worker rather than elevating the entire launcher.
launcher = replace_once(
    launcher,
    '''        else\n            result = 12;\n    }\n    LocalFree(argv);\n''',
    '''        else\n            result = 12;\n    } else if (argc >= 4 && lstrcmpW(argv[1], L"--mvpmodern-laa") == 0) {\n        char exe_path[MAX_PATH];\n        int enable = _wtoi(argv[3]) != 0;\n        exe_path[0] = 0;\n        WideCharToMultiByte(CP_ACP, 0, argv[2], -1, exe_path, sizeof(exe_path), NULL, NULL);\n        exe_path[sizeof(exe_path) - 1] = 0;\n        result = exe_path[0] && write_laa_direct(exe_path, enable) ? 0 : 34;\n    }\n    LocalFree(argv);\n''',
    'LAA elevated worker command',
)

# Keep the visible switch synchronized to the real executable header whenever
# setup status is refreshed (initial detection and Browse both pass through here).
launcher = replace_once(
    launcher,
    '''    if (!status_text || !exe_edit) return;\n    GetWindowTextA(exe_edit, exe_path, sizeof(exe_path));\n    if (!file_exists(exe_path)) {\n''',
    '''    if (!status_text || !exe_edit) return;\n    GetWindowTextA(exe_edit, exe_path, sizeof(exe_path));\n    if (file_exists(exe_path)) refresh_laa_checkbox(exe_path);\n    else if (laa_check) {\n        EnableWindow(laa_check, FALSE);\n        Button_SetCheck(laa_check, BST_UNCHECKED);\n    }\n    if (!file_exists(exe_path)) {\n''',
    'refresh actual LAA state',
)

# Saving settings or launching applies the checkbox before proceeding. The INI
# records intent/history, but the actual executable header remains the source of
# truth when the launcher is reopened.
launcher = replace_once(
    launcher,
    '    int skip_intro;\n',
    '    int skip_intro;\n    int laa_enabled;\n',
    'LAA local',
)
launcher = replace_once(
    launcher,
    '''    skip_intro = 0;\n    write_config(width, height, aspect_enabled, save_enabled);\n''',
    '''    skip_intro = 0;\n    laa_enabled = laa_check && Button_GetCheck(laa_check) == BST_CHECKED;\n    if (!apply_laa_setting(hwnd, exe_path, laa_enabled)) return 0;\n    write_config(width, height, aspect_enabled, save_enabled);\n''',
    'apply LAA during save/launch',
)
launcher = replace_once(
    launcher,
    '''        WritePrivateProfileStringA("Modern", "SkipIntro", skip_intro ? "1" : "0", ini);\n''',
    '''        WritePrivateProfileStringA("Modern", "SkipIntro", skip_intro ? "1" : "0", ini);\n        WritePrivateProfileStringA("Modern", "LargeAddressAware", laa_enabled ? "1" : "0", ini);\n''',
    'persist LAA preference',
)

# Add the switch next to Controller Setup without moving the proven layout.
launcher = replace_once(
    launcher,
    '''        CreateWindowA("BUTTON", "Controller Setup...", WS_CHILD | WS_VISIBLE, 96, 124, 140, 26, hwnd, (HMENU)ID_CONTROLLER_CONFIG, NULL, NULL);\n''',
    '''        CreateWindowA("BUTTON", "Controller Setup...", WS_CHILD | WS_VISIBLE, 96, 124, 140, 26, hwnd, (HMENU)ID_CONTROLLER_CONFIG, NULL, NULL);\n        laa_check = CreateWindowA("BUTTON", "4 GB / Large Address Aware (backs up EXE)",\n            WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX, 248, 126, 256, 22, hwnd,\n            (HMENU)ID_LARGE_ADDRESS_AWARE, NULL, NULL);\n        Button_SetCheck(laa_check, BST_UNCHECKED);\n''',
    'LAA checkbox UI',
)

# If the executable path is typed/pasted manually, refresh the PE state when the
# edit loses focus instead of leaving a stale checkbox from the previous path.
launcher = replace_once(
    launcher,
    '''        case ID_CONTROLLER_CONFIG:\n            show_controller_configurator(hwnd);\n            return 0;\n''',
    '''        case ID_EXE_EDIT:\n            if (HIWORD(wparam) == EN_KILLFOCUS) refresh_setup_status();\n            return 0;\n        case ID_CONTROLLER_CONFIG:\n            show_controller_configurator(hwnd);\n            return 0;\n''',
    'manual path refresh command',
)

LAUNCHER.write_text(launcher, encoding="utf-8")


# ---------------------------------------------------------------------------
# Runtime: one concise per-process diagnostic independent of verbose controller
# logging. This tells us whether SafeDisc's actual child image preserved LAA and
# what user-mode address ceiling Windows gave that process.
# ---------------------------------------------------------------------------
runtime_marker = 'static void load_config(void)\n'
if runtime.count(runtime_marker) != 1:
    raise SystemExit(f"large address aware v34 runtime helper marker: found {runtime.count(runtime_marker)}")

runtime_helpers = r'''static void log_laa_runtime_diagnostic(void)
{
    char dir[MAX_PATH];
    char path[MAX_PATH];
    char exe[MAX_PATH];
    char line[1024];
    SYSTEMTIME st;
    SYSTEM_INFO si;
    BYTE *base = (BYTE *)GetModuleHandleA(NULL);
    IMAGE_DOS_HEADER *dos = NULL;
    IMAGE_NT_HEADERS32 *nt = NULL;
    WORD characteristics = 0;
    int valid_pe32 = 0;
    int laa = 0;
    HANDLE file;
    DWORD written;

    if (base) {
        dos = (IMAGE_DOS_HEADER *)base;
        if (dos->e_magic == IMAGE_DOS_SIGNATURE && dos->e_lfanew > 0) {
            nt = (IMAGE_NT_HEADERS32 *)(base + dos->e_lfanew);
            if (nt->Signature == IMAGE_NT_SIGNATURE &&
                nt->FileHeader.Machine == IMAGE_FILE_MACHINE_I386 &&
                nt->OptionalHeader.Magic == IMAGE_NT_OPTIONAL_HDR32_MAGIC) {
                valid_pe32 = 1;
                characteristics = nt->FileHeader.Characteristics;
                laa = (characteristics & IMAGE_FILE_LARGE_ADDRESS_AWARE) != 0;
            }
        }
    }
    exe[0] = 0;
    GetModuleFileNameA(NULL, exe, sizeof(exe));
    exe[sizeof(exe) - 1] = 0;
    GetSystemInfo(&si);
    GetLocalTime(&st);

    if (!get_module_dir(dir, sizeof(dir))) return;
    if (!append_path(dir, sizeof(dir), "MVP2005Modern-LAA.log")) return;
    lstrcpynA(path, dir, sizeof(path));
    snprintf(line, sizeof(line),
        "[%04u-%02u-%02u %02u:%02u:%02u.%03u] runtime pid=%lu image=\"%s\" pe32=%d characteristics=0x%04x laa=%d min_app=%p max_app=%p arch=%u\r\n",
        st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond,
        st.wMilliseconds, (unsigned long)GetCurrentProcessId(), exe, valid_pe32,
        characteristics, laa, si.lpMinimumApplicationAddress,
        si.lpMaximumApplicationAddress, (unsigned int)si.wProcessorArchitecture);
    line[sizeof(line) - 1] = 0;

    file = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
        NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return;
    WriteFile(file, line, (DWORD)lstrlenA(line), &written, NULL);
    CloseHandle(file);
}

'''
runtime = runtime.replace(runtime_marker, runtime_helpers + runtime_marker, 1)
runtime = replace_once(
    runtime,
    '    debug_logging = GetPrivateProfileIntA("Debug", "Logging", 0, ini) != 0;\n',
    '    debug_logging = GetPrivateProfileIntA("Debug", "Logging", 0, ini) != 0;\n    log_laa_runtime_diagnostic();\n',
    'runtime LAA diagnostic call',
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern Large Address Aware launcher/runtime diagnostics v34")
