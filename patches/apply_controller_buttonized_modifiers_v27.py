from pathlib import Path

RUNTIME = Path("src/runtime.c")
CONTROLLER = Path("src/controller_config.c")
runtime = RUNTIME.read_text(encoding="utf-8")
controller = CONTROLLER.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller buttonized modifiers v27 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# v27: keep every proven v24-v26 control exactly where it is, but stop asking
# MVP to understand the modern pad's trigger axis as L2/R2.  The user's v26 log
# proves LT and LB+face are reaching the game simultaneously, yet MVP does not
# treat LT as its L2 modifier.  Likewise Back->R2 axis is reaching the game but
# does not expose the bullpen/manager menu.  Use discrete logical buttons for the
# two trigger modifiers, matching old 12-button DirectInput-era MVP profiles.
#
# Logical slots 11/12 are otherwise unused by the stable layout:
#   LT          -> slot 11 -> VPAD L2
#   RT or Back  -> slot 12 -> VPAD R2
# The real trigger axis is neutralized during gameplay so there is only one
# interpretation path.  Face buttons, RB pitch 5, Start, L3 and sticks are frozen.
#
# The user also recalled LB as the cutoff/relay control.  A long-standing MVP PC
# controller profile maps relay to button 5, which is our working LB slot.  Bind
# both relay and cutoff directly to LB while retaining its existing contextual
# field-switch/advance-all role.

controller = replace_once(
    controller,
    '        (unsigned long)(generic_layout ? (buttons ? buttons : 12) : 10),\n',
    '        (unsigned long)(generic_layout ? (buttons ? buttons : 12) : 12),\n',
    "advertise 12 logical buttons",
)

controller = replace_once(
    controller,
    '    const char *l2 = generic_layout ? "button 7" : "axis- 3";\n'
    '    const char *r2 = generic_layout ? "button 8" : "axis+ 3";\n',
    '    const char *l2 = generic_layout ? "button 7" : "button 11";\n'
    '    const char *r2 = generic_layout ? "button 8" : "button 12";\n',
    "buttonize L2 and R2",
)

controller = replace_once(
    controller,
    '    write_binding(file, "VPAD_FIELD_RELAY_THROW", r2);\n',
    '    write_binding(file, "VPAD_FIELD_RELAY_THROW", l1);\n',
    "LB relay",
)
controller = replace_once(
    controller,
    '    write_binding(file, "VPAD_FIELD_CUTOFF_THROW", r2);\n',
    '    write_binding(file, "VPAD_FIELD_CUTOFF_THROW", l1);\n',
    "LB cutoff",
)

CONTROLLER.write_text(controller, encoding="utf-8")

runtime = replace_once(
    runtime,
    '''                BYTE rb = bytes[48 + 6];\n                BYTE back = bytes[48 + 7];\n\n                /* Empirical gameplay map from the user's successful tests:\n''',
    '''                BYTE rb = bytes[48 + 6];\n                BYTE back = bytes[48 + 7];\n                LONG trigger_axis = ((LONG *)bytes)[2];\n                BYTE lt_virtual = trigger_axis < 16384 ? 0x80 : 0;\n                BYTE rt_virtual = trigger_axis > 49151 ? 0x80 : 0;\n\n                /* Empirical gameplay map from the user's successful tests:\n''',
    "capture trigger directions",
)

runtime = replace_once(
    runtime,
    '''                 *   RB -> slot 7 (slot 7 empirically fires pitch 5)\n                 *   Back/View -> R2 alias via axis+3; never emit the bad slot 2.\n                 * LB remains native L1 so quick pickoff/change fielder/advance-all\n                 * and the pitching modifier combinations keep their original roles. */\n                bytes[48 + 0] = a;\n                bytes[48 + 1] = b;\n                bytes[48 + 2] = 0;\n                bytes[48 + 3] = x;\n                bytes[48 + 4] = y;\n                bytes[48 + 6] = 0;\n                bytes[48 + 7] = rb;\n\n                /* Back/View is a second R2 input in gameplay. controller.cfg maps\n                 * R2 to axis+3. 65407 is the same near-max positive value emitted\n                 * by a fully pressed native RT in the canonical XInput bridge. */\n                if (back) ((LONG *)bytes)[2] = 65407;\n''',
    '''                 *   RB -> slot 7 (slot 7 empirically fires pitch 5)\n                 *   LT -> slot 11, RT/Back -> slot 12.  These are discrete L2/R2\n                 * logical controls; the trigger axis is neutralized below.\n                 * LB stays slot 5 and controller.cfg directly binds relay/cutoff\n                 * to that already-proven physical control. */\n                bytes[48 + 0] = a;\n                bytes[48 + 1] = b;\n                bytes[48 + 2] = 0;\n                bytes[48 + 3] = x;\n                bytes[48 + 4] = y;\n                bytes[48 + 6] = 0;\n                bytes[48 + 7] = rb;\n                bytes[48 + 11] = lt_virtual;\n                bytes[48 + 12] = (rt_virtual || back) ? 0x80 : 0;\n                ((LONG *)bytes)[2] = 32767;\n''',
    "discrete L2/R2 gameplay map",
)

runtime = replace_once(
    runtime,
    'MVP2005 Modern controller diagnostics + stable gameplay + Back/R2 alias v26\\r\\n',
    'MVP2005 Modern controller diagnostics + discrete L2/R2 + LB cutoff v27\\r\\n',
    "diagnostic banner",
)

runtime = replace_once(
    runtime,
    'controller hooks requested; stable gameplay A0/B1/X3/Y4, RB->7 pitch5, Start fixed; LB=L1 contextual, LT=L2 normal-pick modifier, RT=R2 cutoff/menu, Back=second R2; bad slot2 disabled',
    'controller hooks requested; stable A0/B1/X3/Y4 RB->7; LB->slot5 relay/cutoff, LT->slot11 L2, RT/Back->slot12 R2; trigger axis neutral; Start/L3 frozen',
    "startup diagnostic text",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern discrete trigger buttons + LB cutoff v27")
