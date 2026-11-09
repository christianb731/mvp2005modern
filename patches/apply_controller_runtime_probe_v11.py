from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller runtime probe v11 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# v10 proved the physical button stream itself is exactly the normal MVP/Xbox
# one-based mapping. The remaining question is whether MVP is polling the same
# named DirectInput device/profile that controller.cfg was generated for. Log the
# actual device identity for every CreateDevice instance and include that identity
# on successful button-state transitions.
replace_once(
'''typedef HRESULT (WINAPI *DISetDataFormatFn)(void *self, const void *format);\ntypedef struct DIObjectDataV10 {\n''',
'''typedef HRESULT (WINAPI *DISetDataFormatFn)(void *self, const void *format);\ntypedef HRESULT (WINAPI *DIGetDeviceInfoFn)(void *self, void *info);\ntypedef struct DIDeviceInstanceLocalV11 {\n    DWORD dwSize;\n    GUID guidInstance;\n    GUID guidProduct;\n    DWORD dwDevType;\n    CHAR tszInstanceName[MAX_PATH];\n    CHAR tszProductName[MAX_PATH];\n    GUID guidFFDriver;\n    WORD wUsagePage;\n    WORD wUsage;\n} DIDeviceInstanceLocalV11;\ntypedef struct DIObjectDataV10 {\n''',
"device info typedefs",
)

replace_once(
'''typedef struct ControllerProbeDevice {\n    void *device;\n    GUID guid;\n    DWORD format_size;\n    DWORD format_objects;\n    DWORD previous_buttons;\n    int previous_valid;\n} ControllerProbeDevice;\n''',
'''typedef struct ControllerProbeDevice {\n    void *device;\n    GUID guid;\n    DWORD format_size;\n    DWORD format_objects;\n    DWORD previous_buttons;\n    int previous_valid;\n    char instance_name[MAX_PATH];\n    char product_name[MAX_PATH];\n} ControllerProbeDevice;\n''',
"device identity storage",
)

replace_once(
'''    pos = snprintf(buf, sizeof(buf), "buttons size=%lu pressed=",\n        (unsigned long)data_size);\n''',
'''    pos = snprintf(buf, sizeof(buf),\n        "buttons self=%p instance=\\\"%s\\\" product=\\\"%s\\\" size=%lu pressed=",\n        slot->device, slot->instance_name[0] ? slot->instance_name : "?",\n        slot->product_name[0] ? slot->product_name : "?",\n        (unsigned long)data_size);\n''',
"button identity prefix",
)

replace_once(
'''    slot = controller_probe_add(device, guid);\n    if (!slot) return;\n    vtbl = *(void ***)device;\n    if (!vtbl) return;\n\n    state_ok = patch_vtable_slot(vtbl, 9, controller_probe_GetDeviceState,\n''',
'''    slot = controller_probe_add(device, guid);\n    if (!slot) return;\n    vtbl = *(void ***)device;\n    if (!vtbl) return;\n\n    {\n        DIGetDeviceInfoFn get_info = NULL;\n        DIDeviceInstanceLocalV11 info;\n        HRESULT info_hr = E_FAIL;\n        char info_buf[768];\n        if (vtbl[15]) memcpy(&get_info, &vtbl[15], sizeof(get_info));\n        ZeroMemory(&info, sizeof(info));\n        info.dwSize = sizeof(info);\n        if (get_info) info_hr = get_info(device, &info);\n        if (SUCCEEDED(info_hr)) {\n            lstrcpynA(slot->instance_name, info.tszInstanceName, sizeof(slot->instance_name));\n            lstrcpynA(slot->product_name, info.tszProductName, sizeof(slot->product_name));\n        }\n        snprintf(info_buf, sizeof(info_buf),\n            "controller identity self=%p guid=%08lx-%04x-%04x infohr=%08lx instance=\\\"%s\\\" product=\\\"%s\\\" devtype=%08lx\\r\\n",\n            device, (unsigned long)guid->Data1, (unsigned int)guid->Data2,\n            (unsigned int)guid->Data3, (unsigned long)info_hr,\n            slot->instance_name[0] ? slot->instance_name : "?",\n            slot->product_name[0] ? slot->product_name : "?",\n            (unsigned long)(SUCCEEDED(info_hr) ? info.dwDevType : 0));\n        controller_probe_log(info_buf);\n    }\n\n    state_ok = patch_vtable_slot(vtbl, 9, controller_probe_GetDeviceState,\n''',
"query device identity",
)

replace_once(
'''    controller_probe_log("MVP2005 Modern controller runtime probe v10 starting\\r\\n");\n''',
'''    controller_probe_log("MVP2005 Modern controller runtime probe v11 starting\\r\\n");\n''',
"version banner",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern active DirectInput device identity probe v11")
