from pathlib import Path
import re

LAUNCHER = Path("src/launcher.c")
RUNTIME = Path("src/runtime.c")
launcher = LAUNCHER.read_text(encoding="utf-8")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"skip intro v35 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, new: str, label: str) -> str:
    updated, count = re.subn(pattern, lambda _m: new, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"skip intro v35 {label}: expected exactly one match, found {count}")
    return updated


# ---------------------------------------------------------------------------
# Launcher: restore a visible Skip Intro checkbox on top of the proven v0.34 UI.
# The movie files themselves are never renamed, replaced, truncated, or deleted.
# ---------------------------------------------------------------------------
launcher = replace_once(
    launcher,
    '''        skip_intro_check = NULL;\n        load_runtime_controls();\n''',
    '''        skip_intro_check = CreateWindowA("BUTTON", "Skip EA Sports / MVP intro videos",\n            WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX, 96, 154, 300, 22, hwnd,\n            (HMENU)ID_SKIP_INTRO, NULL, NULL);\n        Button_SetCheck(skip_intro_check, BST_UNCHECKED);\n        load_runtime_controls();\n''',
    "restore skip-intro checkbox",
)

launcher = replace_once(
    launcher,
    '    skip_intro = 0;\n',
    '    skip_intro = skip_intro_check && Button_GetCheck(skip_intro_check) == BST_CHECKED;\n',
    "read skip-intro checkbox",
)

# Make room for the restored control without disturbing the existing controller
# and LAA row.
launcher = replace_once(
    launcher,
    '''        CreateWindowA("STATIC", "Compatibility: SafeDiscShim 0.9.0 + dgVoodoo2 2.87.5 + MVP2005 Modern runtime",\n            WS_CHILD | WS_VISIBLE, 12, 154, 492, 20, hwnd, NULL, NULL, NULL);\n''',
    '''        CreateWindowA("STATIC", "Compatibility: SafeDiscShim 0.9.0 + dgVoodoo2 2.87.5 + MVP2005 Modern runtime",\n            WS_CHILD | WS_VISIBLE, 12, 180, 492, 20, hwnd, NULL, NULL, NULL);\n''',
    "move compatibility caption",
)
for label in ["Verify / Repair", "Save Settings", "Launch Game"]:
    launcher = launcher.replace(f'"{label}", WS_CHILD | WS_VISIBLE, ', f'"{label}", WS_CHILD | WS_VISIBLE, ', 1)
launcher = launcher.replace('96, 180, 108, 26, hwnd, (HMENU)ID_SETUP_REPAIR',
                            '96, 206, 108, 26, hwnd, (HMENU)ID_SETUP_REPAIR', 1)
launcher = launcher.replace('214, 180, 108, 26, hwnd, (HMENU)ID_SAVE',
                            '214, 206, 108, 26, hwnd, (HMENU)ID_SAVE', 1)
launcher = launcher.replace('332, 180, 108, 26, hwnd, (HMENU)ID_LAUNCH',
                            '332, 206, 108, 26, hwnd, (HMENU)ID_LAUNCH', 1)
launcher = launcher.replace('12, 220, 492, 20, hwnd, (HMENU)ID_STATUS',
                            '12, 246, 492, 20, hwnd, (HMENU)ID_STATUS', 1)
launcher = replace_once(
    launcher,
    '''    window_rect.right = 520;\n    window_rect.bottom = 250;\n''',
    '''    window_rect.right = 520;\n    window_rect.bottom = 282;\n''',
    "grow launcher window",
)

LAUNCHER.write_text(launcher, encoding="utf-8")


