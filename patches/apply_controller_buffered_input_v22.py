from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller buffered input v22 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"controller buffered input v22 {label}: expected exactly one match, found {count}")
    return updated


# ---------------------------------------------------------------------------
# Root cause addressed by v22
# ---------------------------------------------------------------------------
# The early v10 probe only began seeing the user's real button transitions after
# it hooked IDirectInputDevice::GetDeviceData (the buffered event path). v13 and
# every later production remapper only transformed GetDeviceState. That left MVP
# receiving TWO representations of the same controller: our corrected state plus
# untouched raw buffered button events. This explains the seemingly impossible
# results where the diagnostic OUT state was correct but MVP still opened a menu,
# paused from L3, or put pitch 5 on Back/Start.
#
# v22 remaps the buffered button-event offsets with the exact same physical ->
# logical mapping as the state path. F7/canonical modes produce logical slots
# 1..10; F8/zero-based produces 0..9; F5/raw is untouched. No controller.cfg
# action changes are made here.

# Add the buffered DirectInput function type next to GetDeviceState.
runtime = replace_once(
    runtime,
    'typedef HRESULT (WINAPI *ControllerDIGetDeviceStateFn)(void *self, DWORD data_size, void *data);\n',
    'typedef HRESULT (WINAPI *ControllerDIGetDeviceStateFn)(void *self, DWORD data_size, void *data);\n'
    'typedef HRESULT (WINAPI *ControllerDIGetDeviceDataFn)(void *self, DWORD object_size, void *data, DWORD *count, DWORD flags);\n',
    "GetDeviceData typedef",
)

runtime = replace_once(
    runtime,
    'static ControllerDIGetDeviceStateFn controller_real_GetDeviceState;\n',
    'static ControllerDIGetDeviceStateFn controller_real_GetDeviceState;\n'
    'static ControllerDIGetDeviceDataFn controller_real_GetDeviceData;\n',
    "GetDeviceData real pointer",
)

# Insert the buffered-event translator immediately after the existing diagnostic
# GetDeviceState wrapper and before controller_patch_device(). DIDEVICEOBJECTDATA
# is 16 bytes on the legacy DirectInput7 path MVP uses; later runtimes may append
# fields, so only the first four DWORDs are accessed and object_size is respected.
marker = '''static void controller_patch_device(void *device)\n'''
if runtime.count(marker) != 1:
    raise SystemExit(f"controller buffered input v22 patch-device marker: found {runtime.count(marker)}")

helpers = r'''typedef struct ControllerBufferedObjectData {
    DWORD dwOfs;
    DWORD dwData;
    DWORD dwTimeStamp;
    DWORD dwSequence;
} ControllerBufferedObjectData;

static int controller_buffered_logical_button(int raw_index)
{
    int i;
    for (i = 0; i < 10; i++)
        if (controller_button_sources[i] == raw_index) return i;
    return -1;
}

static HRESULT WINAPI controller_fake_GetDeviceData(void *self, DWORD object_size,
    void *data, DWORD *count, DWORD flags)
{
    DWORD returned;
    DWORD i;
    HRESULT hr = controller_real_GetDeviceData ?
        controller_real_GetDeviceData(self, object_size, data, count, flags) : E_FAIL;

    if (FAILED(hr) || !controller_remap_enabled || !data || !count || object_size < 16)
        return hr;

    returned = *count;
    for (i = 0; i < returned; i++) {
        BYTE *base = (BYTE *)data + ((size_t)i * object_size);
        ControllerBufferedObjectData *ev = (ControllerBufferedObjectData *)base;
        DWORD old_ofs = ev->dwOfs;

        if (old_ofs >= 48 && old_ofs < 80 && controller_diag_mode != 0) {
            int raw_index = (int)(old_ofs - 48);
            int logical = controller_buffered_logical_button(raw_index);
            if (logical >= 0) {
                int out_index = (controller_diag_mode == 3) ? logical : (logical + 1);
                ev->dwOfs = (DWORD)(48 + out_index);
                if (ev->dwOfs != old_ofs) {
                    controller_diag_logf(
                        "BUFFERED BUTTON self=%p mode=%d/%s raw_slot=%d -> out_slot=%d data=%08lx %s",
                        self, controller_diag_mode, controller_diag_mode_name(controller_diag_mode),
                        raw_index, out_index, (unsigned long)ev->dwData,
                        (ev->dwData & 0x80) ? "DOWN" : "UP");
                }
            }
        }
    }
    return hr;
}

'''
runtime = runtime.replace(marker, helpers + marker, 1)

# Patch BOTH input APIs. The state path was already guarded against repatching a
# shared vtable; do the same for buffered input at slot 10.
old_hook = '''    if (vtbl[9] != (void *)controller_fake_GetDeviceState)\n        patch_vtable_slot(vtbl, 9, controller_fake_GetDeviceState,\n            (void **)&controller_real_GetDeviceState);\n'''
new_hook = '''    if (vtbl[9] != (void *)controller_fake_GetDeviceState)\n        patch_vtable_slot(vtbl, 9, controller_fake_GetDeviceState,\n            (void **)&controller_real_GetDeviceState);\n    if (vtbl[10] != (void *)controller_fake_GetDeviceData)\n        patch_vtable_slot(vtbl, 10, controller_fake_GetDeviceData,\n            (void **)&controller_real_GetDeviceData);\n'''
runtime = replace_once(runtime, old_hook, new_hook, "patch buffered vtable slot")

# Self-identify the run so there is no ambiguity about which binary produced a
# diagnostic file.
runtime = replace_once(
    runtime,
    'MVP2005 Modern controller diagnostics + canonical one-based v21\\r\\n',
    'MVP2005 Modern controller diagnostics + buffered-path normalization v22\\r\\n',
    "diagnostic banner",
)

runtime = replace_once(
    runtime,
    'controller hooks requested; default=F7 canonical one-based XInput; Ctrl+F4 toggles legacy face split; F5 raw DI, F6 DI remap/raw axes, F7 XInput 1-based, F8 XInput 0-based, F9 DI remap+neutral trigger, F10 XInput+neutral trigger; Ctrl+1..0 B-slot test, Ctrl+F11 clear B-slot, Ctrl+F12 marker',
    'controller hooks requested; GetDeviceState + GetDeviceData normalized; default=F7 canonical one-based XInput; F5 raw DI, F6 DI remap/raw axes, F7 XInput 1-based, F8 XInput 0-based, F9 DI remap+neutral trigger, F10 XInput+neutral trigger; Ctrl+1..0 B-slot test, Ctrl+F11 clear B-slot, Ctrl+F12 marker',
    "startup diagnostic text",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern buffered DirectInput normalization v22")
