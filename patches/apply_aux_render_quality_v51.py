from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"aux render quality v51 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


def replace_regex_once(pattern: str, replacement: str, label: str) -> None:
    global text
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"aux render quality v51 {label}: expected exactly one match, found {count}")
    text = updated


# v0.50 showed one dedicated gameplay render-to-texture allocation path at
# mvp2005.exe+0x003B473D, paired with depth allocation at +0x003B4858 and
# matching 128/256 viewports.  v0.51 performs a deliberately narrow 2x quality
# experiment on only those exact resources.  The main 2560x1440 scene, frontend,
# ordinary textures, copy paths, shaders, and all other render targets are left
# untouched.

replace_once(
    'MVP2005 Modern v0.50 gameplay graphics audit',
    'MVP2005 Modern v0.51 auxiliary render-target quality preview + audit',
    'audit header',
)
replace_once(
    'mode=PASSIVE no resource/render-state/filter/viewport modification',
    'mode=EXPERIMENTAL exact gameplay auxiliary render-target/depth/viewport scaling only',
    'audit mode',
)

helper_marker = '''static void gfx_audit_note_present_params(const char *where, void *presentation_parameters)\n'''
if text.count(helper_marker) != 1:
    raise SystemExit(f"aux render quality v51 helper marker: expected one match, found {text.count(helper_marker)}")

helpers = r'''static LONG gfx_aux_quality_config_loaded;
static int gfx_aux_quality_scale = 2;
static LONG gfx_aux_scaled_texture_count;
static LONG gfx_aux_scaled_depth_count;
static LONG gfx_aux_scaled_viewport_count;

static void gfx_aux_quality_load_config(void)
{
    char path[MAX_PATH];
    int scale;

    if (InterlockedCompareExchange(&gfx_aux_quality_config_loaded, 1, 0) != 0)
        return;

    scale = 2;
    if (get_module_dir(path, sizeof(path)) &&
        append_path(path, sizeof(path), "mvp2005fix.ini")) {
        scale = GetPrivateProfileIntA("Graphics", "AuxiliaryScale", 2, path);
    }

    if (scale != 1 && scale != 2 && scale != 4)
        scale = 2;
    gfx_aux_quality_scale = scale;
    gfx_ensure_log();
    gfx_logf("AUX_QUALITY CONFIG scale=%d exact_texture_rva=0x003b473d exact_depth_rva=0x003b4858 eligible_sizes=128,256", scale);
}

static int gfx_aux_quality_texture_eligible(DWORD rva, UINT width, UINT height,
    UINT levels, DWORD usage, DWORD format, DWORD pool)
{
    if (gfx_aux_quality_scale <= 1) return 0;
    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) == 0) return 0;
    if (rva != 0x003b473dUL) return 0;
    if (width != height || (width != 128 && width != 256)) return 0;
    if (levels != 1 || (usage & 1UL) == 0) return 0;
    if (format != 21 || pool != 0) return 0; /* A8R8G8B8, DEFAULT */
    return 1;
}

static int gfx_aux_quality_depth_eligible(DWORD rva, UINT width, UINT height,
    DWORD format, DWORD multisample)
{
    if (gfx_aux_quality_scale <= 1) return 0;
    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) == 0) return 0;
    if (rva != 0x003b4858UL) return 0;
    if (width != height || (width != 128 && width != 256)) return 0;
    if (format != 75 || multisample != 0) return 0; /* D24S8, no MSAA */
    return 1;
}

'''
text = text.replace(helper_marker, helpers + helper_marker, 1)

