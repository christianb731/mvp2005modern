from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"menu scale v43 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# D3D8 diagnostics + one conservative behavioral experiment.
#
# MVP's gameplay already renders at the requested HD resolution, while frontend
# input remains intentionally mapped into the game's 800x600 logical UI space.
# The safest first scaling hypothesis is therefore a too-small frontend viewport
# inside a larger render target.  v0.43 tests exactly that and nothing broader:
# when we are in frontend phase, SetViewport asks for 800x600 at (0,0), and the
# currently bound render target is larger, expand that viewport to the complete
# render target.  Mouse mapping remains unchanged, which should preserve hit
# testing if the frontend is simply using an 800x600 logical projection.
#
# If the render target is itself only 800x600, v0.43 deliberately does NOT force
# an invalid larger viewport.  The dedicated log then gives us CopyRects,
# SetRenderTarget, texture/surface creation, Present, viewport, and projection
# evidence to choose the next approach without guessing.
# ---------------------------------------------------------------------------

replace_once(
'''typedef HRESULT (WINAPI *PresentFn)(void *self, const RECT *source_rect,\n    const RECT *dest_rect, HWND dest_window_override, const RGNDATA *dirty_region);\n''',
'''typedef HRESULT (WINAPI *PresentFn)(void *self, const RECT *source_rect,\n    const RECT *dest_rect, HWND dest_window_override, const RGNDATA *dirty_region);\ntypedef struct D3DViewport8MenuLocal {\n    DWORD X;\n    DWORD Y;\n    DWORD Width;\n    DWORD Height;\n    float MinZ;\n    float MaxZ;\n} D3DViewport8MenuLocal;\ntypedef struct D3DSurfaceDesc8MenuLocal {\n    DWORD Format;\n    DWORD Type;\n    DWORD Usage;\n    DWORD Pool;\n    UINT Size;\n    DWORD MultiSampleType;\n    UINT Width;\n    UINT Height;\n} D3DSurfaceDesc8MenuLocal;\ntypedef HRESULT (WINAPI *SetViewportMenuFn)(void *self, const D3DViewport8MenuLocal *viewport);\ntypedef HRESULT (WINAPI *GetViewportMenuFn)(void *self, D3DViewport8MenuLocal *viewport);\ntypedef HRESULT (WINAPI *SetRenderTargetMenuFn)(void *self, void *render_target, void *depth_stencil);\ntypedef HRESULT (WINAPI *GetRenderTargetMenuFn)(void *self, void **render_target);\ntypedef HRESULT (WINAPI *GetBackBufferMenuFn)(void *self, UINT back_buffer, DWORD type, void **surface);\ntypedef HRESULT (WINAPI *CopyRectsMenuFn)(void *self, void *source_surface,\n    const RECT *source_rects, UINT rect_count, void *dest_surface, const POINT *dest_points);\ntypedef HRESULT (WINAPI *CreateTextureMenuFn)(void *self, UINT width, UINT height, UINT levels,\n    DWORD usage, DWORD format, DWORD pool, void **texture);\ntypedef HRESULT (WINAPI *CreateRenderTargetMenuFn)(void *self, UINT width, UINT height, DWORD format,\n    DWORD multisample, BOOL lockable, void **surface);\ntypedef HRESULT (WINAPI *CreateImageSurfaceMenuFn)(void *self, UINT width, UINT height,\n    DWORD format, void **surface);\ntypedef HRESULT (WINAPI *SurfaceGetDescMenuFn)(void *self, D3DSurfaceDesc8MenuLocal *desc);\ntypedef ULONG (WINAPI *UnknownReleaseMenuFn)(void *self);\n''',
"D3D diagnostic typedefs",
)

