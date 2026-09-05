"""Low-level host-timed Open DMX framing."""

from __future__ import annotations

import time


BREAK_SECONDS = 0.0001
MARK_AFTER_BREAK_SECONDS = 0.000012


def send_open_dmx_frame(serial_port, channels, start_address, *, sleep=time.sleep):
    """Send one DMX512 frame without POSIX ``tcsendbreak`` rounding."""
    if not 1 <= start_address <= 510:
        raise ValueError("start_address must leave room for the three Halo channels")
    frame = bytearray(512)
    frame[start_address - 1:start_address + 2] = bytes(channels)

    # PySerial's POSIX send_break duration is quantized in 250 ms units, so a
    # requested 100 us break becomes tcsendbreak(..., 0), typically 250-500 ms.
    # Toggle the line explicitly to produce a DMX-sized break and mark-after-break.
    serial_port.break_condition = True
    sleep(BREAK_SECONDS)
    serial_port.break_condition = False
    sleep(MARK_AFTER_BREAK_SECONDS)
    serial_port.write(bytes([0]) + frame)
    serial_port.flush()
