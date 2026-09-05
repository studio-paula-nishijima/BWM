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
    #
    # This is deliberately phase, not an absolute time calculated from the
    # frequency at a previous pulse.  A new control value therefore affects
    # the oscillator immediately, including during a short high-flow peak.
    # A channel begins at phase zero: its first pulse follows one accumulated
    # cycle rather than being an implicit t=0 pulse.

    phase = 0.0

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
            # Silence is a genuine oscillator boundary.  Do not let a partial
            # cycle from before it advance the next later active region.
            phase = 0.0
            current_time = interval_end

            continue

        u = values[i]

        freq = compute_frequency(
            u,
            f_min,
            f_max,
            mode
        )

        # -------------------------------------------------
        # Phase-responsive pulse generation
        # -------------------------------------------------
        #
        # Calculate each boundary crossing at its exact position in this
        # control interval.  This retains precise event times while allowing
        # an interval to cross more than one cycle.
        accumulated_phase = phase + (freq * scaled_dt)
        completed_cycles = int(np.floor(accumulated_phase + 1e-12))

        if completed_cycles:
            first_crossing = (1.0 - phase) / freq
            period = 1.0 / freq

        for cycle in range(completed_cycles):

            events.append({

                "playback_time": interval_start + first_crossing + (cycle * period),

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

        # Retain only the incomplete cycle.  Avoid a floating-point value
        # infinitesimally below one becoming a spurious immediate pulse in
        # the next interval.
        phase = accumulated_phase - completed_cycles
        if phase >= 1.0 - 1e-12:
            phase = 0.0

        # -------------------------------------------------
        # Advance global playback clock
        # -------------------------------------------------

        current_time = interval_end

    return events
