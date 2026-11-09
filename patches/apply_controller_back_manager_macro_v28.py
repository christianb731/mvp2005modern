from pathlib import Path

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller Back manager macro v28 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# v28: freeze the proven v27 gameplay layout. The new log proves Back and RT are
# both delivered as the exact same logical R2 button (slot 12), while RT works as
# relay in the field. Back therefore is not an input-translation problem: tapping
# R2 by itself simply does not enter the pitching manager/bullpen menu. MVP's
# documented control is R2 + D-pad left/right. Make modern Back a one-button macro
# for that chord while leaving physical RT as ordinary R2/cutoff.
#
# On a Back press we synthesize R2 + one D-pad LEFT pulse for 180 ms. This is long
# enough to survive polling and short enough to behave as one menu step. The pulse
# continues briefly after a quick tap, so the user does not have to hold Back.
# LT remains the original L2/normal-pickoff modifier on slot 11; tapping LT alone
# is intentionally a no-op. It is only meaningful as LT + B/Y/X with a runner on.

runtime = replace_once(
    runtime,
    '''                bytes[48 + 11] = lt_virtual;\n                bytes[48 + 12] = (rt_virtual || back) ? 0x80 : 0;\n                ((LONG *)bytes)[2] = 32767;\n''',
    '''                bytes[48 + 11] = lt_virtual;\n                bytes[48 + 12] = rt_virtual ? 0x80 : 0;\n                ((LONG *)bytes)[2] = 32767;\n\n                /* Back/View is a direct manager-menu shortcut. MVP's R2 control\n                 * is contextual: the bullpen/dugout/alignment strip is entered by\n                 * holding R2 and using D-pad left/right. A plain R2 tap therefore\n                 * looks like \"nothing\" while pitching. Turn one Back press into\n                 * a short R2 + D-pad-left chord, while physical RT remains an\n                 * ordinary R2/cutoff input. */\n                {\n                    static int back_was_down;\n                    static DWORD back_menu_until;\n                    DWORD now = GetTickCount();\n                    int back_down = back != 0;\n                    if (back_down && !back_was_down)\n                        back_menu_until = now + 180;\n                    back_was_down = back_down;\n                    if (back_menu_until && (LONG)(back_menu_until - now) > 0) {\n                        bytes[48 + 12] = 0x80;\n                        ((DWORD *)(bytes + 32))[0] = 27000; /* D-pad left */\n                    } else if (back_menu_until) {\n                        back_menu_until = 0;\n                    }\n                }\n''',
    "Back one-button manager chord",
)

runtime = replace_once(
    runtime,
    'MVP2005 Modern controller diagnostics + discrete L2/R2 + LB cutoff v27\\r\\n',
    'MVP2005 Modern controller diagnostics + Back manager shortcut v28\\r\\n',
    "diagnostic banner",
)

runtime = replace_once(
    runtime,
    'controller hooks requested; stable A0/B1/X3/Y4 RB->7; LB->slot5 relay/cutoff, LT->slot11 L2, RT/Back->slot12 R2; trigger axis neutral; Start/L3 frozen',
    'controller hooks requested; stable A0/B1/X3/Y4 RB->7; LB->slot5, LT->slot11 L2 combo, RT->slot12 R2/cutoff, Back=R2+Dpad-left manager shortcut; Start/L3 frozen',
    "startup diagnostic text",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern one-button Back manager-menu shortcut v28")
