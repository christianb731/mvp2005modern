/* Test-build input provider for the isolated smoke game. The command file
 * contains a serial number, an expected scene name, and one button name. */
static char menu_test_input_path[MAX_PATH];
static unsigned long menu_test_initial_serial;
static __thread unsigned long menu_test_serial;
static __thread ULONGLONG menu_test_poll_at;
static __thread ULONGLONG menu_test_release_at;
static __thread WORD menu_test_button;

static int read_menu_test_command(unsigned long *serial, char *scene, char *button)
{
    char command[64], extra;
    DWORD length = 0;
    HANDLE input = CreateFileA(menu_test_input_path, GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL, NULL);
    if (input == INVALID_HANDLE_VALUE) return 0;
    BOOL read = ReadFile(input, command, sizeof(command), &length, NULL);
    CloseHandle(input);
    if (!read || !length || length == sizeof(command) || memchr(command, 0, length)) return 0;
    command[length] = '\0';
    unsigned long parsed_serial;
    if (sscanf(command, "%lu %7s %7s %c", &parsed_serial, scene, button, &extra) != 3 ||
        !parsed_serial || parsed_serial > 0x7fffffffUL) return 0;
    *serial = parsed_serial;
    return 1;
}

static void init_menu_controller_test(const char *ini)
{
    static const char filename[] = "MVP2005Modern-MenuInput.txt";
    char executable[MAX_PATH], scene[8], button[8];
    DWORD length = GetModuleFileNameA(NULL, executable, sizeof(executable));
    const char *separator = strrchr(ini, '\\');
    size_t directory_length = separator ? (size_t)(separator + 1 - ini) : 0;
    const char *basename = length && length < sizeof(executable) ? strrchr(executable, '\\') : NULL;

    if (!GetPrivateProfileIntA("MenuControllerTest", "Enabled", 0, ini)) return;
    if (!basename || _stricmp(basename + 1, "MVP2005Smoke.exe") ||
        !directory_length || directory_length + sizeof(filename) > sizeof(menu_test_input_path)) {
        log_line("menu test input unavailable: expected isolated MVP2005Smoke.exe and launcher folder\n");
        return;
    }
    memcpy(menu_test_input_path, ini, directory_length);
    memcpy(menu_test_input_path + directory_length, filename, sizeof(filename));
    /* The existing command belongs to the previous run. */
    read_menu_test_command(&menu_test_initial_serial, scene, button);
    log_line("menu test input enabled for isolated MVP2005Smoke.exe\n");
}

static WORD read_menu_test_buttons(DWORD scene, int eligible)
{
    static const struct { const char *name; WORD button; } buttons[] = {
        {"up", CXINPUT_DPAD_UP}, {"down", CXINPUT_DPAD_DOWN},
        {"left", CXINPUT_DPAD_LEFT}, {"right", CXINPUT_DPAD_RIGHT},
        {"a", CXINPUT_A}, {"b", CXINPUT_B},
    };
    ULONGLONG now = GetTickCount64();
    unsigned long serial;
    char scene_name[8], button_name[8], line[144];
    DWORD expected_scene = 0;

    if (!eligible || now >= menu_test_release_at) menu_test_button = 0;
    if (now < menu_test_poll_at || menu_test_button) return menu_test_button;
    menu_test_poll_at = now + 32;
    if (!read_menu_test_command(&serial, scene_name, button_name) ||
        serial <= menu_test_initial_serial || serial <= menu_test_serial) return 0;
    menu_test_serial = serial;
    if (!strcmp(scene_name, "main")) expected_scene = MENU_SCENE_MAIN;
    if (!strcmp(scene_name, "team")) expected_scene = MENU_SCENE_TEAM;
    if (!strcmp(scene_name, "title")) expected_scene = MENU_SCENE_TITLE;
    if (eligible && expected_scene && expected_scene == scene) {
        for (size_t i = 0; i < sizeof(buttons) / sizeof(buttons[0]); ++i) {
            if (strcmp(button_name, buttons[i].name)) continue;
            menu_test_button = buttons[i].button;
            menu_test_release_at = now + 110;
            /* Give the controller edge detector at least one neutral frame before another command. */
            menu_test_poll_at = menu_test_release_at + 32;
            break;
        }
    }
    snprintf(line, sizeof(line), "menu test input serial=%lu scene=%08lx button=%s %s\n",
        serial, (unsigned long)scene, button_name, menu_test_button ? "accepted" : "rejected");
    log_line(line);
    return menu_test_button;
}

static void trace_menu_test_grid(void *grid, int controller_focus)
{
    static __thread LONG previous_row = -1;
    static __thread int previous_focus = -1;
    LONG row;
    char line[96];

    if (!menu_test_input_path[0] || gfx_caller_rva(*(void **)grid) != 0x0049f5d0) return;
    /* The mouse dispatcher compares its hit row to this field before selecting it. */
    memcpy(&row, (const BYTE *)grid + 0x68, sizeof(row));
    if (row == previous_row && controller_focus == previous_focus) return;
    previous_row = row;
    previous_focus = controller_focus;
    snprintf(line, sizeof(line), "menu test grid row=%ld controller_focus=%d\n",
        (long)row, controller_focus);
    log_line(line);
}
