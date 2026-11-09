/* MVP's native hit-test dispatcher calls the owning scene only after a
 * visible control accepts the current pointer position. Trace this path to
 * identify the controls and scenes that actually receive menu input. */
typedef BYTE (__attribute__((thiscall)) *MenuDispatchFn)(void *control, void *scene);
typedef void (__attribute__((thiscall)) *MenuFrameFn)(void *frontend);
typedef BYTE (__attribute__((thiscall)) *MenuActionFn)(void *frontend, DWORD player, DWORD action);
typedef void (__attribute__((thiscall)) *MenuSelectRowFn)(void *grid, LONG row);
typedef BYTE (__attribute__((thiscall)) *MenuSceneActionFn)(void *scene, DWORD player);
typedef void (__attribute__((thiscall)) *MenuQueueActionFn)(void *frontend, DWORD action, DWORD player);
static void *volatile menu_dispatch_original;
static void *volatile menu_scene_dispatch_original;
static void *volatile menu_grid_dispatch_original;
static void *volatile menu_frame_original;
static void *volatile menu_action_original;
static LONG menu_dispatch_samples;
static LONG menu_scene_samples;
static LONG menu_grid_samples;
static LONG menu_frame_samples;
static LONG menu_action_samples;
static int menu_trace_archive_opens;
static LONG menu_trace_archive_samples;
static int menu_trace_actions_enabled;
static int menu_controller_enabled;
static int menu_controller_title_enabled;
static int menu_controller_my_mvp_enabled;
static MenuQueueActionFn menu_controller_queue_action;
static int menu_trace_controls_enabled;
static volatile LONG menu_pointer_messages;
static __thread LONG menu_pointer_seen;
static __thread POINT menu_pointer_position;
static __thread int menu_controller_grid_focus;
static __thread void *menu_trace_frontend;
static __thread DWORD menu_controller_action;
static __thread int menu_controller_back_requested;

enum {
    MENU_SCENE_TITLE = 0x004b7900,
    MENU_SCENE_MAIN = 0x004b74b0,
    MENU_SCENE_MODES = 0x004a7db0,
    MENU_SCENE_MY_MVP = 0x004b8020,
    MENU_SCENE_OPTIONS = 0x004b71c0,
    MENU_SCENE_AUDIO = 0x004bebf0,
    MENU_SCENE_TEAM = 0x004bcdb8,
    MENU_SCENE_NAV = 0x004a5900,
    MENU_ROW_GRID = 0x0049f5d0,
    MENU_NAV_BUTTON = 0x0049c2a0,
    MENU_SELECT_ROW_RVA = 0x0020ee60,
    MENU_MAIN_ACTIVITY_RVA = 0x0028a460,
    MENU_NAV_ACTIVATE_RVA = 0x0023da50,
    MENU_QUEUE_ACTION_RVA = 0x001efee0,
    MENU_MY_MVP_COMMAND_RVA = 0x002b9320,
    MENU_ACTION_CONFIRM = 1,
    MENU_ACTION_CANCEL = 2,
    MENU_ACTION_BACK = 5,
    MENU_ACTION_UP = 6,
    MENU_ACTION_DOWN = 8
};

#ifdef MENU_CONTROLLER_TEST_BUILD
#include "menu_controller_test.inc"
#endif

static void menu_controller_pointer_message(HWND hwnd, UINT msg)
{
    if (menu_controller_enabled && hwnd == borderless_window &&
        ((msg != WM_MOUSEMOVE && is_client_coordinate_mouse_message(msg)) ||
         msg == WM_MOUSEWHEEL || msg == WM_MOUSEHWHEEL)) {
        InterlockedIncrement(&menu_pointer_messages);
    }
}

static int menu_controller_pointer_active(void)
{
    POINT current;
    LONG messages = InterlockedCompareExchange(&menu_pointer_messages, 0, 0);
    return messages != menu_pointer_seen || !GetCursorPos(&current) ||
        current.x != menu_pointer_position.x || current.y != menu_pointer_position.y ||
        ((GetAsyncKeyState(VK_LBUTTON) | GetAsyncKeyState(VK_RBUTTON) |
          GetAsyncKeyState(VK_MBUTTON)) & 0x8000);
}

static int menu_controller_grid_scene(DWORD scene)
{
    return scene == MENU_SCENE_MAIN || scene == MENU_SCENE_MODES ||
        scene == MENU_SCENE_MY_MVP || scene == MENU_SCENE_OPTIONS || scene == MENU_SCENE_AUDIO;
}

