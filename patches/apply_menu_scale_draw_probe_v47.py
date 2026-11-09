from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"menu scale v47 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


def replace_regex_once(pattern: str, replacement: str, label: str) -> None:
    global text
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"menu scale v47 {label}: expected exactly one match, found {count}")
    text = updated


# v0.46 proved that shader handle is not a semantic UI/background classifier.
# Different frontend elements share the same few shaders, so giving them different
# projections split the menu into incompatible coordinate spaces. v0.47 restores
# one coherent frontend transform while preserving the full 0,0 HD viewport that
# avoided v0.45's non-zero-viewport clipping.
#
# It also fixes a subtle interaction with the older gameplay aspect hook: the
# fitted 800x600 matrix no longer resembles MVP's original 2D ortho matrix, so the
# older hook could mistake it for 3D and multiply the X row a second time. We
# explicitly classify the fitted frontend matrix before those older tests.
#
# Finally, hook only the four D3D8 draw entry points (no nested COM/surface calls)
# and log caller RVA + shader/stride/primitive metadata. This should let the next
# true-widescreen attempt identify actual background draw paths instead of guessing
# from shader IDs.

replace_once(
    'MVP2005 Modern v0.46 hybrid 16:9 frontend scaling',
    'MVP2005 Modern v0.47 coherent frontend fit + draw-path probe',
    'diagnostic header',
)
replace_once(
    'experiment=full HD viewport; frontend 800x600 orthographic matrices become UI FIT or background COVER for 16:9; mouse tracks centered UI; gameplay untouched',
    'experiment=full HD viewport; every exact 800x600 frontend ortho matrix uses one coherent centered fit; draw calls traced by caller; gameplay untouched',
    'diagnostic description',
)

# Replace v0.46's shader-based split with one coherent projection. At 2560x1440,
# X clip space becomes -0.75..+0.75, i.e. physical X=320..2240, while Y remains
# the complete 600 logical units / 1440 physical pixels. All UI layers therefore
# share exactly one coordinate system, but D3D's viewport itself stays full-size.
replace_regex_once(
    r'''    \{\n        const float \*menu_matrix_in = \(const float \*\)constant_data;\n        float menu_matrix_copy\[256\];\n        int menu_matrix_match = 0;\n        int menu_matrix_ui_fit = 0;\n        int menu_matrix_cover = 0;\n.*?        menu_diag_note_matrix\(register_address, constant_data, constant_count\);\n    \}\n''',
    r'''    {
        const float *menu_matrix_in = (const float *)constant_data;
        float menu_matrix_copy[256];
        int menu_matrix_match = 0;

        if (menu_scale_enabled && constant_data && constant_count >= 4 &&
            constant_count <= 64 && (register_address == 0 || register_address == 12) &&
            InterlockedCompareExchange(&gameplay_input_phase, 0, 0) == 0 &&
            menu_matrix_in[0] > 0.00249f && menu_matrix_in[0] < 0.00251f &&
            menu_matrix_in[1] > -0.00001f && menu_matrix_in[1] < 0.00001f &&
            menu_matrix_in[2] > -0.00001f && menu_matrix_in[2] < 0.00001f &&
            menu_matrix_in[3] > -1.001f && menu_matrix_in[3] < -0.999f &&
            menu_matrix_in[4] > -0.00001f && menu_matrix_in[4] < 0.00001f &&
            menu_matrix_in[5] > -0.00335f && menu_matrix_in[5] < -0.00332f &&
            menu_matrix_in[6] > -0.00001f && menu_matrix_in[6] < 0.00001f &&
            menu_matrix_in[7] > 0.999f && menu_matrix_in[7] < 1.001f) {
            memcpy(menu_matrix_copy, constant_data, constant_count * 4 * sizeof(float));
            menu_matrix_match = 1;

            /* Full 2560x1440 viewport + logical 800x600 fit:
               clip X = x*(1.5/800)-0.75; Y remains original. */
            menu_matrix_copy[0] = 0.001875f;
            menu_matrix_copy[3] = -0.750000f;
            constant_data = menu_matrix_copy;

            if (InterlockedIncrement(&menu_wide_matrix_log_count) <= 320) {
                menu_diag_logf(
                    "FIT MATRIX reg=%lu shader=0x%08lx mode=COHERENT_FIT before=[%.6f %.6f %.6f %.6f | %.6f %.6f %.6f %.6f] after=[%.6f %.6f %.6f %.6f | %.6f %.6f %.6f %.6f]",
                    (unsigned long)register_address,
                    (unsigned long)current_vertex_shader,
                    menu_matrix_in[0], menu_matrix_in[1], menu_matrix_in[2], menu_matrix_in[3],
                    menu_matrix_in[4], menu_matrix_in[5], menu_matrix_in[6], menu_matrix_in[7],
                    menu_matrix_copy[0], menu_matrix_copy[1], menu_matrix_copy[2], menu_matrix_copy[3],
                    menu_matrix_copy[4], menu_matrix_copy[5], menu_matrix_copy[6], menu_matrix_copy[7]);
            }
        }

        /* Diagnostics classify the original MVP matrix, not our fitted copy. */
        menu_diag_note_matrix(register_address,
            menu_matrix_match ? (const void *)menu_matrix_in : constant_data,
            constant_count);
    }
''',
    'coherent matrix transform',
)

