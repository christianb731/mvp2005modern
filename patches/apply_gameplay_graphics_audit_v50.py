from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"graphics audit v50 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# v0.50 passive gameplay graphics audit
#
# This build intentionally changes NO rendering/resource/state values.  It hooks
# safe IDirect3DDevice8 entry points, records only arguments and state already
# observed by those calls, and correlates texture/render-target pointers with the
# metadata seen at creation time.  No nested COM queries are used -- specifically
# avoiding the risky v0.43 GetRenderTarget/GetBackBuffer/GetDesc pattern.
# ---------------------------------------------------------------------------

marker = '''static int borderless_window_matches_monitor(HWND hwnd, RECT *window_out,\n'''
if text.count(marker) != 1:
    raise SystemExit(f"graphics audit v50 helper marker: expected one match, found {text.count(marker)}")

helpers = r'''typedef struct GfxViewport8Audit {
    DWORD X;
    DWORD Y;
    DWORD Width;
    DWORD Height;
    float MinZ;
    float MaxZ;
} GfxViewport8Audit;

typedef HRESULT (WINAPI *GfxCreateTextureFn)(void *self, UINT width, UINT height,
    UINT levels, DWORD usage, DWORD format, DWORD pool, void **texture);
typedef HRESULT (WINAPI *GfxCreateRenderTargetFn)(void *self, UINT width, UINT height,
    DWORD format, DWORD multisample, BOOL lockable, void **surface);
typedef HRESULT (WINAPI *GfxCreateDepthStencilFn)(void *self, UINT width, UINT height,
    DWORD format, DWORD multisample, void **surface);
typedef HRESULT (WINAPI *GfxCreateImageSurfaceFn)(void *self, UINT width, UINT height,
    DWORD format, void **surface);
typedef HRESULT (WINAPI *GfxCopyRectsFn)(void *self, void *source_surface,
    const RECT *source_rects, UINT rect_count, void *dest_surface,
    const POINT *dest_points);
typedef HRESULT (WINAPI *GfxUpdateTextureFn)(void *self, void *source_texture,
    void *dest_texture);
typedef HRESULT (WINAPI *GfxSetRenderTargetFn)(void *self, void *render_target,
    void *depth_stencil);
typedef HRESULT (WINAPI *GfxSetViewportFn)(void *self,
    const GfxViewport8Audit *viewport);
typedef HRESULT (WINAPI *GfxSetRenderStateFn)(void *self, DWORD state, DWORD value);
typedef HRESULT (WINAPI *GfxSetTextureFn)(void *self, DWORD stage, void *texture);
typedef HRESULT (WINAPI *GfxSetTextureStageStateFn)(void *self, DWORD stage,
    DWORD type, DWORD value);
typedef HRESULT (WINAPI *GfxDrawPrimitiveFn)(void *self, DWORD primitive_type,
    UINT start_vertex, UINT primitive_count);
typedef HRESULT (WINAPI *GfxDrawIndexedPrimitiveFn)(void *self, DWORD primitive_type,
    UINT min_index, UINT num_vertices, UINT start_index, UINT primitive_count);
typedef HRESULT (WINAPI *GfxDrawPrimitiveUPFn)(void *self, DWORD primitive_type,
    UINT primitive_count, const void *vertex_data, UINT vertex_stride);
typedef HRESULT (WINAPI *GfxDrawIndexedPrimitiveUPFn)(void *self,
    DWORD primitive_type, UINT min_vertex_index, UINT num_vertex_indices,
    UINT primitive_count, const void *index_data, DWORD index_format,
    const void *vertex_data, UINT vertex_stride);
typedef HRESULT (WINAPI *GfxSetPixelShaderFn)(void *self, DWORD handle);

typedef struct GfxTextureRecord {
    void *object;
    UINT width;
    UINT height;
    UINT levels;
    DWORD usage;
    DWORD format;
    DWORD pool;
    DWORD caller_rva;
} GfxTextureRecord;

typedef struct GfxSurfaceRecord {
    void *object;
    UINT width;
    UINT height;
    DWORD format;
    DWORD multisample;
    DWORD kind;
    DWORD caller_rva;
} GfxSurfaceRecord;

static GfxCreateTextureFn gfx_real_CreateTexture;
static GfxCreateRenderTargetFn gfx_real_CreateRenderTarget;
static GfxCreateDepthStencilFn gfx_real_CreateDepthStencil;
static GfxCreateImageSurfaceFn gfx_real_CreateImageSurface;
static GfxCopyRectsFn gfx_real_CopyRects;
static GfxUpdateTextureFn gfx_real_UpdateTexture;
static GfxSetRenderTargetFn gfx_real_SetRenderTarget;
static GfxSetViewportFn gfx_real_SetViewport;
static GfxSetRenderStateFn gfx_real_SetRenderState;
static GfxSetTextureFn gfx_real_SetTexture;
static GfxSetTextureStageStateFn gfx_real_SetTextureStageState;
static GfxDrawPrimitiveFn gfx_real_DrawPrimitive;
static GfxDrawIndexedPrimitiveFn gfx_real_DrawIndexedPrimitive;
static GfxDrawPrimitiveUPFn gfx_real_DrawPrimitiveUP;
static GfxDrawIndexedPrimitiveUPFn gfx_real_DrawIndexedPrimitiveUP;
static GfxSetPixelShaderFn gfx_real_SetPixelShader;

static HANDLE gfx_log_handle = INVALID_HANDLE_VALUE;
static LONG gfx_log_lines;
static LONG gfx_texture_create_count;
static LONG gfx_surface_create_count;
static LONG gfx_copy_count;
static LONG gfx_update_count;
static LONG gfx_texture_bind_count;
static LONG gfx_tss_count;
static LONG gfx_rs_count;
static LONG gfx_rt_switch_count;
static LONG gfx_viewport_count;
static LONG gfx_draw_sample_count;
static LONG gfx_gameplay_frame_count;
static LONG gfx_frame_draws;
static LONG gfx_frame_primitives;
static LONG gfx_frame_texture_binds;
static LONG gfx_frame_rt_switches;
static LONG gfx_last_phase = -1;
static DWORD gfx_current_pixel_shader;
static void *gfx_current_render_target;
static void *gfx_current_depth_target;
static void *gfx_bound_textures[8];
static DWORD gfx_last_rs[256];
static BYTE gfx_last_rs_valid[256];
static DWORD gfx_last_tss[8][32];
static BYTE gfx_last_tss_valid[8][32];
static GfxViewport8Audit gfx_last_viewport;
static int gfx_last_viewport_valid;
static GfxTextureRecord gfx_textures[4096];
static LONG gfx_texture_record_count;
static GfxSurfaceRecord gfx_surfaces[512];
static LONG gfx_surface_record_count;

static DWORD gfx_caller_rva(void *caller)
{
    BYTE *base = (BYTE *)GetModuleHandleA(NULL);
    IMAGE_DOS_HEADER *dos;
    IMAGE_NT_HEADERS *nt;
    ULONG_PTR p;
    ULONG_PTR b;

    if (!base || !caller) return 0xffffffffUL;
    dos = (IMAGE_DOS_HEADER *)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return 0xffffffffUL;
    nt = (IMAGE_NT_HEADERS *)(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return 0xffffffffUL;
    p = (ULONG_PTR)caller;
    b = (ULONG_PTR)base;
    if (p < b || p >= b + nt->OptionalHeader.SizeOfImage) return 0xffffffffUL;
    return (DWORD)(p - b);
}

static const char *gfx_phase_name(void)
{
    return InterlockedCompareExchange(&gameplay_input_phase, 0, 0) ?
        "GAMEPLAY" : "FRONTEND/LOAD";
}

static const char *gfx_format_name(DWORD format)
{
    switch (format) {
    case 20: return "R8G8B8";
    case 21: return "A8R8G8B8";
    case 22: return "X8R8G8B8";
    case 23: return "R5G6B5";
    case 24: return "X1R5G5B5";
    case 25: return "A1R5G5B5";
    case 26: return "A4R4G4B4";
    case 28: return "A8";
    case 41: return "P8";
    case 50: return "L8";
    case 51: return "A8L8";
    case 70: return "D16_LOCKABLE";
    case 71: return "D32";
    case 73: return "D15S1";
    case 75: return "D24S8";
    case 77: return "D24X8";
    case 79: return "D24X4S4";
    case 80: return "D16";
    case 0x31545844UL: return "DXT1";
    case 0x33545844UL: return "DXT3";
    case 0x35545844UL: return "DXT5";
    default: return "OTHER";
    }
}

static const char *gfx_filter_name(DWORD value)
{
    switch (value) {
    case 0: return "NONE";
    case 1: return "POINT";
    case 2: return "LINEAR";
    case 3: return "ANISOTROPIC";
    case 4: return "FLATCUBIC";
    case 5: return "GAUSSIANCUBIC";
    default: return "OTHER";
    }
}

static void gfx_log_write(const char *line)
{
    DWORD written;
    LONG n;
    if (gfx_log_handle == INVALID_HANDLE_VALUE || !line) return;
    n = InterlockedIncrement(&gfx_log_lines);
    if (n > 18000) return;
    WriteFile(gfx_log_handle, line, (DWORD)lstrlenA(line), &written, NULL);
    if ((n & 127) == 0) FlushFileBuffers(gfx_log_handle);
}

static void gfx_logf(const char *fmt, ...)
{
    char message[1800];
    char line[2048];
    SYSTEMTIME st;
    va_list args;
    int n;

    if (gfx_log_handle == INVALID_HANDLE_VALUE) return;
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
    gfx_log_write(line);
}

static void gfx_ensure_log(void)
{
    char path[MAX_PATH];
    char image[MAX_PATH];
    if (gfx_log_handle != INVALID_HANDLE_VALUE) return;
    if (!get_module_dir(path, sizeof(path)) ||
        !append_path(path, sizeof(path), "MVP2005Modern-Graphics.log")) return;
    gfx_log_handle = CreateFileA(path, GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL, NULL);
    if (gfx_log_handle == INVALID_HANDLE_VALUE) return;
    image[0] = 0;
    GetModuleFileNameA(NULL, image, sizeof(image));
    image[sizeof(image) - 1] = 0;
    gfx_logf("MVP2005 Modern v0.50 gameplay graphics audit");
    gfx_logf("mode=PASSIVE no resource/render-state/filter/viewport modification");
    gfx_logf("image=\"%s\" base=%p configured_output=%ux%u",
        image, GetModuleHandleA(NULL),
        (unsigned int)menu_scale_target_width,
        (unsigned int)menu_scale_target_height);
}

static void gfx_register_texture(void *object, UINT width, UINT height, UINT levels,
    DWORD usage, DWORD format, DWORD pool, DWORD caller_rva)
{
    LONG index;
    if (!object) return;
    index = InterlockedIncrement(&gfx_texture_record_count) - 1;
    if (index < 0 || index >= (LONG)(sizeof(gfx_textures) / sizeof(gfx_textures[0]))) return;
    gfx_textures[index].object = object;
    gfx_textures[index].width = width;
    gfx_textures[index].height = height;
    gfx_textures[index].levels = levels;
    gfx_textures[index].usage = usage;
    gfx_textures[index].format = format;
    gfx_textures[index].pool = pool;
    gfx_textures[index].caller_rva = caller_rva;
}

static GfxTextureRecord *gfx_find_texture(void *object)
{
    LONG i = InterlockedCompareExchange(&gfx_texture_record_count, 0, 0);
    if (i > (LONG)(sizeof(gfx_textures) / sizeof(gfx_textures[0])))
        i = (LONG)(sizeof(gfx_textures) / sizeof(gfx_textures[0]));
    while (i-- > 0) {
        if (gfx_textures[i].object == object) return &gfx_textures[i];
    }
    return NULL;
}

static void gfx_register_surface(void *object, UINT width, UINT height, DWORD format,
    DWORD multisample, DWORD kind, DWORD caller_rva)
{
    LONG index;
    if (!object) return;
    index = InterlockedIncrement(&gfx_surface_record_count) - 1;
    if (index < 0 || index >= (LONG)(sizeof(gfx_surfaces) / sizeof(gfx_surfaces[0]))) return;
    gfx_surfaces[index].object = object;
    gfx_surfaces[index].width = width;
    gfx_surfaces[index].height = height;
    gfx_surfaces[index].format = format;
    gfx_surfaces[index].multisample = multisample;
    gfx_surfaces[index].kind = kind;
    gfx_surfaces[index].caller_rva = caller_rva;
}

static GfxSurfaceRecord *gfx_find_surface(void *object)
{
    LONG i = InterlockedCompareExchange(&gfx_surface_record_count, 0, 0);
    if (i > (LONG)(sizeof(gfx_surfaces) / sizeof(gfx_surfaces[0])))
        i = (LONG)(sizeof(gfx_surfaces) / sizeof(gfx_surfaces[0]));
    while (i-- > 0) {
        if (gfx_surfaces[i].object == object) return &gfx_surfaces[i];
    }
    return NULL;
}

static void gfx_audit_note_present_params(const char *where, void *presentation_parameters)
{
    D3DPresentParameters8Local *pp = (D3DPresentParameters8Local *)presentation_parameters;
    gfx_ensure_log();
    if (!pp) {
        gfx_logf("PRESENTPARAMS where=%s ptr=NULL", where ? where : "UNKNOWN");
        return;
    }
    gfx_logf(
        "PRESENTPARAMS where=%s phase=%s backbuffer=%ux%u fmt=0x%08lx(%s) count=%u ms=%lu swap=%lu windowed=%d auto_depth=%d depth_fmt=0x%08lx(%s) flags=0x%08lx refresh=%u interval=%u",
        where ? where : "UNKNOWN", gfx_phase_name(),
        pp->BackBufferWidth, pp->BackBufferHeight,
        (unsigned long)pp->BackBufferFormat, gfx_format_name(pp->BackBufferFormat),
        pp->BackBufferCount, (unsigned long)pp->MultiSampleType,
        (unsigned long)pp->SwapEffect, pp->Windowed, pp->EnableAutoDepthStencil,
        (unsigned long)pp->AutoDepthStencilFormat,
        gfx_format_name(pp->AutoDepthStencilFormat), (unsigned long)pp->Flags,
        pp->FullScreen_RefreshRateInHz, pp->FullScreen_PresentationInterval);
}

static HRESULT WINAPI gfx_fake_CreateTexture(void *self, UINT width, UINT height,
    UINT levels, DWORD usage, DWORD format, DWORD pool, void **texture)
{
    void *caller = __builtin_return_address(0);
    DWORD rva = gfx_caller_rva(caller);
    HRESULT hr = gfx_real_CreateTexture ?
        gfx_real_CreateTexture(self, width, height, levels, usage, format, pool, texture) : E_FAIL;
    LONG n = InterlockedIncrement(&gfx_texture_create_count);
    void *out = texture ? *texture : NULL;
    gfx_register_texture(SUCCEEDED(hr) ? out : NULL, width, height, levels,
        usage, format, pool, rva);
    if (n <= 3000 || width >= 1024 || height >= 1024 || (usage & 3)) {
        gfx_logf(
            "CREATE_TEXTURE n=%ld phase=%s caller_rva=0x%08lx size=%ux%u levels=%u usage=0x%08lx format=0x%08lx(%s) pool=%lu hr=0x%08lx object=%p",
            (long)n, gfx_phase_name(), (unsigned long)rva, width, height, levels,
            (unsigned long)usage, (unsigned long)format, gfx_format_name(format),
            (unsigned long)pool, (unsigned long)hr, out);
    }
    return hr;
}

static HRESULT WINAPI gfx_fake_CreateRenderTarget(void *self, UINT width, UINT height,
    DWORD format, DWORD multisample, BOOL lockable, void **surface)
{
    void *caller = __builtin_return_address(0);
    DWORD rva = gfx_caller_rva(caller);
    HRESULT hr = gfx_real_CreateRenderTarget ?
        gfx_real_CreateRenderTarget(self, width, height, format, multisample, lockable, surface) : E_FAIL;
    void *out = surface ? *surface : NULL;
    LONG n = InterlockedIncrement(&gfx_surface_create_count);
    gfx_register_surface(SUCCEEDED(hr) ? out : NULL, width, height, format,
        multisample, 1, rva);
    gfx_logf(
        "CREATE_RT n=%ld phase=%s caller_rva=0x%08lx size=%ux%u format=0x%08lx(%s) ms=%lu lockable=%d hr=0x%08lx object=%p",
        (long)n, gfx_phase_name(), (unsigned long)rva, width, height,
        (unsigned long)format, gfx_format_name(format), (unsigned long)multisample,
        lockable, (unsigned long)hr, out);
    return hr;
}

static HRESULT WINAPI gfx_fake_CreateDepthStencil(void *self, UINT width, UINT height,
    DWORD format, DWORD multisample, void **surface)
{
    void *caller = __builtin_return_address(0);
    DWORD rva = gfx_caller_rva(caller);
    HRESULT hr = gfx_real_CreateDepthStencil ?
        gfx_real_CreateDepthStencil(self, width, height, format, multisample, surface) : E_FAIL;
    void *out = surface ? *surface : NULL;
    LONG n = InterlockedIncrement(&gfx_surface_create_count);
    gfx_register_surface(SUCCEEDED(hr) ? out : NULL, width, height, format,
        multisample, 2, rva);
    gfx_logf(
        "CREATE_DEPTH n=%ld phase=%s caller_rva=0x%08lx size=%ux%u format=0x%08lx(%s) ms=%lu hr=0x%08lx object=%p",
        (long)n, gfx_phase_name(), (unsigned long)rva, width, height,
        (unsigned long)format, gfx_format_name(format), (unsigned long)multisample,
        (unsigned long)hr, out);
    return hr;
}

static HRESULT WINAPI gfx_fake_CreateImageSurface(void *self, UINT width, UINT height,
    DWORD format, void **surface)
{
    void *caller = __builtin_return_address(0);
    DWORD rva = gfx_caller_rva(caller);
    HRESULT hr = gfx_real_CreateImageSurface ?
        gfx_real_CreateImageSurface(self, width, height, format, surface) : E_FAIL;
    void *out = surface ? *surface : NULL;
    LONG n = InterlockedIncrement(&gfx_surface_create_count);
    gfx_register_surface(SUCCEEDED(hr) ? out : NULL, width, height, format, 0, 3, rva);
    if (n <= 800 || width >= 1024 || height >= 1024) {
        gfx_logf(
            "CREATE_IMAGE n=%ld phase=%s caller_rva=0x%08lx size=%ux%u format=0x%08lx(%s) hr=0x%08lx object=%p",
            (long)n, gfx_phase_name(), (unsigned long)rva, width, height,
            (unsigned long)format, gfx_format_name(format), (unsigned long)hr, out);
    }
    return hr;
}

static HRESULT WINAPI gfx_fake_CopyRects(void *self, void *source_surface,
    const RECT *source_rects, UINT rect_count, void *dest_surface,
    const POINT *dest_points)
{
    LONG n = InterlockedIncrement(&gfx_copy_count);
    if (n <= 500) {
        gfx_logf(
            "COPY_RECTS n=%ld phase=%s caller_rva=0x%08lx src=%p dst=%p count=%u rect0=%s%ld,%ld-%ld,%ld point0=%s%ld,%ld",
            (long)n, gfx_phase_name(),
            (unsigned long)gfx_caller_rva(__builtin_return_address(0)),
            source_surface, dest_surface, rect_count,
            (source_rects && rect_count) ? "" : "NULL/",
            (source_rects && rect_count) ? source_rects[0].left : 0L,
            (source_rects && rect_count) ? source_rects[0].top : 0L,
            (source_rects && rect_count) ? source_rects[0].right : 0L,
            (source_rects && rect_count) ? source_rects[0].bottom : 0L,
            dest_points ? "" : "NULL/",
            dest_points ? dest_points[0].x : 0L,
            dest_points ? dest_points[0].y : 0L);
    }
    return gfx_real_CopyRects ? gfx_real_CopyRects(self, source_surface, source_rects,
        rect_count, dest_surface, dest_points) : E_FAIL;
}

static HRESULT WINAPI gfx_fake_UpdateTexture(void *self, void *source_texture,
    void *dest_texture)
{
    LONG n = InterlockedIncrement(&gfx_update_count);
    if (n <= 500) {
        GfxTextureRecord *src = gfx_find_texture(source_texture);
        GfxTextureRecord *dst = gfx_find_texture(dest_texture);
        gfx_logf(
            "UPDATE_TEXTURE n=%ld phase=%s caller_rva=0x%08lx src=%p%s%ux%u dst=%p%s%ux%u",
            (long)n, gfx_phase_name(),
            (unsigned long)gfx_caller_rva(__builtin_return_address(0)),
            source_texture, src ? " size=" : " size=UNKNOWN/", src ? src->width : 0,
            src ? src->height : 0, dest_texture,
            dst ? " size=" : " size=UNKNOWN/", dst ? dst->width : 0,
            dst ? dst->height : 0);
    }
    return gfx_real_UpdateTexture ? gfx_real_UpdateTexture(self, source_texture,
        dest_texture) : E_FAIL;
}

static HRESULT WINAPI gfx_fake_SetRenderTarget(void *self, void *render_target,
    void *depth_stencil)
{
    if (render_target != gfx_current_render_target || depth_stencil != gfx_current_depth_target) {
        GfxSurfaceRecord *rt = gfx_find_surface(render_target);
        GfxSurfaceRecord *ds = gfx_find_surface(depth_stencil);
        LONG n = InterlockedIncrement(&gfx_rt_switch_count);
        InterlockedIncrement(&gfx_frame_rt_switches);
        gfx_current_render_target = render_target;
        gfx_current_depth_target = depth_stencil;
        if (n <= 1000) {
            gfx_logf(
                "SET_RT n=%ld phase=%s caller_rva=0x%08lx rt=%p%s%ux%u fmt=%s depth=%p%s%ux%u fmt=%s",
                (long)n, gfx_phase_name(),
                (unsigned long)gfx_caller_rva(__builtin_return_address(0)),
                render_target, rt ? " size=" : " size=UNKNOWN/",
                rt ? rt->width : 0, rt ? rt->height : 0,
                rt ? gfx_format_name(rt->format) : "UNKNOWN",
                depth_stencil, ds ? " size=" : " size=UNKNOWN/",
                ds ? ds->width : 0, ds ? ds->height : 0,
                ds ? gfx_format_name(ds->format) : "UNKNOWN");
        }
    }
    return gfx_real_SetRenderTarget ?
        gfx_real_SetRenderTarget(self, render_target, depth_stencil) : E_FAIL;
}

static HRESULT WINAPI gfx_fake_SetViewport(void *self, const GfxViewport8Audit *viewport)
{
    if (viewport && (!gfx_last_viewport_valid ||
        viewport->X != gfx_last_viewport.X || viewport->Y != gfx_last_viewport.Y ||
        viewport->Width != gfx_last_viewport.Width || viewport->Height != gfx_last_viewport.Height ||
        viewport->MinZ != gfx_last_viewport.MinZ || viewport->MaxZ != gfx_last_viewport.MaxZ)) {
        LONG n = InterlockedIncrement(&gfx_viewport_count);
        gfx_last_viewport = *viewport;
        gfx_last_viewport_valid = 1;
        if (n <= 500) {
            gfx_logf(
                "SET_VIEWPORT n=%ld phase=%s caller_rva=0x%08lx xy=%lu,%lu size=%lux%lu z=%.3f..%.3f",
                (long)n, gfx_phase_name(),
                (unsigned long)gfx_caller_rva(__builtin_return_address(0)),
                (unsigned long)viewport->X, (unsigned long)viewport->Y,
                (unsigned long)viewport->Width, (unsigned long)viewport->Height,
                viewport->MinZ, viewport->MaxZ);
        }
    }
    return gfx_real_SetViewport ? gfx_real_SetViewport(self, viewport) : E_FAIL;
}

static int gfx_render_state_interesting(DWORD state)
{
    switch (state) {
    case 7: case 8: case 9: case 14: case 15: case 19: case 20: case 22:
    case 23: case 26: case 27: case 28: case 29: case 34: case 35: case 36:
    case 37: case 38: case 40: case 47: case 48: case 52: case 137: case 143:
    case 154: case 156: case 157: case 161: case 162: case 168: case 171:
        return 1;
    default:
        return 0;
    }
}

static HRESULT WINAPI gfx_fake_SetRenderState(void *self, DWORD state, DWORD value)
{
    if (state < 256 && gfx_render_state_interesting(state) &&
        (!gfx_last_rs_valid[state] || gfx_last_rs[state] != value)) {
        LONG n = InterlockedIncrement(&gfx_rs_count);
        gfx_last_rs_valid[state] = 1;
        gfx_last_rs[state] = value;
        if (n <= 1200) {
            gfx_logf(
                "RENDER_STATE n=%ld phase=%s caller_rva=0x%08lx state=%lu value=0x%08lx(%lu)",
                (long)n, gfx_phase_name(),
                (unsigned long)gfx_caller_rva(__builtin_return_address(0)),
                (unsigned long)state, (unsigned long)value, (unsigned long)value);
        }
    }
    return gfx_real_SetRenderState ? gfx_real_SetRenderState(self, state, value) : E_FAIL;
}

static HRESULT WINAPI gfx_fake_SetTexture(void *self, DWORD stage, void *texture)
{
    if (stage < 8 && gfx_bound_textures[stage] != texture) {
        GfxTextureRecord *rec = gfx_find_texture(texture);
        LONG n = InterlockedIncrement(&gfx_texture_bind_count);
        InterlockedIncrement(&gfx_frame_texture_binds);
        gfx_bound_textures[stage] = texture;
        if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0 &&
            (n <= 1200 || (n % 1000) == 0)) {
            gfx_logf(
                "SET_TEXTURE n=%ld phase=GAMEPLAY caller_rva=0x%08lx stage=%lu object=%p%s%ux%u levels=%u fmt=%s create_rva=0x%08lx",
                (long)n, (unsigned long)gfx_caller_rva(__builtin_return_address(0)),
                (unsigned long)stage, texture, rec ? " size=" : " size=UNKNOWN/",
                rec ? rec->width : 0, rec ? rec->height : 0,
                rec ? rec->levels : 0, rec ? gfx_format_name(rec->format) : "UNKNOWN",
                rec ? (unsigned long)rec->caller_rva : 0xffffffffUL);
        }
    }
    return gfx_real_SetTexture ? gfx_real_SetTexture(self, stage, texture) : E_FAIL;
}

static int gfx_tss_interesting(DWORD type)
{
    switch (type) {
    case 13: case 14: case 15: case 16: case 17: case 18: case 19:
    case 20: case 21: case 25:
        return 1;
    default:
        return 0;
    }
}

static HRESULT WINAPI gfx_fake_SetTextureStageState(void *self, DWORD stage,
    DWORD type, DWORD value)
{
    if (stage < 8 && type < 32 && gfx_tss_interesting(type) &&
        (!gfx_last_tss_valid[stage][type] || gfx_last_tss[stage][type] != value)) {
        LONG n = InterlockedIncrement(&gfx_tss_count);
        gfx_last_tss_valid[stage][type] = 1;
        gfx_last_tss[stage][type] = value;
        if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0 && n <= 1200) {
            if (type == 16 || type == 17 || type == 18) {
                gfx_logf(
                    "TSS n=%ld phase=GAMEPLAY caller_rva=0x%08lx stage=%lu type=%lu value=%lu filter=%s",
                    (long)n, (unsigned long)gfx_caller_rva(__builtin_return_address(0)),
                    (unsigned long)stage, (unsigned long)type, (unsigned long)value,
                    gfx_filter_name(value));
            } else {
                gfx_logf(
                    "TSS n=%ld phase=GAMEPLAY caller_rva=0x%08lx stage=%lu type=%lu value=0x%08lx(%lu)",
                    (long)n, (unsigned long)gfx_caller_rva(__builtin_return_address(0)),
                    (unsigned long)stage, (unsigned long)type,
                    (unsigned long)value, (unsigned long)value);
            }
        }
    }
    return gfx_real_SetTextureStageState ?
        gfx_real_SetTextureStageState(self, stage, type, value) : E_FAIL;
}

static void gfx_log_draw_sample(const char *kind, void *caller, DWORD primitive_type,
    UINT primitive_count, UINT arg_stride, UINT a, UINT b, UINT c)
{
    LONG draw_index;
    GfxTextureRecord *tex0;
    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) == 0) return;
    InterlockedIncrement(&gfx_frame_draws);
    InterlockedExchangeAdd(&gfx_frame_primitives, (LONG)primitive_count);
    draw_index = InterlockedIncrement(&gfx_draw_sample_count);
    if (draw_index > 600 && (draw_index % 2000) != 0) return;
    tex0 = gfx_find_texture(gfx_bound_textures[0]);
    gfx_logf(
        "DRAW n=%ld kind=%s caller_rva=0x%08lx type=%lu prims=%u a=%u b=%u c=%u arg_stride=%u stream_stride=%lu vs=0x%08lx ps=0x%08lx rt=%p tex0=%p%s%ux%u fmt=%s",
        (long)draw_index, kind, (unsigned long)gfx_caller_rva(caller),
        (unsigned long)primitive_type, primitive_count, a, b, c, arg_stride,
        (unsigned long)current_stream_stride, (unsigned long)current_vertex_shader,
        (unsigned long)gfx_current_pixel_shader, gfx_current_render_target,
        gfx_bound_textures[0], tex0 ? " size=" : " size=UNKNOWN/",
        tex0 ? tex0->width : 0, tex0 ? tex0->height : 0,
        tex0 ? gfx_format_name(tex0->format) : "UNKNOWN");
}

static HRESULT WINAPI gfx_fake_DrawPrimitive(void *self, DWORD primitive_type,
    UINT start_vertex, UINT primitive_count)
{
    gfx_log_draw_sample("DP", __builtin_return_address(0), primitive_type,
        primitive_count, 0, start_vertex, 0, 0);
    return gfx_real_DrawPrimitive ?
        gfx_real_DrawPrimitive(self, primitive_type, start_vertex, primitive_count) : E_FAIL;
}

static HRESULT WINAPI gfx_fake_DrawIndexedPrimitive(void *self, DWORD primitive_type,
    UINT min_index, UINT num_vertices, UINT start_index, UINT primitive_count)
{
    gfx_log_draw_sample("DIP", __builtin_return_address(0), primitive_type,
        primitive_count, 0, min_index, num_vertices, start_index);
    return gfx_real_DrawIndexedPrimitive ?
        gfx_real_DrawIndexedPrimitive(self, primitive_type, min_index,
            num_vertices, start_index, primitive_count) : E_FAIL;
}

static HRESULT WINAPI gfx_fake_DrawPrimitiveUP(void *self, DWORD primitive_type,
    UINT primitive_count, const void *vertex_data, UINT vertex_stride)
{
    gfx_log_draw_sample("DPUP", __builtin_return_address(0), primitive_type,
        primitive_count, vertex_stride, 0, 0, 0);
    return gfx_real_DrawPrimitiveUP ?
        gfx_real_DrawPrimitiveUP(self, primitive_type, primitive_count,
            vertex_data, vertex_stride) : E_FAIL;
}

static HRESULT WINAPI gfx_fake_DrawIndexedPrimitiveUP(void *self,
    DWORD primitive_type, UINT min_vertex_index, UINT num_vertex_indices,
    UINT primitive_count, const void *index_data, DWORD index_format,
    const void *vertex_data, UINT vertex_stride)
{
    gfx_log_draw_sample("DIPUP", __builtin_return_address(0), primitive_type,
        primitive_count, vertex_stride, min_vertex_index, num_vertex_indices,
        (UINT)index_format);
    return gfx_real_DrawIndexedPrimitiveUP ?
        gfx_real_DrawIndexedPrimitiveUP(self, primitive_type, min_vertex_index,
            num_vertex_indices, primitive_count, index_data, index_format,
            vertex_data, vertex_stride) : E_FAIL;
}

static HRESULT WINAPI gfx_fake_SetPixelShader(void *self, DWORD handle)
{
    if (gfx_current_pixel_shader != handle) {
        gfx_current_pixel_shader = handle;
        if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0) {
            gfx_logf("PIXEL_SHADER phase=GAMEPLAY caller_rva=0x%08lx handle=0x%08lx",
                (unsigned long)gfx_caller_rva(__builtin_return_address(0)),
                (unsigned long)handle);
        }
    }
    return gfx_real_SetPixelShader ? gfx_real_SetPixelShader(self, handle) : E_FAIL;
}

static void gfx_audit_present_tick(void)
{
    LONG phase = InterlockedCompareExchange(&gameplay_input_phase, 0, 0) ? 1 : 0;
    LONG previous = InterlockedExchange(&gfx_last_phase, phase);
    LONG draws = InterlockedExchange(&gfx_frame_draws, 0);
    LONG prims = InterlockedExchange(&gfx_frame_primitives, 0);
    LONG binds = InterlockedExchange(&gfx_frame_texture_binds, 0);
    LONG rt = InterlockedExchange(&gfx_frame_rt_switches, 0);

    gfx_ensure_log();
    if (previous != phase) {
        gfx_logf("PHASE_CHANGE previous=%s now=%s",
            previous < 0 ? "UNKNOWN" : (previous ? "GAMEPLAY" : "FRONTEND/LOAD"),
            phase ? "GAMEPLAY" : "FRONTEND/LOAD");
    }
    if (phase) {
        LONG frame = InterlockedIncrement(&gfx_gameplay_frame_count);
        if (frame <= 40 || (frame % 120) == 0) {
            gfx_logf(
                "FRAME frame=%ld draws=%ld primitives=%ld texture_binds=%ld rt_switches=%ld viewport=%s%lux%lu rt=%p depth=%p vs=0x%08lx ps=0x%08lx",
                (long)frame, (long)draws, (long)prims, (long)binds, (long)rt,
                gfx_last_viewport_valid ? "" : "UNKNOWN/",
                gfx_last_viewport_valid ? (unsigned long)gfx_last_viewport.Width : 0UL,
                gfx_last_viewport_valid ? (unsigned long)gfx_last_viewport.Height : 0UL,
                gfx_current_render_target, gfx_current_depth_target,
                (unsigned long)current_vertex_shader,
                (unsigned long)gfx_current_pixel_shader);
        }
    }
}

static void gfx_audit_log_hook_status(int texture_ok, int rt_ok, int depth_ok,
    int image_ok, int copy_ok, int update_ok, int set_rt_ok, int viewport_ok,
    int rs_ok, int set_texture_ok, int tss_ok, int dp_ok, int dip_ok,
    int dpup_ok, int dipup_ok, int ps_ok)
{
    gfx_ensure_log();
    gfx_logf(
        "HOOKS texture=%d create_rt=%d create_depth=%d image=%d copy=%d update_texture=%d set_rt=%d viewport=%d render_state=%d set_texture=%d tss=%d draw=%d/%d/%d/%d pixel_shader=%d",
        texture_ok, rt_ok, depth_ok, image_ok, copy_ok, update_ok, set_rt_ok,
        viewport_ok, rs_ok, set_texture_ok, tss_ok, dp_ok, dip_ok, dpup_ok,
        dipup_ok, ps_ok);
}

'''
text = text.replace(marker, helpers + marker, 1)

