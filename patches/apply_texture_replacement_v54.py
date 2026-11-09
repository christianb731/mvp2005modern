from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"texture replacement v54 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# v0.54 turns the validated v0.53 texture metadata/bind hooks into a general
# content-addressed texture replacement layer.  MVP's ordinary textures are
# managed textures and the v0.50-v0.52 audit showed no actual device-level
# UpdateTexture traffic, so hook IDirect3DTexture8::LockRect/UnlockRect instead.
# We hash the bytes MVP itself writes while they are still locked; there are no
# extra COM queries or readbacks.  On bind, an optional matching DDS can be
# loaded into a separate managed texture at any supported resolution.

# Extend the production texture record with lock/fingerprint/replacement state.
old_struct = '''typedef struct GfxTextureRecord {
    void *object;
    UINT width;
    UINT height;
    UINT levels;
    DWORD usage;
    DWORD format;
    DWORD pool;
    DWORD caller_rva;
} GfxTextureRecord;
'''
new_struct = '''typedef struct GfxTextureRecord {
    void *object;
    UINT width;
    UINT height;
    UINT levels;
    DWORD usage;
    DWORD format;
    DWORD pool;
    DWORD caller_rva;
    void *locked_bits;
    INT locked_pitch;
    UINT locked_level;
    int locked_full;
    int fingerprint_ready;
    DWORD fingerprint_hi;
    DWORD fingerprint_lo;
    int replacement_checked;
    void *replacement;
    UINT replacement_width;
    UINT replacement_height;
    UINT replacement_levels;
    DWORD replacement_format;
} GfxTextureRecord;
'''
replace_once(old_struct, new_struct, 'texture record extension')

# Texture-interface method types. D3D8 IDirect3DTexture8 slots are:
# 16 LockRect, 17 UnlockRect (IUnknown/resource/base-texture methods precede them).
type_marker = '''typedef HRESULT (WINAPI *GfxSetPixelShaderFn)(void *self, DWORD handle);\n'''
if text.count(type_marker) != 1:
    raise SystemExit(f"texture replacement v54 type marker: expected one match, found {text.count(type_marker)}")
type_block = r'''typedef struct GfxLockedRect8Local {
    INT Pitch;
    void *pBits;
} GfxLockedRect8Local;
typedef HRESULT (WINAPI *GfxTextureLockRectFn)(void *self, UINT level,
    GfxLockedRect8Local *locked_rect, const RECT *rect, DWORD flags);
typedef HRESULT (WINAPI *GfxTextureUnlockRectFn)(void *self, UINT level);
typedef ULONG (WINAPI *GfxReleaseFn)(void *self);
'''
text = text.replace(type_marker, type_marker + type_block, 1)

# Globals live beside the production device-method pointers.
global_marker = '''static GfxSetPixelShaderFn gfx_real_SetPixelShader;\n'''
if text.count(global_marker) != 1:
    raise SystemExit(f"texture replacement v54 global marker: expected one match, found {text.count(global_marker)}")
global_block = r'''static GfxTextureLockRectFn texmod_real_LockRect;
static GfxTextureUnlockRectFn texmod_real_UnlockRect;
static void **texmod_texture_vtbl;
static HANDLE texmod_log_handle = INVALID_HANDLE_VALUE;
static LONG texmod_log_initialized;
static LONG texmod_log_lines;
static LONG texmod_hook_attempted;
static LONG texmod_fingerprint_count;
static LONG texmod_replacement_count;
static LONG texmod_dump_count;
static LONG texmod_config_loaded;
static int texmod_enabled = 1;
static int texmod_catalog = 1;
static int texmod_dump = 0;
static int texmod_min_dimension = 64;
'''
text = text.replace(global_marker, global_marker + global_block, 1)

# Insert replacement infrastructure immediately after gfx_find_texture(), where
# it can safely reuse the already-validated production metadata lookup.
marker = '''static void gfx_register_surface(void *object, UINT width, UINT height, DWORD format,\n'''
if text.count(marker) != 1:
    raise SystemExit(f"texture replacement v54 helper marker: expected one match, found {text.count(marker)}")

