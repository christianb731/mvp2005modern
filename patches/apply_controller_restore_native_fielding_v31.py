from pathlib import Path

RUNTIME = Path("src/runtime.c")
CONTROLLER = Path("src/controller_config.c")
runtime = RUNTIME.read_text(encoding="utf-8")
controller = CONTROLLER.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller native fielding v31 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# v31: correct the two fielding assumptions using the user's physical MVP 2004
# control-summary evidence and the current generated controller profile.
#
# The photographed PC control summary says Change Fielder = button 5. On the
# pictured Dual-Action/PS2-style numbering, 5 is L1/LB; L2/LT is button 7.
# Therefore v30's LT -> button-5 alias was based on a misread of the diagram.
# Remove it. LB remains the native button-5 source and controller.cfg already
# binds VPAD_FIELD_SWITCH to button 5.
#
# v27 had also moved relay/cutoff from R2 to L1 based on an earlier recollection.
# The user has now corrected that RT was NOT actually relaying. Restore both
# relay and cutoff actions to the profile's R2 binding. In the current modern
# 12-button profile R2 is logical button 12, which physical RT already emits.
# Back/View remains a plain second R2 source (no macro).

controller = replace_once(
    controller,
    '    write_binding(file, "VPAD_FIELD_RELAY_THROW", l1);\n',
    '    write_binding(file, "VPAD_FIELD_RELAY_THROW", r2);\n',
    "restore relay to R2",
)
controller = replace_once(
    controller,
    '    write_binding(file, "VPAD_FIELD_CUTOFF_THROW", l1);\n',
    '    write_binding(file, "VPAD_FIELD_CUTOFF_THROW", r2);\n',
    "restore cutoff to R2",
)
CONTROLLER.write_text(controller, encoding="utf-8")

runtime = replace_once(
    runtime,
    '''                /* MVP's control summary assigns Change Fielder to button 5.\n                 * Route LT to that already-proven logical slot instead of trying\n                 * to emulate a separate L2/button-11 function. LB remains another\n                 * source for the same native button-5 action. */\n                if (lt_virtual) bytes[48 + 5] = 0x80;\n                bytes[48 + 11] = 0;\n                bytes[48 + 12] = (rt_virtual || back) ? 0x80 : 0;\n                ((LONG *)bytes)[2] = 32767;\n''',
    '''                /* Physical control-summary numbering: button 5 is L1/LB,\n                 * not L2/LT. Keep LT out of the proven gameplay map. LB remains\n                 * the native field-switch source. RT/Back remain R2 (button 12),\n                 * now restored in controller.cfg as relay/cutoff. */\n                bytes[48 + 11] = 0;\n                bytes[48 + 12] = (rt_virtual || back) ? 0x80 : 0;\n                ((LONG *)bytes)[2] = 32767;\n''',
    "remove incorrect LT field-switch alias",
)

runtime = replace_once(
    runtime,
    'MVP2005 Modern controller diagnostics + LT field-switch layout v30\\r\\n',
    'MVP2005 Modern controller diagnostics + native fielding controls v31\\r\\n',
    "diagnostic banner",
)

runtime = replace_once(
    runtime,
    'controller hooks requested; stable A0/B1/X3/Y4 RB->7; LB and LT -> slot5 native field-switch/context action, RT->slot12 R2/cutoff, Back=plain R2 alias; Start/L3 frozen',
    'controller hooks requested; stable A0/B1/X3/Y4 RB->7; LB->slot5 native field switch, RT/Back->slot12 native R2 relay/cutoff, LT unused; Start/L3 frozen',
    "startup diagnostic text",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern native LB field-switch + R2 relay/cutoff v31")
