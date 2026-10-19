from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"texture packs v55 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


def replace_regex_once(pattern: str, replacement: str, label: str) -> None:
    global text
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"texture packs v55 {label}: expected exactly one match, found {count}")
    text = updated


# v0.55 keeps v0.54's content-addressed DDS loader and adds one deliberately
# simple user-facing abstraction: a named active texture pack. We do not build
# a general mod manager or attempt archive/geometry merging. A pack is only a
# directory of stock-content-ID DDS replacements, so game files and UV layouts
# remain untouched.

replace_once(
    'static int texmod_min_dimension = 64;\n',
    'static int texmod_min_dimension = 64;\nstatic char texmod_active_pack[64];\n',
    'active-pack global',
)

replace_regex_once(
    r'''static void texmod_load_config\(void\)\n\{.*?\n\}\n\n(?=static int texmod_get_root)''',
    r'''static int texmod_pack_name_valid(const char *name)
{
    const unsigned char *p = (const unsigned char *)name;
    if (!name || !name[0]) return 1;
    if (lstrlenA(name) >= (int)sizeof(texmod_active_pack)) return 0;
    if (lstrcmpA(name, ".") == 0 || lstrcmpA(name, "..") == 0) return 0;
    while (*p) {
        if (*p == '\\' || *p == '/' || *p == ':' || *p == '*' || *p == '?' ||
            *p == '"' || *p == '<' || *p == '>' || *p == '|') return 0;
        if (*p < 32) return 0;
        p++;
    }
    return 1;
}

static void texmod_load_config(void)
{
    char path[MAX_PATH];
    char pack[64];
    int min_dim;

    if (InterlockedCompareExchange(&texmod_config_loaded, 1, 0) != 0)
        return;

    texmod_active_pack[0] = 0;
    pack[0] = 0;
    if (get_module_dir(path, sizeof(path)) &&
        append_path(path, sizeof(path), "mvp2005fix.ini")) {
        texmod_enabled = GetPrivateProfileIntA("TextureMods", "Enabled", 1, path) ? 1 : 0;
        texmod_catalog = GetPrivateProfileIntA("TextureMods", "Catalog", 1, path) ? 1 : 0;
        texmod_dump = GetPrivateProfileIntA("TextureMods", "DumpTextures", 0, path) ? 1 : 0;
        min_dim = GetPrivateProfileIntA("TextureMods", "MinDimension", 64, path);
        GetPrivateProfileStringA("TextureMods", "ActivePack", "", pack,
            (DWORD)sizeof(pack), path);
        if (min_dim < 1) min_dim = 1;
        if (min_dim > 4096) min_dim = 4096;
        texmod_min_dimension = min_dim;
    }

    if (pack[0]) {
        if (texmod_pack_name_valid(pack))
            lstrcpynA(texmod_active_pack, pack, sizeof(texmod_active_pack));
        else
            texmod_logf("PACK_REJECT name=%s reason=invalid_name", pack);
    }

    texmod_logf("MVP2005 Modern v0.55 named texture packs");
    texmod_logf("CONFIG enabled=%d catalog=%d dump=%d min_dimension=%d active_pack=%s replacement_format=DDS",
        texmod_enabled, texmod_catalog, texmod_dump, texmod_min_dimension,
        texmod_active_pack[0] ? texmod_active_pack : "<none>");
}

''',
    'config + pack validation',
)

root_marker = '''static int texmod_level_layout(DWORD format, UINT width, UINT height,\n'''
if text.count(root_marker) != 1:
    raise SystemExit(f"texture packs v55 root marker: expected one match, found {text.count(root_marker)}")

path_helpers = r'''static int texmod_append_dds_name(char *path, size_t path_size, const char *id)
{
    if (!path || !id || !id[0]) return 0;
    if (!append_path(path, path_size, id)) return 0;
    if (lstrlenA(path) + 4 >= (int)path_size) return 0;
    lstrcatA(path, ".dds");
    return 1;
}

static int texmod_build_replacement_path(char *path, size_t path_size,
    const char *id, char *source, size_t source_size)
{
    char dir[MAX_PATH];

    if (!path || path_size == 0 || !id) return 0;
    path[0] = 0;
    if (source && source_size) source[0] = 0;

    /* One named pack is intentionally supported in v0.55. This keeps conflict
       semantics obvious while the runtime replacement layer is still preview. */
    if (texmod_active_pack[0]) {
        if (texmod_get_root(dir, sizeof(dir), "Packs", 1) &&
            append_path(dir, sizeof(dir), texmod_active_pack)) {
            CreateDirectoryA(dir, NULL);
            if (append_path(dir, sizeof(dir), "Textures")) {
                CreateDirectoryA(dir, NULL);
                lstrcpynA(path, dir, (int)path_size);
                if (texmod_append_dds_name(path, path_size, id) &&
                    GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES) {
                    if (source && source_size)
                        _snprintf(source, source_size - 1, "pack:%s", texmod_active_pack);
                    if (source && source_size) source[source_size - 1] = 0;
                    return 1;
                }
            }
        }
    }

    /* Retain the flat v0.54 folder as a developer/legacy fallback. */
    if (!texmod_get_root(dir, sizeof(dir), "Replacements", 1)) return 0;
    lstrcpynA(path, dir, (int)path_size);
    if (!texmod_append_dds_name(path, path_size, id)) return 0;
    if (GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) return 0;
    if (source && source_size) lstrcpynA(source, "legacy:Replacements", (int)source_size);
    return 1;
}

'''
text = text.replace(root_marker, path_helpers + root_marker, 1)

replace_once(
'''    char path[MAX_PATH];
    char id[96];
    HANDLE file;
''',
'''    char path[MAX_PATH];
    char id[96];
    char source[96];
    HANDLE file;
''',
    'replacement local source label',
)

replace_once(
'''    texmod_make_id(rec, id, sizeof(id));
    if (!texmod_get_root(dir, sizeof(dir), "Replacements", 1)) return 0;
    lstrcpynA(path, dir, sizeof(path));
    if (!append_path(path, sizeof(path), id)) return 0;
    if (lstrlenA(path) + 4 >= (int)sizeof(path)) return 0;
    lstrcatA(path, ".dds");

    file = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
''',
'''    texmod_make_id(rec, id, sizeof(id));
    if (!texmod_build_replacement_path(path, sizeof(path), id, source, sizeof(source)))
        return 0;

    file = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
''',
    'pack-aware replacement lookup',
)

replace_once(
'''    texmod_logf("REPLACE_OK id=%s original=%ux%u/%s replacement=%ux%u/%s levels=%u",
        id, rec->width, rec->height, gfx_format_name(rec->format),
        width, height, gfx_format_name(format), levels);
''',
'''    texmod_logf("REPLACE_OK id=%s source=%s original=%ux%u/%s replacement=%ux%u/%s levels=%u",
        id, source[0] ? source : "unknown", rec->width, rec->height,
        gfx_format_name(rec->format), width, height, gfx_format_name(format), levels);
''',
    'replacement source diagnostics',
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern named texture packs v55")