replace_once(
'''static PresentFn real_Present;\nstatic volatile LONG gameplay_window_transition_seen;\n''',
'''static PresentFn real_Present;\nstatic SetViewportMenuFn menu_real_SetViewport;\nstatic GetViewportMenuFn menu_real_GetViewport;\nstatic SetRenderTargetMenuFn menu_real_SetRenderTarget;\nstatic CopyRectsMenuFn menu_real_CopyRects;\nstatic CreateTextureMenuFn menu_real_CreateTexture;\nstatic CreateRenderTargetMenuFn menu_real_CreateRenderTarget;\nstatic CreateImageSurfaceMenuFn menu_real_CreateImageSurface;\nstatic HANDLE menu_diag_log_handle = INVALID_HANDLE_VALUE;\nstatic LONG menu_diag_line_count;\nstatic LONG menu_viewport_log_count;\nstatic LONG menu_present_log_count;\nstatic LONG menu_copyrects_log_count;\nstatic LONG menu_rt_log_count;\nstatic LONG menu_resource_log_count;\nstatic LONG menu_matrix_log_count;\nstatic volatile LONG menu_scale_apply_count;\nstatic volatile LONG menu_last_matrix_was_2d;\nstatic volatile LONG menu_last_matrix_tick;\nstatic UINT menu_scale_target_width;\nstatic UINT menu_scale_target_height;\nstatic int menu_scale_enabled = 1;\nstatic int menu_scale_diagnostics = 1;\nstatic volatile LONG gameplay_window_transition_seen;\n''',
"menu diagnostic globals",
)

# Load experimental controls and the launcher's requested resolution.  No new UI
# is added for this probe.  A tester can manually set [MenuScale] Enabled=0 to
# retain diagnostics while disabling the viewport experiment.
replace_once(
'''    borderless_enabled = GetPrivateProfileIntA("Borderless", "Enabled", 0, ini) != 0;\n''',
'''    borderless_enabled = GetPrivateProfileIntA("Borderless", "Enabled", 0, ini) != 0;\n    menu_scale_enabled = GetPrivateProfileIntA("MenuScale", "Enabled", 1, ini) != 0;\n    menu_scale_diagnostics = GetPrivateProfileIntA("MenuScale", "Diagnostics", 1, ini) != 0;\n    menu_scale_target_width = GetPrivateProfileIntA("Resolution", "Width", 0, ini);\n    menu_scale_target_height = GetPrivateProfileIntA("Resolution", "Height", 0, ini);\n''',
"menu scale config",
)

# Forward declaration lets the existing matrix hook report 2D/3D evidence even
# though the full diagnostic helpers live near the existing Present hook.
replace_once(
'''static HRESULT WINAPI fake_SetVertexShaderConstant(void *self, DWORD register_address,\n''',
'''static void menu_diag_note_matrix(DWORD register_address, const void *constant_data, DWORD constant_count);\n\nstatic HRESULT WINAPI fake_SetVertexShaderConstant(void *self, DWORD register_address,\n''',
"matrix diagnostic forward declaration",
)

replace_once(
'''    (void)current_vertex_shader;\n    (void)current_stream_stride;\n\n    if (constant_data && constant_count <= 64 && constant_count >= 4 &&\n''',
'''    (void)current_vertex_shader;\n    (void)current_stream_stride;\n\n    menu_diag_note_matrix(register_address, constant_data, constant_count);\n\n    if (constant_data && constant_count <= 64 && constant_count >= 4 &&\n''',
"matrix diagnostic call",
)

marker = '''static int borderless_window_matches_monitor(HWND hwnd, RECT *window_out,\n'''
if text.count(marker) != 1:
    raise SystemExit(f"menu scale v43 helper marker: expected exactly one match, found {text.count(marker)}")