static int menu_controller_list_matches(DWORD scene, const void *grid)
{
    static const struct { DWORD scene; SHORT bounds[4]; } lists[] = {
        {MENU_SCENE_MODES, {322, 121, 243, 261}},
        {MENU_SCENE_MY_MVP, {320, 191, 245, 124}},
        {MENU_SCENE_OPTIONS, {82, 140, 245, 198}},
    };

    for (size_t i = 0; i < sizeof(lists) / sizeof(lists[0]); ++i) {
        if (scene == lists[i].scene)
            return !memcmp((const BYTE *)grid + 0x2a, lists[i].bounds, sizeof(lists[i].bounds));
    }
    return 0;
}

static BYTE menu_controller_confirm_my_mvp(void *grid, void *owner)
{
    void *entry = (*(void ***)owner)[0x108 / sizeof(void *)];
    MenuQueueActionFn select;
    LONG rows, columns, row, column;

    /* The stock grid click sends command 1 to this owner. It reads the selected
     * cell from the list initialized at owner+0x134. */
    if (*(void **)((BYTE *)owner + 0x134) != grid || !(((const BYTE *)grid)[0x28] & 1) ||
        gfx_caller_rva(entry) != MENU_MY_MVP_COMMAND_RVA) return 0;
    memcpy(&rows, (const BYTE *)grid + 0x50, sizeof(rows));
    memcpy(&columns, (const BYTE *)grid + 0x54, sizeof(columns));
    memcpy(&row, (const BYTE *)grid + 0x68, sizeof(row));
    memcpy(&column, (const BYTE *)grid + 0x6c, sizeof(column));
    if (row < 0 || row >= rows || column < 0 || column >= columns) return 0;
    menu_controller_action = 0;
    memcpy(&select, &entry, sizeof(select));
    select(owner, MENU_ACTION_CONFIRM, 0);
    return 1;
}

static void menu_controller_move_row(void *grid, void *owner, DWORD scene)
{
    void **vtable = *(void ***)grid;
    MenuSelectRowFn select_row;
    LONG row, rows, next;

    if (gfx_caller_rva(vtable) != MENU_ROW_GRID ||
        gfx_caller_rva(vtable[0x10c / sizeof(void *)]) != MENU_SELECT_ROW_RVA) return;
    memcpy(&rows, (const BYTE *)grid + 0x50, sizeof(rows));
    memcpy(&row, (const BYTE *)grid + 0x68, sizeof(row));
    if (rows <= 0 || row >= rows || (row < 0 && scene == MENU_SCENE_MAIN)) return;
    next = row < 0 ? 0 : row + (menu_controller_action == MENU_ACTION_UP ? -1 : 1);
    menu_controller_action = 0;
    if (scene == MENU_SCENE_MAIN) {
        void *activity = (*(void ***)owner)[0xf4 / sizeof(void *)];
        if (gfx_caller_rva(activity) == MENU_MAIN_ACTIVITY_RVA) {
            MenuSceneActionFn reset_idle;
            memcpy(&reset_idle, &activity, sizeof(reset_idle));
            reset_idle(owner, 0);
        }
    }
    if (next < 0 || next >= rows) return;
    memcpy(&select_row, &vtable[0x10c / sizeof(void *)], sizeof(select_row));
    select_row(grid, next);
}

static void trace_menu_archive_open(const char *path, HANDLE result)
{
    size_t length;
    DWORD error;
    char line[MAX_PATH + 80];

    if (!menu_trace_archive_opens || !path) return;
    length = strlen(path);
    if (length < 4 || _stricmp(path + length - 4, ".big") ||
        InterlockedIncrement(&menu_trace_archive_samples) > 300) return;
    error = GetLastError();
    snprintf(line, sizeof(line), "menu archive open %s error=%lu path=%s\n",
        result == INVALID_HANDLE_VALUE ? "failed" : "ok",
        (unsigned long)(result == INVALID_HANDLE_VALUE ? error : 0), path);
    log_line(line);
    SetLastError(error);
}

