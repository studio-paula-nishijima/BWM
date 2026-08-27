"""A transport-neutral Halo 60x intensity/CCT demonstration.

The plan deliberately keeps intensity and CCT as separate fields.  A DMX,
UART, or vendor SDK adapter can consume :meth:`Halo60xCue.frames` without
having to infer one channel from the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


MIN_CCT_K = 2700
MAX_CCT_K = 6500


def cct_to_dmx(cct_kelvin: float) -> int:
    """Map the Halo 60x profile-1 CCT range to its 8-bit DMX channel."""
    if not MIN_CCT_K <= cct_kelvin <= MAX_CCT_K:
        raise ValueError(f"cct_kelvin must be between {MIN_CCT_K} and {MAX_CCT_K}")
    return round((cct_kelvin - MIN_CCT_K) * 255 / (MAX_CCT_K - MIN_CCT_K))


def state_to_dmx_channels(state: "Halo60xState") -> tuple[int, int, int]:
    """Return Halo profile-1 channels: intensity, CCT, strobe."""
    return (round(state.brightness_percent * 255 / 100), cct_to_dmx(state.cct_kelvin), 0)


@dataclass(frozen=True)
class Halo60xState:
    """A complete fixture state; strobe is intentionally not configurable."""

    brightness_percent: float
    cct_kelvin: float
    strobe: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.brightness_percent <= 100:
            raise ValueError("brightness_percent must be between 0 and 100")
        if not MIN_CCT_K <= self.cct_kelvin <= MAX_CCT_K:
            raise ValueError(f"cct_kelvin must be between {MIN_CCT_K} and {MAX_CCT_K}")
        if self.strobe != 0:
            raise ValueError("the Halo 60x demonstration requires strobe=0")


BLACKOUT = Halo60xState(0, 4200)


@dataclass(frozen=True)
class Halo60xCue:
    """One linear fade followed by an observable hold at its end state."""

    label: str
    start: Halo60xState
    end: Halo60xState
    fade_seconds: float
    hold_seconds: float

    def __post_init__(self) -> None:
        if self.fade_seconds < 0 or self.hold_seconds < 0:
            raise ValueError("fade_seconds and hold_seconds must be non-negative")
        if self.start.strobe != 0 or self.end.strobe != 0:
            raise ValueError("all Halo 60x cues must keep strobe off")

    def state_at(self, seconds: float) -> Halo60xState:
        """Return the linearly interpolated state during this cue."""
        if seconds < 0 or seconds > self.fade_seconds + self.hold_seconds:
            raise ValueError("seconds is outside this cue")
        progress = 1.0 if self.fade_seconds == 0 else min(seconds / self.fade_seconds, 1.0)
        return Halo60xState(
            self.start.brightness_percent + progress * (self.end.brightness_percent - self.start.brightness_percent),
            self.start.cct_kelvin + progress * (self.end.cct_kelvin - self.start.cct_kelvin),
        )

    def frames(self, interval_seconds: float = 0.1) -> Iterator[Halo60xState]:
        """Yield smooth, fixed-rate states for a real-time fixture adapter."""
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        duration = self.fade_seconds + self.hold_seconds
        elapsed = 0.0
        while elapsed < duration:
            yield self.state_at(elapsed)
            elapsed += interval_seconds
        yield self.end


def _cue(label: str, start: Halo60xState, end: Halo60xState, fade: float, hold: float) -> Halo60xCue:
    return Halo60xCue(label, start, end, fade, hold)


def build_halo60x_demo(*, fade_seconds: float = 4.0, hold_seconds: float = 5.0,
                       check_fade_seconds: float = 12.0, blackout_hold_seconds: float = 3.0) -> tuple[Halo60xCue, ...]:
    """Build the complete Halo 60x demonstration in the requested order."""
    if min(fade_seconds, hold_seconds, check_fade_seconds, blackout_hold_seconds) < 0:
        raise ValueError("demo timings must be non-negative")

    looks = (
        (100, 2700, "bright warm"), (100, 4200, "bright neutral"), (100, 6500, "bright cool"),
        (70, 2700, "medium warm"), (70, 4200, "medium neutral"), (70, 6500, "medium cool"),
        (45, 2700, "dim warm"), (45, 4200, "dim neutral"), (45, 6500, "dim cool"),
    )
    cues: list[Halo60xCue] = [_cue("begin blackout", BLACKOUT, BLACKOUT, 0, blackout_hold_seconds)]
    current = BLACKOUT
    for brightness, cct, label in looks:
        target = Halo60xState(brightness, cct)
        cues.append(_cue(label, current, target, fade_seconds, hold_seconds))
        current = target

    # The first check changes only CCT while brightness remains exactly 70%.
    medium_warm = Halo60xState(70, 2700)
    cues.append(_cue("transition check setup: 70% warm", current, medium_warm, fade_seconds, hold_seconds))
    medium_cool = Halo60xState(70, 6500)
    cues.append(_cue("CCT check: 2700 K to 6500 K at 70%", medium_warm, medium_cool, check_fade_seconds, hold_seconds))
    cues.append(_cue("CCT check: 6500 K back to 2700 K at 70%", medium_cool, medium_warm, check_fade_seconds, hold_seconds))

    # The second check changes only brightness while CCT remains exactly 4200 K.
    dim_neutral = Halo60xState(45, 4200)
    cues.append(_cue("transition check setup: 45% neutral", medium_warm, dim_neutral, fade_seconds, hold_seconds))
    bright_neutral = Halo60xState(100, 4200)
    cues.append(_cue("brightness check: 45% to 100% at 4200 K", dim_neutral, bright_neutral, check_fade_seconds, hold_seconds))
    cues.append(_cue("brightness check: 100% back to 45% at 4200 K", bright_neutral, dim_neutral, check_fade_seconds, hold_seconds))

    cues.append(_cue("fade to blackout", dim_neutral, BLACKOUT, fade_seconds, blackout_hold_seconds))
    return tuple(cues)
