from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"skip intro v36 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


runtime = replace_once(
    runtime,
    'static HANDLE intro_diag_log_handle = INVALID_HANDLE_VALUE;\n',
    'static HANDLE intro_diag_log_handle = INVALID_HANDLE_VALUE;\nstatic LONG intro_diag_easports_dumped;\nstatic LONG intro_diag_mvpintro_dumped;\n',
    'trace globals',
)

marker = 'static int intro_diag_target_path(const char *path)\n'
if runtime.count(marker) != 1:
    raise SystemExit(f"skip intro v36 trace helper marker: found {runtime.count(marker)}")

helpers = r'''static void intro_diag_describe_caller(void *caller, char *out, DWORD out_size);
typedef USHORT (WINAPI *IntroRtlCaptureStackBackTraceFn)(ULONG, ULONG, PVOID *, PULONG);

static int intro_diag_name_is(const char *path, const char *name)
{
    const char *base;
    const char *p;
    if (!path || !name) return 0;
    base = path;
    for (p = path; *p; p++) if (*p == '\\' || *p == '/') base = p + 1;
    return _stricmp(base, name) == 0;
}

static void intro_diag_dump_code(void *caller)
{
    BYTE *p = (BYTE *)caller;
    MEMORY_BASIC_INFORMATION mbi;
    BYTE *start;
    BYTE *end;
    BYTE *cur;
    char line[768];
    size_t used;
    int count;

    ZeroMemory(&mbi, sizeof(mbi));
    if (!caller || VirtualQuery(caller, &mbi, sizeof(mbi)) != sizeof(mbi)) {
        intro_diag_logf("CODE dump unavailable caller=%p", caller);
        return;
    }
    start = p - 48;
    end = p + 112;
    if (start < (BYTE *)mbi.BaseAddress) start = (BYTE *)mbi.BaseAddress;
    if (end > (BYTE *)mbi.BaseAddress + mbi.RegionSize)
        end = (BYTE *)mbi.BaseAddress + mbi.RegionSize;

    intro_diag_logf("CODE dump caller=%p range=%p..%p (caller is offset +48 when full range is readable)",
        caller, start, end);
    cur = start;
    while (cur < end) {
        int i;
        count = (int)(end - cur);
        if (count > 16) count = 16;
        used = (size_t)snprintf(line, sizeof(line), "CODE %p:", cur);
        for (i = 0; i < count && used + 4 < sizeof(line); i++)
            used += (size_t)snprintf(line + used, sizeof(line) - used, " %02X", cur[i]);
        line[sizeof(line) - 1] = 0;
        intro_diag_logf("%s", line);
        cur += count;
    }
}

static void intro_diag_dump_stack(void)
{
    HMODULE ntdll = GetModuleHandleA("ntdll.dll");
    IntroRtlCaptureStackBackTraceFn capture = NULL;
    FARPROC proc = NULL;
    PVOID frames[24];
    USHORT count = 0;
    USHORT i;

    if (ntdll) proc = GetProcAddress(ntdll, "RtlCaptureStackBackTrace");
    if (!proc) {
        HMODULE k32 = GetModuleHandleA("kernel32.dll");
        if (k32) proc = GetProcAddress(k32, "RtlCaptureStackBackTrace");
    }
    if (proc) memcpy(&capture, &proc, sizeof(capture));
    if (!capture) {
        intro_diag_logf("STACK capture unavailable");
        return;
    }

    ZeroMemory(frames, sizeof(frames));
    count = capture(0, 24, frames, NULL);
    intro_diag_logf("STACK frames=%u", (unsigned int)count);
    for (i = 0; i < count; i++) {
        char desc[2 * MAX_PATH];
        intro_diag_describe_caller(frames[i], desc, sizeof(desc));
        intro_diag_logf("STACK[%u] %p %s", (unsigned int)i, frames[i], desc);
    }
}

static void intro_diag_trace_once(const char *path, void *caller)
{
    LONG *slot = NULL;
    if (intro_diag_name_is(path, "easports.vp6")) slot = &intro_diag_easports_dumped;
    else if (intro_diag_name_is(path, "mvpintro.vp6")) slot = &intro_diag_mvpintro_dumped;
    if (!slot || InterlockedCompareExchange(slot, 1, 0) != 0) return;

    intro_diag_logf("TRACE BEGIN path=\"%s\" caller=%p", path, caller);
    intro_diag_dump_code(caller);
    intro_diag_dump_stack();
    intro_diag_logf("TRACE END path=\"%s\"", path);
}

'''
runtime = runtime.replace(marker, helpers + marker, 1)

# v0.35 proved ERROR_FILE_NOT_FOUND causes MVP to spin/retry and hang. In v0.36
# we explicitly restore normal movie I/O while keeping the same checkbox as the
# trigger for a one-boot diagnostic trace. The user's files stay untouched.
old_a = r'''        if (skip_intro_enabled) {
            intro_diag_logf("VP6 BLOCK A path=\"%s\" -> ERROR_FILE_NOT_FOUND", name);
            SetLastError(ERROR_FILE_NOT_FOUND);
            return INVALID_HANDLE_VALUE;
        }
'''
new_a = r'''        if (skip_intro_enabled) {
            intro_diag_logf("VP6 TRACE A path=\"%s\"; v0.36 passes file through normally", name);
            intro_diag_trace_once(name, return_address);
        }
'''
runtime = replace_once(runtime, old_a, new_a, 'remove ANSI missing-file block')

old_w = r'''        if (skip_intro_enabled) {
            intro_diag_logf("VP6 BLOCK W path=\"%s\" -> ERROR_FILE_NOT_FOUND", path);
            SetLastError(ERROR_FILE_NOT_FOUND);
            return INVALID_HANDLE_VALUE;
        }
'''
new_w = r'''        if (skip_intro_enabled) {
            intro_diag_logf("VP6 TRACE W path=\"%s\"; v0.36 passes file through normally", path);
            intro_diag_trace_once(path, return_address);
        }
'''
runtime = replace_once(runtime, old_w, new_w, 'remove Unicode missing-file block')

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern Skip Intro callsite trace v36")