# Recognize the exact fitted matrix so the older v16 gameplay detector and the
# original gameplay widescreen/aspect correction do not reinterpret it as 3D.
marker = '''static int append_path(char *out, size_t out_size, const char *dir, const char *leaf)\n'''
if text.count(marker) != 1:
    raise SystemExit(f"menu scale v47 fitted classifier marker expected one match, found {text.count(marker)}")
classifier = r'''static int menu_v47_is_fitted_frontend_matrix(const float *f)
{
    if (!f) return 0;
    return f[0] > 0.001874f && f[0] < 0.001876f &&
           f[1] > -0.00001f && f[1] < 0.00001f &&
           f[2] > -0.00001f && f[2] < 0.00001f &&
           f[3] > -0.751f && f[3] < -0.749f &&
           f[4] > -0.00001f && f[4] < 0.00001f &&
           f[5] > -0.00335f && f[5] < -0.00332f &&
           f[6] > -0.00001f && f[6] < 0.00001f &&
           f[7] > 0.999f && f[7] < 1.001f;
}

'''
text = text.replace(marker, classifier + marker, 1)

needle = '!is_probably_2d_ortho_matrix((const float *)constant_data)'
needle_count = text.count(needle)
if needle_count != 2:
    raise SystemExit(f"menu scale v47 expected two 3D-classifier conditions, found {needle_count}")
text = text.replace(
    needle,
    needle + ' &&\n        !menu_v47_is_fitted_frontend_matrix((const float *)constant_data)',
)

# ---- Safe draw-call diagnostics ---------------------------------------------
# D3D8 IDirect3DDevice8 slots 70..73 are DrawPrimitive, DrawIndexedPrimitive,
# DrawPrimitiveUP, DrawIndexedPrimitiveUP. These wrappers only inspect primitive
# arguments and already-tracked shader/stride state; they never query COM objects.
replace_once(
'''typedef HRESULT (WINAPI *SetStreamSourceFn)(void *self, UINT stream_number, void *stream_data,\n    UINT stride);\n''',
'''typedef HRESULT (WINAPI *SetStreamSourceFn)(void *self, UINT stream_number, void *stream_data,\n    UINT stride);\ntypedef HRESULT (WINAPI *DrawPrimitiveMenuFn)(void *self, DWORD primitive_type,\n    UINT start_vertex, UINT primitive_count);\ntypedef HRESULT (WINAPI *DrawIndexedPrimitiveMenuFn)(void *self, DWORD primitive_type,\n    UINT min_index, UINT num_vertices, UINT start_index, UINT primitive_count);\ntypedef HRESULT (WINAPI *DrawPrimitiveUPMenuFn)(void *self, DWORD primitive_type,\n    UINT primitive_count, const void *vertex_data, UINT vertex_stride);\ntypedef HRESULT (WINAPI *DrawIndexedPrimitiveUPMenuFn)(void *self, DWORD primitive_type,\n    UINT min_vertex_index, UINT num_vertex_indices, UINT primitive_count,\n    const void *index_data, DWORD index_format, const void *vertex_data,\n    UINT vertex_stride);\n''',
'draw typedefs',
)

