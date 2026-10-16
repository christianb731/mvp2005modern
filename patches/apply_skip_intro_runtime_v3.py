from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"skip intro runtime {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
'''static int debug_logging;\n''',
'''static int debug_logging;\nstatic int skip_intro_enabled;\n''',
"config state",
)

replace_once(
'''    save_fix_enabled = GetPrivateProfileIntA("SaveFix", "Enabled", 1, ini) != 0;\n''',
'''    save_fix_enabled = GetPrivateProfileIntA("SaveFix", "Enabled", 1, ini) != 0;\n    skip_intro_enabled = GetPrivateProfileIntA("Modern", "SkipIntro", 0, ini) != 0;\n''',
"read skip setting",
)

marker = '''static BOOL WINAPI fake_GetDiskFreeSpaceExA(\n'''
if text.count(marker) != 1:
    raise SystemExit(f"skip intro runtime helper marker: expected one match, found {text.count(marker)}")

helper = r'''static void patch_frontend_movies_default_in_memory(void)
{
    /*
     * MVP has an internal boolean named ENABLE_FRONTEND_MOVIES. Its video/settings
     * constructor contains this unique sequence (retail patched executable):
     *
     *   mov al,1
     *   xor ecx,ecx
     *   mov [esi+38],al
     *   mov [esi+39],al
     *   mov [esi+3a],al   <- ENABLE_FRONTEND_MOVIES
     *   mov [esi+3c],al ...
     *
     * ECX is intentionally zero at this point. Changing only the ModRM byte of
     * the [esi+3a] assignment from AL to CL initializes the frontend-movies flag
     * to false while leaving every neighboring visual feature enabled. This is
     * safer than replacing VP6 files with zero-byte placeholders, which crashes
     * some modern/wrapper configurations.
     */
    static const BYTE signature[] = {
        0xB0, 0x01, 0x33, 0xC9,
        0x88, 0x46, 0x38,
        0x88, 0x46, 0x39,
        0x88, 0x46, 0x3A,
        0x88, 0x46, 0x3C,
        0x88, 0x46, 0x3D,
        0x88, 0x46, 0x3E,
        0x88, 0x46, 0x3F,
        0x88, 0x46, 0x40
    };
    BYTE *base;
    IMAGE_DOS_HEADER *dos;
    IMAGE_NT_HEADERS *nt;
    IMAGE_SECTION_HEADER *section;
    BYTE *match = NULL;
    DWORD matches = 0;
    DWORD old_protect;
    WORD s;
    DWORD i;

    if (!skip_intro_enabled) return;

    base = (BYTE *)GetModuleHandleA(NULL);
    if (!base) return;
    dos = (IMAGE_DOS_HEADER *)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return;
    nt = (IMAGE_NT_HEADERS *)(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return;

    section = IMAGE_FIRST_SECTION(nt);
    for (s = 0; s < nt->FileHeader.NumberOfSections; s++, section++) {
        DWORD size = section->Misc.VirtualSize;
        BYTE *start;
        if (memcmp(section->Name, ".text\0\0\0", IMAGE_SIZEOF_SHORT_NAME) != 0) continue;
        if (size < sizeof(signature)) continue;
        start = base + section->VirtualAddress;
        for (i = 0; i <= size - sizeof(signature); i++) {
            if (memcmp(start + i, signature, sizeof(signature)) == 0) {
                match = start + i;
                matches++;
            }
        }
    }

    if (matches != 1) {
        log_line(matches ?
            "frontend movie setting signature ambiguous; intro skip skipped\n" :
            "frontend movie setting signature not found; intro skip skipped\n");
        return;
    }

    /* signature+11 is the ModRM byte in 88 46 3A. 46=AL, 4E=CL. */
    if (!VirtualProtect(match + 11, 1, PAGE_EXECUTE_READWRITE, &old_protect)) {
        log_line("frontend movie setting protection change failed\n");
        return;
    }
    match[11] = 0x4E;
    FlushInstructionCache(GetCurrentProcess(), match + 10, 3);
    VirtualProtect(match + 11, 1, old_protect, &old_protect);
    log_line("frontend intro movies disabled through internal setting\n");
}

'''
text = text.replace(marker, helper + marker, 1)

replace_once(
'''    patch_resolution_in_memory();\n''',
'''    patch_resolution_in_memory();\n    patch_frontend_movies_default_in_memory();\n''',
"startup patch call",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied runtime frontend-intro skip v3")
