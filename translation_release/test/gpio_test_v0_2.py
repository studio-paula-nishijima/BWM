from gpiozero import OutputDevice
from time import sleep

PIN = 14

solenoid = OutputDevice(PIN)

print("HIGH")
solenoid.on()

sleep(1)

print("LOW")
solenoid.off()
