from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"texture filter production v53 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


def replace_regex_once(pattern: str, replacement: str, label: str) -> None:
    global text
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"texture filter production v53 {label}: expected exactly one match, found {count}")
    text = updated


# v0.52 produced a small but visible gameplay improvement and all sampled D3D8
# filter-state requests succeeded.  Promote that behavior while retiring the
# v0.50-v0.52 broad graphics audit and the visually-insignificant auxiliary RT
# scaling experiment.  Production keeps only CreateTexture metadata and
# SetTexture filtering hooks.  SetTextureStageState is called through the
# original vtable entry without installing an extra wrapper.

replace_once(
    'MVP2005 Modern v0.52 texture filtering quality preview + audit',
    'MVP2005 Modern v0.53 production texture filtering',
    'header',
)
replace_once(
    'mode=EXPERIMENTAL gameplay stage0 ordinary-texture filtering only; auxiliary scaling defaults off',
    'mode=PRODUCTION gameplay stage0 ordinary-texture filtering; broad graphics audit retired',
    'mode',
)

# Keep enough metadata capacity for long sessions/modded texture sets.  Records
# are tiny and newest-first lookup already handles pointer reuse correctly.
replace_once(
    'static GfxTextureRecord gfx_textures[4096];',
    'static GfxTextureRecord gfx_textures[16384];',
    'texture metadata capacity',
)

# Production config: same defaults as v0.52, but no graphics log creation.
replace_regex_once(
    r'''static void gfx_filter_quality_load_config\(void\)\n\{.*?\n\}\n\n(?=static int gfx_filter_quality_texture_eligible)''',
    r'''static void gfx_filter_quality_load_config(void)
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
}

''',
    'production filter config',
)

# Retire the auxiliary-scaling CreateTexture experiment entirely.  We still
# register successful textures so SetTexture can cheaply classify ordinary
# textures without any nested COM queries.
replace_regex_once(
    r'''static HRESULT WINAPI gfx_fake_CreateTexture\(void \*self, UINT width, UINT height,\n    UINT levels, DWORD usage, DWORD format, DWORD pool, void \*\*texture\)\n\{.*?\n\}\n\n(?=static HRESULT WINAPI gfx_fake_CreateRenderTarget)''',
    r'''static HRESULT WINAPI gfx_fake_CreateTexture(void *self, UINT width, UINT height,
    UINT levels, DWORD usage, DWORD format, DWORD pool, void **texture)
{
    HRESULT hr = gfx_real_CreateTexture ?
        gfx_real_CreateTexture(self, width, height, levels, usage, format, pool, texture) : E_FAIL;
    void *out = texture ? *texture : NULL;

    if (SUCCEEDED(hr) && out)
        gfx_register_texture(out, width, height, levels, usage, format, pool, 0);
    return hr;
}

''',
    'lean CreateTexture hook',
)

# Exact v0.52 filtering semantics, minus all audit counters/logging.  Filtering
# remains stage-0 only, gameplay only, >=128x128, and excludes render-target
# textures.  Mip filtering is changed only when the texture actually has mips.
replace_regex_once(
    r'''static HRESULT WINAPI gfx_fake_SetTexture\(void \*self, DWORD stage, void \*texture\)\n\{.*?\n\}\n\n(?=static int gfx_tss_interesting)''',
    r'''static HRESULT WINAPI gfx_fake_SetTexture(void *self, DWORD stage, void *texture)
{
    GfxTextureRecord *rec = gfx_find_texture(texture);
    HRESULT hr;

    gfx_filter_quality_load_config();
    hr = gfx_real_SetTexture ? gfx_real_SetTexture(self, stage, texture) : E_FAIL;

    if (SUCCEEDED(hr) && gfx_filter_quality_texture_eligible(stage, rec) &&
        gfx_real_SetTextureStageState) {
        gfx_real_SetTextureStageState(self, stage, 21,
            (DWORD)gfx_filter_quality_anisotropy); /* MAXANISOTROPY */
        gfx_real_SetTextureStageState(self, stage, 16, 2); /* MAGFILTER LINEAR */
        gfx_real_SetTextureStageState(self, stage, 17, 3); /* MINFILTER ANISOTROPIC */
        if (rec->levels > 1)
            gfx_real_SetTextureStageState(self, stage, 18, 2); /* MIPFILTER LINEAR */
    }

    return hr;
}

''',
    'lean SetTexture filtering hook',
)

# Remove graphics-audit work from the production Present/CreateDevice/Reset
# paths.  The old helper bodies remain inert in source to minimize patch churn.
if text.count('    gfx_audit_present_tick();\n') != 1:
    raise SystemExit(f"texture filter production v53 Present audit call: expected one match, found {text.count('    gfx_audit_present_tick();')}")
text = text.replace('    gfx_audit_present_tick();\n', '', 1)