# ---------------------------------------------------------------------------
# Runtime diagnostics + first real attempt.
#
# v0.2 replaced the two VP6 files with zero-byte placeholders and could crash.
# v0.3 only toggled the internal ENABLE_FRONTEND_MOVIES default and did not skip
# the startup clips. v0.35 keeps the old internal toggle as a secondary signal,
# but the actual new attempt is runtime-only: when SkipIntro=1, exact opens of
# easports.vp6 or mvpintro.vp6 are reported as ERROR_FILE_NOT_FOUND. This leaves
# the user's movie files completely untouched and is instantly reversible by
# unchecking the launcher option.
#
# The dedicated log is intentionally independent of the large controller log.
# It records the internal-signature result plus the module/offset of each exact
# VP6 open request, giving us a direct patch target if MVP does not tolerate a
# missing-file result cleanly.
# ---------------------------------------------------------------------------
runtime = replace_once(
    runtime,
    'static int skip_intro_enabled;\n',
    'static int skip_intro_enabled;\nstatic HANDLE intro_diag_log_handle = INVALID_HANDLE_VALUE;\n',
    "intro diagnostic global",
)

marker = 'static void patch_frontend_movies_default_in_memory(void)\n'
if runtime.count(marker) != 1:
    raise SystemExit(f"skip intro v35 internal patch marker: found {runtime.count(marker)}")

helpers = r'''static void intro_diag_write(const char *text)
{
    DWORD written;
    if (intro_diag_log_handle == INVALID_HANDLE_VALUE || !text) return;
    WriteFile(intro_diag_log_handle, text, (DWORD)lstrlenA(text), &written, NULL);
    FlushFileBuffers(intro_diag_log_handle);
}

static void intro_diag_logf(const char *fmt, ...)
{
    char message[1536];
    char line[1792];
    SYSTEMTIME st;
    va_list args;
    int n;
    if (intro_diag_log_handle == INVALID_HANDLE_VALUE) return;
    va_start(args, fmt);
    n = vsnprintf(message, sizeof(message), fmt, args);
    va_end(args);
    if (n < 0) message[0] = 0;
    message[sizeof(message) - 1] = 0;
    GetLocalTime(&st);
    snprintf(line, sizeof(line),
        "[%04u-%02u-%02u %02u:%02u:%02u.%03u] pid=%lu tid=%lu %s\r\n",
        st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond,
        st.wMilliseconds, (unsigned long)GetCurrentProcessId(),
        (unsigned long)GetCurrentThreadId(), message);
    line[sizeof(line) - 1] = 0;
    intro_diag_write(line);
}

static void intro_diag_open_log(void)
{
    char path[MAX_PATH];
    char image[MAX_PATH];
    if (!skip_intro_enabled || intro_diag_log_handle != INVALID_HANDLE_VALUE) return;
    if (!get_module_dir(path, sizeof(path)) ||
        !append_path(path, sizeof(path), "MVP2005Modern-Intro.log")) return;
    /* Called before the existing CreateFile hooks are installed. */
    intro_diag_log_handle = CreateFileA(path, GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL, NULL);
    if (intro_diag_log_handle == INVALID_HANDLE_VALUE) return;
    image[0] = 0;
    GetModuleFileNameA(NULL, image, sizeof(image));
    image[sizeof(image) - 1] = 0;
    intro_diag_logf("MVP2005 Modern Skip Intro diagnostics v35");
    intro_diag_logf("skip_intro=1 image=\"%s\" base=%p", image, GetModuleHandleA(NULL));
}

static int intro_diag_target_path(const char *path)
{
    const char *base;
    const char *p;
    if (!path || !*path) return 0;
    base = path;
    for (p = path; *p; p++) {
        if (*p == '\\' || *p == '/') base = p + 1;
    }
    return _stricmp(base, "easports.vp6") == 0 ||
        _stricmp(base, "mvpintro.vp6") == 0;
}

static void intro_diag_describe_caller(void *caller, char *out, DWORD out_size)
{
    MEMORY_BASIC_INFORMATION mbi;
    char module[MAX_PATH];
    HMODULE base = NULL;
    if (!out_size) return;
    out[0] = 0;
    ZeroMemory(&mbi, sizeof(mbi));
    if (caller && VirtualQuery(caller, &mbi, sizeof(mbi)) == sizeof(mbi))
        base = (HMODULE)mbi.AllocationBase;
    module[0] = 0;
    if (base) GetModuleFileNameA(base, module, sizeof(module));
    module[sizeof(module) - 1] = 0;
    if (base)
        snprintf(out, out_size, "%s+0x%08lx", module[0] ? module : "<module>",
            (unsigned long)((BYTE *)caller - (BYTE *)base));
    else
        snprintf(out, out_size, "unknown@%p", caller);
    out[out_size - 1] = 0;
}

'''
runtime = runtime.replace(marker, helpers + marker, 1)

