from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"skip intro v37 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, new: str, label: str) -> str:
    updated, count = re.subn(pattern, lambda _m: new, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"skip intro v37 {label}: expected exactly one match, found {count}")
    return updated


# v0.35/36 proved two things:
#   1. ERROR_FILE_NOT_FOUND makes MVP retry/spin rather than skip.
#   2. both startup clips pass through a generic worker-thread file/stream path,
#      so patching that code path risks unrelated streamed assets.
#
# v0.37 instead keeps the user's originals untouched. On first open of each
# startup VP6, it copies that installed file into a private runtime cache,
# validates the RIFF/AVI structure, shortens AVI duration metadata to ~120 ms,
# and redirects only that exact basename to the cached copy. If validation or
# cache creation fails, the hook opens the original normally.

runtime = replace_once(
    runtime,
    'static LONG intro_diag_mvpintro_dumped;\n',
    '''static LONG intro_diag_mvpintro_dumped;\n'''
    '''static volatile LONG intro_cache_easports_state;\n'''
    '''static volatile LONG intro_cache_mvpintro_state;\n'''
    '''static char intro_cache_easports_path[MAX_PATH];\n'''
    '''static char intro_cache_mvpintro_path[MAX_PATH];\n''',
    'cache globals',
)

runtime = replace_once(
    runtime,
    'intro_diag_logf("MVP2005 Modern Skip Intro diagnostics v35");',
    'intro_diag_logf("MVP2005 Modern Skip Intro diagnostics v37 short-VP6 cache");',
    'diagnostic version header',
)

# The old ENABLE_FRONTEND_MOVIES byte patch was conclusively observed to apply,
# yet both startup VP6 files still opened and played. Retire it so v0.37 changes
# only the movie source presented to the existing player.
runtime = replace_regex_once(
    runtime,
    r'''static void patch_frontend_movies_default_in_memory\(void\)\n\{.*?\n\}\n\n(?=static BOOL WINAPI fake_GetDiskFreeSpaceExA)''',
    r'''static void patch_frontend_movies_default_in_memory(void)
{
    if (!skip_intro_enabled) return;
    intro_diag_open_log();
    intro_diag_logf("legacy ENABLE_FRONTEND_MOVIES byte patch retired in v37; using validated short-VP6 cache redirect");
}

''',
    'retire ineffective internal flag patch',
)

# Insert cache helpers immediately before the existing hooked CreateFileA.
# At this point the controller diagnostic real-function pointers are already
# declared, so cache I/O can bypass our own CreateFile hooks and cannot recurse.
marker = '''static HANDLE WINAPI controller_diag_CreateFileA(LPCSTR name, DWORD access, DWORD share,\n'''
if runtime.count(marker) != 1:
    raise SystemExit(f"skip intro v37 CreateFileA marker: found {runtime.count(marker)}")

