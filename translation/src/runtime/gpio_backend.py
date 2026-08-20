"""Reusable GPIO pulse workers with distinct session-quiesce and shutdown paths."""

from queue import Empty, Queue
import threading
import time


class GPIOBackend:
    def __init__(self, pin_map, device_factory=None, sleep_fn=time.sleep):
        if device_factory is None:
            # Keep import-only/test paths independent of Pi GPIO packages.
            from gpiozero import OutputDevice
            device_factory = OutputDevice
        self.devices, self.queues, self.threads = {}, {}, {}
        self.stop_event = threading.Event()
        self._sleep = sleep_fn
        self._lock = threading.Condition()
        self._accepting = True
        self._generation = 0
        self._active_channels = set()
        for channel, pin in pin_map.items():
            print(f"[GPIOBackend] Initializing {channel} on GPIO {pin}")
            self.devices[channel] = device_factory(pin)
            self.queues[channel] = Queue()
            thread = threading.Thread(target=self._worker, args=(channel,), daemon=False)
            thread.start()
            self.threads[channel] = thread

    def _worker(self, channel):
        device, queue = self.devices[channel], self.queues[channel]
        while not self.stop_event.is_set():
            try:
                item = queue.get(timeout=0.2)
            except Empty:
                continue
            if item is None:
                queue.task_done()
                break
            generation, duration = item
            with self._lock:
                if not self._accepting or generation != self._generation:
                    queue.task_done()
                    continue
                self._active_channels.add(channel)
            try:
                device.on()
                self._sleep(duration)  # A valid pulse already on may finish.
            finally:
                device.off()
                queue.task_done()
                with self._lock:
                    self._active_channels.discard(channel)
                    self._lock.notify_all()
        device.off()

    def pulse(self, channel, duration):
        if channel not in self.queues:
            raise ValueError(f"Unknown channel: {channel}")
        with self._lock:
            if not self._accepting or self.stop_event.is_set():
                print(f"[GPIOBackend] Ignored pulse for {channel}; no active session")
                return False
            self.queues[channel].put((self._generation, duration))
            return True

    def begin_session(self):
        """Open hardware admission for a new session after a completed quiesce."""
        with self._lock:
            if self.stop_event.is_set():
                raise RuntimeError("GPIOBackend is shut down")
            self._accepting = True
        print("[GPIOBackend] Session admission enabled")

    def is_idle(self):
        """Whether no admitted pulse remains queued or physically active."""
        with self._lock:
            # Queue unfinished-task accounting covers the small get-before-lock
            # window in a worker, unlike Queue.empty().
            return not self._active_channels and all(queue.unfinished_tasks == 0
                                                     for queue in self.queues.values())

    def quiesce(self):
        """Cancel pending pulses and leave claimed outputs OFF, ready for reuse."""
        with self._lock:
            self._accepting = False
            self._generation += 1
            dropped = 0
            for queue in self.queues.values():
                while True:
                    try:
                        queue.get_nowait()
                    except Empty:
                        break
                    else:
                        queue.task_done()
                        dropped += 1
            # A just-dequeued stale pulse sees the new generation before `on`.
            # A pulse already ON finishes, then its worker drives it OFF.
            while self._active_channels:
                self._lock.wait()
            for device in self.devices.values():
                device.off()
        print(f"[GPIOBackend] Session quiesced; dropped {dropped} pending pulse(s), outputs OFF")

    def shutdown(self):
        """Full process cleanup: quiesce, terminate workers, and release devices."""
        print("[GPIOBackend] Full shutdown initiated")
        self.quiesce()
        self.stop_event.set()
        for queue in self.queues.values():
            queue.put(None)
        for channel, thread in self.threads.items():
            thread.join(timeout=2.0)
            if thread.is_alive():
                print(f"[GPIOBackend WARNING] Thread still alive: {channel}")
        for device in self.devices.values():
            try:
                device.off()
                device.close()
            except Exception as exc:
                print(f"[GPIOBackend ERROR] device cleanup failed: {exc}")
        print("[GPIOBackend] Full shutdown complete")