runtime = replace_regex_once(
    runtime,
    r'''static void patch_frontend_movies_default_in_memory\(void\)\n\{.*?\n\}\n\n(?=static BOOL WINAPI fake_GetDiskFreeSpaceExA)''',
    r'''static void patch_frontend_movies_default_in_memory(void)
{
    static const BYTE signature[] = {
        0xB0, 0x01, 0x33, 0xC9,
        0x88, 0x46, 0x38,
        0x88, 0x46, 0x39,
        0x88, 0x46, 0x3A,
        0x88, 0x46, 0x3C,
        0x88, 0x46, 0x3D,
        0x88, 0x46, 0x3E,
        0x88, 0x46, 0x3F,
        0x88, 0x46, 0x40
    };
    BYTE *base;
    IMAGE_DOS_HEADER *dos;
    IMAGE_NT_HEADERS *nt;
    IMAGE_SECTION_HEADER *section;
    BYTE *match = NULL;
    DWORD matches = 0;
    DWORD old_protect;
    WORD s;
    DWORD i;

    if (!skip_intro_enabled) return;
    intro_diag_open_log();

    base = (BYTE *)GetModuleHandleA(NULL);
    if (!base) {
        intro_diag_logf("internal flag probe: main module base unavailable");
        return;
    }
    dos = (IMAGE_DOS_HEADER *)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
        intro_diag_logf("internal flag probe: bad DOS signature");
        return;
    }
    nt = (IMAGE_NT_HEADERS *)(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) {
        intro_diag_logf("internal flag probe: bad NT signature");
        return;
    }

    section = IMAGE_FIRST_SECTION(nt);
    for (s = 0; s < nt->FileHeader.NumberOfSections; s++, section++) {
        DWORD size = section->Misc.VirtualSize;
        BYTE *start;
        if (memcmp(section->Name, ".text\0\0\0", IMAGE_SIZEOF_SHORT_NAME) != 0) continue;
        if (size < sizeof(signature)) continue;
        start = base + section->VirtualAddress;
        for (i = 0; i <= size - sizeof(signature); i++) {
            if (memcmp(start + i, signature, sizeof(signature)) == 0) {
                match = start + i;
                matches++;
            }
        }
    }

    intro_diag_logf("internal ENABLE_FRONTEND_MOVIES signature matches=%lu",
        (unsigned long)matches);
    if (matches != 1) return;

    intro_diag_logf("internal signature rva=0x%08lx target_modrm_before=0x%02x",
        (unsigned long)(match - base), (unsigned int)match[11]);
    if (!VirtualProtect(match + 11, 1, PAGE_EXECUTE_READWRITE, &old_protect)) {
        intro_diag_logf("internal flag patch VirtualProtect failed winerr=%lu",
            (unsigned long)GetLastError());
        return;
    }
    match[11] = 0x4E;
    FlushInstructionCache(GetCurrentProcess(), match + 10, 3);
    VirtualProtect(match + 11, 1, old_protect, &old_protect);
    intro_diag_logf("internal flag patch applied target_modrm_after=0x%02x",
        (unsigned int)match[11]);
}

''',
    "diagnostic internal movie flag patch",
)