# Observe the final presentation parameters that are actually submitted after the
# established borderless preparation.  No fields are changed by the audit.
replace_once(
'''    prepare_borderless_create(self, adapter, focus_window, presentation_parameters);\n    hr = real_CreateDevice(self, adapter, device_type, focus_window, behavior_flags,\n''',
'''    prepare_borderless_create(self, adapter, focus_window, presentation_parameters);\n    gfx_audit_note_present_params("CREATEDEVICE", presentation_parameters);\n    hr = real_CreateDevice(self, adapter, device_type, focus_window, behavior_flags,\n''',
    'CreateDevice present-parameter observation',
)

replace_once(
'''    prepare_borderless_reset(presentation_parameters);\n    hr = real_Reset ? real_Reset(self, presentation_parameters) : E_FAIL;\n''',
'''    prepare_borderless_reset(presentation_parameters);\n    gfx_audit_note_present_params("RESET", presentation_parameters);\n    hr = real_Reset ? real_Reset(self, presentation_parameters) : E_FAIL;\n''',
    'Reset present-parameter observation',
)

# Add one passive frame-summary call to the already-proven production Present
# hook; no D3D query is made from inside Present.
replace_once(
'''{\n    enforce_borderless_at_present();\n    return real_Present ? real_Present(self, source_rect, dest_rect,\n        dest_window_override, dirty_region) : E_FAIL;\n}\n''',
'''{\n    gfx_audit_present_tick();\n    enforce_borderless_at_present();\n    return real_Present ? real_Present(self, source_rect, dest_rect,\n        dest_window_override, dirty_region) : E_FAIL;\n}\n''',
    'Present passive frame summary',
)

