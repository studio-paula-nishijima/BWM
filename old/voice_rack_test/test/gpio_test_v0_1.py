import time
import RPi.GPIO as GPIO

PIN = 14

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.OUT)

print("HIGH")
GPIO.output(PIN, GPIO.HIGH)

time.sleep(2)

print("LOW")
GPIO.output(PIN, GPIO.LOW)

GPIO.cleanup()