helpers = r'''static void menu_diag_write(const char *text_line)
{
    DWORD written;
    LONG n;
    if (menu_diag_log_handle == INVALID_HANDLE_VALUE || !text_line) return;
    WriteFile(menu_diag_log_handle, text_line, (DWORD)lstrlenA(text_line), &written, NULL);
    n = InterlockedIncrement(&menu_diag_line_count);
    if ((n & 63) == 0) FlushFileBuffers(menu_diag_log_handle);
}

static void menu_diag_logf(const char *fmt, ...)
{
    char message[1800];
    char line[2048];
    SYSTEMTIME st;
    va_list args;
    int n;
    if (!menu_scale_diagnostics || menu_diag_log_handle == INVALID_HANDLE_VALUE) return;
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
    menu_diag_write(line);
}

static void menu_diag_ensure_open(void)
{
    char path[MAX_PATH];
    char image[MAX_PATH];
    if (!menu_scale_diagnostics || menu_diag_log_handle != INVALID_HANDLE_VALUE) return;
    if (!get_module_dir(path, sizeof(path)) ||
        !append_path(path, sizeof(path), "MVP2005Modern-MenuScale.log")) return;
    menu_diag_log_handle = CreateFileA(path, GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL, NULL);
    if (menu_diag_log_handle == INVALID_HANDLE_VALUE) return;
    image[0] = 0;
    GetModuleFileNameA(NULL, image, sizeof(image));
    image[sizeof(image) - 1] = 0;
    menu_diag_logf("MVP2005 Modern v0.43 frontend menu scaling probe");
    menu_diag_logf(
        "config enabled=%d diagnostics=%d target=%ux%u borderless=%d image=\"%s\" base=%p",
        menu_scale_enabled, menu_scale_diagnostics,
        (unsigned int)menu_scale_target_width, (unsigned int)menu_scale_target_height,
        borderless_enabled, image, GetModuleHandleA(NULL));
    menu_diag_logf(
        "experiment=expand frontend 800x600 viewport only when active render target is larger; gameplay untouched");
}

static int menu_surface_desc(void *surface, D3DSurfaceDesc8MenuLocal *desc)
{
    void **vtbl;
    SurfaceGetDescMenuFn fn = NULL;
    if (!surface || !desc) return 0;
    vtbl = *(void ***)surface;
    if (!vtbl) return 0;
    memcpy(&fn, &vtbl[12], sizeof(fn));
    if (!fn) return 0;
    ZeroMemory(desc, sizeof(*desc));
    return SUCCEEDED(fn(surface, desc));
}

static void menu_release_unknown(void *object)
{
    void **vtbl;
    UnknownReleaseMenuFn fn = NULL;
    if (!object) return;
    vtbl = *(void ***)object;
    if (!vtbl) return;
    memcpy(&fn, &vtbl[2], sizeof(fn));
    if (fn) fn(object);
}

static int menu_get_bound_rt_desc(void *device, D3DSurfaceDesc8MenuLocal *desc)
{
    void **vtbl;
    GetRenderTargetMenuFn fn = NULL;
    void *surface = NULL;
    int ok = 0;
    if (!device || !desc) return 0;
    vtbl = *(void ***)device;
    if (!vtbl) return 0;
    memcpy(&fn, &vtbl[32], sizeof(fn));
    if (!fn || FAILED(fn(device, &surface)) || !surface) return 0;
    ok = menu_surface_desc(surface, desc);
    menu_release_unknown(surface);
    return ok;
}

static int menu_get_backbuffer_desc(void *device, D3DSurfaceDesc8MenuLocal *desc)
{
    void **vtbl;
    GetBackBufferMenuFn fn = NULL;
    void *surface = NULL;
    int ok = 0;
    if (!device || !desc) return 0;
    vtbl = *(void ***)device;
    if (!vtbl) return 0;
    memcpy(&fn, &vtbl[16], sizeof(fn));
    if (!fn || FAILED(fn(device, 0, 0, &surface)) || !surface) return 0;
    ok = menu_surface_desc(surface, desc);
    menu_release_unknown(surface);
    return ok;
}

static void menu_diag_note_matrix(DWORD register_address, const void *constant_data,
    DWORD constant_count)
{
    const float *f = (const float *)constant_data;
    int is_2d;
    LONG n;
    if (!menu_scale_diagnostics || !constant_data || constant_count < 4 || constant_count > 64 ||
        (register_address != 0 && register_address != 12)) return;
    menu_diag_ensure_open();
    is_2d = is_probably_2d_ortho_matrix(f);
    InterlockedExchange(&menu_last_matrix_was_2d, is_2d ? 1 : 0);
    InterlockedExchange(&menu_last_matrix_tick, (LONG)GetTickCount());
    n = InterlockedIncrement(&menu_matrix_log_count);
    if (n <= 160) {
        menu_diag_logf(
            "MATRIX n=%ld class=%s phase=%s reg=%lu count=%lu shader=0x%08lx stride=%lu "
            "m0=[%.6f %.6f %.6f %.6f] m1=[%.6f %.6f %.6f %.6f]",
            (long)n, is_2d ? "2D_ORTHO" : "3D_OR_OTHER",
            InterlockedCompareExchange(&gameplay_input_phase, 0, 0) ? "GAMEPLAY" : "FRONTEND",
            (unsigned long)register_address, (unsigned long)constant_count,
            (unsigned long)current_vertex_shader, (unsigned long)current_stream_stride,
            f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7]);
    }
}

static HRESULT WINAPI menu_fake_SetViewport(void *self, const D3DViewport8MenuLocal *viewport)
{
    D3DViewport8MenuLocal adjusted;
    const D3DViewport8MenuLocal *to_send = viewport;
    D3DSurfaceDesc8MenuLocal rt;
    int have_rt = menu_get_bound_rt_desc(self, &rt);
    int gameplay = InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0;
    int candidate = 0;
    int applied = 0;
    LONG n;

    menu_diag_ensure_open();
    if (viewport && !gameplay && viewport->X == 0 && viewport->Y == 0 &&
        viewport->Width == 800 && viewport->Height == 600) {
        candidate = 1;
        if (menu_scale_enabled && have_rt && rt.Width > viewport->Width && rt.Height > viewport->Height) {
            adjusted = *viewport;
            adjusted.Width = rt.Width;
            adjusted.Height = rt.Height;
            to_send = &adjusted;
            applied = 1;
            InterlockedIncrement(&menu_scale_apply_count);
        }
    }

    n = InterlockedIncrement(&menu_viewport_log_count);
    if (n <= 320 || candidate || gameplay) {
        menu_diag_logf(
            "SETVIEWPORT n=%ld phase=%s in=%lu,%lu %lux%lu z=%.3f..%.3f "
            "rt=%s%ux%u logical=%ux%u target=%ux%u candidate=%d applied=%d out=%lux%lu",
            (long)n, gameplay ? "GAMEPLAY" : "FRONTEND",
            viewport ? (unsigned long)viewport->X : 0UL,
            viewport ? (unsigned long)viewport->Y : 0UL,
            viewport ? (unsigned long)viewport->Width : 0UL,
            viewport ? (unsigned long)viewport->Height : 0UL,
            viewport ? viewport->MinZ : 0.0f, viewport ? viewport->MaxZ : 0.0f,
            have_rt ? "" : "UNKNOWN/", have_rt ? rt.Width : 0, have_rt ? rt.Height : 0,
            (unsigned int)borderless_logical_width, (unsigned int)borderless_logical_height,
            (unsigned int)menu_scale_target_width, (unsigned int)menu_scale_target_height,
            candidate, applied,
            to_send ? (unsigned long)to_send->Width : 0UL,
            to_send ? (unsigned long)to_send->Height : 0UL);
    }

    return menu_real_SetViewport ? menu_real_SetViewport(self, to_send) : E_FAIL;
}

static HRESULT WINAPI menu_fake_GetViewport(void *self, D3DViewport8MenuLocal *viewport)
{
    HRESULT hr = menu_real_GetViewport ? menu_real_GetViewport(self, viewport) : E_FAIL;
    if (SUCCEEDED(hr) && viewport && InterlockedIncrement(&menu_viewport_log_count) <= 360) {
        menu_diag_ensure_open();
        menu_diag_logf("GETVIEWPORT phase=%s out=%lu,%lu %lux%lu z=%.3f..%.3f",
            InterlockedCompareExchange(&gameplay_input_phase, 0, 0) ? "GAMEPLAY" : "FRONTEND",
            (unsigned long)viewport->X, (unsigned long)viewport->Y,
            (unsigned long)viewport->Width, (unsigned long)viewport->Height,
            viewport->MinZ, viewport->MaxZ);
    }
    return hr;
}

static HRESULT WINAPI menu_fake_SetRenderTarget(void *self, void *render_target, void *depth_stencil)
{
    D3DSurfaceDesc8MenuLocal rt;
    D3DSurfaceDesc8MenuLocal ds;
    int have_rt = menu_surface_desc(render_target, &rt);
    int have_ds = menu_surface_desc(depth_stencil, &ds);
    LONG n;
    menu_diag_ensure_open();
    n = InterlockedIncrement(&menu_rt_log_count);
    if (n <= 240) {
        menu_diag_logf(
            "SETRENDERTARGET n=%ld phase=%s rt=%p %s%ux%u fmt=%lu usage=0x%08lx "
            "depth=%p %s%ux%u fmt=%lu",
            (long)n,
            InterlockedCompareExchange(&gameplay_input_phase, 0, 0) ? "GAMEPLAY" : "FRONTEND",
            render_target, have_rt ? "" : "UNKNOWN/", have_rt ? rt.Width : 0, have_rt ? rt.Height : 0,
            have_rt ? (unsigned long)rt.Format : 0UL, have_rt ? (unsigned long)rt.Usage : 0UL,
            depth_stencil, have_ds ? "" : "UNKNOWN/", have_ds ? ds.Width : 0, have_ds ? ds.Height : 0,
            have_ds ? (unsigned long)ds.Format : 0UL);
    }
    return menu_real_SetRenderTarget ? menu_real_SetRenderTarget(self, render_target, depth_stencil) : E_FAIL;
}

static HRESULT WINAPI menu_fake_CopyRects(void *self, void *source_surface,
    const RECT *source_rects, UINT rect_count, void *dest_surface, const POINT *dest_points)
{
    D3DSurfaceDesc8MenuLocal src;
    D3DSurfaceDesc8MenuLocal dst;
    int have_src = menu_surface_desc(source_surface, &src);
    int have_dst = menu_surface_desc(dest_surface, &dst);
    LONG n;
    menu_diag_ensure_open();
    n = InterlockedIncrement(&menu_copyrects_log_count);
    if (n <= 320) {
        if (source_rects && rect_count) {
            menu_diag_logf(
                "COPYRECTS n=%ld phase=%s count=%u src=%p %s%ux%u rect0=%ld,%ld-%ld,%ld "
                "dst=%p %s%ux%u point0=%ld,%ld",
                (long)n,
                InterlockedCompareExchange(&gameplay_input_phase, 0, 0) ? "GAMEPLAY" : "FRONTEND",
                (unsigned int)rect_count, source_surface,
                have_src ? "" : "UNKNOWN/", have_src ? src.Width : 0, have_src ? src.Height : 0,
                source_rects[0].left, source_rects[0].top, source_rects[0].right, source_rects[0].bottom,
                dest_surface, have_dst ? "" : "UNKNOWN/", have_dst ? dst.Width : 0, have_dst ? dst.Height : 0,
                dest_points ? dest_points[0].x : -1L, dest_points ? dest_points[0].y : -1L);
        } else {
            menu_diag_logf(
                "COPYRECTS n=%ld phase=%s count=%u src=%p %s%ux%u rects=NULL dst=%p %s%ux%u points=%s",
                (long)n,
                InterlockedCompareExchange(&gameplay_input_phase, 0, 0) ? "GAMEPLAY" : "FRONTEND",
                (unsigned int)rect_count, source_surface,
                have_src ? "" : "UNKNOWN/", have_src ? src.Width : 0, have_src ? src.Height : 0,
                dest_surface, have_dst ? "" : "UNKNOWN/", have_dst ? dst.Width : 0, have_dst ? dst.Height : 0,
                dest_points ? "NONNULL" : "NULL");
        }
    }
    return menu_real_CopyRects ? menu_real_CopyRects(self, source_surface, source_rects,
        rect_count, dest_surface, dest_points) : E_FAIL;
}

static HRESULT WINAPI menu_fake_CreateTexture(void *self, UINT width, UINT height, UINT levels,
    DWORD usage, DWORD format, DWORD pool, void **texture)
{
    HRESULT hr = menu_real_CreateTexture ? menu_real_CreateTexture(self, width, height, levels,
        usage, format, pool, texture) : E_FAIL;
    LONG n;
    menu_diag_ensure_open();
    n = InterlockedIncrement(&menu_resource_log_count);
    if (n <= 400 || width >= 640 || height >= 480) {
        menu_diag_logf(
            "CREATETEXTURE n=%ld phase=%s request=%ux%u levels=%u usage=0x%08lx fmt=%lu pool=%lu hr=0x%08lx out=%p",
            (long)n,
            InterlockedCompareExchange(&gameplay_input_phase, 0, 0) ? "GAMEPLAY" : "FRONTEND",
            width, height, levels, (unsigned long)usage, (unsigned long)format,
            (unsigned long)pool, (unsigned long)hr, texture ? *texture : NULL);
    }
    return hr;
}

static HRESULT WINAPI menu_fake_CreateRenderTarget(void *self, UINT width, UINT height, DWORD format,
    DWORD multisample, BOOL lockable, void **surface)
{
    HRESULT hr = menu_real_CreateRenderTarget ? menu_real_CreateRenderTarget(self, width, height,
        format, multisample, lockable, surface) : E_FAIL;
    LONG n;
    menu_diag_ensure_open();
    n = InterlockedIncrement(&menu_resource_log_count);
    if (n <= 440 || width >= 640 || height >= 480) {
        menu_diag_logf(
            "CREATERENDERTARGET n=%ld phase=%s request=%ux%u fmt=%lu ms=%lu lockable=%d hr=0x%08lx out=%p",
            (long)n,
            InterlockedCompareExchange(&gameplay_input_phase, 0, 0) ? "GAMEPLAY" : "FRONTEND",
            width, height, (unsigned long)format, (unsigned long)multisample,
            lockable, (unsigned long)hr, surface ? *surface : NULL);
    }
    return hr;
}

static HRESULT WINAPI menu_fake_CreateImageSurface(void *self, UINT width, UINT height,
    DWORD format, void **surface)
{
    HRESULT hr = menu_real_CreateImageSurface ? menu_real_CreateImageSurface(self, width, height,
        format, surface) : E_FAIL;
    LONG n;
    menu_diag_ensure_open();
    n = InterlockedIncrement(&menu_resource_log_count);
    if (n <= 480 || width >= 640 || height >= 480) {
        menu_diag_logf(
            "CREATEIMAGESURFACE n=%ld phase=%s request=%ux%u fmt=%lu hr=0x%08lx out=%p",
            (long)n,
            InterlockedCompareExchange(&gameplay_input_phase, 0, 0) ? "GAMEPLAY" : "FRONTEND",
            width, height, (unsigned long)format, (unsigned long)hr,
            surface ? *surface : NULL);
    }
    return hr;
}

static void menu_diag_present(void *self, const RECT *source_rect, const RECT *dest_rect,
    HWND dest_window_override)
{
    D3DSurfaceDesc8MenuLocal bb;
    D3DSurfaceDesc8MenuLocal rt;
    D3DViewport8MenuLocal vp;
    int have_bb = menu_get_backbuffer_desc(self, &bb);
    int have_rt = menu_get_bound_rt_desc(self, &rt);
    int have_vp = menu_real_GetViewport && SUCCEEDED(menu_real_GetViewport(self, &vp));
    RECT client;
    int have_client = borderless_window && GetClientRect(borderless_window, &client);
    LONG n = InterlockedIncrement(&menu_present_log_count);
    if (n <= 420 || (n % 120) == 0) {
        menu_diag_ensure_open();
        menu_diag_logf(
            "PRESENT n=%ld phase=%s bb=%s%ux%u rt=%s%ux%u vp=%s%lu,%lu %lux%lu "
            "client=%s%ldx%ld src=%s dst=%s override=%p scale_applies=%ld last_matrix=%s age_ms=%lu",
            (long)n,
            InterlockedCompareExchange(&gameplay_input_phase, 0, 0) ? "GAMEPLAY" : "FRONTEND",
            have_bb ? "" : "UNKNOWN/", have_bb ? bb.Width : 0, have_bb ? bb.Height : 0,
            have_rt ? "" : "UNKNOWN/", have_rt ? rt.Width : 0, have_rt ? rt.Height : 0,
            have_vp ? "" : "UNKNOWN/", have_vp ? (unsigned long)vp.X : 0UL,
            have_vp ? (unsigned long)vp.Y : 0UL, have_vp ? (unsigned long)vp.Width : 0UL,
            have_vp ? (unsigned long)vp.Height : 0UL,
            have_client ? "" : "UNKNOWN/", have_client ? client.right - client.left : 0L,
            have_client ? client.bottom - client.top : 0L,
            source_rect ? "NONNULL" : "NULL", dest_rect ? "NONNULL" : "NULL",
            dest_window_override,
            (long)InterlockedCompareExchange(&menu_scale_apply_count, 0, 0),
            InterlockedCompareExchange(&menu_last_matrix_was_2d, 0, 0) ? "2D" : "3D/OTHER",
            (unsigned long)(GetTickCount() - (DWORD)InterlockedCompareExchange(&menu_last_matrix_tick, 0, 0)));
        if (source_rect)
            menu_diag_logf("PRESENT source_rect=%ld,%ld-%ld,%ld",
                source_rect->left, source_rect->top, source_rect->right, source_rect->bottom);
        if (dest_rect)
            menu_diag_logf("PRESENT dest_rect=%ld,%ld-%ld,%ld",
                dest_rect->left, dest_rect->top, dest_rect->right, dest_rect->bottom);
    }
}

'''
text = text.replace(marker, helpers + marker, 1)

