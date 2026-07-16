import numpy as np
from collections import defaultdict


EVENTS_FILE = "events.npy"


def main():

    events = np.load(
        EVENTS_FILE,
        allow_pickle=True
    )

    events = list(events)

    # ------------------------------------------
    # Collect unique timestep frequencies
    # ------------------------------------------

    timestep_freqs = defaultdict(dict)

    for e in events:

        if e["type"] != "solenoid":
            continue

        channel = e["target"]

        timestamp = e["timestamp"]

        freq = e["metadata"]["frequency"]

        # only store one value per timestep
        timestep_freqs[channel][timestamp] = freq

    print("\n=== TIMESTEP-WEIGHTED FREQUENCIES ===\n")

    for channel in sorted(timestep_freqs):

        freqs = np.array(
            list(
                timestep_freqs[channel].values()
            )
        )

        print(f"{channel}")

        print(
            f"  timesteps : {len(freqs)}"
        )

        print(
            f"  min freq  : {freqs.min():.3f} Hz"
        )

        print(
            f"  max freq  : {freqs.max():.3f} Hz"
        )

        print(
            f"  mean freq : {freqs.mean():.3f} Hz"
        )

        print(
            f"  median    : {np.median(freqs):.3f} Hz"
        )

        print()

    # ------------------------------------------
    # Pulse-weighted frequencies
    # ------------------------------------------

    pulse_freqs = defaultdict(list)

    for e in events:

        if e["type"] != "solenoid":
            continue

        pulse_freqs[e["target"]].append(
            e["metadata"]["frequency"]
        )

    print(
        "\n=== PULSE-WEIGHTED FREQUENCIES ===\n"
    )

    for channel in sorted(pulse_freqs):

        freqs = np.array(
            pulse_freqs[channel]
        )

        print(f"{channel}")

        print(
            f"  pulses     : {len(freqs)}"
        )

        print(
            f"  mean freq  : {freqs.mean():.3f} Hz"
        )

        print(
            f"  median     : {np.median(freqs):.3f} Hz"
        )

        print()


if __name__ == "__main__":

    main()
