from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")

old = '''            if (borderless_logical_width == 800 &&
                borderless_logical_height == 600 &&
                cx > 0 && cy > 0 &&
                cy == monitor_height && cx < monitor_width &&
                cx * 3 == cy * 4 &&
                InterlockedCompareExchange(&gameplay_window_transition_seen, 1, 0) == 0) {
                InterlockedExchange(&gameplay_input_phase, 1);
                InterlockedExchange(&input_probe_log_count, 0);
                InterlockedExchange(&geometry_probe_log_count, 0);
                InterlockedExchange(&message_scale_log_count, 0);
                InterlockedExchange(&setcursor_probe_log_count, 0);
                log_line("gameplay 4:3 transition detected; mouse scaling disabled and diagnostics reset\\n");
            }
'''

new = '''            /* MVP enters gameplay by requesting a large 4:3 window even when
             * dgVoodoo keeps the host presentation monitor-sized. Do not depend
             * on the monitor rectangle here: the raw request itself is the most
             * reliable phase signal observed in every gameplay trace. */
            if (borderless_logical_width == 800 &&
                borderless_logical_height == 600 &&
                cx > (int)borderless_logical_width &&
                cy > (int)borderless_logical_height &&
                cx * 3 == cy * 4) {
                LONG was_gameplay = InterlockedExchange(&gameplay_input_phase, 1);
                if (!was_gameplay) {
                    InterlockedExchange(&gameplay_window_transition_seen, 1);
                    InterlockedExchange(&input_probe_log_count, 0);
                    InterlockedExchange(&geometry_probe_log_count, 0);
                    InterlockedExchange(&message_scale_log_count, 0);
                    InterlockedExchange(&setcursor_probe_log_count, 0);
                    log_line("gameplay 4:3 request detected; raw mouse passthrough enabled\\n");
                }
            }
'''

count = text.count(old)
if count != 1:
    raise SystemExit(f"v13 gameplay detector replacement: expected exactly one match, found {count}")
text = text.replace(old, new, 1)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern robust gameplay mouse phase detector v13")