# Add Present-state logging without changing the already proven borderless guard.
replace_once(
'''{\n    enforce_borderless_at_present();\n    return real_Present ? real_Present(self, source_rect, dest_rect,\n''',
'''{\n    enforce_borderless_at_present();\n    menu_diag_present(self, source_rect, dest_rect, dest_window_override);\n    return real_Present ? real_Present(self, source_rect, dest_rect,\n''',
"Present diagnostics",
)

# Install the D3D8 probe hooks alongside the already proven Reset/Present/shader hooks.
replace_once(
'''        int reset_ok, present_ok, shader_ok, constants_ok, stream_ok;\n''',
'''        int reset_ok, present_ok, viewport_ok, getviewport_ok, rt_ok, copy_ok;\n        int texture_ok, create_rt_ok, image_ok, shader_ok, constants_ok, stream_ok;\n''',
"menu hook success variables",
)

replace_once(
'''        reset_ok = patch_vtable_slot(vtbl, 14, fake_Reset, (void **)&real_Reset);\n        present_ok = patch_vtable_slot(vtbl, 15, fake_Present, (void **)&real_Present);\n        shader_ok = patch_vtable_slot(vtbl, 76, fake_SetVertexShader, (void **)&real_SetVertexShader);\n''',
'''        reset_ok = patch_vtable_slot(vtbl, 14, fake_Reset, (void **)&real_Reset);\n        present_ok = patch_vtable_slot(vtbl, 15, fake_Present, (void **)&real_Present);\n        texture_ok = patch_vtable_slot(vtbl, 20, menu_fake_CreateTexture, (void **)&menu_real_CreateTexture);\n        create_rt_ok = patch_vtable_slot(vtbl, 25, menu_fake_CreateRenderTarget, (void **)&menu_real_CreateRenderTarget);\n        image_ok = patch_vtable_slot(vtbl, 27, menu_fake_CreateImageSurface, (void **)&menu_real_CreateImageSurface);\n        copy_ok = patch_vtable_slot(vtbl, 28, menu_fake_CopyRects, (void **)&menu_real_CopyRects);\n        rt_ok = patch_vtable_slot(vtbl, 31, menu_fake_SetRenderTarget, (void **)&menu_real_SetRenderTarget);\n        viewport_ok = patch_vtable_slot(vtbl, 40, menu_fake_SetViewport, (void **)&menu_real_SetViewport);\n        getviewport_ok = patch_vtable_slot(vtbl, 41, menu_fake_GetViewport, (void **)&menu_real_GetViewport);\n        shader_ok = patch_vtable_slot(vtbl, 76, fake_SetVertexShader, (void **)&real_SetVertexShader);\n''',
"menu vtable hooks",
)

replace_once(
'''        if (reset_ok && present_ok && shader_ok && constants_ok && stream_ok) {\n''',
'''        menu_diag_ensure_open();\n        menu_diag_logf(\n            "HOOKS reset=%d present=%d texture=%d create_rt=%d image=%d copy=%d set_rt=%d set_vp=%d get_vp=%d shader=%d constants=%d stream=%d",\n            reset_ok, present_ok, texture_ok, create_rt_ok, image_ok, copy_ok, rt_ok,\n            viewport_ok, getviewport_ok, shader_ok, constants_ok, stream_ok);\n        if (reset_ok && present_ok && viewport_ok && getviewport_ok && rt_ok && copy_ok &&\n            texture_ok && create_rt_ok && image_ok && shader_ok && constants_ok && stream_ok) {\n''',
"menu hook success condition",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern frontend menu scaling probe v43")
