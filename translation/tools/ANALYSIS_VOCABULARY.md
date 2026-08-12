# Detector-analysis vocabulary

Use presentation names below when comparing CSVs. Raw CSV column names remain
stable for compatibility; absent columns in older logs mean **not recorded**,
not false.

| Raw field | Canonical meaning |
|---|---|
| `speech_gate_open` | Primary speech processing gate; in `shadow` mode it is pipeline observability, not WebRTC assist. |
| `webrtc_assist_open` | WebRTC assist state used by the assisted profile policy. |
| `comparison_speech_is_speech` | WebRTC VAD result for the selected assisted-profile mode. Additional `webrtc_mode_*` fields are diagnostic comparisons. |
| `low_proportion` | Canonical measured current-frame low-band proportion. |
| `temporal_v1_low_proportion_max` / `temporal_v1_low_proportion_max_pass` | Configured current-frame low-band upper bound and inclusive pass state. A blank threshold means the condition was disabled or not recorded. |
| `threshold_crossing_route` | Policy confirmation route reached; this is not necessarily an emitted trigger. |
| `trigger_route` / `trigger` | Detector trigger emitted after policy and detector cooldown. |
| `trigger_suppression_reason` | Reason the policy route did not emit a detector trigger. |
| `actuation_requested` / `actuation_started` | A real detector trigger requested physical actuation / the servo sequence actually started. |
| `actuation_suppression_reason` | Hardware pacing reason an actuation request did not start. |

Do not conflate temporal evidence, policy confirmation, emitted detector
triggers, and physical actuation when comparing runs.
