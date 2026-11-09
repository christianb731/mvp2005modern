"""Include the simulated input source in the isolated menu test build."""

from pathlib import Path


runtime = Path("src/runtime.c")
source = runtime.read_text(encoding="utf-8")
anchor = '#include "menu_control_trace.inc"'
if source.count(anchor) != 1:
    raise SystemExit("Expected one menu control trace include")

fixture = Path(__file__).resolve().parent.parent / "src" / "menu_controller_test.inc"
Path("src/menu_controller_test.inc").write_bytes(fixture.read_bytes())
runtime.write_text(source.replace(anchor, "#define MENU_CONTROLLER_TEST_BUILD 1\n" + anchor),
                   encoding="utf-8")
print("Applied MVP2005 Modern simulated menu controller input")
