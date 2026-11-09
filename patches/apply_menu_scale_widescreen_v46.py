from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"menu scale v46 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


def replace_regex_once(pattern: str, replacement: str, label: str) -> None:
    global text
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"menu scale v46 {label}: expected exactly one match, found {count}")
    text = updated


# v0.45 proved that a non-zero centered D3D viewport clips some frontend draws:
# the background/panels moved into the 4:3 viewport, while several menu labels
# remained effectively screen-space and were cut off at viewport X=320.
#
# v0.46 keeps the viewport at the complete HD backbuffer (origin 0,0) and moves
# aspect correction into the frontend's verified 800x600 orthographic matrix.
# This avoids viewport-origin clipping.  It also tests a hybrid true-widescreen
# presentation:
#   - the common UI shader (handle 0x00000005 in v0.44/v0.45 diagnostics) gets
#     a centered 4:3 FIT transform inside the full viewport;
#   - other verified 800x600 2D layers get a 16:9 COVER transform, preserving
#     proportions while cropping 75 logical pixels from the top and bottom.
# Gameplay/3D matrices are untouched.

replace_once(
    'MVP2005 Modern v0.45 aspect-correct frontend scaling',
    'MVP2005 Modern v0.46 hybrid 16:9 frontend scaling',
    'diagnostic header',
)
replace_once(
    'experiment=center logical 800x600 frontend in aspect-correct 4:3 viewport inside HD backbuffer; mouse uses same transform; gameplay untouched',
    'experiment=full HD viewport; frontend 800x600 orthographic matrices become UI FIT or background COVER for 16:9; mouse tracks centered UI; gameplay untouched',
    'diagnostic description',
)

replace_once(
'''static LONG menu_mouse_log_count;\nstatic volatile LONG menu_last_matrix_was_2d;\n''',
'''static LONG menu_mouse_log_count;\nstatic LONG menu_wide_matrix_log_count;\nstatic volatile LONG menu_last_matrix_was_2d;\n''',
    'widescreen matrix counter',
)

# The non-zero viewport origin is the source of v0.45's clipping. Keep the full
# target viewport and use the matrix hook for all aspect work instead.
replace_regex_once(
    r'''static HRESULT WINAPI menu_fake_SetViewport\(void \*self, const D3DViewport8MenuLocal \*viewport\)\n\{.*?\n\}\n\n(?=static HRESULT WINAPI menu_fake_GetViewport)''',
    r'''static HRESULT WINAPI menu_fake_SetViewport(void *self, const D3DViewport8MenuLocal *viewport)
{
    D3DViewport8MenuLocal adjusted;
    const D3DViewport8MenuLocal *to_send = viewport;
    int gameplay = InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0;
    int candidate = 0;
    int applied = 0;
    HRESULT hr;
    LONG n;

    menu_diag_ensure_open();
    n = InterlockedIncrement(&menu_viewport_log_count);
    menu_diag_logf(
        "SETVIEWPORT ENTER n=%ld phase=%s ptr=%p in=%lu,%lu %lux%lu z=%.3f..%.3f logical=%ux%u target=%ux%u",
        (long)n, gameplay ? "GAMEPLAY" : "FRONTEND", viewport,
        viewport ? (unsigned long)viewport->X : 0UL,
        viewport ? (unsigned long)viewport->Y : 0UL,
        viewport ? (unsigned long)viewport->Width : 0UL,
        viewport ? (unsigned long)viewport->Height : 0UL,
        viewport ? viewport->MinZ : 0.0f, viewport ? viewport->MaxZ : 0.0f,
        (unsigned int)borderless_logical_width, (unsigned int)borderless_logical_height,
        (unsigned int)menu_scale_target_width, (unsigned int)menu_scale_target_height);

    if (viewport && !gameplay && viewport->X == 0 && viewport->Y == 0 &&
        viewport->Width == 800 && viewport->Height == 600) {
        candidate = 1;
        if (menu_scale_enabled && menu_scale_target_width >= 800 &&
            menu_scale_target_height >= 600 &&
            (menu_scale_target_width != 800 || menu_scale_target_height != 600)) {
            adjusted = *viewport;
            adjusted.X = 0;
            adjusted.Y = 0;
            adjusted.Width = menu_scale_target_width;
            adjusted.Height = menu_scale_target_height;
            to_send = &adjusted;
            applied = 1;
            InterlockedIncrement(&menu_scale_apply_count);
        }
    }

    hr = menu_real_SetViewport ? menu_real_SetViewport(self, to_send) : E_FAIL;
    menu_diag_logf(
        "SETVIEWPORT EXIT n=%ld candidate=%d applied=%d out=%lu,%lu %lux%lu hr=0x%08lx",
        (long)n, candidate, applied,
        to_send ? (unsigned long)to_send->X : 0UL,
        to_send ? (unsigned long)to_send->Y : 0UL,
        to_send ? (unsigned long)to_send->Width : 0UL,
        to_send ? (unsigned long)to_send->Height : 0UL,
        (unsigned long)hr);
    return hr;
}

''',
    'full-target SetViewport wrapper',
)