helpers = r'''typedef struct IntroAviPatchContext {
    DWORD target_us;
    DWORD target_frames;
    DWORD avih_count;
    DWORD video_streams;
    DWORD vp60_streams;
    DWORD strh_count;
    DWORD dmlh_count;
} IntroAviPatchContext;

static DWORD intro_cache_u32(const BYTE *p)
{
    DWORD v = 0;
    memcpy(&v, p, sizeof(v));
    return v;
}

static void intro_cache_put_u32(BYTE *p, DWORD v)
{
    memcpy(p, &v, sizeof(v));
}

static int intro_cache_fourcc(const BYTE *p, const char *s)
{
    return p && s && memcmp(p, s, 4) == 0;
}

static void intro_cache_fourcc_text(const BYTE *p, char out[5])
{
    int i;
    for (i = 0; i < 4; i++) {
        BYTE c = p[i];
        out[i] = (c >= 32 && c <= 126) ? (char)c : '.';
    }
    out[4] = 0;
}

static void intro_cache_hexdump_prefix(const BYTE *buffer, DWORD size)
{
    DWORD offset;
    DWORD limit = size < 128 ? size : 128;
    for (offset = 0; offset < limit; offset += 16) {
        char line[128];
        size_t used;
        DWORD i;
        DWORD count = limit - offset;
        if (count > 16) count = 16;
        used = (size_t)snprintf(line, sizeof(line), "SOURCE %04lx:", (unsigned long)offset);
        for (i = 0; i < count && used + 4 < sizeof(line); i++)
            used += (size_t)snprintf(line + used, sizeof(line) - used,
                " %02X", buffer[offset + i]);
        line[sizeof(line) - 1] = 0;
        intro_diag_logf("%s", line);
    }
}

static void intro_cache_scan_avi(BYTE *buffer, DWORD start, DWORD end,
    int patch, int depth, IntroAviPatchContext *ctx)
{
    DWORD pos = start;
    if (!buffer || !ctx || depth > 8 || start >= end) return;

    while (pos + 8 <= end) {
        BYTE *chunk = buffer + pos;
        DWORD size = intro_cache_u32(chunk + 4);
        DWORD data = pos + 8;
        ULONGLONG raw_next = (ULONGLONG)data + (ULONGLONG)size + (size & 1u);
        DWORD next;

        if (data > end) break;
        if (raw_next > end) next = end;
        else next = (DWORD)raw_next;

        if (intro_cache_fourcc(chunk, "LIST") && size >= 4 && data + 4 <= end) {
            BYTE *list_type = buffer + data;
            DWORD list_end = data + size;
            char type[5];
            if (list_end > end || list_end < data) list_end = end;
            intro_cache_fourcc_text(list_type, type);
            if (intro_cache_fourcc(list_type, "hdrl") ||
                intro_cache_fourcc(list_type, "strl") ||
                intro_cache_fourcc(list_type, "odml")) {
                intro_cache_scan_avi(buffer, data + 4, list_end,
                    patch, depth + 1, ctx);
            }
        } else if (intro_cache_fourcc(chunk, "avih") && size >= 40 && data + 40 <= end) {
            DWORD us_per_frame = intro_cache_u32(buffer + data + 0);
            DWORD total_frames = intro_cache_u32(buffer + data + 16);
            DWORD streams = intro_cache_u32(buffer + data + 24);
            DWORD width = intro_cache_u32(buffer + data + 32);
            DWORD height = intro_cache_u32(buffer + data + 36);
            DWORD target = 3;
            ctx->avih_count++;
            if (us_per_frame) {
                ULONGLONG n = (ULONGLONG)ctx->target_us + us_per_frame - 1;
                target = (DWORD)(n / us_per_frame);
                if (!target) target = 1;
            }
            if (!ctx->target_frames) ctx->target_frames = target;
            if (patch) {
                DWORD new_total = total_frames;
                if (!new_total || new_total > ctx->target_frames)
                    new_total = ctx->target_frames;
                intro_diag_logf(
                    "AVI avih us_per_frame=%lu total_frames=%lu->%lu streams=%lu size=%lux%lu target_us=%lu",
                    (unsigned long)us_per_frame, (unsigned long)total_frames,
                    (unsigned long)new_total, (unsigned long)streams,
                    (unsigned long)width, (unsigned long)height,
                    (unsigned long)ctx->target_us);
                intro_cache_put_u32(buffer + data + 16, new_total);
            }
        } else if (intro_cache_fourcc(chunk, "strh") && size >= 36 && data + 36 <= end) {
            char type[5];
            char handler[5];
            DWORD scale = intro_cache_u32(buffer + data + 20);
            DWORD rate = intro_cache_u32(buffer + data + 24);
            DWORD old_length = intro_cache_u32(buffer + data + 32);
            DWORD new_length = old_length;
            ctx->strh_count++;
            intro_cache_fourcc_text(buffer + data + 0, type);
            intro_cache_fourcc_text(buffer + data + 4, handler);
            if (intro_cache_fourcc(buffer + data + 0, "vids")) {
                ctx->video_streams++;
                if (intro_cache_fourcc(buffer + data + 4, "VP60"))
                    ctx->vp60_streams++;
            }
            if (scale && rate) {
                ULONGLONG numerator = (ULONGLONG)ctx->target_us * rate;
                ULONGLONG denominator = (ULONGLONG)1000000u * scale;
                ULONGLONG units = (numerator + denominator - 1) / denominator;
                if (!units) units = 1;
                if (units > 0xffffffffULL) units = 0xffffffffULL;
                if (!new_length || new_length > (DWORD)units)
                    new_length = (DWORD)units;
            }
            if (patch) {
                intro_diag_logf(
                    "AVI strh type=%s handler=%s scale=%lu rate=%lu length=%lu->%lu",
                    type, handler, (unsigned long)scale, (unsigned long)rate,
                    (unsigned long)old_length, (unsigned long)new_length);
                intro_cache_put_u32(buffer + data + 32, new_length);
            }
        } else if (intro_cache_fourcc(chunk, "dmlh") && size >= 4 && data + 4 <= end) {
            DWORD old_total = intro_cache_u32(buffer + data);
            DWORD new_total = old_total;
            ctx->dmlh_count++;
            if (ctx->target_frames && (!new_total || new_total > ctx->target_frames))
                new_total = ctx->target_frames;
            if (patch) {
                intro_diag_logf("AVI dmlh total_frames=%lu->%lu",
                    (unsigned long)old_total, (unsigned long)new_total);
                intro_cache_put_u32(buffer + data, new_total);
            }
        }

        if (next <= pos) break;
        pos = next;
    }
}

static int intro_cache_patch_avi_file(const char *path, const char *source_name)
{
    HANDLE h;
    LARGE_INTEGER file_size;
    LARGE_INTEGER zero;
    BYTE *buffer = NULL;
    DWORD read_size;
    DWORD got = 0;
    DWORD written = 0;
    IntroAviPatchContext ctx;
    int ok = 0;

    if (!controller_diag_real_CreateFileA || !controller_diag_real_ReadFile ||
        !controller_diag_real_CloseHandle) return 0;

    h = controller_diag_real_CreateFileA(path, GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        intro_diag_logf("CACHE patch open failed path=\"%s\" winerr=%lu",
            path, (unsigned long)GetLastError());
        return 0;
    }
    if (!GetFileSizeEx(h, &file_size) || file_size.QuadPart < 12) {
        intro_diag_logf("CACHE invalid size source=\"%s\" size=%lld",
            source_name, (long long)file_size.QuadPart);
        goto done;
    }
    read_size = file_size.QuadPart > (2 * 1024 * 1024) ?
        (2 * 1024 * 1024) : (DWORD)file_size.QuadPart;
    buffer = (BYTE *)HeapAlloc(GetProcessHeap(), 0, read_size);
    if (!buffer) {
        intro_diag_logf("CACHE HeapAlloc failed bytes=%lu", (unsigned long)read_size);
        goto done;
    }
    if (!controller_diag_real_ReadFile(h, buffer, read_size, &got, NULL) || got != read_size) {
        intro_diag_logf("CACHE header read failed wanted=%lu got=%lu winerr=%lu",
            (unsigned long)read_size, (unsigned long)got, (unsigned long)GetLastError());
        goto done;
    }

    intro_diag_logf("CACHE inspect source=\"%s\" copy=\"%s\" size=%lld header_bytes=%lu",
        source_name, path, (long long)file_size.QuadPart, (unsigned long)read_size);
    if (!intro_cache_fourcc(buffer, "RIFF") || !intro_cache_fourcc(buffer + 8, "AVI ")) {
        char tag0[5];
        char tag8[5];
        intro_cache_fourcc_text(buffer, tag0);
        intro_cache_fourcc_text(buffer + 8, tag8);
        intro_diag_logf("CACHE reject: expected RIFF/AVI, got tag0=%s tag8=%s", tag0, tag8);
        intro_cache_hexdump_prefix(buffer, read_size);
        goto done;
    }

    ZeroMemory(&ctx, sizeof(ctx));
    ctx.target_us = 120000;
    intro_cache_scan_avi(buffer, 12, read_size, 0, 0, &ctx);
    if (!ctx.avih_count || !ctx.video_streams) {
        intro_diag_logf("CACHE reject: AVI header incomplete avih=%lu video_streams=%lu strh=%lu",
            (unsigned long)ctx.avih_count, (unsigned long)ctx.video_streams,
            (unsigned long)ctx.strh_count);
        intro_cache_hexdump_prefix(buffer, read_size);
        goto done;
    }
    if (!ctx.vp60_streams) {
        intro_diag_logf("CACHE reject: video stream found but VP60 handler not found; leaving original untouched");
        goto done;
    }

    /* Reset counters but retain target duration/frame count for the patch pass. */
    ctx.avih_count = 0;
    ctx.video_streams = 0;
    ctx.vp60_streams = 0;
    ctx.strh_count = 0;
    ctx.dmlh_count = 0;
    intro_cache_scan_avi(buffer, 12, read_size, 1, 0, &ctx);

    zero.QuadPart = 0;
    if (!SetFilePointerEx(h, zero, NULL, FILE_BEGIN) ||
        !WriteFile(h, buffer, read_size, &written, NULL) ||
        written != read_size || !FlushFileBuffers(h)) {
        intro_diag_logf("CACHE header write failed wrote=%lu/%lu winerr=%lu",
            (unsigned long)written, (unsigned long)read_size,
            (unsigned long)GetLastError());
        goto done;
    }
    intro_diag_logf(
        "CACHE validation PASS target_frames=%lu avih=%lu video_streams=%lu vp60=%lu strh=%lu dmlh=%lu",
        (unsigned long)ctx.target_frames, (unsigned long)ctx.avih_count,
        (unsigned long)ctx.video_streams, (unsigned long)ctx.vp60_streams,
        (unsigned long)ctx.strh_count, (unsigned long)ctx.dmlh_count);
    ok = 1;

done:
    if (buffer) HeapFree(GetProcessHeap(), 0, buffer);
    controller_diag_real_CloseHandle(h);
    return ok;
}

static int intro_cache_copy_source(const char *source, const char *dest)
{
    HANDLE in_h = INVALID_HANDLE_VALUE;
    HANDLE out_h = INVALID_HANDLE_VALUE;
    BYTE *buffer = NULL;
    DWORD got = 0;
    DWORD wrote = 0;
    ULONGLONG total = 0;
    int ok = 0;

    if (!controller_diag_real_CreateFileA || !controller_diag_real_ReadFile ||
        !controller_diag_real_CloseHandle) return 0;

    in_h = controller_diag_real_CreateFileA(source, GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (in_h == INVALID_HANDLE_VALUE) {
        intro_diag_logf("CACHE source open failed path=\"%s\" winerr=%lu",
            source, (unsigned long)GetLastError());
        goto done;
    }
    out_h = controller_diag_real_CreateFileA(dest, GENERIC_WRITE,
        FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (out_h == INVALID_HANDLE_VALUE) {
        intro_diag_logf("CACHE destination open failed path=\"%s\" winerr=%lu",
            dest, (unsigned long)GetLastError());
        goto done;
    }
    buffer = (BYTE *)HeapAlloc(GetProcessHeap(), 0, 128 * 1024);
    if (!buffer) goto done;

    for (;;) {
        if (!controller_diag_real_ReadFile(in_h, buffer, 128 * 1024, &got, NULL)) {
            intro_diag_logf("CACHE source read failed winerr=%lu", (unsigned long)GetLastError());
            goto done;
        }
        if (!got) break;
        if (!WriteFile(out_h, buffer, got, &wrote, NULL) || wrote != got) {
            intro_diag_logf("CACHE destination write failed wanted=%lu wrote=%lu winerr=%lu",
                (unsigned long)got, (unsigned long)wrote, (unsigned long)GetLastError());
            goto done;
        }
        total += got;
    }
    if (!FlushFileBuffers(out_h)) goto done;
    intro_diag_logf("CACHE copied source=\"%s\" dest=\"%s\" bytes=%llu",
        source, dest, (unsigned long long)total);
    ok = 1;

done:
    if (buffer) HeapFree(GetProcessHeap(), 0, buffer);
    if (out_h != INVALID_HANDLE_VALUE) controller_diag_real_CloseHandle(out_h);
    if (in_h != INVALID_HANDLE_VALUE) controller_diag_real_CloseHandle(in_h);
    if (!ok) DeleteFileA(dest);
    return ok;
}

static int intro_cache_build(const char *source, const char *basename,
    char *cache_path, DWORD cache_path_size)
{
    char module_dir[MAX_PATH];
    char cache_dir[MAX_PATH];
    char temp_path[MAX_PATH];
    DWORD err;

    if (!get_module_dir(module_dir, sizeof(module_dir))) return 0;
    lstrcpynA(cache_dir, module_dir, sizeof(cache_dir));
    if (!append_path(cache_dir, sizeof(cache_dir), "MVP2005Modern.IntroCache")) return 0;
    if (!CreateDirectoryA(cache_dir, NULL)) {
        err = GetLastError();
        if (err != ERROR_ALREADY_EXISTS) {
            intro_diag_logf("CACHE directory creation failed path=\"%s\" winerr=%lu",
                cache_dir, (unsigned long)err);
            return 0;
        }
    }
    lstrcpynA(cache_path, cache_dir, cache_path_size);
    if (!append_path(cache_path, cache_path_size, basename)) return 0;
    snprintf(temp_path, sizeof(temp_path), "%s.tmp", cache_path);
    temp_path[sizeof(temp_path) - 1] = 0;
    DeleteFileA(temp_path);

    if (!intro_cache_copy_source(source, temp_path)) return 0;
    if (!intro_cache_patch_avi_file(temp_path, source)) {
        DeleteFileA(temp_path);
        return 0;
    }
    if (!MoveFileExA(temp_path, cache_path,
        MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        intro_diag_logf("CACHE publish failed temp=\"%s\" dest=\"%s\" winerr=%lu",
            temp_path, cache_path, (unsigned long)GetLastError());
        DeleteFileA(temp_path);
        return 0;
    }
    intro_diag_logf("CACHE ready source=\"%s\" cache=\"%s\"", source, cache_path);
    return 1;
}

static int intro_cache_prepare(const char *source, char *out, DWORD out_size)
{
    volatile LONG *state;
    char *stored_path;
    const char *basename;
    LONG current;
    int builder = 0;
    DWORD waited = 0;

    if (intro_diag_name_is(source, "easports.vp6")) {
        state = &intro_cache_easports_state;
        stored_path = intro_cache_easports_path;
        basename = "easports.vp6";
    } else if (intro_diag_name_is(source, "mvpintro.vp6")) {
        state = &intro_cache_mvpintro_state;
        stored_path = intro_cache_mvpintro_path;
        basename = "mvpintro.vp6";
    } else {
        return 0;
    }

    current = InterlockedCompareExchange((volatile LONG *)state, 1, 0);
    if (current == 0) {
        int ok;
        builder = 1;
        intro_diag_logf("CACHE build begin basename=%s source=\"%s\"", basename, source);
        ok = intro_cache_build(source, basename, stored_path, MAX_PATH);
        InterlockedExchange((volatile LONG *)state, ok ? 2 : -1);
        intro_diag_logf("CACHE build %s basename=%s", ok ? "PASS" : "FAIL", basename);
    } else if (current == 1) {
        while ((current = InterlockedCompareExchange((volatile LONG *)state, 1, 1)) == 1 &&
               waited < 5000) {
            Sleep(1);
            waited++;
        }
        if (current == 1) {
            intro_diag_logf("CACHE wait timeout basename=%s", basename);
            return 0;
        }
    }

    current = InterlockedCompareExchange((volatile LONG *)state, 2, 2);
    if (current != 2 || !stored_path[0]) {
        if (!builder)
            intro_diag_logf("CACHE unavailable basename=%s state=%ld; using original",
                basename, (long)current);
        return 0;
    }
    lstrcpynA(out, stored_path, out_size);
    return 1;
}

'''
runtime = runtime.replace(marker, helpers + marker, 1)

