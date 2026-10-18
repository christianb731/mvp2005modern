from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"skip intro v39 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, new: str, label: str) -> str:
    updated, count = re.subn(pattern, lambda _m: new, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"skip intro v39 {label}: expected exactly one match, found {count}")
    return updated


runtime = replace_once(
    runtime,
    'intro_diag_logf("MVP2005 Modern Skip Intro diagnostics v38 EA MVhd/SCHl short cache");',
    'intro_diag_logf("MVP2005 Modern Skip Intro diagnostics v39 self-consistent EA prefix trim");',
    'diagnostic version header',
)

runtime = replace_once(
    runtime,
    'legacy ENABLE_FRONTEND_MOVIES byte patch retired; v38 uses validated EA MVhd/SCHl duration metadata in private cache',
    'legacy ENABLE_FRONTEND_MOVIES byte patch retired; v39 builds a physically trimmed EA VP6/ADPCM cache with original SCEl terminator',
    'retired flag message',
)

new_audio_and_patcher = r'''typedef struct IntroEaAudioMeta {
    DWORD revision;
    DWORD sample_rate;
    DWORD old_samples;
    DWORD samples_offset;
    BYTE samples_bytes;
} IntroEaAudioMeta;

static int intro_cache_parse_schl_meta(const BYTE *buffer, DWORD total_size,
    DWORD chunk_pos, DWORD chunk_size, IntroEaAudioMeta *meta)
{
    DWORD p;
    DWORD end;
    DWORD sample_rate = 0;
    DWORD revision = 0xffffffffu;
    DWORD old_samples = 0;
    DWORD samples_offset = 0;
    BYTE samples_bytes = 0;
    int in_subheader = 0;

    if (!buffer || !meta || chunk_size < 24 || chunk_pos + chunk_size < chunk_pos ||
        chunk_pos + chunk_size > total_size)
        return 0;
    end = chunk_pos + chunk_size;
    if (!intro_cache_fourcc(buffer + chunk_pos, "SCHl"))
        return 0;
    if (chunk_pos + 16 > end || !intro_cache_fourcc(buffer + chunk_pos + 8, "GSTR")) {
        intro_diag_logf("EA SCHl reject: missing GSTR payload at offset=0x%08lx size=%lu",
            (unsigned long)chunk_pos, (unsigned long)chunk_size);
        return 0;
    }

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
        if (p >= end) return 0;
        bytes = buffer[p++];
        if (!bytes || bytes > 4 || p + bytes > end) return 0;
        value = intro_cache_read_be(buffer + p, bytes);
        if (in_subheader && tag == 0x80)
            revision = value;
        else if (in_subheader && tag == 0x84)
            sample_rate = value;
        else if (in_subheader && tag == 0x85) {
            samples_offset = p;
            samples_bytes = bytes;
            old_samples = value;
        }
        p += bytes;
    }

    if (!sample_rate)
        sample_rate = (revision == 3) ? 48000u : 22050u;
    if (!samples_offset || !samples_bytes || !old_samples || !sample_rate) {
        intro_diag_logf(
            "EA SCHl reject: duration metadata incomplete revision=%lu sample_rate=%lu samples=%lu bytes=%u",
            (unsigned long)revision, (unsigned long)sample_rate,
            (unsigned long)old_samples, (unsigned int)samples_bytes);
        return 0;
    }

    ZeroMemory(meta, sizeof(*meta));
    meta->revision = revision;
    meta->sample_rate = sample_rate;
    meta->old_samples = old_samples;
    meta->samples_offset = samples_offset;
    meta->samples_bytes = samples_bytes;
    intro_diag_logf(
        "EA SCHl metadata revision=%lu sample_rate=%lu samples=%lu duration_ms=%lu field_offset=0x%08lx bytes=%u",
        (unsigned long)revision, (unsigned long)sample_rate,
        (unsigned long)old_samples,
        (unsigned long)(((ULONGLONG)old_samples * 1000ULL) / sample_rate),
        (unsigned long)samples_offset, (unsigned int)samples_bytes);
    return 1;
}

static DWORD intro_cache_scdl_samples(const BYTE *chunk, DWORD chunk_size, DWORD revision)
{
    if (!chunk || chunk_size < 12 || !intro_cache_fourcc(chunk, "SCDl"))
        return 0;
    if (revision == 3)
        return ((DWORD)chunk[8] << 24) | ((DWORD)chunk[9] << 16) |
            ((DWORD)chunk[10] << 8) | (DWORD)chunk[11];
    if (revision == 1 || revision == 2)
        return intro_cache_u32(chunk + 8);
    return 0;
}

static void intro_cache_log_chunk(const BYTE *chunk, DWORD pos, DWORD size, DWORD index)
{
    char tag[5];
    if (index >= 40) return;
    intro_cache_fourcc_text(chunk, tag);
    intro_diag_logf("EA CHUNK[%lu] offset=0x%08lx tag=%s size=%lu",
        (unsigned long)index, (unsigned long)pos, tag, (unsigned long)size);
}

static int intro_cache_patch_avi_file(const char *path, const char *source_name)
{
    HANDLE h;
    LARGE_INTEGER file_size_li;
    LARGE_INTEGER zero;
    LARGE_INTEGER verify_size;
    BYTE *input = NULL;
    BYTE *output = NULL;
    DWORD file_size;
    DWORD got = 0;
    DWORD written = 0;
    DWORD mvhd_size;
    WORD width;
    WORD height;
    DWORD old_frames;
    DWORD max_frame_size;
    DWORD rate;
    DWORD scale;
    DWORD target_us = 120000u;
    DWORD target_frames;
    DWORD target_audio_samples;
    DWORD pos;
    DWORD chunk_index = 0;
    DWORD schl_pos = 0xffffffffu;
    DWORD end_pos = 0xffffffffu;
    DWORD end_size = 0;
    DWORD cutoff = 0;
    DWORD video_frames = 0;
    DWORD keyframes = 0;
    DWORD audio_blocks = 0;
    ULONGLONG audio_samples64 = 0;
    DWORD audio_samples;
    DWORD output_size;
    IntroEaAudioMeta audio;
    int first_video_seen = 0;
    int first_video_was_key = 0;
    int ok = 0;

    if (!controller_diag_real_CreateFileA || !controller_diag_real_ReadFile ||
        !controller_diag_real_CloseHandle) return 0;

    h = controller_diag_real_CreateFileA(path, GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        intro_diag_logf("EA TRIM open failed path=\"%s\" winerr=%lu",
            path, (unsigned long)GetLastError());
        return 0;
    }
    if (!GetFileSizeEx(h, &file_size_li) || file_size_li.QuadPart < 64 ||
        file_size_li.QuadPart > (128LL * 1024LL * 1024LL) ||
        file_size_li.QuadPart > 0xffffffffLL) {
        intro_diag_logf("EA TRIM reject size source=\"%s\" size=%lld",
            source_name, (long long)file_size_li.QuadPart);
        goto done;
    }
    file_size = (DWORD)file_size_li.QuadPart;
    input = (BYTE *)HeapAlloc(GetProcessHeap(), 0, file_size);
    if (!input) {
        intro_diag_logf("EA TRIM HeapAlloc input failed bytes=%lu", (unsigned long)file_size);
        goto done;
    }
    if (!controller_diag_real_ReadFile(h, input, file_size, &got, NULL) || got != file_size) {
        intro_diag_logf("EA TRIM read failed wanted=%lu got=%lu winerr=%lu",
            (unsigned long)file_size, (unsigned long)got, (unsigned long)GetLastError());
        goto done;
    }

    if (!intro_cache_fourcc(input, "MVhd")) {
        char tag0[5];
        intro_cache_fourcc_text(input, tag0);
        intro_diag_logf("EA TRIM reject expected MVhd got=%s", tag0);
        goto done;
    }
    mvhd_size = intro_cache_u32(input + 4);
    if (mvhd_size < 32 || mvhd_size > file_size) {
        intro_diag_logf("EA TRIM reject bad MVhd size=%lu", (unsigned long)mvhd_size);
        goto done;
    }
    width = intro_cache_u16(input + 12);
    height = intro_cache_u16(input + 14);
    old_frames = intro_cache_u32(input + 16);
    max_frame_size = intro_cache_u32(input + 20);
    rate = intro_cache_u32(input + 24);
    scale = intro_cache_u32(input + 28);
    if (!width || !height || !old_frames || !rate || !scale) {
        intro_diag_logf("EA TRIM reject MVhd fields dimensions=%ux%u frames=%lu rate=%lu scale=%lu",
            (unsigned int)width, (unsigned int)height, (unsigned long)old_frames,
            (unsigned long)rate, (unsigned long)scale);
        goto done;
    }
    {
        ULONGLONG n = (ULONGLONG)target_us * (ULONGLONG)rate;
        ULONGLONG d = 1000000ULL * (ULONGLONG)scale;
        ULONGLONG t = (n + d - 1ULL) / d;
        if (!t) t = 1;
        if (t > 0xffffffffULL) t = 0xffffffffULL;
        target_frames = (DWORD)t;
    }

    ZeroMemory(&audio, sizeof(audio));
    pos = 0;
    while (pos + 8 <= file_size) {
        DWORD chunk_size = intro_cache_u32(input + pos + 4);
        if (chunk_size < 8 || (ULONGLONG)pos + chunk_size > file_size) {
            intro_diag_logf("EA TRIM reject malformed chunk offset=0x%08lx size=%lu file=%lu",
                (unsigned long)pos, (unsigned long)chunk_size, (unsigned long)file_size);
            goto done;
        }
        intro_cache_log_chunk(input + pos, pos, chunk_size, chunk_index++);
        if (intro_cache_fourcc(input + pos, "SCHl") && schl_pos == 0xffffffffu) {
            schl_pos = pos;
            if (!intro_cache_parse_schl_meta(input, file_size, pos, chunk_size, &audio))
                goto done;
        } else if (intro_cache_fourcc(input + pos, "SCEl") && end_pos == 0xffffffffu) {
            end_pos = pos;
            end_size = chunk_size;
        }
        pos += chunk_size;
    }
    if (pos != file_size) {
        intro_diag_logf("EA TRIM reject chunk walk ended offset=0x%08lx file=%lu",
            (unsigned long)pos, (unsigned long)file_size);
        goto done;
    }
    if (schl_pos == 0xffffffffu || !audio.sample_rate || end_pos == 0xffffffffu || !end_size) {
        intro_diag_logf("EA TRIM reject missing structure SCHl=%d SCEl=%d sample_rate=%lu",
            schl_pos != 0xffffffffu, end_pos != 0xffffffffu,
            (unsigned long)audio.sample_rate);
        goto done;
    }

    {
        ULONGLONG t = ((ULONGLONG)audio.sample_rate * target_us + 999999ULL) / 1000000ULL;
        if (!t) t = 1;
        if (t > 0xffffffffULL) t = 0xffffffffULL;
        target_audio_samples = (DWORD)t;
    }

    intro_diag_logf(
        "EA TRIM plan source_size=%lu dimensions=%ux%u old_frames=%lu fps_x1000=%lu max_frame=%lu target_us=%lu target_frames=%lu target_audio_samples=%lu revision=%lu SCEl=0x%08lx/%lu",
        (unsigned long)file_size, (unsigned int)width, (unsigned int)height,
        (unsigned long)old_frames,
        (unsigned long)(((ULONGLONG)rate * 1000ULL + scale / 2u) / scale),
        (unsigned long)max_frame_size, (unsigned long)target_us,
        (unsigned long)target_frames, (unsigned long)target_audio_samples,
        (unsigned long)audio.revision, (unsigned long)end_pos, (unsigned long)end_size);

    /* Preserve the exact original chunk order. Copy a real prefix until it
       contains enough decoded video duration and enough decoded audio duration,
       then append the file's own original SCEl terminator. */
    pos = 0;
    while (pos + 8 <= end_pos) {
        DWORD chunk_size = intro_cache_u32(input + pos + 4);
        if (chunk_size < 8 || (ULONGLONG)pos + chunk_size > end_pos) {
            intro_diag_logf("EA TRIM select reject chunk offset=0x%08lx size=%lu end=0x%08lx",
                (unsigned long)pos, (unsigned long)chunk_size, (unsigned long)end_pos);
            goto done;
        }
        if (intro_cache_fourcc(input + pos, "MV0K") ||
            intro_cache_fourcc(input + pos, "MV0F")) {
            if (!first_video_seen) {
                first_video_seen = 1;
                first_video_was_key = intro_cache_fourcc(input + pos, "MV0K");
            }
            video_frames++;
            if (intro_cache_fourcc(input + pos, "MV0K")) keyframes++;
        } else if (intro_cache_fourcc(input + pos, "SCDl")) {
            DWORD samples = intro_cache_scdl_samples(input + pos, chunk_size, audio.revision);
            if (!samples) {
                intro_diag_logf("EA TRIM reject SCDl without readable duration offset=0x%08lx size=%lu revision=%lu",
                    (unsigned long)pos, (unsigned long)chunk_size, (unsigned long)audio.revision);
                goto done;
            }
            audio_blocks++;
            audio_samples64 += samples;
            if (audio_samples64 > 0xffffffffULL) {
                intro_diag_logf("EA TRIM reject accumulated audio samples overflow");
                goto done;
            }
        }
        cutoff = pos + chunk_size;
        if (video_frames >= target_frames && audio_samples64 >= target_audio_samples)
            break;
        pos += chunk_size;
    }

    if (!first_video_seen || !first_video_was_key || !keyframes || !video_frames ||
        !audio_blocks || !audio_samples64 || cutoff >= end_pos) {
        intro_diag_logf(
            "EA TRIM reject selected prefix key_first=%d keyframes=%lu video_frames=%lu audio_blocks=%lu audio_samples=%llu cutoff=0x%08lx end=0x%08lx",
            first_video_was_key, (unsigned long)keyframes, (unsigned long)video_frames,
            (unsigned long)audio_blocks, (unsigned long long)audio_samples64,
            (unsigned long)cutoff, (unsigned long)end_pos);
        goto done;
    }
    audio_samples = (DWORD)audio_samples64;
    {
        ULONGLONG max_value = audio.samples_bytes == 4 ? 0xffffffffULL :
            ((1ULL << (audio.samples_bytes * 8)) - 1ULL);
        if ((ULONGLONG)audio_samples > max_value) {
            intro_diag_logf("EA TRIM reject audio samples=%lu do not fit header bytes=%u",
                (unsigned long)audio_samples, (unsigned int)audio.samples_bytes);
            goto done;
        }
    }

    if ((ULONGLONG)cutoff + end_size > 0xffffffffULL) goto done;
    output_size = cutoff + end_size;
    output = (BYTE *)HeapAlloc(GetProcessHeap(), 0, output_size);
    if (!output) {
        intro_diag_logf("EA TRIM HeapAlloc output failed bytes=%lu", (unsigned long)output_size);
        goto done;
    }
    memcpy(output, input, cutoff);
    memcpy(output + cutoff, input + end_pos, end_size);

    /* The media payload is now physically consistent with these exact counts. */
    intro_cache_put_u32(output + 16, video_frames);
    intro_cache_write_be(output + audio.samples_offset, audio.samples_bytes, audio_samples);

    /* If this EA file uses an SCCl count block, make its count agree with the
       number of retained SCDl blocks. PC EA multimedia uses little-endian sizes. */
    pos = 0;
    while (pos + 8 <= cutoff) {
        DWORD chunk_size = intro_cache_u32(output + pos + 4);
        if (chunk_size < 8 || pos + chunk_size > cutoff) break;
        if (intro_cache_fourcc(output + pos, "SCCl") && chunk_size >= 12) {
            DWORD old_count = intro_cache_u32(output + pos + 8);
            intro_cache_put_u32(output + pos + 8, audio_blocks);
            intro_diag_logf("EA TRIM SCCl blocks=%lu->%lu offset=0x%08lx",
                (unsigned long)old_count, (unsigned long)audio_blocks,
                (unsigned long)pos);
        }
        pos += chunk_size;
    }

    zero.QuadPart = 0;
    if (!SetFilePointerEx(h, zero, NULL, FILE_BEGIN) ||
        !WriteFile(h, output, output_size, &written, NULL) ||
        written != output_size) {
        intro_diag_logf("EA TRIM write failed wrote=%lu/%lu winerr=%lu",
            (unsigned long)written, (unsigned long)output_size,
            (unsigned long)GetLastError());
        goto done;
    }
    {
        LARGE_INTEGER end_pointer;
        end_pointer.QuadPart = output_size;
        if (!SetFilePointerEx(h, end_pointer, NULL, FILE_BEGIN) ||
            !SetEndOfFile(h) || !FlushFileBuffers(h)) {
            intro_diag_logf("EA TRIM truncate/flush failed winerr=%lu",
                (unsigned long)GetLastError());
            goto done;
        }
    }
    if (!GetFileSizeEx(h, &verify_size) || verify_size.QuadPart != output_size) {
        intro_diag_logf("EA TRIM verify size FAIL expected=%lu actual=%lld",
            (unsigned long)output_size, (long long)verify_size.QuadPart);
        goto done;
    }

    intro_diag_logf(
        "EA TRIM PASS source_bytes=%lu cache_bytes=%lu cutoff=0x%08lx SCEl_bytes=%lu frames=%lu/%lu audio_samples=%lu/%lu audio_blocks=%lu duration_video_ms=%lu duration_audio_ms=%lu payload_prefix_unchanged=1 originals_untouched=1",
        (unsigned long)file_size, (unsigned long)output_size, (unsigned long)cutoff,
        (unsigned long)end_size, (unsigned long)video_frames, (unsigned long)old_frames,
        (unsigned long)audio_samples, (unsigned long)audio.old_samples,
        (unsigned long)audio_blocks,
        (unsigned long)(((ULONGLONG)video_frames * scale * 1000ULL) / rate),
        (unsigned long)(((ULONGLONG)audio_samples * 1000ULL) / audio.sample_rate));
    ok = 1;

done:
    if (output) HeapFree(GetProcessHeap(), 0, output);
    if (input) HeapFree(GetProcessHeap(), 0, input);
    controller_diag_real_CloseHandle(h);
    return ok;
}

'''

runtime = replace_regex_once(
    runtime,
    r'''static int intro_cache_parse_schl\(BYTE \*buffer, DWORD chunk_pos, DWORD chunk_size,.*?\n\}\n\nstatic int intro_cache_patch_avi_file\(const char \*path, const char \*source_name\)\n\{.*?\n\}\n\n(?=static int intro_cache_copy_source)''',
    new_audio_and_patcher,
    'replace metadata-only EA patcher with self-consistent physical trim',
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern self-consistent EA VP6 prefix trim v39")