static BYTE __attribute__((thiscall)) trace_menu_dispatch(void *control, void *scene)
{
    MenuDispatchFn original;
    void *entry = InterlockedCompareExchangePointer(&menu_dispatch_original, NULL, NULL);
    DWORD control_class = 0xffffffffUL;
    DWORD scene_class = 0xffffffffUL;
    SHORT bounds[4] = {0};
    int sample = control && scene &&
        InterlockedCompareExchange(&menu_dispatch_samples, 0, 0) < 100;
    BYTE handled;

    if (!entry) return 0;
    memcpy(&original, &entry, sizeof(original));
    if (sample) {
        /* A handled click can release the current scene before it returns. */
        control_class = gfx_caller_rva(*(void **)control);
        scene_class = gfx_caller_rva(*(void **)scene);
        memcpy(bounds, (const BYTE *)control + 0x2a, sizeof(bounds));
    }
    handled = original(control, scene);
    if (sample && handled && InterlockedIncrement(&menu_dispatch_samples) <= 100) {
        char line[192];
        snprintf(line, sizeof(line),
            "menu control handled scene_rva=%08lx control_rva=%08lx rect=%d,%d %dx%d caller_rva=%08lx\n",
            (unsigned long)scene_class, (unsigned long)control_class,
            bounds[0], bounds[1], bounds[2], bounds[3],
            (unsigned long)gfx_caller_rva(__builtin_return_address(0)));
        log_line(line);
    }
    return handled;
}

static BYTE __attribute__((thiscall)) trace_menu_scene_dispatch(void *scene, void *owner)
{
    MenuDispatchFn original;
    void *entry = InterlockedCompareExchangePointer(&menu_scene_dispatch_original, NULL, NULL);
    DWORD scene_class = gfx_caller_rva(*(void **)scene);
    BYTE handled;

    if (!entry) return 0;
    memcpy(&original, &entry, sizeof(original));
    handled = original(scene, owner);
    if (handled && InterlockedIncrement(&menu_scene_samples) <= 100) {
        char line[128];
        snprintf(line, sizeof(line), "menu scene handled scene_rva=%08lx caller_rva=%08lx\n",
            (unsigned long)scene_class, (unsigned long)gfx_caller_rva(__builtin_return_address(0)));
        log_line(line);
    }
    return handled;
}

static BYTE __attribute__((thiscall)) trace_menu_grid_dispatch(void *grid, void *owner)
{
    MenuDispatchFn original;
    void *entry = InterlockedCompareExchangePointer(&menu_grid_dispatch_original, NULL, NULL);
    DWORD scene_class = owner ? gfx_caller_rva(*(void **)owner) : 0xffffffffUL;
    DWORD grid_class = gfx_caller_rva(*(void **)grid);
    /* Audio's native directional handlers retrieve the list cached at +0x140. */
    int list_matches = menu_controller_list_matches(scene_class, grid) ||
        (scene_class == MENU_SCENE_AUDIO && *(void **)((BYTE *)owner + 0x140) == grid);
    SHORT bounds[4];
    BYTE handled;

    if (!entry) return 0;
    memcpy(&original, &entry, sizeof(original));
#ifdef MENU_CONTROLLER_TEST_BUILD
    if (scene_class == MENU_SCENE_MAIN || list_matches)
        trace_menu_test_grid(grid, grid_class, scene_class, menu_controller_grid_focus);
#endif
    if (menu_controller_grid_focus && (scene_class == MENU_SCENE_MAIN ||
        (list_matches && grid_class == MENU_ROW_GRID))) {
        if (!menu_controller_pointer_active()) {
            /* The native directional actions scroll the grid. Select a row
             * through the same widget method used by the mouse instead. */
            if (menu_trace_frontend &&
                (menu_controller_action == MENU_ACTION_UP || menu_controller_action == MENU_ACTION_DOWN)) {
                menu_controller_move_row(grid, owner, scene_class);
            }
            if (menu_trace_frontend && scene_class == MENU_SCENE_MY_MVP &&
                menu_controller_action == MENU_ACTION_CONFIRM) {
                return menu_controller_confirm_my_mvp(grid, owner);
            }
            return 0;
        }
        menu_controller_grid_focus = 0;
        menu_controller_action = 0;
    }
    if (!menu_trace_controls_enabled) return original(grid, owner);
    memcpy(bounds, (const BYTE *)grid + 0x2a, sizeof(bounds));
    handled = original(grid, owner);
    if (handled && InterlockedIncrement(&menu_grid_samples) <= 100) {
        char line[176];
        snprintf(line, sizeof(line),
            "menu grid handled scene_rva=%08lx rect=%d,%d %dx%d caller_rva=%08lx grid_rva=%08lx\n",
            (unsigned long)scene_class, bounds[0], bounds[1], bounds[2], bounds[3],
            (unsigned long)gfx_caller_rva(__builtin_return_address(0)), (unsigned long)grid_class);
        log_line(line);
    }
    return handled;
}

enum {
    MENU_SCENE_ARRAY = 0x38,
    MENU_SCENE_COUNT = 0x1c8,
    MENU_SCENE_CAPACITY = (MENU_SCENE_COUNT - MENU_SCENE_ARRAY) / sizeof(void *),
    MENU_ACTION_PLAYERS = 2,
    MENU_ACTION_COUNT = 25
};

