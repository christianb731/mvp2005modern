from pathlib import Path

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller empirical hybrid v23 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# v23: stop treating one-based vs zero-based as an all-or-nothing theory.
# ---------------------------------------------------------------------------
# The user's own successful/failed controls across v21/F7 and v21/F8 give us a
# directly observed gameplay map:
#   F8: A at slot 0 works, B at slot 1 works.
#   F7: X at slot 3 works, Y at slot 4 works.
#   Any control placed at slot 2 opens the unwanted manager menu.
#   Back at slot 7 fires pitch 5 instead of its intended action.
#
# Use exactly those observed-good positions simultaneously during gameplay:
#   A -> 0, B -> 1, [2 intentionally unused], X -> 3, Y -> 4.
# Keep LB/RB, Start, L3/R3 on the v21 canonical slots for now. Suppress Back in
# gameplay so it cannot throw an unintended pitch. Frontend/menu input remains
# the normal v21 one-based mapping, so menu navigation is not destabilized.
#
# v22's buffered GetDeviceData hypothesis is also retired. The user's v22 log
# contains zero BUFFERED BUTTON entries despite extensive input, proving MVP is
# not consuming that hooked path in this run. Do not patch slot 10 anymore.

# Disable the v22 buffered-event hook while leaving the helper code harmlessly
# compiled for diagnostics/history.
runtime = replace_once(
    runtime,
    '''    if (vtbl[9] != (void *)controller_fake_GetDeviceState)\n        patch_vtable_slot(vtbl, 9, controller_fake_GetDeviceState,\n            (void **)&controller_real_GetDeviceState);\n    if (vtbl[10] != (void *)controller_fake_GetDeviceData)\n        patch_vtable_slot(vtbl, 10, controller_fake_GetDeviceData,\n            (void **)&controller_real_GetDeviceData);\n''',
    '''    if (vtbl[9] != (void *)controller_fake_GetDeviceState)\n        patch_vtable_slot(vtbl, 9, controller_fake_GetDeviceState,\n            (void **)&controller_real_GetDeviceState);\n''',
    "disable unused buffered hook",
)

# Apply the empirical mixed slot layout only to the default F7/native-XInput
# state and only while the proven RC1 gameplay phase detector is active.
old = '''        if (controller_write_xinput_state(data_size, data)) {\n            if (controller_diag_mode == 3) {\n'''
new = '''        if (controller_write_xinput_state(data_size, data)) {\n            if (controller_diag_mode == 2 &&\n                InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0) {\n                BYTE a = bytes[48 + 1];\n                BYTE b = bytes[48 + 2];\n                BYTE x = bytes[48 + 3];\n                BYTE y = bytes[48 + 4];\n\n                /* Empirical gameplay map from the user's successful tests:\n                 *   A slot 0 (worked in F8)\n                 *   B slot 1 (worked in F8)\n                 *   slot 2 unused (consistently opens manager menu)\n                 *   X slot 3 (worked in F7)\n                 *   Y slot 4 (worked in F7)\n                 * Back/slot 7 is suppressed because it consistently fires pitch 5. */\n                bytes[48 + 0] = a;\n                bytes[48 + 1] = b;\n                bytes[48 + 2] = 0;\n                bytes[48 + 3] = x;\n                bytes[48 + 4] = y;\n                bytes[48 + 7] = 0;\n            }\n            if (controller_diag_mode == 3) {\n'''
runtime = replace_once(runtime, old, new, "empirical gameplay face map")

# Make the state log explicitly show gameplay/frontend phase so one future log
# immediately proves whether the hybrid branch was active for a press.
runtime = replace_once(
    runtime,
    '''        "STATE self=%p caller=%p mode=%d/%s bslot=%d RAW btn=[%s] axes=%ld,%ld,%ld,%ld,%ld,%ld pov=%08lx | OUT btn=[%s] axes=%ld,%ld,%ld,%ld,%ld,%ld pov=%08lx | keys Esc=%d Enter=%d",\n        self, caller, controller_diag_mode, controller_diag_mode_name(controller_diag_mode),\n        controller_diag_b_slot_override, raw_buttons,\n''',
    '''        "STATE self=%p caller=%p mode=%d/%s phase=%ld bslot=%d RAW btn=[%s] axes=%ld,%ld,%ld,%ld,%ld,%ld pov=%08lx | OUT btn=[%s] axes=%ld,%ld,%ld,%ld,%ld,%ld pov=%08lx | keys Esc=%d Enter=%d",\n        self, caller, controller_diag_mode, controller_diag_mode_name(controller_diag_mode),\n        (long)InterlockedCompareExchange(&gameplay_input_phase, 0, 0),\n        controller_diag_b_slot_override, raw_buttons,\n''',
    "log gameplay phase",
)

runtime = replace_once(
    runtime,
    'MVP2005 Modern controller diagnostics + buffered-path normalization v22\\r\\n',
    'MVP2005 Modern controller diagnostics + empirical hybrid gameplay map v23\\r\\n',
    "diagnostic banner",
)

runtime = replace_once(
    runtime,
    'controller hooks requested; GetDeviceState + GetDeviceData normalized; default=F7 canonical one-based XInput; F5 raw DI, F6 DI remap/raw axes, F7 XInput 1-based, F8 XInput 0-based, F9 DI remap+neutral trigger, F10 XInput+neutral trigger; Ctrl+1..0 B-slot test, Ctrl+F11 clear B-slot, Ctrl+F12 marker',
    'controller hooks requested; default=F7 with empirical gameplay map A0/B1/(2 blocked)/X3/Y4 and Back suppressed; frontend stays canonical; F5-F10 diagnostics retained; Ctrl+1..0 B-slot test, Ctrl+F11 clear B-slot, Ctrl+F12 marker',
    "startup diagnostic text",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern empirical hybrid gameplay controller map v23")
