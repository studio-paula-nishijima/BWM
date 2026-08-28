# BWM Vision BLE activation contract

This is a diagnostic/reference contract. A future production Pi receiver must
validate and deduplicate these events using the existing semantic ingress; it
must not create a BLE-specific session controller.

## Roles and discovery

- ESP32S3 BWM Vision node: BLE peripheral/GATT server, advertised complete
  local name `BWM Vision` and the service UUID below.
- Raspberry Pi: BLE central/GATT client. Scan by service UUID (preferred), with
  the advertised name as a human-readable diagnostic.

Service UUID: `7a9e4c10-5b8d-4bd6-9c17-2f3e8a4b1001`

Activation characteristic UUID: `7a9e4c10-5b8d-4bd6-9c17-2f3e8a4b1002`

The characteristic has the **Notify** property only. The Pi connects, discovers
the service/characteristic, enables notifications, and remains connected. The
ESP restarts advertising after a disconnect; the Pi should rescan/reconnect.

## Wire format

Each notification is a frame: one byte flags, little-endian unsigned 16-bit
sequence number, then UTF-8 JSON bytes. `0x01` marks the first frame and must
have sequence zero; `0x02` marks the final frame. Frames use the negotiated ATT
MTU less three bytes, and JSON is reconstructed by concatenating payload bytes
in contiguous sequence order. The ESP currently emits at most 320 JSON bytes.

Example reconstructed event:

```json
{"version":1,"id":"01234567-89ab-cdef-0123-456789abcdef","type":"installation.activation","origin":"person_detector","timestamp":"2026-08-28T12:00:00Z","payload":{"state":"active"},"diagnostics":{"trigger_source":"camera_confirmation"}}
```

Notifications are best effort, not indications. When no Pi is connected, an
activation is dropped rather than queued; the ESP records `dropped_no_pi` in
its local diagnostics. There is no acknowledgement or Pi-to-ESP state path.
IDs are unique per constructed event. A future simultaneous MQTT+BLE mode must
retain the same ID for the same constructed event so the production ingress can
deduplicate it.

## Production semantic mapping

For a complete, valid event, future Pi work must preserve `version`, `id`,
`type`, `origin`, `payload.state`, and trigger-source diagnostics, then pass
`installation.activation`, `origin=person_detector`, `state=active` through:

`validation -> ID deduplication -> semantic activation ingress -> PlaybackSessionRuntime`.

The standalone client below does none of that; it only reports events.

## Diagnostic client

On the Pi, install its isolated dependency and run:

```bash
python3 -m pip install bleak
python3 person_detector/tools/ble_activation_test.py --verbose
```

For a hardware-free parser/framing check: `python3 person_detector/tools/ble_activation_test.py --self-test`.
