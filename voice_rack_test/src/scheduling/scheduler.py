import numpy as np


def compute_frequency(
    u,
    f_min,
    f_max,
    mode="linear"
):

    if mode == "linear":

        return (
            f_min +
            u * (f_max - f_min)
        )

    elif mode == "log":

        return (
            f_min *
            (f_max / f_min) ** u
        )

    raise ValueError(mode)


def generate_events(
    timestamps,
    values,
    active_mask,
    dt,
    config
):

    f_min = config["freq_min"]

    f_max = config["freq_max"]

    t_on = config["t_on"]

    mode = config["scaling"]

    channel = config["channel_name"]

    time_scale = config["time_scale"]

    events = []

    # -------------------------------------------------
    # Playback time compression
    # -------------------------------------------------

    scaled_dt = dt / time_scale

    # -------------------------------------------------
    # Global continuous playback clock
    # -------------------------------------------------

    current_time = 0.0

    # -------------------------------------------------
    # Persistent pulse oscillator phase
    # -------------------------------------------------

    next_pulse_time = 0.0

    # -------------------------------------------------
    # Main timeline traversal
    # -------------------------------------------------

    for i in range(len(values)):

        # -------------------------------------------------
        # Current control state
        # -------------------------------------------------

        active = active_mask[i]

        interval_start = current_time

        interval_end = current_time + scaled_dt

        # -------------------------------------------------
        # Inactive region
        # -------------------------------------------------

        if not active:

            current_time = interval_end

            continue

        u = values[i]

        freq = compute_frequency(
            u,
            f_min,
            f_max,
            mode
        )

        period = 1.0 / freq

        # -------------------------------------------------
        # Ensure oscillator never falls behind
        # -------------------------------------------------

        if next_pulse_time < interval_start:

            next_pulse_time = interval_start

        # -------------------------------------------------
        # Continuous pulse generation
        # -------------------------------------------------

        while next_pulse_time <= interval_end:

            events.append({

                "playback_time": next_pulse_time,

                "timestamp": timestamps[i],

                "type": "solenoid",

                "target": channel,

                "action": "pulse",

                "duration": t_on,

                "metadata": {

                    "frequency": float(freq),

                    "source_value": float(values[i])
                }
            })

            # ---------------------------------------------
            # Advance persistent oscillator
            # ---------------------------------------------

            next_pulse_time += period

        # -------------------------------------------------
        # Advance global playback clock
        # -------------------------------------------------

        current_time = interval_end

    return events
