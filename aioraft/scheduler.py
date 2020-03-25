import asyncio


class Timer:
    def __init__(self, interval, callback):
        self.interval = interval
        self.callback = callback
        self.loop = asyncio.get_event_loop()
        self.scheduler_task = self.loop.call_later(self.interval, self._run)
        self.is_active = False

    def start(self):
        self.is_active = True

    def _run(self):
        if self.is_active:
            self.callback()
            self.scheduler_task = self.loop.call_later(self.interval, self._run)

    def stop(self):
        self.is_active = False
        self.scheduler_task.cancel()

    def reset(self):
        self.stop()
        self.start()