replace_once(
'''static SetStreamSourceFn real_SetStreamSource;\nstatic DWORD current_vertex_shader;\n''',
'''static SetStreamSourceFn real_SetStreamSource;\nstatic DrawPrimitiveMenuFn menu_real_DrawPrimitive;\nstatic DrawIndexedPrimitiveMenuFn menu_real_DrawIndexedPrimitive;\nstatic DrawPrimitiveUPMenuFn menu_real_DrawPrimitiveUP;\nstatic DrawIndexedPrimitiveUPMenuFn menu_real_DrawIndexedPrimitiveUP;\nstatic LONG menu_draw_log_count;\nstatic DWORD current_vertex_shader;\n''',
'draw globals',
)

stream_fn = '''static HRESULT WINAPI fake_SetStreamSource(void *self, UINT stream_number, void *stream_data,\n    UINT stride)\n{\n    if (stream_number == 0) current_stream_stride = stride;\n    return real_SetStreamSource(self, stream_number, stream_data, stride);\n}\n\n'''
if text.count(stream_fn) != 1:
    raise SystemExit(f"menu scale v47 fake_SetStreamSource expected one match, found {text.count(stream_fn)}")

draw_code = r'''static DWORD menu_v47_draw_caller_rva(void *caller)
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

static void menu_v47_log_draw(const char *kind, void *caller, DWORD primitive_type,
    UINT primitive_count, UINT arg_stride, UINT a, UINT b, UINT c)
{
    LONG n;
    DWORD rva;
    LONG frame;

    if (!menu_scale_diagnostics ||
        InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0) return;

    n = InterlockedIncrement(&menu_draw_log_count);
    if (n > 1600) return;
    rva = menu_v47_draw_caller_rva(caller);
    frame = InterlockedCompareExchange(&menu_present_log_count, 0, 0);
    menu_diag_logf(
        "DRAW n=%ld frame=%ld kind=%s caller=%p rva=0x%08lx shader=0x%08lx stream_stride=%lu arg_stride=%lu type=%lu prims=%lu a=%lu b=%lu c=%lu",
        (long)n, (long)frame, kind, caller, (unsigned long)rva,
        (unsigned long)current_vertex_shader, (unsigned long)current_stream_stride,
        (unsigned long)arg_stride, (unsigned long)primitive_type,
        (unsigned long)primitive_count, (unsigned long)a, (unsigned long)b,
        (unsigned long)c);
}

static HRESULT WINAPI menu_fake_DrawPrimitive(void *self, DWORD primitive_type,
    UINT start_vertex, UINT primitive_count)
{
    void *caller = __builtin_return_address(0);
    menu_v47_log_draw("DP", caller, primitive_type, primitive_count, 0,
        start_vertex, 0, 0);
    return menu_real_DrawPrimitive ?
        menu_real_DrawPrimitive(self, primitive_type, start_vertex, primitive_count) : E_FAIL;
}

static HRESULT WINAPI menu_fake_DrawIndexedPrimitive(void *self, DWORD primitive_type,
    UINT min_index, UINT num_vertices, UINT start_index, UINT primitive_count)
{
    void *caller = __builtin_return_address(0);
    menu_v47_log_draw("DIP", caller, primitive_type, primitive_count, 0,
        min_index, num_vertices, start_index);
    return menu_real_DrawIndexedPrimitive ?
        menu_real_DrawIndexedPrimitive(self, primitive_type, min_index, num_vertices,
            start_index, primitive_count) : E_FAIL;
}

static HRESULT WINAPI menu_fake_DrawPrimitiveUP(void *self, DWORD primitive_type,
    UINT primitive_count, const void *vertex_data, UINT vertex_stride)
{
    void *caller = __builtin_return_address(0);
    menu_v47_log_draw("DPUP", caller, primitive_type, primitive_count, vertex_stride,
        0, 0, 0);
    return menu_real_DrawPrimitiveUP ?
        menu_real_DrawPrimitiveUP(self, primitive_type, primitive_count,
            vertex_data, vertex_stride) : E_FAIL;
}

static HRESULT WINAPI menu_fake_DrawIndexedPrimitiveUP(void *self, DWORD primitive_type,
    UINT min_vertex_index, UINT num_vertex_indices, UINT primitive_count,
    const void *index_data, DWORD index_format, const void *vertex_data,
    UINT vertex_stride)
{
    void *caller = __builtin_return_address(0);
    menu_v47_log_draw("DIPUP", caller, primitive_type, primitive_count, vertex_stride,
        min_vertex_index, num_vertex_indices, (UINT)index_format);
    return menu_real_DrawIndexedPrimitiveUP ?
        menu_real_DrawIndexedPrimitiveUP(self, primitive_type, min_vertex_index,
            num_vertex_indices, primitive_count, index_data, index_format,
            vertex_data, vertex_stride) : E_FAIL;
}

'''
text = text.replace(stream_fn, stream_fn + draw_code, 1)

