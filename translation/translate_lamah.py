import sys
from pathlib import Path

sys.path.append(
    str(Path(__file__).resolve().parent / "src")
)

import yaml
import numpy as np

from configs.runtime_config import PROJECT_ROOT, RUNTIME_CONFIG

from lamah.lamah_loader import (
    load_lamah_column
)

from scheduling.scheduler import (
    generate_events
)

from scheduling.safety import (
    enforce_solenoid_safety
)

from preprocess.shaping import (
    apply_frequency_shaping
)

from preprocess.peak_preservation import (
    apply_window_max
)


def normalize_percentile(x):

    lo = np.percentile(x, 5)

    hi = np.percentile(x, 95)

    return np.clip(
        (x - lo) / (hi - lo + 1e-9),
        0,
        1
    )
    
def normalize_linear(x):

    lo = np.min(x)
    hi = np.max(x)

    return np.clip(
        (x - lo) / (hi - lo + 1e-9),
        0,
        1
    )

def run():

    with (PROJECT_ROOT / "configs" / "channels.yaml").open(encoding="utf-8") as f:

        config = yaml.safe_load(f)

    all_events = []

    for name, ch in config["channels"].items():

        print(f"Loading {name}")

        timestamps, raw = next(
            load_lamah_column(
                ch["csv_path"],
                ch["column"],
                ch["date_columns"]
            )
        )

        mask = (
            (timestamps >= np.datetime64(ch["start_date"])) &
            (timestamps <= np.datetime64(ch["end_date"]))
        )

        timestamps = timestamps[mask]

        raw = raw[mask]

        dt_seconds = (
            timestamps[1] - timestamps[0]
        ).astype("timedelta64[s]").astype(float)

        active = raw >= ch["threshold"]
        
        peak_cfg = ch.get(
            "peak_preservation",
            {}
        )
        
        if peak_cfg.get(
            "enabled",
            False
        ):
        
            if len(timestamps) > 1:
        
                playback_dt = (
                    timestamps[1] - timestamps[0]
                ) / np.timedelta64(1, "s")
                
                playback_dt = float(playback_dt)
                playback_dt /= ch["time_scale"]
        
                raw = apply_window_max(
        
                    raw,
                    playback_dt,
                    ch["freq_max"],
                    ch["time_scale"],
                    1.0
                )

        # u = normalize_percentile(raw)
        u = normalize_linear(raw)
        
        u = apply_frequency_shaping(
            u,        
            ch.get(
                "frequency_shaping",
                "none"
            ),        
            ch.get(
                "frequency_gamma",
                1.0
            )
        )

        ch["channel_name"] = name

        events = generate_events(
            timestamps,
            u,
            active,
            dt_seconds,
            ch
        )

        all_events.extend(events)

    events = sorted(
        all_events,
        key=lambda e: e["playback_time"]
    )

    events = enforce_solenoid_safety(events, RUNTIME_CONFIG.get("safety"))

    np.save(
        PROJECT_ROOT / RUNTIME_CONFIG["files"]["events_file"],
        np.array(events, dtype=object)
    )

    print(f"Saved {len(events)} events")


if __name__ == "__main__":

    run()
