# MVP2005 Modern asset tools

## Mod package preview

Put replacement BIG archives in a ZIP using their paths from the game folder, such as `data/frontend/uniforms.big`. With Python 3.11 or later, run this command from the source folder.

```powershell
python tools/mod_preview.py "C:\Mods\uniforms.zip" --game "C:\Games\MVP Baseball 2005"
```

The preview validates each packaged BIG archive and shows which installed files differ, with SHA-256 hashes for both versions. It reads the ZIP in place and leaves the game files untouched. This first version supports existing `.big` files under `data/` and a maximum of 256 MiB per replacement.

### Install and restore on Windows

Close the game before installing or restoring. Keep it closed until the command finishes. Try the package on a separate game copy first.

In the `v0.53-mod-manager` build, extract the full ZIP so the `tools` folder sits beside `MVP2005Modern.exe`. With Python 3.11 or later, Tkinter, and the system Windows Python Launcher installed, select the game's executable in MVP2005 Modern and click **Mods…**. Use **Preview ZIP…** to see which archives will change, then **Install** to apply the package. Use **Restore originals** to roll it back. You can also open the manager directly with `python tools/mod_manager.pyw --game "C:\Games\MVP Baseball 2005"`.

The command-line interface uses the same installer and recovery journal.

```powershell
python tools/mod_install.py --game "C:\Games\MVP Baseball 2005" install "C:\Mods\uniforms.zip"
python tools/mod_install.py --game "C:\Games\MVP Baseball 2005" restore
```

The command-line installer supports one active package. It stages the validated replacements, verifies backups, and records their hashes in `MVP2005Modern.Mods` before changing installed files. It uses Windows file replacement to preserve the destination permissions. Run `restore` after an interrupted operation. If a file has been edited since installation, restore reports the conflicting path and leaves the backups available. BIG validation checks archive structure. In-game compatibility still needs a game test.

## `fsh_tool.py`

`fsh_tool.py` is a dependency-free Python inspector/extractor for EA SHPI/FSH texture containers used by MVP Baseball 2005 and related EA Sports titles.

It currently understands the common PC texture record types:

- `0x60` DXT1
- `0x61` DXT3
- `0x62` DXT5
- `0x6D` A4R4G4B4
- `0x78` R5G6B5
- `0x7B` P8 metadata (palette export is not implemented yet)
- `0x7D` A8R8G8B8
- `0x7E` A1R5G5B5
- `0x7F` R8G8B8

The tool also parses the normal 16-byte SHPI header, 8-byte directory entries, entry geometry fields, extra bytes between the directory and first record, and common `0x69` / `0x70` eTXT attachments.

Most importantly for MVP2005 Modern, supported non-indexed entries are assigned the same content-addressed ID used by the v0.54 runtime texture replacement layer. This makes it possible to map a texture from an FSH file directly to its expected external replacement filename without first discovering the texture through a runtime log.

## Usage

Inspect a file:

```bash
python tools/fsh_tool.py path/to/texture.fsh
```

Print machine-readable metadata:

```bash
python tools/fsh_tool.py path/to/texture.fsh --json
```

Extract supported entries as DDS files:

```bash
python tools/fsh_tool.py path/to/texture.fsh --extract extracted
```

Also emit PNG for supported uncompressed formats:

```bash
python tools/fsh_tool.py path/to/texture.fsh --extract extracted --png
```

Also preserve raw entry payloads:

```bash
python tools/fsh_tool.py path/to/texture.fsh --extract extracted --raw
```

For each supported entry the extractor emits a normal descriptive DDS name and a second DDS copy using the exact MVP2005 Modern runtime ID, for example:

```text
128x128_A8R8G8B8_0123456789abcdef.dds
```

That runtime-named file can be edited/replaced and placed under:

```text
MVP2005Modern.Textures/Replacements/
```

## Current limitations

- Indexed/P8 palette reconstruction is not implemented yet.
- DXT textures are preserved losslessly into DDS rather than decompressed to PNG.
- Mipmap/footer conventions need more samples before the tool should attempt FSH repacking.
- FSH writing/repacking is intentionally deferred until more MVP-specific examples are validated.
- BIG archive support is the next asset-layer target; once BIG contents can be enumerated, FSH source paths can be associated with runtime texture IDs.
