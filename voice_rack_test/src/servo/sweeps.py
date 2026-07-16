import time


def simple_sweep(set_pulse, target_pulse, time_allowed):
    set_pulse(target_pulse)
    time.sleep(time_allowed)
    return target_pulse


def constant_speed(set_pulse, current_pulse, target_pulse, speed, frame_seconds=0.02):

    pulse_difference = target_pulse - current_pulse
    direction = 1 if pulse_difference > 0 else -1

    steps = int(abs(pulse_difference) / (speed * frame_seconds))

    if steps <= 0:
        set_pulse(target_pulse)
        return target_pulse

    for i in range(steps):
        set_pulse(current_pulse + direction * i * speed * frame_seconds)
        time.sleep(frame_seconds)

    set_pulse(target_pulse)
    return target_pulse
