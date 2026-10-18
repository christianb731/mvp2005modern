from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"skip intro v38 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, new: str, label: str) -> str:
    updated, count = re.subn(pattern, lambda _m: new, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"skip intro v38 {label}: expected exactly one match, found {count}")
    return updated


# v0.37 diagnostics proved MVP's .vp6 files are not RIFF/AVI. They use EA's
# native Multimedia container:
#   MVhd <32-byte header>, SCHl/GSTR audio header, MV0K/MV0F video chunks.
# The documented MVhd payload stores width/height, video frame count, maximum
# frame size and the VP6 time base. SCHl's element stream stores audio revision,
# sample rate and total sample count. v0.38 edits ONLY those declared duration
# fields in the private cached copy; compressed frame/audio chunks remain intact.
# Any validation failure leaves the user's original file path in use.

runtime = replace_once(
    runtime,
    'intro_diag_logf("MVP2005 Modern Skip Intro diagnostics v37 short-VP6 cache");',
    'intro_diag_logf("MVP2005 Modern Skip Intro diagnostics v38 EA MVhd/SCHl short cache");',
    'diagnostic version header',
)

runtime = replace_once(
    runtime,
    'legacy ENABLE_FRONTEND_MOVIES byte patch retired in v37; using validated short-VP6 cache redirect',
    'legacy ENABLE_FRONTEND_MOVIES byte patch retired; v38 uses validated EA MVhd/SCHl duration metadata in private cache',
    'retired flag message',
)