helpers = r'''static void texmod_logf(const char *fmt, ...)
{
    char path[MAX_PATH];
    char line[1024];
    char final_line[1100];
    va_list args;
    int len;
    DWORD written;
    LONG n;

    if (InterlockedCompareExchange(&texmod_log_initialized, 1, 0) == 0) {
        if (get_module_dir(path, sizeof(path)) &&
            append_path(path, sizeof(path), "MVP2005Modern-TextureMods.log")) {
            texmod_log_handle = CreateFileA(path, GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, CREATE_ALWAYS,
                FILE_ATTRIBUTE_NORMAL, NULL);
        }
    }
    if (texmod_log_handle == INVALID_HANDLE_VALUE || !fmt) return;

    n = InterlockedIncrement(&texmod_log_lines);
    if (n > 6000) return;
    va_start(args, fmt);
    len = _vsnprintf(line, sizeof(line) - 1, fmt, args);
    va_end(args);
    if (len < 0 || len >= (int)sizeof(line)) len = sizeof(line) - 1;
    line[len] = 0;
    wsprintfA(final_line, "%s\r\n", line);
    WriteFile(texmod_log_handle, final_line, (DWORD)lstrlenA(final_line), &written, NULL);
    if ((n & 63) == 0) FlushFileBuffers(texmod_log_handle);
}

static void texmod_load_config(void)
{
    char path[MAX_PATH];
    int min_dim;

    if (InterlockedCompareExchange(&texmod_config_loaded, 1, 0) != 0)
        return;

    if (get_module_dir(path, sizeof(path)) &&
        append_path(path, sizeof(path), "mvp2005fix.ini")) {
        texmod_enabled = GetPrivateProfileIntA("TextureMods", "Enabled", 1, path) ? 1 : 0;
        texmod_catalog = GetPrivateProfileIntA("TextureMods", "Catalog", 1, path) ? 1 : 0;
        texmod_dump = GetPrivateProfileIntA("TextureMods", "DumpTextures", 0, path) ? 1 : 0;
        min_dim = GetPrivateProfileIntA("TextureMods", "MinDimension", 64, path);
        if (min_dim < 1) min_dim = 1;
        if (min_dim > 4096) min_dim = 4096;
        texmod_min_dimension = min_dim;
    }

    texmod_logf("MVP2005 Modern v0.54 texture replacement infrastructure");
    texmod_logf("CONFIG enabled=%d catalog=%d dump=%d min_dimension=%d replacement_format=DDS",
        texmod_enabled, texmod_catalog, texmod_dump, texmod_min_dimension);
}

static int texmod_get_root(char *path, size_t path_size, const char *leaf,
    int create_dirs)
{
    if (!path || path_size == 0) return 0;
    if (!get_module_dir(path, path_size)) return 0;
    if (!append_path(path, path_size, "MVP2005Modern.Textures")) return 0;
    if (create_dirs) CreateDirectoryA(path, NULL);
    if (leaf && leaf[0]) {
        if (!append_path(path, path_size, leaf)) return 0;
        if (create_dirs) CreateDirectoryA(path, NULL);
    }
    return 1;
}

static int texmod_level_layout(DWORD format, UINT width, UINT height,
    UINT *row_bytes, UINT *rows)
{
    UINT blocks_w;
    UINT blocks_h;
    UINT bpp = 0;

    if (!row_bytes || !rows || width == 0 || height == 0) return 0;
    if (format == 0x31545844UL || format == 0x33545844UL || format == 0x35545844UL) {
        blocks_w = (width + 3) / 4;
        blocks_h = (height + 3) / 4;
        if (blocks_w == 0) blocks_w = 1;
        if (blocks_h == 0) blocks_h = 1;
        *row_bytes = blocks_w * (format == 0x31545844UL ? 8U : 16U);
        *rows = blocks_h;
        return 1;
    }

    switch (format) {
    case 20: bpp = 3; break; /* R8G8B8 */
    case 21: case 22: bpp = 4; break; /* A8/X8R8G8B8 */
    case 23: case 24: case 25: case 26: case 51: bpp = 2; break;
    case 28: case 41: case 50: bpp = 1; break;
    default: return 0;
    }
    *row_bytes = width * bpp;
    *rows = height;
    return 1;
}

static unsigned long long texmod_hash_byte(unsigned long long hash, BYTE value)
{
    hash ^= (unsigned long long)value;
    hash *= 1099511628211ULL;
    return hash;
}

static unsigned long long texmod_hash_dword(unsigned long long hash, DWORD value)
{
    hash = texmod_hash_byte(hash, (BYTE)(value & 0xff));
    hash = texmod_hash_byte(hash, (BYTE)((value >> 8) & 0xff));
    hash = texmod_hash_byte(hash, (BYTE)((value >> 16) & 0xff));
    hash = texmod_hash_byte(hash, (BYTE)((value >> 24) & 0xff));
    return hash;
}

static int texmod_hash_locked_texture(GfxTextureRecord *rec,
    DWORD *hash_hi, DWORD *hash_lo)
{
    unsigned long long hash = 14695981039346656037ULL;
    UINT row_bytes;
    UINT rows;
    UINT y;
    BYTE *row;

    if (!rec || !rec->locked_bits || rec->locked_pitch <= 0) return 0;
    if (!texmod_level_layout(rec->format, rec->width, rec->height, &row_bytes, &rows))
        return 0;
    if ((UINT)rec->locked_pitch < row_bytes) return 0;

    hash = texmod_hash_dword(hash, rec->width);
    hash = texmod_hash_dword(hash, rec->height);
    hash = texmod_hash_dword(hash, rec->format);
    row = (BYTE *)rec->locked_bits;
    for (y = 0; y < rows; y++) {
        UINT x;
        for (x = 0; x < row_bytes; x++)
            hash = texmod_hash_byte(hash, row[x]);
        row += rec->locked_pitch;
    }

    if (hash_hi) *hash_hi = (DWORD)(hash >> 32);
    if (hash_lo) *hash_lo = (DWORD)(hash & 0xffffffffULL);
    return 1;
}

static void texmod_make_id(const GfxTextureRecord *rec, char *out, size_t out_size)
{
    if (!out || out_size == 0) return;
    out[0] = 0;
    if (!rec || !rec->fingerprint_ready) return;
    _snprintf(out, out_size - 1, "%ux%u_%s_%08lx%08lx",
        rec->width, rec->height, gfx_format_name(rec->format),
        (unsigned long)rec->fingerprint_hi,
        (unsigned long)rec->fingerprint_lo);
    out[out_size - 1] = 0;
}

static int texmod_dds_pixel_format(DWORD format, DWORD *flags, DWORD *fourcc,
    DWORD *rgb_bits, DWORD *r_mask, DWORD *g_mask, DWORD *b_mask, DWORD *a_mask)
{
    *flags = *fourcc = *rgb_bits = *r_mask = *g_mask = *b_mask = *a_mask = 0;
    switch (format) {
    case 0x31545844UL: case 0x33545844UL: case 0x35545844UL:
        *flags = 0x00000004UL;
        *fourcc = format;
        return 1;
    case 20:
        *flags = 0x00000040UL; *rgb_bits = 24;
        *r_mask = 0x00ff0000UL; *g_mask = 0x0000ff00UL; *b_mask = 0x000000ffUL;
        return 1;
    case 21:
        *flags = 0x00000041UL; *rgb_bits = 32;
        *r_mask = 0x00ff0000UL; *g_mask = 0x0000ff00UL; *b_mask = 0x000000ffUL; *a_mask = 0xff000000UL;
        return 1;
    case 22:
        *flags = 0x00000040UL; *rgb_bits = 32;
        *r_mask = 0x00ff0000UL; *g_mask = 0x0000ff00UL; *b_mask = 0x000000ffUL;
        return 1;
    case 23:
        *flags = 0x00000040UL; *rgb_bits = 16;
        *r_mask = 0x0000f800UL; *g_mask = 0x000007e0UL; *b_mask = 0x0000001fUL;
        return 1;
    case 24:
        *flags = 0x00000040UL; *rgb_bits = 16;
        *r_mask = 0x00007c00UL; *g_mask = 0x000003e0UL; *b_mask = 0x0000001fUL;
        return 1;
    case 25:
        *flags = 0x00000041UL; *rgb_bits = 16;
        *r_mask = 0x00007c00UL; *g_mask = 0x000003e0UL; *b_mask = 0x0000001fUL; *a_mask = 0x00008000UL;
        return 1;
    case 26:
        *flags = 0x00000041UL; *rgb_bits = 16;
        *r_mask = 0x00000f00UL; *g_mask = 0x000000f0UL; *b_mask = 0x0000000fUL; *a_mask = 0x0000f000UL;
        return 1;
    case 28:
        *flags = 0x00000002UL; *rgb_bits = 8; *a_mask = 0x000000ffUL;
        return 1;
    case 50:
        *flags = 0x00020000UL; *rgb_bits = 8; *r_mask = 0x000000ffUL;
        return 1;
    case 51:
        *flags = 0x00020001UL; *rgb_bits = 16; *r_mask = 0x000000ffUL; *a_mask = 0x0000ff00UL;
        return 1;
    default:
        return 0;
    }
}

static void texmod_put_dword(BYTE *buffer, UINT offset, DWORD value)
{
    buffer[offset + 0] = (BYTE)(value & 0xff);
    buffer[offset + 1] = (BYTE)((value >> 8) & 0xff);
    buffer[offset + 2] = (BYTE)((value >> 16) & 0xff);
    buffer[offset + 3] = (BYTE)((value >> 24) & 0xff);
}

static DWORD texmod_get_dword(const BYTE *buffer, UINT offset)
{
    return ((DWORD)buffer[offset]) |
        ((DWORD)buffer[offset + 1] << 8) |
        ((DWORD)buffer[offset + 2] << 16) |
        ((DWORD)buffer[offset + 3] << 24);
}

static int texmod_dump_locked_dds(GfxTextureRecord *rec)
{
    char dir[MAX_PATH];
    char path[MAX_PATH];
    char id[96];
    BYTE header[128];
    DWORD pf_flags, fourcc, rgb_bits, r_mask, g_mask, b_mask, a_mask;
    DWORD dds_flags;
    DWORD written;
    HANDLE file;
    UINT row_bytes;
    UINT rows;
    UINT y;
    BYTE *row;

    if (!rec || !rec->fingerprint_ready || !rec->locked_bits || rec->locked_pitch <= 0)
        return 0;
    if (!texmod_level_layout(rec->format, rec->width, rec->height, &row_bytes, &rows))
        return 0;
    if (!texmod_dds_pixel_format(rec->format, &pf_flags, &fourcc, &rgb_bits,
        &r_mask, &g_mask, &b_mask, &a_mask)) return 0;
    if ((UINT)rec->locked_pitch < row_bytes) return 0;

    texmod_make_id(rec, id, sizeof(id));
    if (!texmod_get_root(dir, sizeof(dir), "Dumped", 1)) return 0;
    lstrcpynA(path, dir, sizeof(path));
    if (!append_path(path, sizeof(path), id)) return 0;
    if (lstrlenA(path) + 4 >= (int)sizeof(path)) return 0;
    lstrcatA(path, ".dds");

    if (GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES) return 1;
    file = CreateFileA(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_NEW,
        FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;

    ZeroMemory(header, sizeof(header));
    texmod_put_dword(header, 0, 0x20534444UL); /* DDS  */
    texmod_put_dword(header, 4, 124);
    dds_flags = 0x00001007UL;
    if (fourcc) dds_flags |= 0x00080000UL;
    else dds_flags |= 0x00000008UL;
    texmod_put_dword(header, 8, dds_flags);
    texmod_put_dword(header, 12, rec->height);
    texmod_put_dword(header, 16, rec->width);
    texmod_put_dword(header, 20, fourcc ? row_bytes * rows : row_bytes);
    texmod_put_dword(header, 76, 32);
    texmod_put_dword(header, 80, pf_flags);
    texmod_put_dword(header, 84, fourcc);
    texmod_put_dword(header, 88, rgb_bits);
    texmod_put_dword(header, 92, r_mask);
    texmod_put_dword(header, 96, g_mask);
    texmod_put_dword(header, 100, b_mask);
    texmod_put_dword(header, 104, a_mask);
    texmod_put_dword(header, 108, 0x00001000UL); /* DDSCAPS_TEXTURE */

    if (!WriteFile(file, header, sizeof(header), &written, NULL) || written != sizeof(header)) {
        CloseHandle(file);
        DeleteFileA(path);
        return 0;
    }

    row = (BYTE *)rec->locked_bits;
    for (y = 0; y < rows; y++) {
        if (!WriteFile(file, row, row_bytes, &written, NULL) || written != row_bytes) {
            CloseHandle(file);
            DeleteFileA(path);
            return 0;
        }
        row += rec->locked_pitch;
    }
    CloseHandle(file);
    InterlockedIncrement(&texmod_dump_count);
    texmod_logf("DUMP id=%s path=Dumped\\%s.dds bytes=%lu",
        id, id, (unsigned long)(128 + row_bytes * rows));
    return 1;
}

static int texmod_parse_dds(const BYTE *data, DWORD size, UINT *width, UINT *height,
    UINT *levels, DWORD *format, DWORD *data_offset)
{
    DWORD pf_flags;
    DWORD fourcc;
    DWORD rgb_bits;
    DWORD r, g, b, a;
    DWORD fmt = 0;
    UINT w, h, mips;
    DWORD offset = 128;
    DWORD needed = 0;
    UINT level;

    if (!data || size < 128 || texmod_get_dword(data, 0) != 0x20534444UL) return 0;
    if (texmod_get_dword(data, 4) != 124 || texmod_get_dword(data, 76) != 32) return 0;
    w = texmod_get_dword(data, 16);
    h = texmod_get_dword(data, 12);
    mips = texmod_get_dword(data, 28);
    if (mips == 0) mips = 1;
    if (w == 0 || h == 0 || w > 8192 || h > 8192 || mips > 16) return 0;
    if (texmod_get_dword(data, 112) != 0) return 0; /* no cube/volume DDS in v0.54 */

    pf_flags = texmod_get_dword(data, 80);
    fourcc = texmod_get_dword(data, 84);
    rgb_bits = texmod_get_dword(data, 88);
    r = texmod_get_dword(data, 92);
    g = texmod_get_dword(data, 96);
    b = texmod_get_dword(data, 100);
    a = texmod_get_dword(data, 104);

    if ((pf_flags & 0x4) &&
        (fourcc == 0x31545844UL || fourcc == 0x33545844UL || fourcc == 0x35545844UL)) {
        fmt = fourcc;
    } else if ((pf_flags & 0x40) && rgb_bits == 32 &&
        r == 0x00ff0000UL && g == 0x0000ff00UL && b == 0x000000ffUL) {
        fmt = a == 0xff000000UL ? 21 : 22;
    } else if ((pf_flags & 0x40) && rgb_bits == 24 &&
        r == 0x00ff0000UL && g == 0x0000ff00UL && b == 0x000000ffUL) {
        fmt = 20;
    } else if ((pf_flags & 0x40) && rgb_bits == 16 &&
        r == 0x0000f800UL && g == 0x000007e0UL && b == 0x0000001fUL) {
        fmt = 23;
    } else if ((pf_flags & 0x40) && rgb_bits == 16 &&
        r == 0x00007c00UL && g == 0x000003e0UL && b == 0x0000001fUL) {
        fmt = a == 0x00008000UL ? 25 : 24;
    } else if ((pf_flags & 0x40) && rgb_bits == 16 &&
        r == 0x00000f00UL && g == 0x000000f0UL && b == 0x0000000fUL && a == 0x0000f000UL) {
        fmt = 26;
    } else if ((pf_flags & 0x2) && rgb_bits == 8 && a == 0x000000ffUL) {
        fmt = 28;
    } else if ((pf_flags & 0x20000) && rgb_bits == 8) {
        fmt = 50;
    } else if ((pf_flags & 0x20000) && rgb_bits == 16 && a == 0x0000ff00UL) {
        fmt = 51;
    } else {
        return 0;
    }

    for (level = 0; level < mips; level++) {
        UINT row_bytes, rows;
        UINT lw = w >> level;
        UINT lh = h >> level;
        if (lw == 0) lw = 1;
        if (lh == 0) lh = 1;
        if (!texmod_level_layout(fmt, lw, lh, &row_bytes, &rows)) return 0;
        if (needed > 0xffffffffUL - row_bytes * rows) return 0;
        needed += row_bytes * rows;
    }
    if (offset + needed > size) return 0;

    *width = w; *height = h; *levels = mips; *format = fmt; *data_offset = offset;
    return 1;
}

static void texmod_release(void *object)
{
    void **vtbl;
    GfxReleaseFn release_fn;
    if (!object) return;
    vtbl = *(void ***)object;
    if (!vtbl || !vtbl[2]) return;
    release_fn = (GfxReleaseFn)vtbl[2];
    release_fn(object);
}

static int texmod_fill_texture_from_dds(void *texture, const BYTE *data,
    DWORD size, UINT width, UINT height, UINT levels, DWORD format, DWORD data_offset)
{
    void **vtbl;
    GfxTextureLockRectFn lock_fn;
    GfxTextureUnlockRectFn unlock_fn;
    DWORD cursor = data_offset;
    UINT level;

    if (!texture || !data) return 0;
    vtbl = *(void ***)texture;
    if (!vtbl) return 0;
    lock_fn = (GfxTextureLockRectFn)vtbl[16];
    unlock_fn = (GfxTextureUnlockRectFn)vtbl[17];
    if (lock_fn == (GfxTextureLockRectFn)texmod_real_LockRect && texmod_real_LockRect)
        lock_fn = texmod_real_LockRect;
    if (lock_fn == NULL || unlock_fn == NULL) return 0;
    if ((void *)lock_fn == (void *)0) return 0;
    if ((void *)lock_fn == (void *)texmod_real_LockRect && texmod_real_LockRect)
        lock_fn = texmod_real_LockRect;
    if ((void *)unlock_fn == (void *)texmod_real_UnlockRect && texmod_real_UnlockRect)
        unlock_fn = texmod_real_UnlockRect;
    /* If the shared texture vtable is hooked, call the saved originals. */
    if (texmod_texture_vtbl && vtbl == texmod_texture_vtbl) {
        lock_fn = texmod_real_LockRect;
        unlock_fn = texmod_real_UnlockRect;
    }

    for (level = 0; level < levels; level++) {
        GfxLockedRect8Local locked;
        HRESULT hr;
        UINT lw = width >> level;
        UINT lh = height >> level;
        UINT row_bytes, rows, y;
        BYTE *dst;
        if (lw == 0) lw = 1;
        if (lh == 0) lh = 1;
        if (!texmod_level_layout(format, lw, lh, &row_bytes, &rows)) return 0;
        if (cursor + row_bytes * rows > size) return 0;
        ZeroMemory(&locked, sizeof(locked));
        hr = lock_fn(texture, level, &locked, NULL, 0);
        if (FAILED(hr) || !locked.pBits || locked.Pitch <= 0 || (UINT)locked.Pitch < row_bytes)
            return 0;
        dst = (BYTE *)locked.pBits;
        for (y = 0; y < rows; y++) {
            CopyMemory(dst, data + cursor, row_bytes);
            cursor += row_bytes;
            dst += locked.Pitch;
        }
        hr = unlock_fn(texture, level);
        if (FAILED(hr)) return 0;
    }
    return 1;
}

static int texmod_try_load_replacement(void *device, GfxTextureRecord *rec)
{
    char dir[MAX_PATH];
    char path[MAX_PATH];
    char id[96];
    HANDLE file;
    DWORD size;
    DWORD read_bytes;
    BYTE *data = NULL;
    UINT width, height, levels;
    DWORD format, data_offset;
    void *replacement = NULL;
    HRESULT hr;
    int ok = 0;

    if (!texmod_enabled || !rec || !rec->fingerprint_ready || rec->replacement_checked)
        return rec && rec->replacement != NULL;
    rec->replacement_checked = 1;

    texmod_make_id(rec, id, sizeof(id));
    if (!texmod_get_root(dir, sizeof(dir), "Replacements", 1)) return 0;
    lstrcpynA(path, dir, sizeof(path));
    if (!append_path(path, sizeof(path), id)) return 0;
    if (lstrlenA(path) + 4 >= (int)sizeof(path)) return 0;
    lstrcatA(path, ".dds");

    file = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;
    size = GetFileSize(file, NULL);
    if (size == INVALID_FILE_SIZE || size < 128 || size > 128UL * 1024UL * 1024UL) {
        CloseHandle(file);
        texmod_logf("REPLACE_REJECT id=%s reason=file_size size=%lu", id, (unsigned long)size);
        return 0;
    }
    data = (BYTE *)HeapAlloc(GetProcessHeap(), 0, size);
    if (!data) { CloseHandle(file); return 0; }
    if (!ReadFile(file, data, size, &read_bytes, NULL) || read_bytes != size) {
        CloseHandle(file); HeapFree(GetProcessHeap(), 0, data); return 0;
    }
    CloseHandle(file);

    if (!texmod_parse_dds(data, size, &width, &height, &levels, &format, &data_offset)) {
        texmod_logf("REPLACE_REJECT id=%s reason=unsupported_dds", id);
        goto done;
    }
    if (!gfx_real_CreateTexture || !device) goto done;
    hr = gfx_real_CreateTexture(device, width, height, levels, 0, format, 1, &replacement);
    if (FAILED(hr) || !replacement) {
        texmod_logf("REPLACE_REJECT id=%s reason=create_failed hr=0x%08lx requested=%ux%u levels=%u fmt=%s",
            id, (unsigned long)hr, width, height, levels, gfx_format_name(format));
        goto done;
    }
    if (!texmod_fill_texture_from_dds(replacement, data, size, width, height,
        levels, format, data_offset)) {
        texmod_logf("REPLACE_REJECT id=%s reason=upload_failed requested=%ux%u levels=%u fmt=%s",
            id, width, height, levels, gfx_format_name(format));
        texmod_release(replacement);
        replacement = NULL;
        goto done;
    }

    rec->replacement = replacement;
    rec->replacement_width = width;
    rec->replacement_height = height;
    rec->replacement_levels = levels;
    rec->replacement_format = format;
    InterlockedIncrement(&texmod_replacement_count);
    texmod_logf("REPLACE_OK id=%s original=%ux%u/%s replacement=%ux%u/%s levels=%u",
        id, rec->width, rec->height, gfx_format_name(rec->format),
        width, height, gfx_format_name(format), levels);
    ok = 1;

done:
    if (data) HeapFree(GetProcessHeap(), 0, data);
    return ok;
}

static HRESULT WINAPI texmod_fake_LockRect(void *self, UINT level,
    GfxLockedRect8Local *locked_rect, const RECT *rect, DWORD flags)
{
    HRESULT hr;
    GfxTextureRecord *rec;

    hr = texmod_real_LockRect ? texmod_real_LockRect(self, level, locked_rect, rect, flags) : E_FAIL;
    if (FAILED(hr)) return hr;
    rec = gfx_find_texture(self);
    if (!rec) return hr;

    rec->locked_bits = locked_rect ? locked_rect->pBits : NULL;
    rec->locked_pitch = locked_rect ? locked_rect->Pitch : 0;
    rec->locked_level = level;
    rec->locked_full = 0;
    if (level == 0 && locked_rect && locked_rect->pBits) {
        if (!rect || (rect->left == 0 && rect->top == 0 &&
            rect->right == (LONG)rec->width && rect->bottom == (LONG)rec->height))
            rec->locked_full = 1;
    }
    return hr;
}

static HRESULT WINAPI texmod_fake_UnlockRect(void *self, UINT level)
{
    GfxTextureRecord *rec = gfx_find_texture(self);
    int new_fingerprint = 0;
    char id[96];
    HRESULT hr;

    texmod_load_config();
    if (texmod_enabled && rec && !rec->fingerprint_ready &&
        level == 0 && rec->locked_level == 0 && rec->locked_full &&
        rec->width >= (UINT)texmod_min_dimension &&
        rec->height >= (UINT)texmod_min_dimension &&
        (rec->usage & 1UL) == 0) {
        DWORD hi, lo;
        if (texmod_hash_locked_texture(rec, &hi, &lo)) {
            rec->fingerprint_hi = hi;
            rec->fingerprint_lo = lo;
            rec->fingerprint_ready = 1;
            new_fingerprint = 1;
            InterlockedIncrement(&texmod_fingerprint_count);
            texmod_make_id(rec, id, sizeof(id));
            if (texmod_catalog) {
                texmod_logf("TEXTURE_ID id=%s size=%ux%u levels=%u fmt=%s pool=%lu create_rva=0x%08lx",
                    id, rec->width, rec->height, rec->levels,
                    gfx_format_name(rec->format), (unsigned long)rec->pool,
                    (unsigned long)rec->caller_rva);
            }
            if (texmod_dump)
                texmod_dump_locked_dds(rec);
        }
    }

    hr = texmod_real_UnlockRect ? texmod_real_UnlockRect(self, level) : E_FAIL;
    if (rec) {
        rec->locked_bits = NULL;
        rec->locked_pitch = 0;
        rec->locked_full = 0;
    }
    (void)new_fingerprint;
    return hr;
}

static int texmod_install_texture_hooks(void *texture)
{
    void **vtbl;
    int lock_ok, unlock_ok;

    if (!texture) return 0;
    vtbl = *(void ***)texture;
    if (!vtbl) return 0;
    if (texmod_texture_vtbl == vtbl && texmod_real_LockRect && texmod_real_UnlockRect)
        return 1;
    if (texmod_texture_vtbl && texmod_texture_vtbl != vtbl) {
        texmod_logf("HOOK_TEXTURE_VARIANT ignored_vtbl=%p active_vtbl=%p", vtbl, texmod_texture_vtbl);
        return 0;
    }
    if (InterlockedCompareExchange(&texmod_hook_attempted, 1, 0) != 0)
        return texmod_texture_vtbl == vtbl;

    texmod_load_config();
    texmod_logf("HOOK_TEXTURE_ATTEMPT vtbl=%p slot16=%p slot17=%p", vtbl, vtbl[16], vtbl[17]);
    lock_ok = patch_vtable_slot(vtbl, 16, texmod_fake_LockRect, (void **)&texmod_real_LockRect);
    unlock_ok = patch_vtable_slot(vtbl, 17, texmod_fake_UnlockRect, (void **)&texmod_real_UnlockRect);
    if (lock_ok && unlock_ok) texmod_texture_vtbl = vtbl;
    texmod_logf("HOOK_TEXTURE_RESULT lock=%d unlock=%d real_lock=%p real_unlock=%p",
        lock_ok, unlock_ok, texmod_real_LockRect, texmod_real_UnlockRect);
    return lock_ok && unlock_ok;
}

'''
text = text.replace(marker, helpers + marker, 1)