# Replace v0.36's trace-only behavior with cache redirection. Existing detailed
# open logging remains, and failures explicitly fall back to the user's original.
old_a = r'''        if (skip_intro_enabled) {
            intro_diag_logf("VP6 TRACE A path=\"%s\"; v0.36 passes file through normally", name);
            intro_diag_trace_once(name, return_address);
        }
'''
new_a = r'''        if (skip_intro_enabled) {
            char cache_path[MAX_PATH];
            if (intro_cache_prepare(name, cache_path, sizeof(cache_path))) {
                HANDLE cached;
                intro_diag_logf("VP6 REDIRECT A original=\"%s\" cache=\"%s\"", name, cache_path);
                cached = controller_diag_real_CreateFileA ?
                    controller_diag_real_CreateFileA(cache_path, access, share, sa,
                        disposition, flags, template_file) : INVALID_HANDLE_VALUE;
                if (cached != INVALID_HANDLE_VALUE) {
                    intro_diag_logf("VP6 CACHE OPEN A result=%p", cached);
                    return cached;
                }
                intro_diag_logf("VP6 cache open failed winerr=%lu; falling back to original",
                    (unsigned long)GetLastError());
            } else {
                intro_diag_logf("VP6 cache unavailable for \"%s\"; falling back to original", name);
            }
        }
'''
runtime = replace_once(runtime, old_a, new_a, 'ANSI cache redirect')