for call, label in [
    ('    gfx_audit_note_present_params("CREATEDEVICE", presentation_parameters);\n', 'CreateDevice audit call'),
    ('    gfx_audit_note_present_params("RESET", presentation_parameters);\n', 'Reset audit call'),
]:
    count = text.count(call)
    if count != 1:
        raise SystemExit(f"texture filter production v53 {label}: expected one match, found {count}")
    text = text.replace(call, '', 1)

# Replace the broad audit hook set with the two production hooks.  Grab the
# original SetTextureStageState pointer directly instead of installing a wrapper.
old_hooks = '''        gfx_texture_ok = patch_vtable_slot(vtbl, 20, gfx_fake_CreateTexture, (void **)&gfx_real_CreateTexture);
        gfx_rt_ok = patch_vtable_slot(vtbl, 25, gfx_fake_CreateRenderTarget, (void **)&gfx_real_CreateRenderTarget);
        gfx_depth_ok = patch_vtable_slot(vtbl, 26, gfx_fake_CreateDepthStencil, (void **)&gfx_real_CreateDepthStencil);
        gfx_image_ok = patch_vtable_slot(vtbl, 27, gfx_fake_CreateImageSurface, (void **)&gfx_real_CreateImageSurface);
        gfx_copy_ok = patch_vtable_slot(vtbl, 28, gfx_fake_CopyRects, (void **)&gfx_real_CopyRects);
        gfx_update_ok = patch_vtable_slot(vtbl, 29, gfx_fake_UpdateTexture, (void **)&gfx_real_UpdateTexture);
        gfx_set_rt_ok = patch_vtable_slot(vtbl, 31, gfx_fake_SetRenderTarget, (void **)&gfx_real_SetRenderTarget);
        gfx_viewport_ok = patch_vtable_slot(vtbl, 40, gfx_fake_SetViewport, (void **)&gfx_real_SetViewport);
        gfx_rs_ok = patch_vtable_slot(vtbl, 50, gfx_fake_SetRenderState, (void **)&gfx_real_SetRenderState);
        gfx_set_texture_ok = patch_vtable_slot(vtbl, 61, gfx_fake_SetTexture, (void **)&gfx_real_SetTexture);
        gfx_tss_ok = patch_vtable_slot(vtbl, 63, gfx_fake_SetTextureStageState, (void **)&gfx_real_SetTextureStageState);
        gfx_dp_ok = patch_vtable_slot(vtbl, 70, gfx_fake_DrawPrimitive, (void **)&gfx_real_DrawPrimitive);
        gfx_dip_ok = patch_vtable_slot(vtbl, 71, gfx_fake_DrawIndexedPrimitive, (void **)&gfx_real_DrawIndexedPrimitive);
        gfx_dpup_ok = patch_vtable_slot(vtbl, 72, gfx_fake_DrawPrimitiveUP, (void **)&gfx_real_DrawPrimitiveUP);
        gfx_dipup_ok = patch_vtable_slot(vtbl, 73, gfx_fake_DrawIndexedPrimitiveUP, (void **)&gfx_real_DrawIndexedPrimitiveUP);
        gfx_ps_ok = patch_vtable_slot(vtbl, 88, gfx_fake_SetPixelShader, (void **)&gfx_real_SetPixelShader);
'''
new_hooks = '''        gfx_texture_ok = patch_vtable_slot(vtbl, 20, gfx_fake_CreateTexture, (void **)&gfx_real_CreateTexture);
        gfx_set_texture_ok = patch_vtable_slot(vtbl, 61, gfx_fake_SetTexture, (void **)&gfx_real_SetTexture);
        gfx_real_SetTextureStageState = (GfxSetTextureStageStateFn)vtbl[63];
        gfx_tss_ok = gfx_real_SetTextureStageState != NULL;
        gfx_rt_ok = gfx_depth_ok = gfx_image_ok = gfx_copy_ok = 0;
        gfx_update_ok = gfx_set_rt_ok = gfx_viewport_ok = gfx_rs_ok = 0;
        gfx_dp_ok = gfx_dip_ok = gfx_dpup_ok = gfx_dipup_ok = gfx_ps_ok = 0;
'''
replace_once(old_hooks, new_hooks, 'production hook set')

# The old hook-status logger would create the graphics log even though the audit
# hooks are retired.  Remove only the call; keeping the dead helper is safer.
old_status = '''        gfx_audit_log_hook_status(gfx_texture_ok, gfx_rt_ok, gfx_depth_ok,
            gfx_image_ok, gfx_copy_ok, gfx_update_ok, gfx_set_rt_ok, gfx_viewport_ok,
            gfx_rs_ok, gfx_set_texture_ok, gfx_tss_ok, gfx_dp_ok, gfx_dip_ok,
            gfx_dpup_ok, gfx_dipup_ok, gfx_ps_ok);
'''
replace_once(old_status, '', 'audit hook-status call')

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern production texture filtering v53")
