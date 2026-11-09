import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mvp_game_test as agent
from set_test_target import update_config


class RunSafetyTests(unittest.TestCase):
    def setUp(self):
        self.target = agent.Target(Path(r"C:\mvp\.build\smoke\MVP2005Modern.exe"),
                                   Path(r"C:\mvp\.build\smoke"),
                                   Path(r"C:\mvp\.build\smoke-game\MVP2005Smoke.exe"), ())

    def test_stale_build_blocks_popen(self):
        stale = agent.Process(30, 10, Path(r"C:\mvp\.build\old\MVP2005Modern.exe"), 2)
        with patch.object(agent, "_processes", return_value=[stale]), patch.object(agent.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "Clean launch requires"):
                agent._launch(agent.Run(self.target))
            popen.assert_not_called()

    def test_only_new_exact_child_can_be_the_game(self):
        launcher = agent.Process(40, 20, self.target.launch, 2)
        game = agent.Process(41, 21, self.target.game, 40)
        run = agent.Run(self.target, launch=object(), launcher=launcher)
        unrelated = [
            agent.Process(42, 21, self.target.game, 3),
            agent.Process(43, 19, self.target.game, 40),
            agent.Process(44, 21, Path(r"C:\old\MVP2005Smoke.exe"), 40),
        ]
        with patch.object(agent, "_processes", return_value=unrelated):
            self.assertEqual(agent._members(run, "game"), [])
        with patch.object(agent, "_processes", return_value=[*unrelated, game]):
            with patch.object(agent, "_process", return_value=game):
                self.assertEqual(agent._members(run, "game"), [game])
        with patch.object(agent, "_process", return_value=agent.Process(41, 50, game.path, 40)):
            self.assertEqual(agent._members(run, "game"), [])

    def test_mouse_is_not_sent_if_cursor_misses_the_target(self):
        run = agent.Run(self.target)
        with (patch.object(agent, "_focus"),
              patch.object(agent.win32gui, "GetClientRect", return_value=(0, 0, 640, 480)),
              patch.object(agent.win32gui, "ClientToScreen", return_value=(200, 200)),
              patch.object(agent.win32gui, "WindowFromPoint", return_value=99),
              patch.object(agent.win32gui, "IsChild", return_value=False),
              patch.object(agent, "_send_mouse") as send):
            with self.assertRaisesRegex(RuntimeError, "obscured"):
                agent._click(run, 20, 100, 100)
            send.assert_not_called()

    def test_non_smoke_target_cannot_use_isolated_cleanup(self):
        self.assertTrue(agent._is_isolated_smoke(self.target))
        retail = agent.Target(self.target.launch, self.target.workdir, Path(r"C:\mvp\mvp2005.exe"), ())
        self.assertFalse(agent._is_isolated_smoke(retail))


class ScriptTests(unittest.TestCase):
    def test_shipped_tests_pass_schema_and_time_budget(self):
        tests = Path(__file__).resolve().parent / "tests"
        with patch.object(agent, "TESTS_DIR", tests):
            for path in sorted(tests.glob("*.json")):
                with self.subTest(test=path.name):
                    self.assertTrue(agent._load_test(path.name)["steps"])

    def test_xinput_reports_first_connected_slot_and_native_button_bits(self):
        slots = []

        def get_state(slot, state):
            slots.append(slot)
            if slot == 0:
                return 1167
            struct.pack_into("<H", state, 4, agent.XINPUT_BUTTONS["dpad_right"])
            return 0

        with patch.object(agent, "_xinput_get_state", return_value=get_state):
            self.assertEqual(agent._xinput_slot(), (1, 0x0008))
        self.assertEqual(slots, [0, 1])

    def test_invalid_late_step_is_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            tests = Path(directory).resolve()
            (tests / "bad.json").write_text(json.dumps({"steps": [
                {"action": "launch"}, {"action": "key_down", "key": "ctrl"},
                {"action": "click", "x": 1, "y": 2, "relative": "false"},
            ]}))
            with patch.object(agent, "TESTS_DIR", tests), patch.object(agent, "_launch") as launch:
                with self.assertRaisesRegex(ValueError, "step 3"):
                    agent.run_game_test("bad")
                launch.assert_not_called()

    def test_log_cursor_ignores_history_and_waits_for_complete_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.log"
            path.write_bytes(b"old marker\r\n")
            cursor = agent.LogCursor(path)
            cursor.snapshot()
            with path.open("ab") as stream:
                stream.write(b"new par")
            cursor.poll()
            self.assertEqual(list(cursor.pending), [])
            with path.open("ab") as stream:
                stream.write(b"tial\r\nnext\n")
            cursor.poll()
            self.assertEqual(list(cursor.pending), ["new partial", "next"])
            path.write_bytes(b"reset\n")
            with self.assertRaisesRegex(RuntimeError, "truncated"):
                cursor.poll()

    def test_intro_cursor_reads_from_new_header_after_game_recreates_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "intro.log"
            path.write_bytes(b"previous run header\nAUTO SKIP PASS\n")
            cursor = agent.LogCursor(path, resets_at_start=True)
            cursor.snapshot()
            cursor.poll()
            self.assertEqual(list(cursor.pending), [])
            path.write_bytes(b"current run header\n")
            cursor.poll()
            self.assertEqual(list(cursor.pending), ["current run header"])

    def test_config_update_preserves_other_servers_and_line_endings(self):
        old = ('[mcp_servers.other.env]\r\nMVP_GAME_EXE = "other"\r\n'
               '[mcp_servers.mvp-game-test.env]\r\nMVP_GAME_EXE = "old"\r\n'
               'MVP_GAME_WORKDIR = "old"\r\nMVP_GAME_ALLOWED_EXES = "old"\r\n# keep\r\n')
        expected = old.replace('"old"', '"new"')
        self.assertEqual(update_config(old, {
            "MVP_GAME_EXE": "new", "MVP_GAME_WORKDIR": "new", "MVP_GAME_ALLOWED_EXES": "new"
        }), expected)


if __name__ == "__main__":
    unittest.main()
