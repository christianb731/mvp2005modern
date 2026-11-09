from pathlib import Path

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller LT field-switch v30 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# v30: use the user's MVP control-summary evidence instead of leaving LT unused.
# The game maps "Change fielder" to control/button 5.  Our empirical runtime has
# already proven logical slot 5 is a stable working control (currently fed by LB),
# and the user's v27 test confirmed that same slot produces the expected contextual
# pickoff behavior while pitching.  Therefore make physical LT feed that exact same
# logical slot 5 in gameplay.
#
# This is intentionally NOT another L2 emulation.  Button 11 is suppressed.  LT is
# simply a second physical source for the known-good button-5 action, so it should
# change fielders in the field and inherit MVP's native contextual use of button 5.
# All proven face buttons, RB pitch 5, Start, L3, RT relay/cutoff and Back handling
# remain untouched.

runtime = replace_once(
    runtime,
    '''                /* LT is intentionally unused: LT+base was verified at the\n                 * input layer but MVP did not respond, while LB already supplies\n                 * the useful pickoff behavior. Back is a plain R2 alias only --\n                 * no synthesized D-pad/menu macro. */\n                bytes[48 + 11] = 0;\n                bytes[48 + 12] = (rt_virtual || back) ? 0x80 : 0;\n                ((LONG *)bytes)[2] = 32767;\n''',
    '''                /* MVP's control summary assigns Change Fielder to button 5.\n                 * Route LT to that already-proven logical slot instead of trying\n                 * to emulate a separate L2/button-11 function. LB remains another\n                 * source for the same native button-5 action. */\n                if (lt_virtual) bytes[48 + 5] = 0x80;\n                bytes[48 + 11] = 0;\n                bytes[48 + 12] = (rt_virtual || back) ? 0x80 : 0;\n                ((LONG *)bytes)[2] = 32767;\n''',
    "route LT to button-5 field switch",
)

runtime = replace_once(
    runtime,
    'MVP2005 Modern controller diagnostics + stable no-macro layout v29\\r\\n',
    'MVP2005 Modern controller diagnostics + LT field-switch layout v30\\r\\n',
    "diagnostic banner",
)

runtime = replace_once(
    runtime,
    'controller hooks requested; stable A0/B1/X3/Y4 RB->7; LB working pickoff/cutoff mapping, RT->slot12 R2/cutoff, Back=plain R2 alias (hold + D-pad for manager), LT unused; Start/L3 frozen',
    'controller hooks requested; stable A0/B1/X3/Y4 RB->7; LB and LT -> slot5 native field-switch/context action, RT->slot12 R2/cutoff, Back=plain R2 alias; Start/L3 frozen',
    "startup diagnostic text",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern LT -> button-5 field-switch mapping v30")