/* The native frame owns these objects for the duration of its dispatch. */
static __thread DWORD menu_trace_actions[MENU_ACTION_PLAYERS];
static __thread DWORD menu_previous_actions[MENU_ACTION_PLAYERS];
static __thread DWORD menu_previous_scenes[MENU_SCENE_CAPACITY];
static __thread DWORD menu_controller_scene;
static __thread DWORD menu_controller_slot;
static __thread WORD menu_controller_previous;
static __thread int menu_controller_armed;
static __thread DWORD menu_controller_release;

static DWORD read_menu_scene_stack(void *frontend, DWORD *scenes)
{
    const BYTE *manager = *(const BYTE **)((const BYTE *)frontend + 0xa0);
    DWORD count;

    if (!manager) return 0;
    count = *(const DWORD *)(manager + MENU_SCENE_COUNT);
    if (count > MENU_SCENE_CAPACITY) return 0;
    for (DWORD i = 0; i < count; ++i) {
        const BYTE *scene = ((const BYTE *const *)(manager + MENU_SCENE_ARRAY))[i];
        if (scene && (scene[0x28] & 2)) scenes[i] = gfx_caller_rva(*(void *const *)scene);
    }
    return count;
}

static void trace_menu_scene_stack(const DWORD *scenes, DWORD count)
{
    if (!memcmp(scenes, menu_previous_scenes, sizeof(menu_previous_scenes))) return;
    memcpy(menu_previous_scenes, scenes, sizeof(menu_previous_scenes));
    if (InterlockedIncrement(&menu_frame_samples) <= 100) {
        char line[128];
        log_line("menu active scene stack changed\n");
        for (DWORD i = 0; i < count; ++i) {
            if (!scenes[i]) continue;
            snprintf(line, sizeof(line), "menu active scene index=%lu class_rva=%08lx\n",
                (unsigned long)i, (unsigned long)scenes[i]);
            log_line(line);
        }
    }
}

static DWORD menu_controller_active_scene(const DWORD *scenes, DWORD count)
{
    DWORD scene = 0;
    int team_controls = 0;
    int settings_controls = 0;
    int team_or_settings_controls = 0;

    for (DWORD i = 0; i < count; ++i) {
        switch (scenes[i]) {
        case 0:
        case 0x004ba980:
        case 0x004baad0:
        case MENU_SCENE_NAV:
        case 0x004a7070:
        case 0x004a5a50:
            break;
        case MENU_SCENE_TITLE:
            if (!menu_controller_title_enabled) return 0;
            if (scene) return 0;
            scene = scenes[i];
            break;
        case MENU_SCENE_MODES:
        case MENU_SCENE_OPTIONS:
        case MENU_SCENE_AUDIO:
            if (!menu_controller_queue_action) return 0;
            if (scene) return 0;
            scene = scenes[i];
            break;
        case MENU_SCENE_MY_MVP:
            if (!menu_controller_my_mvp_enabled) return 0;
            /* fall through */
        case MENU_SCENE_MAIN:
        case MENU_SCENE_TEAM:
            if (scene) return 0;
            scene = scenes[i];
            break;
        case 0x004a6458:
        case 0x004ba2e0:
        case 0x004a4fd0:
            team_controls = 1;
            break;
        case 0x004a9aa0:
            team_or_settings_controls = 1;
            break;
        case 0x004a0de8:
            settings_controls = 1;
            break;
        default:
            /* Other scenes include modal dialogs and the demo. */
            return 0;
        }
    }
    if ((team_controls && scene != MENU_SCENE_TEAM) ||
        (settings_controls && scene != MENU_SCENE_AUDIO) ||
        (team_or_settings_controls && scene != MENU_SCENE_TEAM && scene != MENU_SCENE_AUDIO)) return 0;
    return scene;
}

static int menu_controller_nav_back_scene(DWORD scene)
{
    return scene == MENU_SCENE_TEAM || scene == MENU_SCENE_MY_MVP;
}

