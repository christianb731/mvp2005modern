from pathlib import Path

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller complete gameplay v25 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# v25: finish the gameplay layout without disturbing the now-proven controls.
# ---------------------------------------------------------------------------
# v23/v24 are the first stable baseline and are frozen here:
#   A/B/X/Y all correct
#   RB selects pitch 5
#   Start pauses
#   L3 no longer pauses
#
# One previously-problematic logical slot remains extremely useful: slot 2 has
# repeatedly and consistently opened MVP's manager/bullpen/dugout menu. Physical
# Back/View is currently suppressed during gameplay and therefore available.
# Route Back -> slot 2 and deliberately turn the old bug into a stable binding.
#
# Keep the native trigger axis untouched. The generated controller.cfg already
# describes L2=axis-3 and R2=axis+3, and the diagnostic log proves native XInput
# LT reaches the negative extreme while RT reaches the positive extreme. This is
# the original MVP control model:
#   LT/L2 + base = normal pickoff (the on-screen PICK function)
#   LB/L1 + base = quick pickoff
#   RT/R2 = relay/cutoff and original alignment/bullpen modifier
# Back/View is our explicit modern manager-menu shortcut because slot 2 is the
# only manager-menu input we have proved empirically on this machine.

runtime = replace_once(
    runtime,
    '''                BYTE y = bytes[48 + 4];\n                BYTE rb = bytes[48 + 6];\n\n                /* Empirical gameplay map from the user's successful tests:\n''',
    '''                BYTE y = bytes[48 + 4];\n                BYTE rb = bytes[48 + 6];\n                BYTE back = bytes[48 + 7];\n\n                /* Empirical gameplay map from the user's successful tests:\n''',
    "capture Back/View",
)

runtime = replace_once(
    runtime,
    '''                 *   RB -> slot 7 (slot 7 empirically fired pitch 5 when Back used it)\n                 * Physical Back remains suppressed during gameplay. */\n                bytes[48 + 0] = a;\n                bytes[48 + 1] = b;\n                bytes[48 + 2] = 0;\n                bytes[48 + 3] = x;\n                bytes[48 + 4] = y;\n                bytes[48 + 6] = 0;\n                bytes[48 + 7] = rb;\n''',
    '''                 *   RB -> slot 7 (slot 7 empirically fires pitch 5)\n                 *   Back/View -> slot 2 (slot 2 empirically opens manager menu)\n                 * This intentionally uses the two formerly-problematic slots for\n                 * the exact actions they have repeatedly demonstrated. */\n                bytes[48 + 0] = a;\n                bytes[48 + 1] = b;\n                bytes[48 + 2] = back;\n                bytes[48 + 3] = x;\n                bytes[48 + 4] = y;\n                bytes[48 + 6] = 0;\n                bytes[48 + 7] = rb;\n''',
    "route Back to empirical manager-menu slot",
)

runtime = replace_once(
    runtime,
    'MVP2005 Modern controller diagnostics + empirical hybrid + RB pitch5 v24\\r\\n',
    'MVP2005 Modern controller diagnostics + complete empirical gameplay map v25\\r\\n',
    "diagnostic banner",
)

runtime = replace_once(
    runtime,
    'controller hooks requested; default=F7 empirical gameplay A0/B1/(2 blocked)/X3/Y4, RB->slot7 pitch5, Back suppressed; frontend canonical; F5-F10 diagnostics retained; Ctrl+1..0 B-slot test, Ctrl+F11 clear B-slot, Ctrl+F12 marker',
    'controller hooks requested; default=F7 empirical gameplay A0/B1/Back->2(manager)/X3/Y4, RB->7(pitch5), LT=L2 pick, RT=R2 relay/menu modifier; frontend canonical; F5-F10 diagnostics retained',
    "startup diagnostic text",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern complete empirical gameplay controller map v25")
