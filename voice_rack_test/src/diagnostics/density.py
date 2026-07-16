import numpy as np


def compute_event_density(
    events,
    window=10.0
):

    times = np.array([
        e["playback_time"]
        for e in events
    ])

    if len(times) == 0:

        return np.array([]), np.array([])

    bins = np.arange(
        times.min(),
        times.max(),
        window
    )

    density = []

    for b in bins:

        density.append(

            np.sum(
                (times >= b) &
                (times < b + window)
            ) / window
        )

    return bins, np.array(density)


def burst_statistics(events):

    if len(events) < 2:

        return {
            "burstiness": 0.0
        }

    times = np.array([
        e["playback_time"]
        for e in events
    ])

    intervals = np.diff(times)

    return {

        "mean_interval": float(
            np.mean(intervals)
        ),

        "std_interval": float(
            np.std(intervals)
        ),

        "burstiness": float(
            np.std(intervals) /
            (np.mean(intervals) + 1e-9)
        )
    }
