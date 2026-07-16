from gpiozero import Button
from signal import pause

# GPIO17 with internal pull-up
button = Button(17, pull_up=True, bounce_time=0.05)

def pressed():
    print("BUTTON PRESSED")

def released():
    print("button released")

button.when_pressed = pressed
button.when_released = released

print("Ready - press the button...")
pause()
