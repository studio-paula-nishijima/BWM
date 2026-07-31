import numpy as np


def filter_events_by_date(
    events,
    start_date,
    end_date
):

    filtered = []

    start_date = np.datetime64(start_date)

    end_date = np.datetime64(end_date)

    for e in events:

        ts = np.datetime64(
            e["timestamp"]
        )

        if start_date <= ts <= end_date:

            filtered.append(e)

    return filtered
