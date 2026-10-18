from pathlib import Path

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller Back/R2 alias v26 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# v26: keep the proven v24 face/RB/Start layout and correct the remaining
# contextual controls according to MVP's actual control model.
# ---------------------------------------------------------------------------
# v25's Back -> logical slot 2 shortcut was based on a bad inference. The user's
# v25 test showed Back presents BUNT, not the manager/bullpen controls. Retire that
# slot-2 shortcut permanently.
#
# MVP's documented gameplay model is contextual:
#   L1/LB = change fielder; advance all runners; quick-pickoff/pitchout/
#           intentional-action modifier while pitching.
#   L2/LT = normal pickoff modifier (and batting-box movement).
#   R2/RT = cutoff/relay while fielding; hold + D-pad for alignment and
#           bullpen/dugout/manager controls while pitching.
#
# Keep native LT/RT axis synthesis unchanged. Give modern Back/View a useful,
# conflict-free role by making it a second R2 modifier in gameplay: Back no longer
# emits any button slot; instead, while held, it forces the canonical R2 axis
# positive. This means Back + D-pad accesses the same manager/alignment controls
# as RT + D-pad, and Back also works as an alternate cutoff/relay button in the
# field. LB remains L1 rather than being overloaded as cutoff, because doing so
# would collide with field switch, advance-all, quick pickoff, pitchout, HBP, etc.

runtime = replace_once(
    runtime,
    '''                 *   RB -> slot 7 (slot 7 empirically fires pitch 5)\n                 *   Back/View -> slot 2 (slot 2 empirically opens manager menu)\n                 * This intentionally uses the two formerly-problematic slots for\n                 * the exact actions they have repeatedly demonstrated. */\n                bytes[48 + 0] = a;\n                bytes[48 + 1] = b;\n                bytes[48 + 2] = back;\n                bytes[48 + 3] = x;\n                bytes[48 + 4] = y;\n                bytes[48 + 6] = 0;\n                bytes[48 + 7] = rb;\n''',
    '''                 *   RB -> slot 7 (slot 7 empirically fires pitch 5)\n                 *   Back/View -> R2 alias via axis+3; never emit the bad slot 2.\n                 * LB remains native L1 so quick pickoff/change fielder/advance-all\n                 * and the pitching modifier combinations keep their original roles. */\n                bytes[48 + 0] = a;\n                bytes[48 + 1] = b;\n                bytes[48 + 2] = 0;\n                bytes[48 + 3] = x;\n                bytes[48 + 4] = y;\n                bytes[48 + 6] = 0;\n                bytes[48 + 7] = rb;\n\n                /* Back/View is a second R2 input in gameplay. controller.cfg maps\n                 * R2 to axis+3. 65407 is the same near-max positive value emitted\n                 * by a fully pressed native RT in the canonical XInput bridge. */\n                if (back) ((LONG *)bytes)[2] = 65407;\n''',
    "replace bad Back slot with R2 alias",
)

runtime = replace_once(
    runtime,
    'MVP2005 Modern controller diagnostics + complete empirical gameplay map v25\\r\\n',
    'MVP2005 Modern controller diagnostics + stable gameplay + Back/R2 alias v26\\r\\n',
    "diagnostic banner",
)

runtime = replace_once(
    runtime,
    'controller hooks requested; default=F7 empirical gameplay A0/B1/Back->2(manager)/X3/Y4, RB->7(pitch5), LT=L2 pick, RT=R2 relay/menu modifier; frontend canonical; F5-F10 diagnostics retained',
    'controller hooks requested; stable gameplay A0/B1/X3/Y4, RB->7 pitch5, Start fixed; LB=L1 contextual, LT=L2 normal-pick modifier, RT=R2 cutoff/menu, Back=second R2; bad slot2 disabled',
    "startup diagnostic text",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern Back/View -> R2 contextual alias v26")
