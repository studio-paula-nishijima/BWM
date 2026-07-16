#basic servo test once integrated in rack


import time
import board
import busio
from adafruit_pca9685 import PCA9685

# Initialize I2C
i2c = busio.I2C(board.SCL, board.SDA)

# Initialize PCA9685
pca = PCA9685(i2c)
pca.frequency = 50  # standard servo frequency

# Channel 0
servo = pca.channels[0]

def set_pulse(us):
    duty = int(us / 20000 * 65535)
    servo.duty_cycle = duty

try:
    
    # No-Load Speed (6.0V)    0.043 sec/60° (230RPM)
    # for 5 turns => 1800 degrees => 30*0.0043s = 1.29 s average to do full sweep with no load
    print("Centering servo")
    start_time = time.time()
    set_pulse(1500)
    time_now = time.time()-start_time
    print(f"time: {time_now}")
    #time.sleep(2)
    time.sleep(5)
    
    print("Sweeping to furthest back")
    set_pulse(1000)
    time_now = time.time()-start_time
    print(f"time: {time_now}")
    time.sleep(5)

    time_now = time.time()-start_time
    print(f"time: {time_now}")
    print("Sweeping forward")
    for us in range(1000, 2000, 20):
        set_pulse(us)
        #time.sleep(0.02)
        time.sleep(0.2)
        
    time_now = time.time()-start_time
    print(f"time: {time_now}")
    print("Sweeping backward")
    for us in range(2000, 1000, -20):
        set_pulse(us)
        #time.sleep(0.02)
        time.sleep(0.2)
        
    time_now = time.time()-start_time
    print(f"time: {time_now}")
        
    print("Centering servo")
    set_pulse(1500)
    #time.sleep(2)
    time.sleep(5)

finally:
    servo.duty_cycle = 0
    pca.deinit()
    print("Done.")
