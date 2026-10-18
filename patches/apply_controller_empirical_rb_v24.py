from pathlib import Path

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller empirical RB v24 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# v23 finally produced a stable face-button map and fixed Start/L3. Keep that
# exact mapping. The remaining pitching control is pitch 5.
#
# The user's earlier tests gave us a direct empirical observation that gameplay
# slot 7 fires pitch 5 (Back/View was doing it there). v23 suppresses Back during
# gameplay, so slot 7 is now free. Route physical RB to that proven pitch-5 slot
# instead of continuing to assume the controller.cfg button number is the same as
# the slot MVP actually consumes.
#
# LB is intentionally left untouched. The v23 log shows LB alone at slot 5, while
# the intentional-hit-batter slot 9 appears when L3 is physically pressed. Do not
# change LB based on the apparent double-tap behavior until there is evidence that
# LB alone is producing slot 9.

runtime = replace_once(
    runtime,
    '''                BYTE x = bytes[48 + 3];\n                BYTE y = bytes[48 + 4];\n\n                /* Empirical gameplay map from the user's successful tests:\n''',
    '''                BYTE x = bytes[48 + 3];\n                BYTE y = bytes[48 + 4];\n                BYTE rb = bytes[48 + 6];\n\n                /* Empirical gameplay map from the user's successful tests:\n''',
    "capture RB",
)

runtime = replace_once(
    runtime,
    '''                 *   X slot 3 (worked in F7)\n                 *   Y slot 4 (worked in F7)\n                 * Back/slot 7 is suppressed because it consistently fires pitch 5. */\n                bytes[48 + 0] = a;\n                bytes[48 + 1] = b;\n                bytes[48 + 2] = 0;\n                bytes[48 + 3] = x;\n                bytes[48 + 4] = y;\n                bytes[48 + 7] = 0;\n''',
    '''                 *   X slot 3 (worked in F7)\n                 *   Y slot 4 (worked in F7)\n                 *   RB -> slot 7 (slot 7 empirically fired pitch 5 when Back used it)\n                 * Physical Back remains suppressed during gameplay. */\n                bytes[48 + 0] = a;\n                bytes[48 + 1] = b;\n                bytes[48 + 2] = 0;\n                bytes[48 + 3] = x;\n                bytes[48 + 4] = y;\n                bytes[48 + 6] = 0;\n                bytes[48 + 7] = rb;\n''',
    "route RB to empirical pitch5 slot",
)

runtime = replace_once(
    runtime,
    'MVP2005 Modern controller diagnostics + empirical hybrid gameplay map v23\\r\\n',
    'MVP2005 Modern controller diagnostics + empirical hybrid + RB pitch5 v24\\r\\n',
    "diagnostic banner",
)

runtime = replace_once(
    runtime,
    'controller hooks requested; default=F7 with empirical gameplay map A0/B1/(2 blocked)/X3/Y4 and Back suppressed; frontend stays canonical; F5-F10 diagnostics retained; Ctrl+1..0 B-slot test, Ctrl+F11 clear B-slot, Ctrl+F12 marker',
    'controller hooks requested; default=F7 empirical gameplay A0/B1/(2 blocked)/X3/Y4, RB->slot7 pitch5, Back suppressed; frontend canonical; F5-F10 diagnostics retained; Ctrl+1..0 B-slot test, Ctrl+F11 clear B-slot, Ctrl+F12 marker',
    "startup diagnostic text",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern empirical RB -> pitch 5 mapping v24")