replace_once(
'''        int reset_ok, present_ok, viewport_ok, shader_ok, constants_ok, stream_ok;\n''',
'''        int reset_ok, present_ok, viewport_ok, shader_ok, constants_ok, stream_ok;\n        int draw_ok, draw_indexed_ok, draw_up_ok, draw_indexed_up_ok;\n''',
'draw hook variables',
)

replace_once(
'''        viewport_ok = patch_vtable_slot(vtbl, 40, menu_fake_SetViewport, (void **)&menu_real_SetViewport);\n        shader_ok = patch_vtable_slot(vtbl, 76, fake_SetVertexShader, (void **)&real_SetVertexShader);\n''',
'''        viewport_ok = patch_vtable_slot(vtbl, 40, menu_fake_SetViewport, (void **)&menu_real_SetViewport);\n        draw_ok = patch_vtable_slot(vtbl, 70, menu_fake_DrawPrimitive, (void **)&menu_real_DrawPrimitive);\n        draw_indexed_ok = patch_vtable_slot(vtbl, 71, menu_fake_DrawIndexedPrimitive, (void **)&menu_real_DrawIndexedPrimitive);\n        draw_up_ok = patch_vtable_slot(vtbl, 72, menu_fake_DrawPrimitiveUP, (void **)&menu_real_DrawPrimitiveUP);\n        draw_indexed_up_ok = patch_vtable_slot(vtbl, 73, menu_fake_DrawIndexedPrimitiveUP, (void **)&menu_real_DrawIndexedPrimitiveUP);\n        shader_ok = patch_vtable_slot(vtbl, 76, fake_SetVertexShader, (void **)&real_SetVertexShader);\n''',
'draw vtable hooks',
)

replace_once(
'''            "HOOKS V46 reset=%d present=%d set_vp=%d shader=%d constants=%d stream=%d full_viewport=1 ui_fit_matrix=1 background_cover=1 mouse_fit=1",\n            reset_ok, present_ok, viewport_ok, shader_ok, constants_ok, stream_ok);\n        if (reset_ok && present_ok && viewport_ok && shader_ok && constants_ok && stream_ok) {\n''',
'''            "HOOKS V47 reset=%d present=%d set_vp=%d draw=%d/%d/%d/%d shader=%d constants=%d stream=%d full_viewport=1 coherent_fit=1 draw_trace=1 mouse_fit=1",\n            reset_ok, present_ok, viewport_ok, draw_ok, draw_indexed_ok, draw_up_ok,\n            draw_indexed_up_ok, shader_ok, constants_ok, stream_ok);\n        if (reset_ok && present_ok && viewport_ok && draw_ok && draw_indexed_ok &&\n            draw_up_ok && draw_indexed_up_ok && shader_ok && constants_ok && stream_ok) {\n''',
'draw hook health log',
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern coherent frontend fit + draw-path probe v47")
