from gpiozero import OutputDevice
from queue import Queue
import threading
import time


class GPIOBackend:

    def __init__(self, pin_map):

        self.devices = {}
        self.queues = {}
        self.running = True

        for channel, pin in pin_map.items():

            print(
                f"Initializing {channel} on GPIO {pin}"
            )

            device = OutputDevice(pin)

            self.devices[channel] = device

            q = Queue()

            self.queues[channel] = q

            worker = threading.Thread(
                target=self._worker,
                args=(channel,),
                daemon=False
            )

            worker.start()

    def _worker(self, channel):

        device = self.devices[channel]

        q = self.queues[channel]

        while self.running:

            duration = q.get()

            if duration is None:

                break

            try:

                device.on()

                time.sleep(duration)

                device.off()

            finally:

                q.task_done()

    def pulse(self, channel, duration):

        self.queues[channel].put(duration)

    def shutdown(self):

        self.running = False

        for q in self.queues.values():

            q.put(None)

        for device in self.devices.values():

            device.off()