replace_regex_once(
    r'''static HRESULT WINAPI gfx_fake_CreateTexture\(void \*self, UINT width, UINT height,\n    UINT levels, DWORD usage, DWORD format, DWORD pool, void \*\*texture\)\n\{.*?\n\}\n\n(?=static HRESULT WINAPI gfx_fake_CreateRenderTarget)''',
    r'''static HRESULT WINAPI gfx_fake_CreateTexture(void *self, UINT width, UINT height,
    UINT levels, DWORD usage, DWORD format, DWORD pool, void **texture)
{
    void *caller = __builtin_return_address(0);
    DWORD rva = gfx_caller_rva(caller);
    UINT requested_width = width;
    UINT requested_height = height;
    int scaled = 0;
    HRESULT hr;
    LONG n;
    void *out;

    gfx_aux_quality_load_config();
    if (gfx_aux_quality_texture_eligible(rva, width, height, levels, usage, format, pool)) {
        width *= (UINT)gfx_aux_quality_scale;
        height *= (UINT)gfx_aux_quality_scale;
        scaled = 1;
        gfx_logf("AUX_QUALITY TEXTURE attempt n=%ld original=%ux%u scaled=%ux%u rva=0x%08lx",
            (long)(InterlockedCompareExchange(&gfx_aux_scaled_texture_count, 0, 0) + 1),
            requested_width, requested_height, width, height, (unsigned long)rva);
    }

    hr = gfx_real_CreateTexture ?
        gfx_real_CreateTexture(self, width, height, levels, usage, format, pool, texture) : E_FAIL;
    n = InterlockedIncrement(&gfx_texture_create_count);
    out = texture ? *texture : NULL;
    gfx_register_texture(SUCCEEDED(hr) ? out : NULL, width, height, levels,
        usage, format, pool, rva);

    if (scaled) {
        LONG qn = InterlockedIncrement(&gfx_aux_scaled_texture_count);
        gfx_logf("AUX_QUALITY TEXTURE result n=%ld original=%ux%u actual=%ux%u hr=0x%08lx object=%p",
            (long)qn, requested_width, requested_height, width, height,
            (unsigned long)hr, out);
    }

    if (n <= 3000 || width >= 1024 || height >= 1024 || (usage & 3)) {
        gfx_logf(
            "CREATE_TEXTURE n=%ld phase=%s caller_rva=0x%08lx size=%ux%u levels=%u usage=0x%08lx format=0x%08lx(%s) pool=%lu hr=0x%08lx object=%p",
            (long)n, gfx_phase_name(), (unsigned long)rva, width, height, levels,
            (unsigned long)usage, (unsigned long)format, gfx_format_name(format),
            (unsigned long)pool, (unsigned long)hr, out);
    }
    return hr;
}

''',
    'CreateTexture scaler',
)

replace_regex_once(
    r'''static HRESULT WINAPI gfx_fake_CreateDepthStencil\(void \*self, UINT width, UINT height,\n    DWORD format, DWORD multisample, void \*\*surface\)\n\{.*?\n\}\n\n(?=static HRESULT WINAPI gfx_fake_CreateImageSurface)''',
    r'''static HRESULT WINAPI gfx_fake_CreateDepthStencil(void *self, UINT width, UINT height,
    DWORD format, DWORD multisample, void **surface)
{
    void *caller = __builtin_return_address(0);
    DWORD rva = gfx_caller_rva(caller);
    UINT requested_width = width;
    UINT requested_height = height;
    int scaled = 0;
    HRESULT hr;
    void *out;
    LONG n;

    gfx_aux_quality_load_config();
    if (gfx_aux_quality_depth_eligible(rva, width, height, format, multisample)) {
        width *= (UINT)gfx_aux_quality_scale;
        height *= (UINT)gfx_aux_quality_scale;
        scaled = 1;
        gfx_logf("AUX_QUALITY DEPTH attempt n=%ld original=%ux%u scaled=%ux%u rva=0x%08lx",
            (long)(InterlockedCompareExchange(&gfx_aux_scaled_depth_count, 0, 0) + 1),
            requested_width, requested_height, width, height, (unsigned long)rva);
    }

    hr = gfx_real_CreateDepthStencil ?
        gfx_real_CreateDepthStencil(self, width, height, format, multisample, surface) : E_FAIL;
    out = surface ? *surface : NULL;
    n = InterlockedIncrement(&gfx_surface_create_count);
    gfx_register_surface(SUCCEEDED(hr) ? out : NULL, width, height, format,
        multisample, 2, rva);

    if (scaled) {
        LONG qn = InterlockedIncrement(&gfx_aux_scaled_depth_count);
        gfx_logf("AUX_QUALITY DEPTH result n=%ld original=%ux%u actual=%ux%u hr=0x%08lx object=%p",
            (long)qn, requested_width, requested_height, width, height,
            (unsigned long)hr, out);
    }

    gfx_logf(
        "CREATE_DEPTH n=%ld phase=%s caller_rva=0x%08lx size=%ux%u format=0x%08lx(%s) ms=%lu hr=0x%08lx object=%p",
        (long)n, gfx_phase_name(), (unsigned long)rva, width, height,
        (unsigned long)format, gfx_format_name(format), (unsigned long)multisample,
        (unsigned long)hr, out);
    return hr;
}

''',
    'CreateDepth scaler',
)