old_w = r'''        if (skip_intro_enabled) {
            intro_diag_logf("VP6 TRACE W path=\"%s\"; v0.36 passes file through normally", path);
            intro_diag_trace_once(path, return_address);
        }
'''
new_w = r'''        if (skip_intro_enabled) {
            char cache_path[MAX_PATH];
            if (intro_cache_prepare(path, cache_path, sizeof(cache_path))) {
                HANDLE cached;
                intro_diag_logf("VP6 REDIRECT W original=\"%s\" cache=\"%s\"", path, cache_path);
                cached = controller_diag_real_CreateFileA ?
                    controller_diag_real_CreateFileA(cache_path, access, share, sa,
                        disposition, flags, template_file) : INVALID_HANDLE_VALUE;
                if (cached != INVALID_HANDLE_VALUE) {
                    intro_diag_logf("VP6 CACHE OPEN W-via-A result=%p", cached);
                    return cached;
                }
                intro_diag_logf("VP6 cache open failed winerr=%lu; falling back to original",
                    (unsigned long)GetLastError());
            } else {
                intro_diag_logf("VP6 cache unavailable for \"%s\"; falling back to original", path);
            }
        }
'''
runtime = replace_once(runtime, old_w, new_w, 'Unicode cache redirect')

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern safe short-VP6 intro cache redirect v37")
