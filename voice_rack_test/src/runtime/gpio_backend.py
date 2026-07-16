from gpiozero import OutputDevice
from queue import Queue, Empty
import threading
import time


class GPIOBackend:

    def __init__(self, pin_map):

        self.devices = {}
        self.queues = {}
        self.threads = {}

        # global stop signal for all workers
        self.stop_event = threading.Event()

        for channel, pin in pin_map.items():

            print(f"Initializing {channel} on GPIO {pin}")

            device = OutputDevice(pin)
            self.devices[channel] = device

            q = Queue()
            self.queues[channel] = q

            t = threading.Thread(
                target=self._worker,
                args=(channel,),
                daemon=False  # IMPORTANT: we manage lifecycle explicitly
            )

            t.start()
            self.threads[channel] = t

    # ---------------------------------------------------
    # Worker thread
    # ---------------------------------------------------

    def _worker(self, channel):

        device = self.devices[channel]
        q = self.queues[channel]

        while not self.stop_event.is_set():

            try:
                # timeout prevents deadlock on shutdown
                duration = q.get(timeout=0.2)

            except Empty:
                continue

            # shutdown sentinel
            if duration is None:
                break

            try:
                device.on()
                time.sleep(duration)
            finally:
                device.off()
                q.task_done()

        # HARD SAFETY: ensure GPIO is never left ON
        device.off()

    # ---------------------------------------------------
    # Public API
    # ---------------------------------------------------

    def pulse(self, channel, duration):
        if channel not in self.queues:
            raise ValueError(f"Unknown channel: {channel}")

        self.queues[channel].put(duration)

    # ---------------------------------------------------
    # Shutdown (CRITICAL)
    # ---------------------------------------------------

    def shutdown(self):

        print("[GPIOBackend] Shutdown initiated")

        # 1. signal all threads to stop
        self.stop_event.set()

        # 2. unblock all queues (in case threads are waiting)
        for q in self.queues.values():
            q.put(None)

        # 3. wait for threads to exit cleanly
        for channel, t in self.threads.items():
            t.join(timeout=2.0)

            if t.is_alive():
                print(f"[GPIOBackend WARNING] Thread still alive: {channel}")

        # 4. force-safe hardware state
        for device in self.devices.values():
            try:
                device.off()
            except Exception as e:
                print(f"[GPIOBackend ERROR] device.off failed: {e}")

        print("[GPIOBackend] Shutdown complete")