static void menu_controller_back_via_nav(void *frontend, DWORD expected_scene)
{
    /* Resolve the live navigation bar again after native dispatch in case
     * another input changed the screen or opened a dialog. */
    DWORD scenes[MENU_SCENE_CAPACITY] = {0};
    DWORD count = read_menu_scene_stack(frontend, scenes);
    const BYTE *manager = *(const BYTE **)((const BYTE *)frontend + 0xa0);
    static const SHORT back_bounds[] = {31, 418, 148, 29};

    if (menu_controller_active_scene(scenes, count) != expected_scene ||
        GetForegroundWindow() != borderless_window) return;
    for (DWORD i = 0; i < count; ++i) {
        if (scenes[i] != MENU_SCENE_NAV) continue;
        BYTE *nav = ((BYTE *const *)(manager + MENU_SCENE_ARRAY))[i];
        void **vtable = *(void ***)nav;
        MenuDispatchFn activate;
        void *entry = vtable[0x120 / sizeof(void *)];
        if (gfx_caller_rva(entry) != MENU_NAV_ACTIVATE_RVA) continue;
        memcpy(&activate, &entry, sizeof(activate));
        for (DWORD j = 0; j < 4; ++j) {
            BYTE *button = ((BYTE *const *)(nav + 0x13c))[j];
            if (!button || !(button[0x28] & 1) ||
                gfx_caller_rva(*(void **)button) != MENU_NAV_BUTTON ||
                memcmp(button + 0x2a, back_bounds, sizeof(back_bounds))) continue;
            BYTE handled = activate(nav, button);
#ifdef MENU_CONTROLLER_TEST_BUILD
            if (menu_test_input_path[0]) {
                char line[80];
                snprintf(line, sizeof(line), "menu test %s back %s\n",
                    expected_scene == MENU_SCENE_TEAM ? "team" : "my_mvp", handled ? "handled" : "ignored");
                log_line(line);
            }
#else
            (void)handled;
#endif
            return;
        }
    }
}

static void sample_menu_controller(const DWORD *scenes, DWORD count)
{
    static const struct {
        WORD button;
        DWORD action;
        int left_right;
    } bindings[] = {
        {CXINPUT_A, MENU_ACTION_CONFIRM, 0},
        {CXINPUT_DPAD_UP, MENU_ACTION_UP, 0}, {CXINPUT_DPAD_DOWN, MENU_ACTION_DOWN, 0},
        {CXINPUT_DPAD_LEFT, 10, 1}, {CXINPUT_DPAD_RIGHT, 12, 1},
    };
    const WORD supported = CXINPUT_A | CXINPUT_B | CXINPUT_DPAD_UP | CXINPUT_DPAD_DOWN |
        CXINPUT_DPAD_LEFT | CXINPUT_DPAD_RIGHT;
    DWORD scene = menu_controller_active_scene(scenes, count);
    DWORD slot = 4;
    WORD held = 0;
    WORD pressed;
    int eligible = scene && borderless_window && GetForegroundWindow() == borderless_window &&
        !InterlockedCompareExchange(&gameplay_input_phase, 0, 0);

    menu_controller_action = 0;
#ifdef MENU_CONTROLLER_TEST_BUILD
    if (menu_test_input_path[0]) {
        held = read_menu_test_buttons(scene, eligible);
        if (eligible) slot = 0;
    } else
#endif
    if (eligible) {
        ControllerXInputGetStateFn get_state = controller_load_xinput_get_state();
        ControllerXInputState state;
        if (get_state) {
            for (slot = 0; slot < 4; ++slot) {
                if (get_state(slot, &state) == ERROR_SUCCESS) {
                    held = state.Gamepad.wButtons & supported;
                    break;
                }
            }
        }
    }

    if (scene != menu_controller_scene) {
        menu_controller_release = 0;
        menu_controller_armed = 0;
        menu_controller_grid_focus = 0;
    }
    if (slot != menu_controller_slot) menu_controller_armed = 0;
    menu_controller_scene = scene;
    menu_controller_slot = slot;
    if (eligible && menu_controller_release) {
        menu_controller_action = menu_controller_release;
        return;
    }
    if (slot == 4) {
        menu_controller_grid_focus = 0;
        return;
    }

    pressed = held & ~menu_controller_previous;
    menu_controller_previous = held;
    if (!menu_controller_armed) {
        menu_controller_armed = !held;
        return;
    }
    if (scene == MENU_SCENE_TITLE) {
        /* The title's click handler and action 5 share its start transition.
         * Action 1 has no handler on this scene. */
        if (pressed & CXINPUT_A) menu_controller_action = MENU_ACTION_BACK;
        return;
    }
    if ((pressed & CXINPUT_B) && scene != MENU_SCENE_MAIN &&
        (scene != MENU_SCENE_TEAM || !(pressed & CXINPUT_A))) {
        menu_controller_action = menu_controller_nav_back_scene(scene) ? MENU_ACTION_BACK : MENU_ACTION_CANCEL;
        return;
    }
    for (size_t i = 0; i < sizeof(bindings) / sizeof(bindings[0]); ++i) {
        if ((pressed & bindings[i].button) &&
            (!bindings[i].left_right || scene == MENU_SCENE_TEAM || scene == MENU_SCENE_AUDIO)) {
            if (menu_controller_grid_scene(scene) &&
                (bindings[i].action == MENU_ACTION_UP || bindings[i].action == MENU_ACTION_DOWN ||
                    scene == MENU_SCENE_MY_MVP) &&
                !menu_controller_grid_focus && GetCursorPos(&menu_pointer_position)) {
                menu_pointer_seen = InterlockedCompareExchange(&menu_pointer_messages, 0, 0);
                menu_controller_grid_focus = 1;
            }
            menu_controller_action = bindings[i].action;
            return;
        }
    }
}

