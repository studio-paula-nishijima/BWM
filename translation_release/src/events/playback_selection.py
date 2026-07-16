import random
import numpy as np


def select_random_segment(
    events,
    duration_seconds
):

    if len(events) == 0:

        return events

    total_duration = (
        events[-1]["playback_time"]
        - events[0]["playback_time"]
    )

    if duration_seconds >= total_duration:

        return events

    start_time = random.uniform(
        0,
        total_duration - duration_seconds
    )

    end_time = (
        start_time
        + duration_seconds
    )

    selected = [

        e

        for e in events

        if (
            start_time
            <= e["playback_time"]
            < end_time
        )
    ]

    if len(selected) == 0:

        return events

    return selected
    
def rebase_playback_time(
    events
):

    if len(events) == 0:

        return events

    t0 = events[0]["playback_time"]

    for e in events:

        e["playback_time"] -= t0

    return events

def renormalize_segment_frequencies(
    events,
    freq_min,
    freq_max,
    gamma=1.0
):

    values = np.array([

        e["metadata"]["source_value"]

        for e in events

        if e["type"] == "solenoid"
    ])

    if len(values) == 0:

        return events

    vmin = values.min()

    vmax = values.max()

    if vmax <= vmin:

        return events

    for e in events:

        if e["type"] != "solenoid":

            continue

        value = (
            e["metadata"]["source_value"]
        )

        u = (
            value - vmin
        ) / (
            vmax - vmin
        )

        u = np.clip(
            u,
            0,
            1
        )

        u = u ** gamma

        freq = (

            freq_min

            + u * (
                freq_max
                - freq_min
            )
        )

        e["metadata"]["frequency"] = (
            float(freq)
        )

    return events