replace_regex_once(
    r'''static HRESULT WINAPI gfx_fake_SetViewport\(void \*self, const GfxViewport8Audit \*viewport\)\n\{.*?\n\}\n\n(?=static int gfx_render_state_interesting)''',
    r'''static HRESULT WINAPI gfx_fake_SetViewport(void *self, const GfxViewport8Audit *viewport)
{
    GfxViewport8Audit adjusted;
    const GfxViewport8Audit *effective = viewport;
    GfxSurfaceRecord *depth_rec = NULL;
    int scaled = 0;

    gfx_aux_quality_load_config();
    if (viewport && gfx_aux_quality_scale > 1 &&
        InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0 &&
        viewport->X == 0 && viewport->Y == 0 &&
        viewport->Width == viewport->Height &&
        (viewport->Width == 128 || viewport->Width == 256)) {
        depth_rec = gfx_find_surface(gfx_current_depth_target);
        if (depth_rec && depth_rec->kind == 2 &&
            depth_rec->caller_rva == 0x003b4858UL &&
            depth_rec->width == viewport->Width * (UINT)gfx_aux_quality_scale &&
            depth_rec->height == viewport->Height * (UINT)gfx_aux_quality_scale) {
            adjusted = *viewport;
            adjusted.Width = depth_rec->width;
            adjusted.Height = depth_rec->height;
            effective = &adjusted;
            scaled = 1;
            gfx_logf("AUX_QUALITY VIEWPORT n=%ld original=%lux%lu scaled=%lux%lu depth=%p",
                (long)(InterlockedIncrement(&gfx_aux_scaled_viewport_count)),
                (unsigned long)viewport->Width, (unsigned long)viewport->Height,
                (unsigned long)adjusted.Width, (unsigned long)adjusted.Height,
                gfx_current_depth_target);
        }
    }

    if (effective && (!gfx_last_viewport_valid ||
        effective->X != gfx_last_viewport.X || effective->Y != gfx_last_viewport.Y ||
        effective->Width != gfx_last_viewport.Width || effective->Height != gfx_last_viewport.Height ||
        effective->MinZ != gfx_last_viewport.MinZ || effective->MaxZ != gfx_last_viewport.MaxZ)) {
        LONG n = InterlockedIncrement(&gfx_viewport_count);
        gfx_last_viewport = *effective;
        gfx_last_viewport_valid = 1;
        if (n <= 500) {
            gfx_logf(
                "SET_VIEWPORT n=%ld phase=%s caller_rva=0x%08lx xy=%lu,%lu size=%lux%lu z=%.3f..%.3f%s",
                (long)n, gfx_phase_name(),
                (unsigned long)gfx_caller_rva(__builtin_return_address(0)),
                (unsigned long)effective->X, (unsigned long)effective->Y,
                (unsigned long)effective->Width, (unsigned long)effective->Height,
                effective->MinZ, effective->MaxZ,
                scaled ? " AUX_SCALED" : "");
        }
    }
    return gfx_real_SetViewport ? gfx_real_SetViewport(self, effective) : E_FAIL;
}

''',
    'SetViewport scaler',
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern auxiliary render-target quality preview v51")
