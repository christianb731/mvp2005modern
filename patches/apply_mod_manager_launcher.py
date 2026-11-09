"""Open the ZIP mod manager for the game selected in the launcher."""

from pathlib import Path


launcher = Path("src/launcher.c")
source = launcher.read_text(encoding="utf-8")


def insert_before(anchor: str, addition: str) -> None:
    global source
    if source.count(anchor) != 1:
        raise SystemExit(f"Expected one mod manager launcher anchor: {anchor.strip()}")
    source = source.replace(anchor, addition + anchor, 1)


insert_before("#define WM_AUTOLAUNCH", "#define ID_MOD_MANAGER 1016\n")
insert_before("static void do_launch(HWND hwnd)\n", r'''static HANDLE mod_manager_process;

static int mod_manager_is_open(void)
{
    if (!mod_manager_process) return 0;
    if (WaitForSingleObject(mod_manager_process, 0) == WAIT_TIMEOUT) return 1;
    CloseHandle(mod_manager_process);
    mod_manager_process = NULL;
    return 0;
}

static void do_mod_manager(HWND hwnd)
{
    char exe_path[MAX_PATH], game_dir[MAX_PATH], app_dir[MAX_PATH], script[MAX_PATH];
    char windows_dir[MAX_PATH], python[MAX_PATH], command[3 * MAX_PATH + 40];
    UINT size;
    STARTUPINFOA startup = {0};
    PROCESS_INFORMATION child;

    if (mod_manager_is_open()) {
        MessageBoxA(hwnd, "The Mod Manager is already open.", "Mod Manager", MB_OK);
        return;
    }
    GetWindowTextA(exe_edit, exe_path, sizeof(exe_path));
    path_dirname(exe_path, game_dir, sizeof(game_dir));
    if (!file_exists(exe_path) || !game_dir[0]) {
        MessageBoxA(hwnd, "Select the game's executable first.", "Mod Manager", MB_ICONERROR);
        return;
    }
    get_app_dir(app_dir, sizeof(app_dir));
    join_path(script, sizeof(script), app_dir, "tools\\mod_manager.pyw");
    if (!file_exists(script)) {
        MessageBoxA(hwnd, "Extract the tools folder beside the launcher.", "Mod Manager", MB_ICONERROR);
        return;
    }
    size = GetWindowsDirectoryA(windows_dir, sizeof(windows_dir));
    if (!size || size >= sizeof(windows_dir)) return;
    join_path(python, sizeof(python), windows_dir, "pyw.exe");
    if (!file_exists(python)) {
        MessageBoxA(hwnd, "Install Python 3.11 or later with Tkinter and the Windows Python Launcher.",
            "Mod Manager", MB_ICONERROR);
        return;
    }
    /* path_dirname leaves a separator. Append a dot before the closing quote. */
    snprintf(command, sizeof(command), "\"%s\" -3 -E -B \"%s\" --game \"%s.\"",
        python, script, game_dir);
    startup.cb = sizeof(startup);
    if (!CreateProcessA(python, command, NULL, NULL, FALSE, 0, NULL, app_dir, &startup, &child)) {
        MessageBoxA(hwnd, "Could not open the Mod Manager.", "Mod Manager", MB_ICONERROR);
        return;
    }
    CloseHandle(child.hThread);
    mod_manager_process = child.hProcess;
}

''')

anchor = "    const ResolutionOption *res;\n\n    if (!get_selected(hwnd, exe_path, sizeof(exe_path), game_dir, sizeof(game_dir), &res)) return;\n"
position = source.index("static void do_launch(HWND hwnd)\n")
before, launch = source[:position], source[position:]
if not launch.startswith("static void do_launch(HWND hwnd)\n{\n    char exe_path[MAX_PATH];\n    char game_dir[MAX_PATH];\n" + anchor):
    raise SystemExit("Expected the game launch entry point for the mod manager")
launch = launch.replace("    if (!get_selected", '''    if (mod_manager_is_open()) {
        MessageBoxA(hwnd, "Close the Mod Manager before starting the game.", "Mod Manager", MB_OK);
        return;
    }
    if (!get_selected''', 1)
source = before + launch

insert_before('        CreateWindowA("BUTTON", "Verify / Repair"', '''        CreateWindowA("BUTTON", "Mods...", WS_CHILD | WS_VISIBLE | WS_TABSTOP,
            12, 206, 74, 26, hwnd, (HMENU)ID_MOD_MANAGER, NULL, NULL);
''')
insert_before("        case ID_SETUP_REPAIR:", '''        case ID_MOD_MANAGER:
            do_mod_manager(hwnd);
            return 0;
''')
insert_before("        PostQuitMessage(0);", '''        if (mod_manager_process) CloseHandle(mod_manager_process);
''')
launcher.write_text(source, encoding="utf-8")
print("Applied MVP2005 Modern ZIP mod manager launcher")
