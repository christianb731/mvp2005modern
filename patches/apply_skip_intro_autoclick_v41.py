from pathlib import Path

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"skip intro v41 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


runtime = replace_once(
    runtime,
    'intro_diag_logf("MVP2005 Modern Skip Intro diagnostics v40 SCCl endian-correct trim");',
    'intro_diag_logf("MVP2005 Modern Skip Intro diagnostics v41 guarded automatic skip input");',
    'diagnostic version header',
)

runtime = replace_once(
    runtime,
    'legacy ENABLE_FRONTEND_MOVIES byte patch retired; v40 uses self-consistent EA trim with endian-correct SCCl block count',
    'legacy ENABLE_FRONTEND_MOVIES byte patch retired; v41 keeps the validated trimmed cache and automatically reproduces the user-proven skip input',
    'diagnostic description',
)

marker = '''static HANDLE WINAPI controller_diag_CreateFileA(LPCSTR name, DWORD access, DWORD share,\
'''
if runtime.count(marker) != 1:
    raise SystemExit(f"skip intro v41 CreateFileA marker: found {runtime.count(marker)}")

helpers = r'''static volatile LONG intro_autoskip_state;

static DWORD WINAPI intro_autoskip_thread(LPVOID param)
{
    DWORD delay_ms = 350;
    DWORD pid = GetCurrentProcessId();
    DWORD fg_pid = 0;
    HWND fg = NULL;
    char title[160];
    POINT cursor;
    INPUT input;
    UINT sent_down;
    UINT sent_up;
    DWORD err_down = 0;
    DWORD err_up = 0;
    int attempt;

    (void)param;
    intro_diag_logf("AUTO SKIP thread begin delay_ms=%lu pid=%lu",
        (unsigned long)delay_ms, (unsigned long)pid);
    Sleep(delay_ms);

    /* Never inject into another application. Startup focus can settle a little
       after the worker thread opens the movie, so allow a short bounded wait
       for MVP to own the foreground window. */
    for (attempt = 0; attempt < 20; attempt++) {
        fg = GetForegroundWindow();
        fg_pid = 0;
        if (fg)
            GetWindowThreadProcessId(fg, &fg_pid);
        if (fg && fg_pid == pid)
            break;
        Sleep(50);
    }

    if (!fg || fg_pid != pid) {
        intro_diag_logf(
            "AUTO SKIP abort foreground_not_game hwnd=%p foreground_pid=%lu game_pid=%lu attempts=%d",
            fg, (unsigned long)fg_pid, (unsigned long)pid, attempt + 1);
        return 0;
    }

    title[0] = 0;
    GetWindowTextA(fg, title, sizeof(title));
    if (!GetCursorPos(&cursor)) {
        cursor.x = -1;
        cursor.y = -1;
    }
    intro_diag_logf(
        "AUTO SKIP target hwnd=%p foreground_pid=%lu title=\"%s\" cursor=%ld,%ld no_cursor_move=1",
        fg, (unsigned long)fg_pid, title, (long)cursor.x, (long)cursor.y);

    ZeroMemory(&input, sizeof(input));
    input.type = INPUT_MOUSE;
    input.mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
    SetLastError(ERROR_SUCCESS);
    sent_down = SendInput(1, &input, sizeof(input));
    err_down = GetLastError();
    intro_diag_logf("AUTO SKIP left_down sent=%u winerr=%lu hold_ms=120",
        (unsigned int)sent_down, (unsigned long)err_down);

    /* A real user click remains down across multiple game/input polls. Holding
       briefly is intentional: the user's single physical click was observed to
       skip the complete two-movie startup sequence. */
    Sleep(120);

    ZeroMemory(&input, sizeof(input));
    input.type = INPUT_MOUSE;
    input.mi.dwFlags = MOUSEEVENTF_LEFTUP;
    SetLastError(ERROR_SUCCESS);
    sent_up = SendInput(1, &input, sizeof(input));
    err_up = GetLastError();
    intro_diag_logf("AUTO SKIP left_up sent=%u winerr=%lu",
        (unsigned int)sent_up, (unsigned long)err_up);

    if (sent_down != 1 || sent_up != 1)
        intro_diag_logf("AUTO SKIP FAIL SendInput down=%u up=%u",
            (unsigned int)sent_down, (unsigned int)sent_up);
    else
        intro_diag_logf("AUTO SKIP PASS one guarded click injected");
    return 0;
}

static void intro_autoskip_schedule(const char *movie_path)
{
    HANDLE thread;

    /* The user's manual test showed one click during the EA Sports movie skips
       the whole startup sequence. Schedule exactly once, from the first movie,
       so there is no delayed second click that could land on the main menu. */
    if (!movie_path || !intro_diag_name_is(movie_path, "easports.vp6"))
        return;
    if (InterlockedCompareExchange(&intro_autoskip_state, 1, 0) != 0) {
        intro_diag_logf("AUTO SKIP already scheduled; ignoring duplicate open path=\"%s\"",
            movie_path);
        return;
    }

    intro_diag_logf("AUTO SKIP schedule path=\"%s\"", movie_path);
    thread = CreateThread(NULL, 0, intro_autoskip_thread, NULL, 0, NULL);
    if (!thread) {
        DWORD err = GetLastError();
        InterlockedExchange(&intro_autoskip_state, -1);
        intro_diag_logf("AUTO SKIP CreateThread failed winerr=%lu", (unsigned long)err);
        return;
    }
    CloseHandle(thread);
}

'''

runtime = runtime.replace(marker, helpers + marker, 1)

old_open = r'''                if (cached != INVALID_HANDLE_VALUE) {
                    intro_diag_logf("VP6 CACHE OPEN A result=%p", cached);
                    return cached;
                }
'''
new_open = r'''                if (cached != INVALID_HANDLE_VALUE) {
                    intro_diag_logf("VP6 CACHE OPEN A result=%p", cached);
                    intro_autoskip_schedule(name);
                    return cached;
                }
'''
runtime = replace_once(runtime, old_open, new_open, 'ANSI auto-skip schedule')

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern guarded automatic intro skip input v41")
