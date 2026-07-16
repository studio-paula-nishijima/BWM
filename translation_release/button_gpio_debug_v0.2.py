import RPimport RPi.GPIO as GPIO
import time

PIN = 17

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

print("GPIO17 REAL-TIME MONITOR")
print("Expected: HIGH = idle, LOW = pressed\n")

def read_state():
    return GPIO.input(PIN)

try:
    while True:
        state = read_state()

        if state == 1:
            print("HIGH (idle / not pressed)")
        else:
            print("LOW (pressed)")

        time.sleep(0.5)

except KeyboardInterrupt:
    print("Exiting")

finally:
    GPIO.cleanup()
