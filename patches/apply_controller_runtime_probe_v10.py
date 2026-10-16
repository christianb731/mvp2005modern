from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller runtime probe v10 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# v9 proved MVP creates many legacy DirectInput controller devices, but it did not
# record any GetDeviceState transitions. Extend the probe to the buffered input
# path (GetDeviceData), increase device tracking capacity, and log raw state calls
# even when a device was created after the original small tracking array filled.
replace_once(
'''typedef HRESULT (WINAPI *DIGetDeviceStateFn)(void *self, DWORD data_size, void *data);\ntypedef HRESULT (WINAPI *DISetDataFormatFn)(void *self, const void *format);\n''',
'''typedef HRESULT (WINAPI *DIGetDeviceStateFn)(void *self, DWORD data_size, void *data);\ntypedef HRESULT (WINAPI *DIGetDeviceDataFn)(void *self, DWORD object_size, void *data, DWORD *count, DWORD flags);\ntypedef HRESULT (WINAPI *DISetDataFormatFn)(void *self, const void *format);\ntypedef struct DIObjectDataV10 {\n    DWORD dwOfs;\n    DWORD dwData;\n    DWORD dwTimeStamp;\n    DWORD dwSequence;\n} DIObjectDataV10;\n''',
"buffered input typedefs",
)

replace_once(
'''static DIGetDeviceStateFn controller_probe_real_GetDeviceState;\nstatic DISetDataFormatFn controller_probe_real_SetDataFormat;\nstatic ControllerProbeDevice controller_probe_devices[8];\n''',
'''static DIGetDeviceStateFn controller_probe_real_GetDeviceState;\nstatic DIGetDeviceDataFn controller_probe_real_GetDeviceData;\nstatic DISetDataFormatFn controller_probe_real_SetDataFormat;\nstatic ControllerProbeDevice controller_probe_devices[32];\nstatic LONG controller_probe_state_call_log_count;\nstatic LONG controller_probe_data_call_log_count;\n''',
"globals and capacity",
)

text = text.replace("if (count > 8) count = 8;", "if (count > 32) count = 32;", 1)
text = text.replace("if (index < 0 || index >= 8) return NULL;", "if (index < 0 || index >= 32) return NULL;", 1)