static void __attribute__((thiscall)) trace_menu_frame(void *frontend)
{
    MenuFrameFn original;
    void *entry = InterlockedCompareExchangePointer(&menu_frame_original, NULL, NULL);
    DWORD scenes[MENU_SCENE_CAPACITY] = {0};
    DWORD count;

    if (!entry) return;
    memcpy(&original, &entry, sizeof(original));
    if (menu_trace_frontend) {
        original(frontend);
        return;
    }
    count = read_menu_scene_stack(frontend, scenes);
    if (menu_trace_actions_enabled) trace_menu_scene_stack(scenes, count);
    if (menu_controller_enabled) sample_menu_controller(scenes, count);
    menu_trace_frontend = frontend;
    menu_controller_back_requested = 0;
    memset(menu_trace_actions, 0, sizeof(menu_trace_actions));
    original(frontend);
    menu_trace_frontend = NULL;
    if (menu_controller_back_requested) menu_controller_back_via_nav(frontend, menu_controller_scene);
    for (DWORD player = 0; menu_trace_actions_enabled && player < MENU_ACTION_PLAYERS; ++player) {
        DWORD pressed = menu_trace_actions[player] & ~menu_previous_actions[player];
        menu_previous_actions[player] = menu_trace_actions[player];
        if (pressed && InterlockedIncrement(&menu_action_samples) <= 100) {
            char line[128];
            snprintf(line, sizeof(line), "menu native actions player=%lu pressed_mask=%08lx\n",
                (unsigned long)player, (unsigned long)pressed);
            log_line(line);
        }
    }
}

static BYTE __attribute__((thiscall)) trace_menu_action(void *frontend, DWORD player, DWORD action)
{
    MenuActionFn original;
    void *entry = InterlockedCompareExchangePointer(&menu_action_original, NULL, NULL);
    BYTE pressed;

    if (!entry) return 0;
    memcpy(&original, &entry, sizeof(original));
    pressed = original(frontend, player, action);
    if (frontend != menu_trace_frontend || player >= MENU_ACTION_PLAYERS ||
        action < 1 || action > MENU_ACTION_COUNT ||
        gfx_caller_rva(__builtin_return_address(0)) != 0x00242ecc) return pressed;

    if (menu_controller_enabled && player == 0 && action == menu_controller_action) {
        /* The original loop reaches this call after its pointer handlers. */
        menu_controller_action = 0;
        if (action == MENU_ACTION_BACK && menu_controller_nav_back_scene(menu_controller_scene)) {
            menu_controller_back_requested = 1;
            return pressed;
        }
        if (menu_controller_grid_scene(menu_controller_scene) &&
            (action == MENU_ACTION_UP || action == MENU_ACTION_DOWN)) return pressed;
        if (menu_controller_scene == MENU_SCENE_MY_MVP && action == MENU_ACTION_CONFIRM) return pressed;
        if (action == MENU_ACTION_CANCEL ||
            (menu_controller_scene == MENU_SCENE_AUDIO && action == MENU_ACTION_CONFIRM)) {
            /* Stock Back and Audio Accept queue the action for the transition's
             * second poll later in this frame. */
            if (pressed || ((const BYTE *)frontend)[0xc8]) return pressed;
            menu_controller_queue_action(frontend, action, player);
        }
        if (action == menu_controller_release) {
            menu_controller_release = 0;
        } else if (action >= 6 && action <= 12) {
            menu_controller_release = action + 1;
        }
        pressed = 1;
#ifdef MENU_CONTROLLER_TEST_BUILD
        if (menu_test_input_path[0]) {
            char line[96];
            snprintf(line, sizeof(line), "menu test dispatch scene=%08lx action=%lu\n",
                (unsigned long)menu_controller_scene, (unsigned long)action);
            log_line(line);
        }
#endif
    }
    if (pressed && menu_trace_actions_enabled) {
        menu_trace_actions[player] |= 1UL << (action - 1);
    }
    return pressed;
}

