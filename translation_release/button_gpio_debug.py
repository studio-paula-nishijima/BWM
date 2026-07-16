import RPi.GPIO as GPIO
import time

PIN = 17  # BCM numbering

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

print("GPIO17 raw monitor started (CTRL+C to exit)")
print("Expected: HIGH idle, LOW when pressed\n")

last_state = None

try:
    while True:
        state = GPIO.input(PIN)

        if state != last_state:
            if state == 1:
                print("GPIO17 = HIGH (released)")
            else:
                print("GPIO17 = LOW (pressed)")

            last_state = state

        time.sleep(0.01)

except KeyboardInterrupt:
    print("\nExiting...")

finally:
    GPIO.cleanup()
