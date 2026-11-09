from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"texture filter quality v52 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


def replace_regex_once(pattern: str, replacement: str, label: str) -> None:
    global text
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"texture filter quality v52 {label}: expected exactly one match, found {count}")
    text = updated


# v0.51 proved the 128/256 auxiliary target path can be scaled safely, but the
# visual effect is too subtle to justify enabling it by default.  v0.52 disables
# that experiment by default and instead tests a broader, lower-risk quality win:
# high-quality filtering for ordinary stage-0 gameplay textures.  Render-target
# textures and very small lookup/UI textures are excluded.

replace_once(
    'MVP2005 Modern v0.51 auxiliary render-target quality preview + audit',
    'MVP2005 Modern v0.52 texture filtering quality preview + audit',
    'audit header',
)
replace_once(
    'mode=EXPERIMENTAL exact gameplay auxiliary render-target/depth/viewport scaling only',
    'mode=EXPERIMENTAL gameplay stage0 ordinary-texture filtering only; auxiliary scaling defaults off',
    'audit mode',
)

replace_once(
    'static int gfx_aux_quality_scale = 2;',
    'static int gfx_aux_quality_scale = 1;',
    'aux default static',
)
if text.count('    scale = 2;') != 2:
    raise SystemExit(f"texture filter quality v52 aux local defaults: expected 2 matches, found {text.count('    scale = 2;')}")
text = text.replace('    scale = 2;', '    scale = 1;')
replace_once(
    'GetPrivateProfileIntA("Graphics", "AuxiliaryScale", 2, path)',
    'GetPrivateProfileIntA("Graphics", "AuxiliaryScale", 1, path)',
    'aux ini default',
)

helper_marker = '''static void gfx_audit_note_present_params(const char *where, void *presentation_parameters)\n'''
if text.count(helper_marker) != 1:
    raise SystemExit(f"texture filter quality v52 helper marker: expected one match, found {text.count(helper_marker)}")

helpers = r'''static LONG gfx_filter_quality_config_loaded;
static int gfx_filter_quality_enabled = 1;
static int gfx_filter_quality_anisotropy = 16;
static LONG gfx_filter_quality_bind_count;
static LONG gfx_filter_quality_failure_count;

static void gfx_filter_quality_load_config(void)
{
    char path[MAX_PATH];
    int enabled = 1;
    int anisotropy = 16;

    if (InterlockedCompareExchange(&gfx_filter_quality_config_loaded, 1, 0) != 0)
        return;

    if (get_module_dir(path, sizeof(path)) &&
        append_path(path, sizeof(path), "mvp2005fix.ini")) {
        enabled = GetPrivateProfileIntA("Graphics", "TextureFiltering", 1, path) ? 1 : 0;
        anisotropy = GetPrivateProfileIntA("Graphics", "Anisotropy", 16, path);
    }

    if (anisotropy != 1 && anisotropy != 2 && anisotropy != 4 &&
        anisotropy != 8 && anisotropy != 16)
        anisotropy = 16;

    gfx_filter_quality_enabled = enabled;
    gfx_filter_quality_anisotropy = anisotropy;
    gfx_ensure_log();
    gfx_logf("FILTER_QUALITY CONFIG enabled=%d anisotropy=%d stage=0 min=ANISOTROPIC mag=LINEAR mip=LINEAR exclude_render_targets=1 min_dimension=128",
        enabled, anisotropy);
}

static int gfx_filter_quality_texture_eligible(DWORD stage, GfxTextureRecord *rec)
{
    if (!gfx_filter_quality_enabled) return 0;
    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) == 0) return 0;
    if (stage != 0 || !rec) return 0;
    if ((rec->usage & 1UL) != 0) return 0; /* do not alter sampled render targets */
    if (rec->width < 128 || rec->height < 128) return 0;
    return 1;
}

'''
text = text.replace(helper_marker, helpers + helper_marker, 1)

replace_regex_once(
    r'''static HRESULT WINAPI gfx_fake_SetTexture\(void \*self, DWORD stage, void \*texture\)\n\{.*?\n\}\n\n(?=static int gfx_tss_interesting)''',
    r'''static HRESULT WINAPI gfx_fake_SetTexture(void *self, DWORD stage, void *texture)
{
    GfxTextureRecord *rec = gfx_find_texture(texture);
    HRESULT hr;

    gfx_filter_quality_load_config();

    if (stage < 8 && gfx_bound_textures[stage] != texture) {
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

    hr = gfx_real_SetTexture ? gfx_real_SetTexture(self, stage, texture) : E_FAIL;

    if (SUCCEEDED(hr) && gfx_filter_quality_texture_eligible(stage, rec) &&
        gfx_real_SetTextureStageState) {
        HRESULT h_aniso;
        HRESULT h_mag;
        HRESULT h_min;
        HRESULT h_mip = 0;
        LONG qn;

        h_aniso = gfx_real_SetTextureStageState(self, stage, 21,
            (DWORD)gfx_filter_quality_anisotropy); /* MAXANISOTROPY */
        h_mag = gfx_real_SetTextureStageState(self, stage, 16, 2); /* MAGFILTER LINEAR */
        h_min = gfx_real_SetTextureStageState(self, stage, 17, 3); /* MINFILTER ANISOTROPIC */
        if (rec->levels > 1)
            h_mip = gfx_real_SetTextureStageState(self, stage, 18, 2); /* MIPFILTER LINEAR */

        qn = InterlockedIncrement(&gfx_filter_quality_bind_count);
        if (FAILED(h_aniso) || FAILED(h_mag) || FAILED(h_min) || FAILED(h_mip))
            InterlockedIncrement(&gfx_filter_quality_failure_count);

        if (qn <= 80 || FAILED(h_aniso) || FAILED(h_mag) || FAILED(h_min) || FAILED(h_mip) ||
            (qn % 2000) == 0) {
            gfx_logf(
                "FILTER_QUALITY APPLY n=%ld tex=%p size=%ux%u levels=%u fmt=%s aniso=%d hr_aniso=0x%08lx hr_mag=0x%08lx hr_min=0x%08lx hr_mip=0x%08lx failures=%ld",
                (long)qn, texture, rec->width, rec->height, rec->levels,
                gfx_format_name(rec->format), gfx_filter_quality_anisotropy,
                (unsigned long)h_aniso, (unsigned long)h_mag,
                (unsigned long)h_min, (unsigned long)h_mip,
                (long)InterlockedCompareExchange(&gfx_filter_quality_failure_count, 0, 0));
        }
    }

    return hr;
}

''',
    'SetTexture filtering',
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern gameplay texture filtering quality preview v52")