# Register the creation callsite again (v0.53 intentionally zeroed it) and hook
# the shared IDirect3DTexture8 vtable after the first successful texture create.
old_create = '''static HRESULT WINAPI gfx_fake_CreateTexture(void *self, UINT width, UINT height,
    UINT levels, DWORD usage, DWORD format, DWORD pool, void **texture)
{
    HRESULT hr = gfx_real_CreateTexture ?
        gfx_real_CreateTexture(self, width, height, levels, usage, format, pool, texture) : E_FAIL;
    void *out = texture ? *texture : NULL;

    if (SUCCEEDED(hr) && out)
        gfx_register_texture(out, width, height, levels, usage, format, pool, 0);
    return hr;
}
'''
new_create = '''static HRESULT WINAPI gfx_fake_CreateTexture(void *self, UINT width, UINT height,
    UINT levels, DWORD usage, DWORD format, DWORD pool, void **texture)
{
    DWORD rva = gfx_caller_rva(__builtin_return_address(0));
    HRESULT hr = gfx_real_CreateTexture ?
        gfx_real_CreateTexture(self, width, height, levels, usage, format, pool, texture) : E_FAIL;
    void *out = texture ? *texture : NULL;

    if (SUCCEEDED(hr) && out) {
        gfx_register_texture(out, width, height, levels, usage, format, pool, rva);
        texmod_install_texture_hooks(out);
    }
    return hr;
}
'''
replace_once(old_create, new_create, 'CreateTexture fingerprint hook')

