from pathlib import Path

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"skip intro v42 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# v0.41 is the verified behavior baseline. v0.42 intentionally does not alter
# the EA cache construction, SCCl correction, delay, foreground-process guard,
# SendInput click, or one-shot scheduling. This pass only promotes the feature
# from diagnostic preview to production-style logging.
runtime = replace_once(
    runtime,
    'intro_diag_logf("MVP2005 Modern Skip Intro diagnostics v41 guarded automatic skip input");',
    'intro_diag_logf("MVP2005 Modern Skip Intro v42 production");',
    'production log header',
)

runtime = replace_once(
    runtime,
    'legacy ENABLE_FRONTEND_MOVIES byte patch retired; v41 keeps the validated trimmed cache and automatically reproduces the user-proven skip input',
    'Skip Intro production path active: validated short EA cache + guarded one-shot input',
    'production path description',
)

# Filter at the format-string level, before vsnprintf/GetLocalTime/WriteFile.
# Normal successful startup should now be only a handful of lines, while every
# rejection/fallback/failure/abort remains available for support diagnostics.
old_gate = '''    if (intro_diag_log_handle == INVALID_HANDLE_VALUE) return;\n    va_start(args, fmt);\n'''
new_gate = '''    if (intro_diag_log_handle == INVALID_HANDLE_VALUE || !fmt) return;\n\n    /* Production log policy: keep startup identity, one cache-ready line per\n       movie, final auto-skip success, and all error/fallback paths. Do not\n       format or write the verbose development trace on healthy launches. */\n    if (strncmp(fmt, "MVP2005 Modern Skip Intro", 25) != 0 &&\n        strncmp(fmt, "skip_intro=", 11) != 0 &&\n        strncmp(fmt, "Skip Intro production path active", 33) != 0 &&\n        strncmp(fmt, "CACHE ready", 11) != 0 &&\n        strncmp(fmt, "AUTO SKIP PASS", 14) != 0 &&\n        strstr(fmt, "FAIL") == NULL &&\n        strstr(fmt, "failed") == NULL &&\n        strstr(fmt, "reject") == NULL &&\n        strstr(fmt, "abort") == NULL &&\n        strstr(fmt, "unavailable") == NULL &&\n        strstr(fmt, "timeout") == NULL &&\n        strstr(fmt, "falling back") == NULL &&\n        strstr(fmt, "bad ") == NULL &&\n        strstr(fmt, "missing") == NULL &&\n        strstr(fmt, "ERROR") == NULL &&\n        strstr(fmt, "error") == NULL)\n        return;\n\n    va_start(args, fmt);\n'''
runtime = replace_once(runtime, old_gate, new_gate, 'production log filter')

# The chunk walker still validates every chunk exactly as before, but production
# builds no longer call the formatter 40 times per movie for successful chunks.
old_chunk_logger = '''static void intro_cache_log_chunk(const BYTE *chunk, DWORD pos, DWORD size, DWORD index)\n{\n    char tag[5];\n    if (index >= 40) return;\n    intro_cache_fourcc_text(chunk, tag);\n    intro_diag_logf("EA CHUNK[%lu] offset=0x%08lx tag=%s size=%lu",\n        (unsigned long)index, (unsigned long)pos, tag, (unsigned long)size);\n}\n'''
new_chunk_logger = '''static void intro_cache_log_chunk(const BYTE *chunk, DWORD pos, DWORD size, DWORD index)\n{\n    /* v0.42 production: validation remains active; healthy per-chunk tracing is retired. */\n    (void)chunk;\n    (void)pos;\n    (void)size;\n    (void)index;\n}\n'''
runtime = replace_once(runtime, old_chunk_logger, new_chunk_logger, 'retire healthy chunk trace')

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern Skip Intro production cleanup v42")