# Reuse the CreateFile hooks already installed for the controller runtime. This
# avoids competing MinHook detours on the same Kernel32 exports.
runtime = replace_regex_once(
    runtime,
    r'''static HANDLE WINAPI controller_diag_CreateFileA\(LPCSTR name, DWORD access, DWORD share,\n    LPSECURITY_ATTRIBUTES sa, DWORD disposition, DWORD flags, HANDLE template_file\)\n\{.*?\n\}\n\nstatic HANDLE WINAPI controller_diag_CreateFileW\(LPCWSTR name, DWORD access, DWORD share,\n    LPSECURITY_ATTRIBUTES sa, DWORD disposition, DWORD flags, HANDLE template_file\)\n\{.*?\n\}\n\n(?=static BOOL WINAPI controller_diag_ReadFile)''',
    r'''static HANDLE WINAPI controller_diag_CreateFileA(LPCSTR name, DWORD access, DWORD share,
    LPSECURITY_ATTRIBUTES sa, DWORD disposition, DWORD flags, HANDLE template_file)
{
    int intro_target = name && intro_diag_target_path(name);
    HANDLE h;
    if (intro_target) {
        char caller[2 * MAX_PATH];
        void *return_address = __builtin_return_address(0);
        intro_diag_describe_caller(return_address, caller, sizeof(caller));
        intro_diag_logf("VP6 OPEN A path=\"%s\" access=0x%08lx share=0x%08lx disposition=%lu caller=%s",
            name, (unsigned long)access, (unsigned long)share,
            (unsigned long)disposition, caller);
        if (skip_intro_enabled) {
            intro_diag_logf("VP6 BLOCK A path=\"%s\" -> ERROR_FILE_NOT_FOUND", name);
            SetLastError(ERROR_FILE_NOT_FOUND);
            return INVALID_HANDLE_VALUE;
        }
    }

    h = controller_diag_real_CreateFileA ?
        controller_diag_real_CreateFileA(name, access, share, sa, disposition, flags, template_file) : INVALID_HANDLE_VALUE;
    if (intro_target)
        intro_diag_logf("VP6 PASS A result=%p winerr=%lu", h, (unsigned long)GetLastError());
    if (name && controller_diag_contains_ci_a(name, "controller.cfg")) {
        int slot = controller_diag_track_handle(h);
        controller_diag_logf("CFG OPEN A handle=%p slot=%d access=%08lx disp=%lu path=%s",
            h, slot, (unsigned long)access, (unsigned long)disposition, name);
    }
    return h;
}

static HANDLE WINAPI controller_diag_CreateFileW(LPCWSTR name, DWORD access, DWORD share,
    LPSECURITY_ATTRIBUTES sa, DWORD disposition, DWORD flags, HANDLE template_file)
{
    char path[1024];
    int intro_target = 0;
    HANDLE h;
    path[0] = 0;
    if (name) {
        WideCharToMultiByte(CP_ACP, 0, name, -1, path, sizeof(path), NULL, NULL);
        path[sizeof(path) - 1] = 0;
        intro_target = intro_diag_target_path(path);
    }
    if (intro_target) {
        char caller[2 * MAX_PATH];
        void *return_address = __builtin_return_address(0);
        intro_diag_describe_caller(return_address, caller, sizeof(caller));
        intro_diag_logf("VP6 OPEN W path=\"%s\" access=0x%08lx share=0x%08lx disposition=%lu caller=%s",
            path, (unsigned long)access, (unsigned long)share,
            (unsigned long)disposition, caller);
        if (skip_intro_enabled) {
            intro_diag_logf("VP6 BLOCK W path=\"%s\" -> ERROR_FILE_NOT_FOUND", path);
            SetLastError(ERROR_FILE_NOT_FOUND);
            return INVALID_HANDLE_VALUE;
        }
    }

    h = controller_diag_real_CreateFileW ?
        controller_diag_real_CreateFileW(name, access, share, sa, disposition, flags, template_file) : INVALID_HANDLE_VALUE;
    if (intro_target)
        intro_diag_logf("VP6 PASS W result=%p winerr=%lu", h, (unsigned long)GetLastError());
    if (name && controller_diag_contains_ci_a(path, "controller.cfg")) {
        int slot = controller_diag_track_handle(h);
        controller_diag_logf("CFG OPEN W handle=%p slot=%d access=%08lx disp=%lu path=%s",
            h, slot, (unsigned long)access, (unsigned long)disposition, path);
    }
    return h;
}

''',
    "VP6 CreateFile interception",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern diagnostic runtime Skip Intro v35")
