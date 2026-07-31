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

    current_time = 0.0

    for i in range(len(values)):

        scaled_dt = dt / time_scale

        interval_start = current_time

        interval_end = current_time + scaled_dt

        if not active_mask[i]:

            current_time += scaled_dt

            continue

        u = values[i]

        freq = compute_frequency(
            u,
            f_min,
            f_max,
            mode
        )

        period = 1.0 / freq

        pulse_time = interval_start

        while pulse_time <= interval_end:

            events.append({

                "playback_time": pulse_time,

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

            pulse_time += period

        current_time += scaled_dt

    return events