# Diagnostic-hook failure must never block normal game startup.  The five existing
# production hooks retain their original success condition; graphics-audit hook
# results are logged separately.
replace_once(
'''        int reset_ok, present_ok, shader_ok, constants_ok, stream_ok;\n''',
'''        int reset_ok, present_ok, shader_ok, constants_ok, stream_ok;\n        int gfx_texture_ok, gfx_rt_ok, gfx_depth_ok, gfx_image_ok, gfx_copy_ok;\n        int gfx_update_ok, gfx_set_rt_ok, gfx_viewport_ok, gfx_rs_ok;\n        int gfx_set_texture_ok, gfx_tss_ok, gfx_dp_ok, gfx_dip_ok;\n        int gfx_dpup_ok, gfx_dipup_ok, gfx_ps_ok;\n''',
    'audit hook local variables',
)

replace_once(
'''        present_ok = patch_vtable_slot(vtbl, 15, fake_Present, (void **)&real_Present);\n        shader_ok = patch_vtable_slot(vtbl, 76, fake_SetVertexShader, (void **)&real_SetVertexShader);\n''',
'''        present_ok = patch_vtable_slot(vtbl, 15, fake_Present, (void **)&real_Present);\n        gfx_texture_ok = patch_vtable_slot(vtbl, 20, gfx_fake_CreateTexture, (void **)&gfx_real_CreateTexture);\n        gfx_rt_ok = patch_vtable_slot(vtbl, 25, gfx_fake_CreateRenderTarget, (void **)&gfx_real_CreateRenderTarget);\n        gfx_depth_ok = patch_vtable_slot(vtbl, 26, gfx_fake_CreateDepthStencil, (void **)&gfx_real_CreateDepthStencil);\n        gfx_image_ok = patch_vtable_slot(vtbl, 27, gfx_fake_CreateImageSurface, (void **)&gfx_real_CreateImageSurface);\n        gfx_copy_ok = patch_vtable_slot(vtbl, 28, gfx_fake_CopyRects, (void **)&gfx_real_CopyRects);\n        gfx_update_ok = patch_vtable_slot(vtbl, 29, gfx_fake_UpdateTexture, (void **)&gfx_real_UpdateTexture);\n        gfx_set_rt_ok = patch_vtable_slot(vtbl, 31, gfx_fake_SetRenderTarget, (void **)&gfx_real_SetRenderTarget);\n        gfx_viewport_ok = patch_vtable_slot(vtbl, 40, gfx_fake_SetViewport, (void **)&gfx_real_SetViewport);\n        gfx_rs_ok = patch_vtable_slot(vtbl, 50, gfx_fake_SetRenderState, (void **)&gfx_real_SetRenderState);\n        gfx_set_texture_ok = patch_vtable_slot(vtbl, 61, gfx_fake_SetTexture, (void **)&gfx_real_SetTexture);\n        gfx_tss_ok = patch_vtable_slot(vtbl, 63, gfx_fake_SetTextureStageState, (void **)&gfx_real_SetTextureStageState);\n        gfx_dp_ok = patch_vtable_slot(vtbl, 70, gfx_fake_DrawPrimitive, (void **)&gfx_real_DrawPrimitive);\n        gfx_dip_ok = patch_vtable_slot(vtbl, 71, gfx_fake_DrawIndexedPrimitive, (void **)&gfx_real_DrawIndexedPrimitive);\n        gfx_dpup_ok = patch_vtable_slot(vtbl, 72, gfx_fake_DrawPrimitiveUP, (void **)&gfx_real_DrawPrimitiveUP);\n        gfx_dipup_ok = patch_vtable_slot(vtbl, 73, gfx_fake_DrawIndexedPrimitiveUP, (void **)&gfx_real_DrawIndexedPrimitiveUP);\n        gfx_ps_ok = patch_vtable_slot(vtbl, 88, gfx_fake_SetPixelShader, (void **)&gfx_real_SetPixelShader);\n        shader_ok = patch_vtable_slot(vtbl, 76, fake_SetVertexShader, (void **)&real_SetVertexShader);\n''',
    'audit vtable hooks',
)

replace_once(
'''        if (reset_ok && present_ok && shader_ok && constants_ok && stream_ok) {\n''',
'''        gfx_audit_log_hook_status(gfx_texture_ok, gfx_rt_ok, gfx_depth_ok,\n            gfx_image_ok, gfx_copy_ok, gfx_update_ok, gfx_set_rt_ok, gfx_viewport_ok,\n            gfx_rs_ok, gfx_set_texture_ok, gfx_tss_ok, gfx_dp_ok, gfx_dip_ok,\n            gfx_dpup_ok, gfx_dipup_ok, gfx_ps_ok);\n        if (reset_ok && present_ok && shader_ok && constants_ok && stream_ok) {\n''',
    'audit hook status log',
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern passive gameplay graphics audit v50")
