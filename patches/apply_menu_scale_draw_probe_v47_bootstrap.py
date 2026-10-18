from pathlib import Path

# Compile-fix wrapper for v0.47. The original v47 patch was authored against two
# stale textual signatures. Correct those source strings in-memory, then execute
# the corrected patch against the pinned upstream runtime. Keeping this as a tiny
# wrapper makes the exact fix auditable and avoids duplicating the large diagnostic
# patch while we are still iterating on the frontend experiment.

source_path = Path(__file__).with_name("apply_menu_scale_draw_probe_v47.py")
source = source_path.read_text(encoding="utf-8")

old_marker = "marker = '''static int append_path(char *out, size_t out_size, const char *dir, const char *leaf)\\n'''"
new_marker = "marker = '''static int append_path(char *path, DWORD path_size, const char *leaf)\\n'''"
if source.count(old_marker) != 1:
    raise SystemExit(f"v47 bootstrap append_path marker: expected 1, found {source.count(old_marker)}")
source = source.replace(old_marker, new_marker, 1)

old_stream_return = "    return real_SetStreamSource(self, stream_number, stream_data, stride);\\n"
new_stream_return = "    return real_SetStreamSource ? real_SetStreamSource(self, stream_number, stream_data, stride) : E_FAIL;\\n"
if source.count(old_stream_return) != 1:
    raise SystemExit(f"v47 bootstrap SetStreamSource return: expected 1, found {source.count(old_stream_return)}")
source = source.replace(old_stream_return, new_stream_return, 1)

namespace = {
    "__name__": "__main__",
    "__file__": str(source_path),
}
exec(compile(source, str(source_path), "exec"), namespace, namespace)
