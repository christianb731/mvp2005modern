from pathlib import Path

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller no-macro cleanup v29 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# v29: remove the v28 one-button Back macro completely. The user explicitly does
# not want a synthesized chord. Keep Back as a plain R2 alias only; MVP's manager/
# bullpen interface therefore remains the game's native contextual control:
# hold Back (or RT) + use the D-pad. Back alone is expected to do nothing.
#
# LT + base was tested in v26/v27 and produced no useful in-game action even though
# the diagnostics proved the input reached MVP correctly. LB already provides the
# useful pickoff behavior. Stop spending a physical control on an ineffective L2
# emulation and suppress LT in gameplay for now. This avoids introducing another
# action collision while preserving all confirmed controls.

runtime = replace_once(
    runtime,
    '''                bytes[48 + 11] = lt_virtual;\n                bytes[48 + 12] = rt_virtual ? 0x80 : 0;\n                ((LONG *)bytes)[2] = 32767;\n\n                /* Back/View is a direct manager-menu shortcut. MVP's R2 control\n                 * is contextual: the bullpen/dugout/alignment strip is entered by\n                 * holding R2 and using D-pad left/right. A plain R2 tap therefore\n                 * looks like \"nothing\" while pitching. Turn one Back press into\n                 * a short R2 + D-pad-left chord, while physical RT remains an\n                 * ordinary R2/cutoff input. */\n                {\n                    static int back_was_down;\n                    static DWORD back_menu_until;\n                    DWORD now = GetTickCount();\n                    int back_down = back != 0;\n                    if (back_down && !back_was_down)\n                        back_menu_until = now + 180;\n                    back_was_down = back_down;\n                    if (back_menu_until && (LONG)(back_menu_until - now) > 0) {\n                        bytes[48 + 12] = 0x80;\n                        ((DWORD *)(bytes + 32))[0] = 27000; /* D-pad left */\n                    } else if (back_menu_until) {\n                        back_menu_until = 0;\n                    }\n                }\n''',
    '''                /* LT is intentionally unused: LT+base was verified at the\n                 * input layer but MVP did not respond, while LB already supplies\n                 * the useful pickoff behavior. Back is a plain R2 alias only --\n                 * no synthesized D-pad/menu macro. */\n                bytes[48 + 11] = 0;\n                bytes[48 + 12] = (rt_virtual || back) ? 0x80 : 0;\n                ((LONG *)bytes)[2] = 32767;\n''',
    "remove Back macro and suppress ineffective LT",
)

runtime = replace_once(
    runtime,
    'MVP2005 Modern controller diagnostics + Back manager shortcut v28\\r\\n',
    'MVP2005 Modern controller diagnostics + stable no-macro layout v29\\r\\n',
    "diagnostic banner",
)

runtime = replace_once(
    runtime,
    'controller hooks requested; stable A0/B1/X3/Y4 RB->7; LB->slot5, LT->slot11 L2 combo, RT->slot12 R2/cutoff, Back=R2+Dpad-left manager shortcut; Start/L3 frozen',
    'controller hooks requested; stable A0/B1/X3/Y4 RB->7; LB working pickoff/cutoff mapping, RT->slot12 R2/cutoff, Back=plain R2 alias (hold + D-pad for manager), LT unused; Start/L3 frozen',
    "startup diagnostic text",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern stable no-macro controller cleanup v29")