new_function = r'''static WORD intro_cache_u16(const BYTE *p)
{
    WORD v = 0;
    memcpy(&v, p, sizeof(v));
    return v;
}

static DWORD intro_cache_read_be(const BYTE *p, BYTE bytes)
{
    DWORD v = 0;
    BYTE i;
    for (i = 0; i < bytes; i++)
        v = (v << 8) | p[i];
    return v;
}

static void intro_cache_write_be(BYTE *p, BYTE bytes, DWORD v)
{
    BYTE i;
    for (i = 0; i < bytes; i++) {
        p[bytes - 1 - i] = (BYTE)(v & 0xffu);
        v >>= 8;
    }
}

static int intro_cache_parse_schl(BYTE *buffer, DWORD chunk_pos, DWORD chunk_size,
    DWORD target_us, DWORD *sample_rate_out, DWORD *old_samples_out,
    DWORD *new_samples_out)
{
    DWORD p;
    DWORD end;
    DWORD sample_rate = 0;
    DWORD revision = 0xffffffffu;
    DWORD old_samples = 0;
    DWORD new_samples = 0;
    BYTE *samples_ptr = NULL;
    BYTE samples_bytes = 0;
    int in_subheader = 0;

    if (!buffer || chunk_size < 24 || chunk_pos + chunk_size < chunk_pos)
        return 0;
    end = chunk_pos + chunk_size;
    if (!intro_cache_fourcc(buffer + chunk_pos, "SCHl"))
        return 0;
    if (chunk_pos + 16 > end || !intro_cache_fourcc(buffer + chunk_pos + 8, "GSTR")) {
        intro_diag_logf("EA SCHl reject: missing GSTR payload at offset=0x%08lx size=%lu",
            (unsigned long)chunk_pos, (unsigned long)chunk_size);
        return 0;
    }

    /* SCHl/GSTR layout used by MVP/FIFA: 8-byte chunk header, GSTR + 4-byte
       stream/version value, then EA variable-length header elements. */
    p = chunk_pos + 16;
    while (p < end) {
        BYTE tag = buffer[p++];
        BYTE bytes;
        DWORD value;

        if (tag == 0xff) {
            if (in_subheader) in_subheader = 0;
            break;
        }
        if (tag == 0xfd) {
            in_subheader = 1;
            continue;
        }
        if (p >= end) {
            intro_diag_logf("EA SCHl reject: truncated element tag=0x%02x", (unsigned int)tag);
            return 0;
        }
        bytes = buffer[p++];
        if (!bytes || bytes > 4 || p + bytes > end) {
            intro_diag_logf("EA SCHl reject: bad element tag=0x%02x bytes=%u offset=0x%08lx",
                (unsigned int)tag, (unsigned int)bytes, (unsigned long)(p - 2));
            return 0;
        }
        value = intro_cache_read_be(buffer + p, bytes);
        if (in_subheader && tag == 0x80)
            revision = value;
        else if (in_subheader && tag == 0x84)
            sample_rate = value;
        else if (in_subheader && tag == 0x85) {
            samples_ptr = buffer + p;
            samples_bytes = bytes;
            old_samples = value;
        }
        p += bytes;
    }

    if (!sample_rate)
        sample_rate = (revision == 3) ? 48000u : 22050u;
    if (!samples_ptr || !samples_bytes || !old_samples || !sample_rate) {
        intro_diag_logf(
            "EA SCHl reject: duration metadata incomplete revision=%lu sample_rate=%lu samples=%lu bytes=%u",
            (unsigned long)revision, (unsigned long)sample_rate,
            (unsigned long)old_samples, (unsigned int)samples_bytes);
        return 0;
    }

    {
        ULONGLONG n = (ULONGLONG)target_us * (ULONGLONG)sample_rate + 999999ULL;
        ULONGLONG target = n / 1000000ULL;
        ULONGLONG max_value = samples_bytes == 4 ? 0xffffffffULL :
            ((1ULL << (samples_bytes * 8)) - 1ULL);
        if (!target) target = 1;
        if (target > max_value) {
            intro_diag_logf("EA SCHl reject: target samples=%llu do not fit %u-byte field",
                (unsigned long long)target, (unsigned int)samples_bytes);
            return 0;
        }
        new_samples = old_samples;
        if (new_samples > (DWORD)target)
            new_samples = (DWORD)target;
    }

    intro_diag_logf(
        "EA SCHl revision=%lu sample_rate=%lu samples=%lu->%lu duration_ms=%lu->%lu field_bytes=%u",
        (unsigned long)revision, (unsigned long)sample_rate,
        (unsigned long)old_samples, (unsigned long)new_samples,
        (unsigned long)(((ULONGLONG)old_samples * 1000ULL) / sample_rate),
        (unsigned long)(((ULONGLONG)new_samples * 1000ULL) / sample_rate),
        (unsigned int)samples_bytes);

    intro_cache_write_be(samples_ptr, samples_bytes, new_samples);
    if (sample_rate_out) *sample_rate_out = sample_rate;
    if (old_samples_out) *old_samples_out = old_samples;
    if (new_samples_out) *new_samples_out = new_samples;
    return 1;
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
    DWORD mvhd_size;
    DWORD old_frames;
    DWORD new_frames;
    DWORD max_frame_size;
    DWORD rate;
    DWORD scale;
    DWORD target_frames;
    DWORD target_us = 120000u;
    WORD width;
    WORD height;
    DWORD pos;
    DWORD schl_count = 0;
    DWORD mv0k_count = 0;
    DWORD mv0f_count = 0;
    DWORD sample_rate = 0;
    DWORD old_samples = 0;
    DWORD new_samples = 0;
    int audio_patched = 0;
    int ok = 0;

    if (!controller_diag_real_CreateFileA || !controller_diag_real_ReadFile ||
        !controller_diag_real_CloseHandle) return 0;

    h = controller_diag_real_CreateFileA(path, GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        intro_diag_logf("EA CACHE patch open failed path=\"%s\" winerr=%lu",
            path, (unsigned long)GetLastError());
        return 0;
    }
    if (!GetFileSizeEx(h, &file_size) || file_size.QuadPart < 32) {
        intro_diag_logf("EA CACHE invalid size source=\"%s\" size=%lld",
            source_name, (long long)file_size.QuadPart);
        goto done;
    }

    read_size = file_size.QuadPart > (2 * 1024 * 1024) ?
        (2 * 1024 * 1024) : (DWORD)file_size.QuadPart;
    buffer = (BYTE *)HeapAlloc(GetProcessHeap(), 0, read_size);
    if (!buffer) {
        intro_diag_logf("EA CACHE HeapAlloc failed bytes=%lu", (unsigned long)read_size);
        goto done;
    }
    if (!controller_diag_real_ReadFile(h, buffer, read_size, &got, NULL) || got != read_size) {
        intro_diag_logf("EA CACHE header read failed wanted=%lu got=%lu winerr=%lu",
            (unsigned long)read_size, (unsigned long)got, (unsigned long)GetLastError());
        goto done;
    }

    intro_diag_logf("EA CACHE inspect source=\"%s\" copy=\"%s\" size=%lld header_bytes=%lu",
        source_name, path, (long long)file_size.QuadPart, (unsigned long)read_size);

    if (!intro_cache_fourcc(buffer, "MVhd")) {
        char tag0[5];
        intro_cache_fourcc_text(buffer, tag0);
        intro_diag_logf("EA CACHE reject: expected MVhd, got tag0=%s", tag0);
        intro_cache_hexdump_prefix(buffer, read_size);
        goto done;
    }

    mvhd_size = intro_cache_u32(buffer + 4);
    if (mvhd_size < 32 || mvhd_size > read_size) {
        intro_diag_logf("EA CACHE reject: MVhd size=%lu expected at least 32 and within header buffer",
            (unsigned long)mvhd_size);
        goto done;
    }

    width = intro_cache_u16(buffer + 12);
    height = intro_cache_u16(buffer + 14);
    old_frames = intro_cache_u32(buffer + 16);
    max_frame_size = intro_cache_u32(buffer + 20);
    rate = intro_cache_u32(buffer + 24);
    scale = intro_cache_u32(buffer + 28);
    if (!width || !height || !old_frames || !rate || !scale) {
        intro_diag_logf(
            "EA CACHE reject: MVhd invalid width=%u height=%u frames=%lu rate=%lu scale=%lu",
            (unsigned int)width, (unsigned int)height, (unsigned long)old_frames,
            (unsigned long)rate, (unsigned long)scale);
        goto done;
    }

    {
        ULONGLONG numerator = (ULONGLONG)target_us * (ULONGLONG)rate;
        ULONGLONG denominator = 1000000ULL * (ULONGLONG)scale;
        ULONGLONG target = (numerator + denominator - 1ULL) / denominator;
        if (!target) target = 1;
        if (target > 0xffffffffULL) target = 0xffffffffULL;
        target_frames = (DWORD)target;
    }
    new_frames = old_frames;
    if (new_frames > target_frames)
        new_frames = target_frames;

    intro_diag_logf(
        "EA MVhd size=%lu dimensions=%ux%u frames=%lu->%lu max_frame_chunk=%lu rate=%lu scale=%lu fps_x1000=%lu target_us=%lu",
        (unsigned long)mvhd_size, (unsigned int)width, (unsigned int)height,
        (unsigned long)old_frames, (unsigned long)new_frames,
        (unsigned long)max_frame_size, (unsigned long)rate, (unsigned long)scale,
        (unsigned long)(((ULONGLONG)rate * 1000ULL + scale / 2u) / scale),
        (unsigned long)target_us);

    /* Walk complete EA chunks that fit in the diagnostic/header buffer. EA VP6
       chunk sizes include their own 8-byte tag+size header. */
    pos = 0;
    while (pos + 8 <= read_size) {
        DWORD chunk_size = intro_cache_u32(buffer + pos + 4);
        if (chunk_size < 8) {
            intro_diag_logf("EA CACHE chunk scan stop: bad size=%lu at offset=0x%08lx",
                (unsigned long)chunk_size, (unsigned long)pos);
            break;
        }
        if ((ULONGLONG)pos + chunk_size > read_size)
            break;

        if (intro_cache_fourcc(buffer + pos, "SCHl")) {
            schl_count++;
            if (!audio_patched) {
                audio_patched = intro_cache_parse_schl(buffer, pos, chunk_size,
                    target_us, &sample_rate, &old_samples, &new_samples);
            }
        } else if (intro_cache_fourcc(buffer + pos, "MV0K")) {
            mv0k_count++;
        } else if (intro_cache_fourcc(buffer + pos, "MV0F")) {
            mv0f_count++;
        }
        pos += chunk_size;
    }

    if (!schl_count || !audio_patched || !mv0k_count) {
        intro_diag_logf(
            "EA CACHE reject: structure incomplete SCHl=%lu audio_duration=%d MV0K=%lu MV0F=%lu",
            (unsigned long)schl_count, audio_patched,
            (unsigned long)mv0k_count, (unsigned long)mv0f_count);
        intro_cache_hexdump_prefix(buffer, read_size);
        goto done;
    }

    intro_cache_put_u32(buffer + 16, new_frames);

    zero.QuadPart = 0;
    if (!SetFilePointerEx(h, zero, NULL, FILE_BEGIN) ||
        !WriteFile(h, buffer, read_size, &written, NULL) ||
        written != read_size || !FlushFileBuffers(h)) {
        intro_diag_logf("EA CACHE header write failed wrote=%lu/%lu winerr=%lu",
            (unsigned long)written, (unsigned long)read_size,
            (unsigned long)GetLastError());
        goto done;
    }

    intro_diag_logf(
        "EA CACHE validation PASS frames=%lu->%lu audio_samples=%lu->%lu sample_rate=%lu SCHl=%lu MV0K=%lu MV0F=%lu compressed_payload_unchanged=1",
        (unsigned long)old_frames, (unsigned long)new_frames,
        (unsigned long)old_samples, (unsigned long)new_samples,
        (unsigned long)sample_rate, (unsigned long)schl_count,
        (unsigned long)mv0k_count, (unsigned long)mv0f_count);
    ok = 1;

done:
    if (buffer) HeapFree(GetProcessHeap(), 0, buffer);
    controller_diag_real_CloseHandle(h);
    return ok;
}

'''

runtime = replace_regex_once(
    runtime,
    r'''static int intro_cache_patch_avi_file\(const char \*path, const char \*source_name\)\n\{.*?\n\}\n\n(?=static int intro_cache_copy_source)''',
    new_function,
    'replace AVI cache patcher with EA MVhd/SCHl patcher',
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern EA MVhd/SCHl short-intro metadata patch v38")
