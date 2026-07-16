import numpy as np

def apply_window_max(values, playback_dt, freq_max, time_scale, alpha=0.5):
    """
    Replace each value by the maximum value
    in a window scaled by freq_max and time_scale.

    alpha controls compression compensation:
        0.0 = no scaling
        1.0 = full scaling with time_scale
        0.5 = balanced (recommended)
    """

    if playback_dt <= 0:
        return values

    base_window_seconds = 1.0 / freq_max

    scale_factor = time_scale / 86400.0
    window_seconds = base_window_seconds * (scale_factor ** alpha)

    samples_per_window = int(np.ceil(window_seconds / playback_dt))

    if samples_per_window <= 1:
        return values

    out = values.copy()
    n = len(values)
    half = samples_per_window // 2

    for i in range(n):
        start = max(0, i - half)
        end = min(n, i + half + 1)
        out[i] = np.max(values[start:end])

    return out
