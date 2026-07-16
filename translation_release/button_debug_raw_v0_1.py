# gpio_raw_watch.py

import lgpio
import time
from datetime import datetime

CHIP = 0
PIN = 17

h = lgpio.gpiochip_open(CHIP)
lgpio.gpio_claim_input(h, PIN)

last = None

def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

print("Raw GPIO monitor running")
print("PIN:")
print(PIN)

try:
    while True:
        val = lgpio.gpio_read(h, PIN)

        if val != last:
            print(f"[{ts()}] CHANGE {last} -> {val}")
        else:
            print(f"[{ts()}] stable={val}")

        last = val
        time.sleep(0.05)

except KeyboardInterrupt:
    print("exit")

finally:
    lgpio.gpiochip_close(h)