# v0.43 inserted a single diagnostic call immediately before the existing
# widescreen/gameplay matrix logic. Replace that call with a bounded local copy
# of only the exact 800x600 frontend orthographic matrix observed in v0.44/v0.45.
# This never mutates MVP's source buffer. Subsequent production matrix logic sees
# our local pointer for this one D3D call only.
replace_once(
'''    menu_diag_note_matrix(register_address, constant_data, constant_count);\n''',
'''    {\n        const float *menu_matrix_in = (const float *)constant_data;\n        float menu_matrix_copy[256];\n        int menu_matrix_match = 0;\n        int menu_matrix_ui_fit = 0;\n        int menu_matrix_cover = 0;\n\n        if (menu_scale_enabled && constant_data && constant_count >= 4 &&\n            constant_count <= 64 &&\n            (register_address == 0 || register_address == 12) &&\n            InterlockedCompareExchange(&gameplay_input_phase, 0, 0) == 0 &&\n            is_probably_2d_ortho_matrix(menu_matrix_in) &&\n            menu_matrix_in[0] > 0.00249f && menu_matrix_in[0] < 0.00251f &&\n            menu_matrix_in[3] > -1.001f && menu_matrix_in[3] < -0.999f &&\n            menu_matrix_in[5] < -0.00332f && menu_matrix_in[5] > -0.00335f &&\n            menu_matrix_in[7] > 0.999f && menu_matrix_in[7] < 1.001f) {\n            DWORD shader = current_vertex_shader;\n            memcpy(menu_matrix_copy, constant_data,\n                (size_t)constant_count * 4U * sizeof(float));\n            menu_matrix_match = 1;\n\n            if (shader == 0x00000005UL) {\n                /* UI FIT: 800 logical units occupy 1920 pixels at 1440p,\n                   centered in the 2560-wide target. Equivalent 16:9 logical\n                   canvas width is 1066.6667 with 133.3333-unit side margins. */\n                menu_matrix_copy[0] = 0.001875000f;\n                menu_matrix_copy[3] = -0.750000000f;\n                menu_matrix_ui_fit = 1;\n            } else {\n                /* BACKGROUND COVER: scale uniformly by target width. 800x600\n                   becomes 2560x1920, then center-crop 240 px at top/bottom. */\n                menu_matrix_copy[5] = -0.004444444f;\n                menu_matrix_copy[7] = 1.333333333f;\n                menu_matrix_cover = 1;\n            }\n            constant_data = menu_matrix_copy;\n\n            if (InterlockedIncrement(&menu_wide_matrix_log_count) <= 240) {\n                menu_diag_logf(\n                    "WIDE MATRIX reg=%lu shader=0x%08lx mode=%s before=[%.6f %.6f %.6f %.6f | %.6f %.6f %.6f %.6f] after=[%.6f %.6f %.6f %.6f | %.6f %.6f %.6f %.6f]",\n                    (unsigned long)register_address, (unsigned long)shader,\n                    menu_matrix_ui_fit ? "UI_FIT" : "BACKGROUND_COVER",\n                    menu_matrix_in[0], menu_matrix_in[1], menu_matrix_in[2], menu_matrix_in[3],\n                    menu_matrix_in[4], menu_matrix_in[5], menu_matrix_in[6], menu_matrix_in[7],\n                    menu_matrix_copy[0], menu_matrix_copy[1], menu_matrix_copy[2], menu_matrix_copy[3],\n                    menu_matrix_copy[4], menu_matrix_copy[5], menu_matrix_copy[6], menu_matrix_copy[7]);\n            }\n        }\n\n        (void)menu_matrix_match;\n        (void)menu_matrix_ui_fit;\n        (void)menu_matrix_cover;\n        menu_diag_note_matrix(register_address, constant_data, constant_count);\n    }\n''',
    'frontend widescreen matrix override',
)

# Keep v0.45's mouse transform intentionally: UI_FIT occupies exactly the same
# physical 320..2239 by 0..1439 region, but now the full D3D viewport remains at
# 0,0 so screen-space draws cannot be clipped by the viewport origin.
replace_once(
    'HOOKS V45 reset=%d present=%d set_vp=%d shader=%d constants=%d stream=%d aspect_fit=1 mouse_fit=1',
    'HOOKS V46 reset=%d present=%d set_vp=%d shader=%d constants=%d stream=%d full_viewport=1 ui_fit_matrix=1 background_cover=1 mouse_fit=1',
    'hook diagnostic identity',
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern hybrid 16:9 frontend scaling v46")