static int menu_trace_signature(BYTE *base, DWORD rva, const BYTE *expected, SIZE_T length)
{
    BYTE actual[16];
    SIZE_T bytes_read = 0;

    return length <= sizeof(actual) && gfx_caller_rva(base + rva + length - 1) != 0xffffffffUL &&
        ReadProcessMemory(GetCurrentProcess(), base + rva, actual, length, &bytes_read) &&
        bytes_read == length && !memcmp(actual, expected, length);
}

static void install_menu_action_trace(BYTE *base)
{
    static const BYTE frame_signature[] = {
        0x53, 0x55, 0x56, 0x8b, 0xf1, 0x8b, 0x86, 0xa0, 0x00, 0x00, 0x00
    };
    static const BYTE scene_signature[] = {
        0x8b, 0xb8, 0xc8, 0x01, 0x00, 0x00, 0x4f, 0xbb, 0x02, 0x00, 0x00, 0x00
    };
    static const BYTE action_signature[] = {
        0x53, 0x8b, 0x5c, 0x24, 0x08, 0x56, 0x57, 0x8b, 0x7c, 0x24, 0x14
    };
    static const BYTE caller_signature[] = {
        0xe8, 0xc4, 0xcf, 0xfa, 0xff, 0x84, 0xc0, 0x75, 0x07
    };
    static const BYTE row_signature[] = {
        0x8b, 0x51, 0x6c, 0x8b, 0x01, 0x52, 0x8b, 0x54, 0x24, 0x08, 0x52, 0xff, 0x90, 0x08, 0x01
    };
    static const BYTE back_signature[] = {
        0x53, 0x55, 0x8b, 0x6c, 0x24, 0x0c, 0x56, 0x57, 0x8b, 0xf9, 0x33, 0xdb
    };
    static const BYTE idle_signature[] = {
        0x81, 0xc1, 0x38, 0x01, 0x00, 0x00, 0xe8, 0x55, 0xcf, 0xf6, 0xff, 0xb0, 0x01, 0xc2, 0x04, 0x00
    };
    static const BYTE title_start_signature[] = {
        0x56, 0x8b, 0xf1, 0x83, 0xbe, 0xd8, 0x01, 0x00, 0x00, 0x03, 0x74, 0x06
    };
    static const BYTE queue_action_signature[] = {
        0x8b, 0x44, 0x24, 0x04, 0x8b, 0x54, 0x24, 0x08, 0xc6, 0x81, 0xc8, 0x00, 0x00, 0x00, 0x01
    };
    static const BYTE queue_action_tail[] = {
        0x89, 0x81, 0xcc, 0x00, 0x00, 0x00, 0x89, 0x91, 0xd0, 0x00, 0x00, 0x00, 0xc2, 0x08, 0x00
    };
    static const BYTE my_mvp_command_signature[] = {
        0x83, 0xec, 0x10, 0x8b, 0x44, 0x24, 0x14, 0x83, 0xe8, 0x00, 0x53, 0x8b, 0xd9
    };

    if (menu_controller_enabled &&
        (!menu_trace_signature(base, MENU_SELECT_ROW_RVA, row_signature, sizeof(row_signature)) ||
         !menu_trace_signature(base, MENU_MAIN_ACTIVITY_RVA, idle_signature, sizeof(idle_signature)) ||
         !menu_trace_signature(base, MENU_NAV_ACTIVATE_RVA, back_signature, sizeof(back_signature)))) {
        menu_controller_enabled = 0;
        log_line("menu controller disabled: unsupported row, idle timer, or navigation signature\n");
    }

    if (!menu_trace_signature(base, 0x00242da0, frame_signature, sizeof(frame_signature)) ||
        !menu_trace_signature(base, 0x00242dd7, scene_signature, sizeof(scene_signature)) ||
        !menu_trace_signature(base, 0x001efe90, action_signature, sizeof(action_signature)) ||
        !menu_trace_signature(base, 0x00242ec7, caller_signature, sizeof(caller_signature))) {
        log_line("menu action trace skipped: unsupported executable signature\n");
        return;
    }
    menu_controller_title_enabled = menu_controller_enabled &&
        menu_trace_signature(base, 0x002b7bd0, title_start_signature, sizeof(title_start_signature));
    if (menu_controller_enabled) {
        log_line(menu_controller_title_enabled ? "menu controller title enabled\n" :
            "menu controller title disabled: unsupported handler signature\n");
        if (menu_trace_signature(base, MENU_QUEUE_ACTION_RVA, queue_action_signature, sizeof(queue_action_signature)) &&
            menu_trace_signature(base, MENU_QUEUE_ACTION_RVA + sizeof(queue_action_signature),
                queue_action_tail, sizeof(queue_action_tail))) {
            void *queue = base + MENU_QUEUE_ACTION_RVA;
            memcpy(&menu_controller_queue_action, &queue, sizeof(menu_controller_queue_action));
        }
        log_line(menu_controller_queue_action ? "menu controller game modes enabled\n" :
            "menu controller game modes disabled: unsupported pending-action signature\n");
        menu_controller_my_mvp_enabled = menu_trace_signature(base, MENU_MY_MVP_COMMAND_RVA,
            my_mvp_command_signature, sizeof(my_mvp_command_signature));
        log_line(menu_controller_my_mvp_enabled ? "menu controller my mvp enabled\n" :
            "menu controller my mvp disabled: unsupported command signature\n");
    }
    log_line(hook_function(base + 0x00242da0, trace_menu_frame, &menu_frame_original) > 0 ?
        "menu frame trace installed\n" : "menu frame trace hook unavailable\n");
    log_line(hook_function(base + 0x001efe90, trace_menu_action, &menu_action_original) > 0 ?
        "menu action trace installed\n" : "menu action trace hook unavailable\n");
}

