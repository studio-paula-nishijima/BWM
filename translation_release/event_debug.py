import sys
from pathlib import Path

sys.path.append(
    str(Path(__file__).resolve().parent / "src")
)

import time
import numpy as np
import pandas as pd

from runtime.gpio_backend import GPIOBackend
from runtime.pin_config import PIN_MAP

from runtime.router import EventRouter

from runtime.clock import RealtimeClock

from events.filtering import (
    filter_events_by_date
)


# ---------------------------------------------------
# Optional playback filtering
# ---------------------------------------------------

PLAYBACK_START = "2003-01-01"

PLAYBACK_END = "2017-01-01"


# ---------------------------------------------------
# Load events
# ---------------------------------------------------

events = np.load(
    "events.npy",
    allow_pickle=True
)

for e in events[:30]:
    print(
        e["playback_time"],
        e["target"],
        e["metadata"]["frequency"]
    )
