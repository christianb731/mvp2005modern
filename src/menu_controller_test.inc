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
    if (sscanf(command, "%lu %8s %7s %c", &parsed_serial, scene, button, &extra) != 3 ||
        !parsed_serial || parsed_serial > 0x7fffffffUL) return 0;
    *serial = parsed_serial;
    return 1;
}

static void init_menu_controller_test(const char *ini)
{
    static const char filename[] = "MVP2005Modern-MenuInput.txt";
    char executable[MAX_PATH], scene[9], button[8];
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

static WORD read_menu_test_buttons(DWORD scene, int eligible, WORD supported)
{
    static const struct { const char *name; WORD button; } buttons[] = {
        {"up", CXINPUT_DPAD_UP}, {"down", CXINPUT_DPAD_DOWN},
        {"left", CXINPUT_DPAD_LEFT}, {"right", CXINPUT_DPAD_RIGHT},
        {"a", CXINPUT_A}, {"b", CXINPUT_B}, {"y", CXINPUT_Y},
        {"lb", CXINPUT_LEFT_SHOULDER}, {"rb", CXINPUT_RIGHT_SHOULDER},
    };
    ULONGLONG now = GetTickCount64();
    unsigned long serial;
    char scene_name[9], button_name[8], line[144];
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
    if (!strcmp(scene_name, "modes")) expected_scene = MENU_SCENE_MODES;
    if (!strcmp(scene_name, "my_mvp")) expected_scene = MENU_SCENE_MY_MVP;
    if (!strcmp(scene_name, "options")) expected_scene = MENU_SCENE_OPTIONS;
    if (!strcmp(scene_name, "audio")) expected_scene = MENU_SCENE_AUDIO;
    if (!strcmp(scene_name, "gameplay")) expected_scene = MENU_SCENE_GAMEPLAY_OPTIONS;
    if (!strcmp(scene_name, "tuning")) expected_scene = MENU_SCENE_GAMEPLAY_TUNING;
    if (!strcmp(scene_name, "video")) expected_scene = MENU_SCENE_VIDEO;
    if (!strcmp(scene_name, "prompt")) expected_scene = MENU_SCENE_PROMPT;
    if (eligible && expected_scene && expected_scene == scene) {
        for (size_t i = 0; i < sizeof(buttons) / sizeof(buttons[0]); ++i) {
            if (!(buttons[i].button & supported) || strcmp(button_name, buttons[i].name)) continue;
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

static void trace_menu_test_grid(void *grid, DWORD grid_class, DWORD scene, int controller_focus)
{
    static __thread DWORD previous_scene;
    static __thread LONG previous_row = -1;
    static __thread LONG previous_column = -1;
    static __thread int previous_focus = -1;
    static __thread DWORD reported_unknown_grid_scene;
    const char *prefix = "";
    LONG row, column = -1;
    char line[128];

    if (!menu_test_input_path[0]) return;
    if (grid_class != MENU_ROW_GRID) {
        if (scene != MENU_SCENE_MAIN && scene != reported_unknown_grid_scene) {
            reported_unknown_grid_scene = scene;
            snprintf(line, sizeof(line), "menu test scene=%08lx grid class=%08lx unsupported\n",
                (unsigned long)scene, (unsigned long)grid_class);
            log_line(line);
        }
        return;
    }
    /* The mouse dispatcher compares its hit row to this field before selecting it. */
    memcpy(&row, (const BYTE *)grid + 0x68, sizeof(row));
    if (scene == MENU_SCENE_VIDEO) memcpy(&column, (const BYTE *)grid + 0x6c, sizeof(column));
    if (scene == previous_scene && row == previous_row && column == previous_column &&
        controller_focus == previous_focus) return;
    previous_scene = scene;
    previous_row = row;
    previous_column = column;
    previous_focus = controller_focus;
    if (scene == MENU_SCENE_MODES) prefix = "modes ";
    if (scene == MENU_SCENE_MY_MVP) prefix = "my_mvp ";
    if (scene == MENU_SCENE_OPTIONS) prefix = "options ";
    if (scene == MENU_SCENE_AUDIO) prefix = "audio ";
    if (scene == MENU_SCENE_PROMPT) prefix = "prompt ";
    if (scene == MENU_SCENE_GAMEPLAY_OPTIONS) prefix = "gameplay ";
    if (scene == MENU_SCENE_GAMEPLAY_TUNING) prefix = "tuning ";
    if (scene == MENU_SCENE_VIDEO) prefix = "video ";
    if (scene == MENU_SCENE_GAMEPLAY_OPTIONS || scene == MENU_SCENE_GAMEPLAY_TUNING || scene == MENU_SCENE_VIDEO) {
        LONG first;
        memcpy(&first, (const BYTE *)grid + 0x70, sizeof(first));
        if (scene == MENU_SCENE_VIDEO)
            snprintf(line, sizeof(line), "menu test video grid row=%ld controller_focus=%d first=%ld column=%ld\n",
                (long)row, controller_focus, (long)first, (long)column);
        else
            snprintf(line, sizeof(line), "menu test %sgrid row=%ld controller_focus=%d first=%ld\n",
                prefix, (long)row, controller_focus, (long)first);
    } else {
        snprintf(line, sizeof(line), "menu test %sgrid row=%ld controller_focus=%d\n",
            prefix, (long)row, controller_focus);
    }
    log_line(line);
}
