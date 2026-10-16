from pathlib import Path
import re

LAUNCHER = Path("src/launcher.c")
text = LAUNCHER.read_text(encoding="utf-8")


def replace_regex_once(pattern: str, replacement: str, label: str) -> None:
    global text
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"modern launcher v3 {label}: expected exactly one match, found {count}")
    text = updated


# v0.2 used zero-byte VP6 placeholders, which proved unsafe on the verified
# modern compatibility stack. v0.3 keeps the user's original movie files intact
# and lets the injected runtime disable MVP's own ENABLE_FRONTEND_MOVIES flag.
# This routine also migrates a v0.2 test install by restoring any backups created
# under MVP2005Modern.Backup\\intro before launch.
replace_regex_once(
    r'''static int write_empty_file\(const char \*path\)\n\{.*?\n\}\n\nstatic int apply_intro_setting\(HWND hwnd, const char \*game_dir, int skip\)\n\{.*?\n\}\n''',
    r'''static int apply_intro_setting(HWND hwnd, const char *game_dir, int skip)
{
    const char *names[] = {"easports.vp6", "mvpintro.vp6"};
    char movies_dir[MAX_PATH];
    char backup_dir[MAX_PATH];
    char original[MAX_PATH];
    char backup[MAX_PATH];
    int i;
    (void)skip;

    join_path(movies_dir, sizeof(movies_dir), game_dir, "data\\frontend\\movies");
    if (!ensure_backup_subdir(game_dir, "intro", backup_dir, sizeof(backup_dir))) {
        MessageBoxA(hwnd, "Could not access the MVP2005Modern.Backup folder.",
            "MVP Baseball 2005 Modern", MB_ICONERROR);
        return 0;
    }

    for (i = 0; i < 2; i++) {
        join_path(original, sizeof(original), movies_dir, names[i]);
        join_path(backup, sizeof(backup), backup_dir, names[i]);
        if (file_exists(backup)) {
            if (!CopyFileA(backup, original, FALSE)) {
                MessageBoxA(hwnd,
                    "Could not restore an intro movie backed up by launcher v0.2.",
                    "MVP Baseball 2005 Modern", MB_ICONERROR);
                return 0;
            }
        }
    }

    /* No movie files are modified in v0.3. The runtime reads [Modern]
     * SkipIntro and disables MVP's internal ENABLE_FRONTEND_MOVIES setting. */
    return 1;
}
''',
    "replace file-based intro skip",
)

text = text.replace(
    '"Skip EA Sports / MVP intro videos"',
    '"Skip EA Sports / MVP intro videos (safe runtime method)"',
    1,
)

LAUNCHER.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern launcher intro migration v3")
