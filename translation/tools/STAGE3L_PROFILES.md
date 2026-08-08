# Stage 3L detector profiles

`detector_profile` is separate from `processing_mode`. The default is
`webrtc_assisted_temporal`; select a profile for one run with
`--detector-profile` without modifying YAML.

| Profile | Active components | Confirmation |
| --- | --- | --- |
| `webrtc_assisted_temporal` | Silero, lean `temporal_v1`, WebRTC mode 0 assist | assist: 15; fallback: 24 |
| `temporal_only` | Silero and lean `temporal_v1` | 24 |
| `analysis_full` | Silero, full acoustic observability, WebRTC modes 0--3, grouped and legacy classifier comparisons, reconstructed mode-0 assist gate | assist: 15; fallback: 24 |

The live profiles use the profile-specific temporal minimum of `0.0025`, a
10-frame window, population standard deviation, and low-proportion std minimum
of `0.05`. `temporal_v1` itself remains shared; its historical configuration is
not silently rewritten.

The WebRTC backend is `webrtcvad-wheels==2.0.14`. It may use a native wheel on
Raspberry Pi ARM64; pip may need build tools if no compatible wheel is offered.
WebRTC receives signed little-endian PCM16 created from clamped float32 frames.

The configured default filename tag gains the resolved profile automatically,
and tagged logs are written to `logs/<tag>/`. Explicit `--analysis-tag` values
remain unchanged.

`analysis_full` logs the mode-0 debounce state on every frame. Its continuous
confirmation fields distinguish the configured assisted requirement (15),
fallback requirement (24), and the currently applicable requirement. The
`threshold_crossing_route` is populated only on a threshold-crossing frame as
`webrtc_assisted` or `temporal_fallback`. `trigger_route` is populated only
when that crossing emits a final trigger; suppressed crossings carry
`trigger_suppression_reason` (currently `cooldown`).

`qualifying_run_summary` preserves detector continuity across WAV frames while
also reporting `max_segment_local_qualifying_run`. A sustained live run that
enters an annotation segment from its predecessor is marked
`cross_boundary_continuation` with its carried-frame count; it is not counted
as an independent non-whisper sustained event. Annotation boundaries never
reset the live detector.
