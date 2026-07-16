from gpiozero import DigitalInputDevice
import subprocess
import time
import sys

BUTTON_GPIO = 17
SERVICE_NAME = "play-events.service"

last_press = 0
DEBOUNCE_SEC = 0.4


def is_running():
    result = subprocess.run(
        ["/bin/systemctl", "is-active", SERVICE_NAME],
        capture_output=True,
        text=True
    )
    return result.stdout.strip() == "active"


def toggle():
    global last_press

    now = time.time()
    if now - last_press < DEBOUNCE_SEC:
        return

    last_press = now

    if is_running():
        print("STOP")
        subprocess.Popen(["/bin/systemctl", "stop", SERVICE_NAME])
    else:
        print("START")
        subprocess.Popen(["/bin/systemctl", "start", SERVICE_NAME])


# Standard Raspberry Pi button wiring:
# GPIO17 ---- button ---- GND
# idle = 1, pressed = 0
button = DigitalInputDevice(BUTTON_GPIO, pull_up=True)

# Initialize to actual state to avoid a false edge at startup
last_state = button.value


def press():
    """
    Software-simulated button press.
    """
    toggle()


def poll():
    global last_state

    state = button.value

    # Trigger on physical button press
    # idle=1 -> pressed=0
    if state == 0 and last_state == 1:
        toggle()

    last_state = state


# Allow:
# python button_service.py --press
if len(sys.argv) > 1 and sys.argv[1] == "--press":
    press()
    sys.exit(0)


print("Button controller running")

while True:
    poll()
    time.sleep(0.02)
