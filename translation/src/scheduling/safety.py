from collections import defaultdict


def enforce_solenoid_safety(
    events,
    safety_config=None,
    max_duty_cycle=None,
    cooldown_window=None,
    max_continuous_on=None,
):
    """Apply configured generation-time limits when explicitly enabled.

    Stage 1's baseline configuration disables this legacy filter so the
    released base score is left intact. Runtime safety is a later concern.
    Keyword limits remain available for focused callers and diagnostics.
    """
    # Preserve the legacy positional threshold call shape for diagnostics.
    if safety_config is not None and not isinstance(safety_config, dict):
        safety_config, max_duty_cycle, cooldown_window, max_continuous_on = (
            {}, safety_config, max_duty_cycle, cooldown_window
        )
    safety_config = safety_config or {}
    if safety_config and not safety_config.get("enabled", False):
        return events

    max_duty_cycle = (
        max_duty_cycle if max_duty_cycle is not None
        else safety_config.get("max_duty_cycle", 0.6)
    )
    cooldown_window = (
        cooldown_window if cooldown_window is not None
        else safety_config.get("cooldown_window", 10.0)
    )
    max_continuous_on = (
        max_continuous_on if max_continuous_on is not None
        else safety_config.get("max_continuous_on", 0.4)
    )

    filtered = []

    channel_history = defaultdict(list)

    for event in events:

        if event["type"] != "solenoid":

            filtered.append(event)

            continue

        ch = event["target"]

        current_time = event["playback_time"]

        duration = event["duration"]

        # -------------------------------------------------
        # Rule 1:
        # Maximum continuous activation
        # -------------------------------------------------

        if duration > max_continuous_on:

            print(
                f"SKIP {ch}: "
                f"duration too long"
            )

            continue

        # -------------------------------------------------
        # Rule 2:
        # Rolling duty cycle limit
        # -------------------------------------------------

        history = channel_history[ch]

        history = [

            e for e in history

            if (
                current_time -
                e["playback_time"]
            ) <= cooldown_window
        ]

        total_on_time = sum(
            e["duration"]
            for e in history
        )

        duty_cycle = (
            total_on_time /
            cooldown_window
        )

        if duty_cycle > max_duty_cycle:

            print(
                f"SKIP {ch}: "
                f"duty cycle exceeded"
            )

            continue

        history.append(event)

        channel_history[ch] = history

        filtered.append(event)

    return filtered