replace_once(
'''static HRESULT WINAPI controller_probe_GetDeviceState(void *self, DWORD data_size, void *data)\n{\n    HRESULT hr = controller_probe_real_GetDeviceState ?\n        controller_probe_real_GetDeviceState(self, data_size, data) : E_FAIL;\n    ControllerProbeDevice *slot = controller_probe_find(self);\n    if (SUCCEEDED(hr) && slot && data)\n        controller_probe_log_buttons(slot, data_size, (const BYTE *)data);\n    return hr;\n}\n\n''',
'''static HRESULT WINAPI controller_probe_GetDeviceState(void *self, DWORD data_size, void *data)\n{\n    HRESULT hr = controller_probe_real_GetDeviceState ?\n        controller_probe_real_GetDeviceState(self, data_size, data) : E_FAIL;\n    ControllerProbeDevice *slot = controller_probe_find(self);\n    if (InterlockedIncrement(&controller_probe_state_call_log_count) <= 24) {\n        char buf[192];\n        wsprintfA(buf, "GetDeviceState self=%p size=%lu tracked=%d hr=%08lx\\r\\n",\n            self, (unsigned long)data_size, slot != NULL, (unsigned long)hr);\n        controller_probe_log(buf);\n    }\n    if (SUCCEEDED(hr) && slot && data)\n        controller_probe_log_buttons(slot, data_size, (const BYTE *)data);\n    return hr;\n}\n\nstatic HRESULT WINAPI controller_probe_GetDeviceData(void *self, DWORD object_size,\n    void *data, DWORD *count, DWORD flags)\n{\n    DWORD requested = count ? *count : 0;\n    HRESULT hr = controller_probe_real_GetDeviceData ?\n        controller_probe_real_GetDeviceData(self, object_size, data, count, flags) : E_FAIL;\n    DWORD returned = count ? *count : 0;\n    DWORD i;\n\n    if ((returned || InterlockedIncrement(&controller_probe_data_call_log_count) <= 24)) {\n        char header[224];\n        wsprintfA(header,\n            "GetDeviceData self=%p obj=%lu requested=%lu returned=%lu flags=%08lx hr=%08lx\\r\\n",\n            self, (unsigned long)object_size, (unsigned long)requested,\n            (unsigned long)returned, (unsigned long)flags, (unsigned long)hr);\n        controller_probe_log(header);\n    }\n\n    if (SUCCEEDED(hr) && data && returned && object_size >= 16) {\n        const BYTE *bytes = (const BYTE *)data;\n        for (i = 0; i < returned && i < 64; i++) {\n            const DIObjectDataV10 *ev = (const DIObjectDataV10 *)(bytes + i * object_size);\n            char buf[256];\n            if (ev->dwOfs >= 48 && ev->dwOfs < 80) {\n                DWORD di_index = ev->dwOfs - 48;\n                wsprintfA(buf,\n                    "BUTTON EVENT self=%p ofs=%lu DI[%lu]/MVP[%lu] data=%08lx %s\\r\\n",\n                    self, (unsigned long)ev->dwOfs, (unsigned long)di_index,\n                    (unsigned long)(di_index + 1), (unsigned long)ev->dwData,\n                    (ev->dwData & 0x80) ? "DOWN" : "UP");\n            } else {\n                wsprintfA(buf,\n                    "object event self=%p ofs=%lu data=%08lx ts=%lu seq=%lu\\r\\n",\n                    self, (unsigned long)ev->dwOfs, (unsigned long)ev->dwData,\n                    (unsigned long)ev->dwTimeStamp, (unsigned long)ev->dwSequence);\n            }\n            controller_probe_log(buf);\n        }\n    }\n    return hr;\n}\n\n''',
"state and buffered event logging",
)

replace_once(
'''    int state_ok, format_ok;\n''',
'''    int state_ok, data_ok, format_ok;\n''',
"patch status locals",
)

replace_once(
'''    state_ok = patch_vtable_slot(vtbl, 9, controller_probe_GetDeviceState,\n        (void **)&controller_probe_real_GetDeviceState);\n    format_ok = patch_vtable_slot(vtbl, 11, controller_probe_SetDataFormat,\n        (void **)&controller_probe_real_SetDataFormat);\n\n    wsprintfA(buf,\n        "controller CreateDevice guid=%08lx-%04x-%04x hooks state=%d format=%d self=%p\\r\\n",\n''',
'''    state_ok = patch_vtable_slot(vtbl, 9, controller_probe_GetDeviceState,\n        (void **)&controller_probe_real_GetDeviceState);\n    data_ok = patch_vtable_slot(vtbl, 10, controller_probe_GetDeviceData,\n        (void **)&controller_probe_real_GetDeviceData);\n    format_ok = patch_vtable_slot(vtbl, 11, controller_probe_SetDataFormat,\n        (void **)&controller_probe_real_SetDataFormat);\n\n    wsprintfA(buf,\n        "controller CreateDevice guid=%08lx-%04x-%04x hooks state=%d data=%d format=%d self=%p\\r\\n",\n''',
"hook GetDeviceData",
)

replace_once(
'''        state_ok, format_ok, device);\n''',
'''        state_ok, data_ok, format_ok, device);\n''',
"hook status args",
)

replace_once(
'''    controller_probe_log("MVP2005 Modern controller runtime probe v9 starting\\r\\n");\n''',
'''    controller_probe_log("MVP2005 Modern controller runtime probe v10 starting\\r\\n");\n''',
"version banner",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern DirectInput state/buffered controller runtime probe v10")