# Substitute an external DDS on any texture stage once a source fingerprint is
# known. Keep the production filtering behavior on stage 0, using replacement
# mip count when appropriate.
old_set = '''static HRESULT WINAPI gfx_fake_SetTexture(void *self, DWORD stage, void *texture)
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
'''
new_set = '''static HRESULT WINAPI gfx_fake_SetTexture(void *self, DWORD stage, void *texture)
{
    GfxTextureRecord *rec = gfx_find_texture(texture);
    void *bind_texture = texture;
    UINT bind_levels = rec ? rec->levels : 0;
    HRESULT hr;

    gfx_filter_quality_load_config();
    texmod_load_config();
    if (rec && rec->fingerprint_ready && texmod_enabled) {
        if (!rec->replacement_checked)
            texmod_try_load_replacement(self, rec);
        if (rec->replacement) {
            bind_texture = rec->replacement;
            bind_levels = rec->replacement_levels;
        }
    }

    hr = gfx_real_SetTexture ? gfx_real_SetTexture(self, stage, bind_texture) : E_FAIL;

    if (SUCCEEDED(hr) && gfx_filter_quality_texture_eligible(stage, rec) &&
        gfx_real_SetTextureStageState) {
        gfx_real_SetTextureStageState(self, stage, 21,
            (DWORD)gfx_filter_quality_anisotropy); /* MAXANISOTROPY */
        gfx_real_SetTextureStageState(self, stage, 16, 2); /* MAGFILTER LINEAR */
        gfx_real_SetTextureStageState(self, stage, 17, 3); /* MINFILTER ANISOTROPIC */
        if (bind_levels > 1)
            gfx_real_SetTextureStageState(self, stage, 18, 2); /* MIPFILTER LINEAR */
    }

    return hr;
}
'''
replace_once(old_set, new_set, 'SetTexture replacement bind')

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern content-addressed DDS texture replacement infrastructure v54")