static void install_menu_control_trace(void)
{
    static const BYTE expected[] = {
        0x56, 0x8b, 0xf1, 0xf6, 0x46, 0x28, 0x01, 0x74,
        0x31, 0xe8, 0x52, 0xff, 0xff, 0xff, 0x50, 0xe8
    };
    static const BYTE scene_signature[] = {
        0x8a, 0x41, 0x28, 0xa8, 0x01, 0x0f, 0x84, 0x8f, 0x00, 0x00, 0x00, 0xa8, 0x02
    };
    static const BYTE grid_signature[] = {
        0x83, 0xec, 0x0c, 0x53, 0x55, 0x56, 0x57, 0x8b, 0xf1, 0xe8, 0x52, 0x1d, 0xfe, 0xff
    };
    const DWORD rva = 0x001f1d10;
    const DWORD scene_rva = 0x001fbf70;
    const DWORD grid_rva = 0x0020ff50;
    BYTE *base = (BYTE *)GetModuleHandleA(NULL);
    char ini[MAX_PATH];

    if (!base || !get_ini_path(ini, sizeof(ini))) return;
    menu_trace_actions_enabled = debug_logging &&
        GetPrivateProfileIntA("MenuDebug", "TraceActions", 0, ini) != 0;
    menu_controller_enabled = GetPrivateProfileIntA("MenuController", "Enabled", 0, ini) != 0;
#ifdef MENU_CONTROLLER_TEST_BUILD
    if (menu_controller_enabled) init_menu_controller_test(ini);
#endif
    menu_trace_archive_opens = debug_logging &&
        GetPrivateProfileIntA("MenuDebug", "TraceArchiveOpens", 0, ini) != 0;
    menu_trace_controls_enabled = debug_logging &&
        GetPrivateProfileIntA("MenuDebug", "TraceControls", 0, ini) != 0;
    if (menu_trace_controls_enabled || menu_controller_enabled) {
        if (menu_trace_signature(base, grid_rva, grid_signature, sizeof(grid_signature)) &&
            hook_function(base + grid_rva, trace_menu_grid_dispatch, &menu_grid_dispatch_original) > 0) {
            log_line("menu grid trace installed\n");
        } else {
            menu_controller_enabled = 0;
            log_line("menu grid hook unavailable\n");
        }
    }
    if (menu_trace_actions_enabled || menu_controller_enabled) install_menu_action_trace(base);
    if (!menu_trace_controls_enabled) return;
    if (!menu_trace_signature(base, rva, expected, sizeof(expected)) ||
        !menu_trace_signature(base, scene_rva, scene_signature, sizeof(scene_signature))) {
        log_line("menu control trace skipped: unsupported executable signature\n");
        return;
    }
    log_line(hook_function(base + rva, trace_menu_dispatch, &menu_dispatch_original) > 0 ?
        "menu control trace installed\n" : "menu control trace hook unavailable\n");
    log_line(hook_function(base + scene_rva, trace_menu_scene_dispatch, &menu_scene_dispatch_original) > 0 ?
        "menu scene trace installed\n" : "menu scene trace hook unavailable\n");
}

