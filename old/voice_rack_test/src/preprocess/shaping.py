import numpy as np


def apply_frequency_shaping(
    u,
    mode,
    gamma=1.0
):

    if mode == "none":

        return u

    elif mode == "power":

        return np.power(
            u,
            gamma
        )

    else:

        raise ValueError(
            f"Unknown frequency_shaping: {mode}"
        )