from pathlib import Path

# The v0.50 audit was authored against the pre-failsafe CreateDevice/Reset layout.
# The production runtime wraps prepare_borderless_* inside an if block and keeps a
# fullscreen fallback copy. Rewrite only those two textual anchors in-memory, then
# execute the otherwise unchanged audit patch.
source_path = Path(__file__).with_name("apply_gameplay_graphics_audit_v50.py")
source = source_path.read_text(encoding="utf-8")

old_create_target = "'''    prepare_borderless_create(self, adapter, focus_window, presentation_parameters);\\n    hr = real_CreateDevice(self, adapter, device_type, focus_window, behavior_flags,\\n''',"
new_create_target = "'''        prepare_borderless_create(self, adapter, focus_window, presentation_parameters);\\n    }\\n\\n    hr = real_CreateDevice(self, adapter, device_type, focus_window, behavior_flags,\\n''',"
if source.count(old_create_target) != 1:
    raise SystemExit(f"v50 bootstrap CreateDevice target: expected 1, found {source.count(old_create_target)}")
source = source.replace(old_create_target, new_create_target, 1)

old_create_replacement = "'''    prepare_borderless_create(self, adapter, focus_window, presentation_parameters);\\n    gfx_audit_note_present_params(\"CREATEDEVICE\", presentation_parameters);\\n    hr = real_CreateDevice(self, adapter, device_type, focus_window, behavior_flags,\\n''',"
new_create_replacement = "'''        prepare_borderless_create(self, adapter, focus_window, presentation_parameters);\\n    }\\n\\n    gfx_audit_note_present_params(\"CREATEDEVICE\", presentation_parameters);\\n    hr = real_CreateDevice(self, adapter, device_type, focus_window, behavior_flags,\\n''',"
if source.count(old_create_replacement) != 1:
    raise SystemExit(f"v50 bootstrap CreateDevice replacement: expected 1, found {source.count(old_create_replacement)}")
source = source.replace(old_create_replacement, new_create_replacement, 1)

old_reset_target = "'''    prepare_borderless_reset(presentation_parameters);\\n    hr = real_Reset ? real_Reset(self, presentation_parameters) : E_FAIL;\\n''',"
new_reset_target = "'''        prepare_borderless_reset(presentation_parameters);\\n    }\\n\\n    hr = real_Reset ? real_Reset(self, presentation_parameters) : E_FAIL;\\n''',"
if source.count(old_reset_target) != 1:
    raise SystemExit(f"v50 bootstrap Reset target: expected 1, found {source.count(old_reset_target)}")
source = source.replace(old_reset_target, new_reset_target, 1)

old_reset_replacement = "'''    prepare_borderless_reset(presentation_parameters);\\n    gfx_audit_note_present_params(\"RESET\", presentation_parameters);\\n    hr = real_Reset ? real_Reset(self, presentation_parameters) : E_FAIL;\\n''',"
new_reset_replacement = "'''        prepare_borderless_reset(presentation_parameters);\\n    }\\n\\n    gfx_audit_note_present_params(\"RESET\", presentation_parameters);\\n    hr = real_Reset ? real_Reset(self, presentation_parameters) : E_FAIL;\\n''',"
if source.count(old_reset_replacement) != 1:
    raise SystemExit(f"v50 bootstrap Reset replacement: expected 1, found {source.count(old_reset_replacement)}")
source = source.replace(old_reset_replacement, new_reset_replacement, 1)

namespace = {
    "__name__": "__main__",
    "__file__": str(source_path),
}
exec(compile(source, str(source_path), "exec"), namespace, namespace)
