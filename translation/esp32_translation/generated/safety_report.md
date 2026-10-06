# Full-controller safety simulation

Complete filtered score events: 4931

| Scenario | Admitted artistic pulses | Emergency guard rejections |
|---|---:|---:|
| `base_score` | 4931 | 0 |
| `voice_simultaneous_then_sequence` | 8712 | 0 |
| `voice_cascade` | 4356 | 0 |
| `voice_triple_tap` | 14793 | 0 |
| `voice_split_groups` | 3030 | 0 |
| `voice_double_tap` | 9862 | 0 |

Constants: max pulse 500 ms; minimum OFF 40 ms; 160 events and 9000 ms ON per channel per 10000 ms window.
Per-channel work is serialized like the current Pi GPIO backend; this preserves every admitted tap while bounding storage.
