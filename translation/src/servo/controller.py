import time
import board
import busio
from adafruit_pca9685 import PCA9685


class ServoController:

    def __init__(self, channel, frequency, home_pulse):

        self.channel = channel
        self.home_pulse = home_pulse

        self.i2c = busio.I2C(board.SCL, board.SDA)
        self.pca = PCA9685(self.i2c)
        self.pca.frequency = frequency

        self.servo = self.pca.channels[channel]

        self.set_pulse(home_pulse)

    def set_pulse(self, us):
        duty = int(us / 20000 * 65535)
        self.servo.duty_cycle = duty

    def go_home(self):
        print("SERVO: home")
        self.set_pulse(self.home_pulse)
        time.sleep(0.3)

    def shutdown(self):
        print("SERVO: shutdown")

        try:
            self.set_pulse(self.home_pulse)
            time.sleep(0.2)
        except Exception:
            pass

        try:
            self.servo.duty_cycle = 0
        except Exception:
            pass

        try:
            self.pca.deinit()
        except Exception:
            pass

        print("SERVO: deinit complete")
