from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# Do not change the outer window until Direct3D has accepted the windowed device.
replace_once(
'''    pp->Windowed = TRUE;
    pp->FullScreen_RefreshRateInHz = 0;

    make_borderless_window(hwnd);
    wsprintfA(buf, "borderless CreateDevice %lux%lu fmt=%lu hwnd=%p\\n",
''',
'''    pp->Windowed = TRUE;
    pp->FullScreen_RefreshRateInHz = 0;

    wsprintfA(buf, "borderless CreateDevice try %lux%lu fmt=%lu hwnd=%p swap=%lu flags=%08lx interval=%lu\\n",
''',
"defer CreateDevice window styling",
)

replace_once(
'''        (unsigned long)pp->BackBufferWidth,
        (unsigned long)pp->BackBufferHeight,
        (unsigned long)pp->BackBufferFormat, hwnd);
    log_line(buf);
}

static void prepare_borderless_reset''',
'''        (unsigned long)pp->BackBufferWidth,
        (unsigned long)pp->BackBufferHeight,
        (unsigned long)pp->BackBufferFormat, hwnd,
        (unsigned long)pp->SwapEffect,
        (unsigned long)pp->Flags,
        (unsigned long)pp->FullScreen_PresentationInterval);
    log_line(buf);
}

static void prepare_borderless_reset''',
"expand CreateDevice diagnostics",
)

replace_once(
'''    pp->Windowed = TRUE;
    pp->FullScreen_RefreshRateInHz = 0;

    make_borderless_window(hwnd);
    wsprintfA(buf, "borderless Reset %lux%lu fmt=%lu hwnd=%p\\n",
''',
'''    pp->Windowed = TRUE;
    pp->FullScreen_RefreshRateInHz = 0;

    wsprintfA(buf, "borderless Reset try %lux%lu fmt=%lu hwnd=%p swap=%lu flags=%08lx interval=%lu\\n",
''',
"defer Reset window styling",
)

replace_once(
'''        (unsigned long)pp->BackBufferWidth,
        (unsigned long)pp->BackBufferHeight,
        (unsigned long)pp->BackBufferFormat, hwnd);
    log_line(buf);
}

static HRESULT WINAPI fake_Reset(void *self, void *presentation_parameters)
{
    HRESULT hr;
    prepare_borderless_reset(presentation_parameters);
    hr = real_Reset ? real_Reset(self, presentation_parameters) : E_FAIL;
    if (SUCCEEDED(hr) && borderless_enabled) make_borderless_window(borderless_window);
    return hr;
}
''',
'''        (unsigned long)pp->BackBufferWidth,
        (unsigned long)pp->BackBufferHeight,
        (unsigned long)pp->BackBufferFormat, hwnd,
        (unsigned long)pp->SwapEffect,
        (unsigned long)pp->Flags,
        (unsigned long)pp->FullScreen_PresentationInterval);
    log_line(buf);
}

static HRESULT WINAPI fake_Reset(void *self, void *presentation_parameters)
{
    HRESULT hr;
    D3DPresentParameters8Local original;
    int have_original = 0;
    char buf[192];

    if (borderless_enabled && presentation_parameters) {
        memcpy(&original, presentation_parameters, sizeof(original));
        have_original = 1;
        prepare_borderless_reset(presentation_parameters);
    }

    hr = real_Reset ? real_Reset(self, presentation_parameters) : E_FAIL;

    if (FAILED(hr) && have_original) {
        wsprintfA(buf, "borderless Reset failed hr=%08lx; retrying original fullscreen parameters\\n",
            (unsigned long)hr);
        log_line(buf);
        memcpy(presentation_parameters, &original, sizeof(original));
        borderless_enabled = 0;
        hr = real_Reset ? real_Reset(self, presentation_parameters) : E_FAIL;
        wsprintfA(buf, "fullscreen Reset fallback hr=%08lx\\n", (unsigned long)hr);
        log_line(buf);
    }

    if (SUCCEEDED(hr) && borderless_enabled) make_borderless_window(borderless_window);
    return hr;
}
''',
"Reset fail-safe fallback",
)

replace_once(
'''{
    HRESULT hr;

    prepare_borderless_create(self, adapter, focus_window, presentation_parameters);
    hr = real_CreateDevice(self, adapter, device_type, focus_window, behavior_flags,
        presentation_parameters, returned_device);

    EnterCriticalSection(&vtable_lock);
''',
'''{
    HRESULT hr;
    D3DPresentParameters8Local original;
    int have_original = 0;
    char buf[224];

    if (borderless_enabled && presentation_parameters) {
        D3DPresentParameters8Local *pp = (D3DPresentParameters8Local *)presentation_parameters;
        memcpy(&original, pp, sizeof(original));
        have_original = 1;
        wsprintfA(buf, "original CreateDevice %lux%lu fmt=%lu windowed=%d swap=%lu flags=%08lx refresh=%lu interval=%lu hwnd=%p\\n",
            (unsigned long)pp->BackBufferWidth,
            (unsigned long)pp->BackBufferHeight,
            (unsigned long)pp->BackBufferFormat,
            pp->Windowed ? 1 : 0,
            (unsigned long)pp->SwapEffect,
            (unsigned long)pp->Flags,
            (unsigned long)pp->FullScreen_RefreshRateInHz,
            (unsigned long)pp->FullScreen_PresentationInterval,
            pp->hDeviceWindow ? pp->hDeviceWindow : focus_window);
        log_line(buf);
        prepare_borderless_create(self, adapter, focus_window, presentation_parameters);
    }

    hr = real_CreateDevice(self, adapter, device_type, focus_window, behavior_flags,
        presentation_parameters, returned_device);

    if (FAILED(hr) && have_original) {
        wsprintfA(buf, "borderless CreateDevice failed hr=%08lx; retrying original fullscreen parameters\\n",
            (unsigned long)hr);
        log_line(buf);
        memcpy(presentation_parameters, &original, sizeof(original));
        borderless_enabled = 0;
        hr = real_CreateDevice(self, adapter, device_type, focus_window, behavior_flags,
            presentation_parameters, returned_device);
        wsprintfA(buf, "fullscreen CreateDevice fallback hr=%08lx\\n", (unsigned long)hr);
        log_line(buf);
    } else if (SUCCEEDED(hr) && borderless_enabled) {
        log_line("borderless CreateDevice succeeded\\n");
        make_borderless_window(borderless_window);
    }

    EnterCriticalSection(&vtable_lock);
''',
"CreateDevice fail-safe fallback",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern borderless fail-safe diagnostics")
