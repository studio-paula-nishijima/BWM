import threading
import time

try:
    import RPi.GPIO as GPIO
except:
    GPIO = None

class GPIOBackend:
    def __init__(self, pin_map):
        self.pin_map = pin_map

        if GPIO:
            GPIO.setmode(GPIO.BCM)
            for p in pin_map.values():
                GPIO.setup(p, GPIO.OUT)
                GPIO.output(p, GPIO.LOW)

    def pulse(self, channel, duration):
        pin = self.pin_map[channel]

        def run():
            if GPIO:
                GPIO.output(pin, GPIO.HIGH)
            time.sleep(duration)
            if GPIO:
                GPIO.output(pin, GPIO.LOW)

            # print(f"GPIO HIGH {channel}")

            # time.sleep(duration)

            # print(f"GPIO LOW {channel}")

        threading.Thread(target=run, daemon=True).start()
