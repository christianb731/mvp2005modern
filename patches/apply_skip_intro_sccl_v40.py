from pathlib import Path

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"skip intro v40 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


runtime = replace_once(
    runtime,
    'intro_diag_logf("MVP2005 Modern Skip Intro diagnostics v39 self-consistent EA prefix trim");',
    'intro_diag_logf("MVP2005 Modern Skip Intro diagnostics v40 SCCl endian-correct trim");',
    'diagnostic version header',
)

runtime = replace_once(
    runtime,
    'legacy ENABLE_FRONTEND_MOVIES byte patch retired; v39 builds a physically trimmed EA VP6/ADPCM cache with original SCEl terminator',
    'legacy ENABLE_FRONTEND_MOVIES byte patch retired; v40 uses self-consistent EA trim with endian-correct SCCl block count',
    'retired flag message',
)

old_sccl = r'''        if (intro_cache_fourcc(output + pos, "SCCl") && chunk_size >= 12) {
            DWORD old_count = intro_cache_u32(output + pos + 8);
            intro_cache_put_u32(output + pos + 8, audio_blocks);
            intro_diag_logf("EA TRIM SCCl blocks=%lu->%lu offset=0x%08lx",
                (unsigned long)old_count, (unsigned long)audio_blocks,
                (unsigned long)pos);
        }
'''

new_sccl = r'''        if (intro_cache_fourcc(output + pos, "SCCl") && chunk_size >= 12) {
            DWORD old_count_be = intro_cache_read_be(output + pos + 8, 4);
            DWORD raw_le_before = intro_cache_u32(output + pos + 8);
            DWORD verify_count;

            /* EA SCCl's payload is a big-endian SCDl block count even though
               the surrounding EA chunk size field is little-endian on PC.
               v0.39 incorrectly treated this payload as little-endian, which
               turned sane counts such as 170 (00 00 00 AA) and 2302
               (00 00 08 FE) into huge values and then wrote the replacement
               count in the wrong byte order. */
            intro_cache_write_be(output + pos + 8, 4, audio_blocks);
            verify_count = intro_cache_read_be(output + pos + 8, 4);
            intro_diag_logf(
                "EA TRIM SCCl blocks_be=%lu->%lu raw_le_before=0x%08lx verify_be=%lu offset=0x%08lx",
                (unsigned long)old_count_be, (unsigned long)audio_blocks,
                (unsigned long)raw_le_before, (unsigned long)verify_count,
                (unsigned long)pos);
            if (verify_count != audio_blocks) {
                intro_diag_logf("EA TRIM reject SCCl verification failed expected=%lu got=%lu",
                    (unsigned long)audio_blocks, (unsigned long)verify_count);
                goto done;
            }
        }
'''

runtime = replace_once(runtime, old_sccl, new_sccl, 'SCCl endian fix')

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern Skip Intro SCCl endian correction v40")
