import RPi.GPIO as GPIO
import time

PIN = 17

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

print("GPIO17 REAL-TIME MONITOR")
print("HIGH = idle (not pressed), LOW = pressed\n")

try:
    while True:
        state = GPIO.input(PIN)

        if state == GPIO.HIGH:
            print("HIGH (idle / not pressed)")
        else:
            print("LOW (pressed)")

        time.sleep(0.2)

except KeyboardInterrupt:
    print("Exiting...")

finally:
    GPIO.cleanup()
