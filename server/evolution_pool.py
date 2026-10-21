"""Bounded spawn workers for independent episodes, with ordered result collection."""

from collections import deque
import logging
import multiprocessing as mp
import os
from queue import Empty
import time

from .trials import run_attempt


class _WorkerStop:
    def __init__(self, event):
        self.event = event
        self.parent = mp.parent_process()

    def is_set(self):
        return self.event.is_set() or not self.parent.is_alive()


def _episode_worker(tasks, results, event):
    stop = _WorkerStop(event)
    # A dead coordinator must not leave workers waiting for an unread feeder pipe.
    results.cancel_join_thread()
    try:
        os.nice(5)
    except (AttributeError, OSError):
        pass
    while not stop.is_set():
        try:
            token, index, project, options = tasks.get(timeout=0.2)
        except Empty:
            continue
        try:
            row = run_attempt(
                project,
                options,
                index,
                stop,
                lambda tick, limit: results.put((token, index, "progress", tick / limit)),
            )
            results.put((token, index, "result", row))
        except Exception as exc:
            logging.exception("Evolution episode failed")
            results.put((token, index, "error", f"{type(exc).__name__}: {exc}"))
            return


class EpisodePool:
    def __init__(self, workers, stop):
        context = mp.get_context("spawn")
        self.stop = stop
        self.worker_stop = context.Event()
        self.tasks = context.Queue()
        self.results = context.Queue()
        self.processes = []
        self.pending = deque()
        self.tickets = {}
        self.serial = 0
        self.active = 0
        try:
            for _ in range(workers):
                process = context.Process(
                    target=_episode_worker,
                    args=(self.tasks, self.results, self.worker_stop),
                    daemon=True,
                )
                process.start()
                self.processes.append(process)
        except BaseException:
            self.close()
            raise

    def submit(self, project, options, validation=False):
        token = self.serial
        self.serial += 1
        count = options["validation_attempts"] if validation else options["attempts"]
        trial_options = dict(
            duration=options["duration"],
            randomize=options["randomize"],
            seed=options["validation_seed"] if validation else options["search_seed"],
        )
        self.tickets[token] = dict(rows=[None] * count, fractions=[0.0] * count, completed=0)
        tasks = [(token, i, project, trial_options) for i in range(count)]
        if validation:
            self.pending.extendleft(reversed(tasks))
        else:
            self.pending.extend(tasks)
        self._dispatch()
        return token

    def _dispatch(self):
        while self.pending and self.active < len(self.processes) and not self.stop.is_set():
            self.tasks.put(self.pending.popleft())
            self.active += 1

    def collect(self, token, progress):
        ticket = self.tickets[token]
        count = len(ticket["rows"])
        while ticket["completed"] < count:
            cancelled = self.stop.is_set()
            if not cancelled and any(p.exitcode is not None for p in self.processes):
                raise RuntimeError("Процесс эволюции завершился без результата")
            try:
                key, index, kind, value = self.results.get(timeout=0 if cancelled else 0.1)
            except Empty:
                if cancelled:
                    return None
            else:
                target = self.tickets[key]
                if kind == "error":
                    raise RuntimeError(value)
                if kind == "result":
                    if value is None:
                        return None
                    target["rows"][index] = value
                    target["completed"] += 1
                    target["fractions"][index] = 1.0
                    self.active -= 1
                    self._dispatch()
                else:
                    target["fractions"][index] = value
            total = sum(ticket["fractions"])
            progress(int(total), count, total - int(total))
        del self.tickets[token]
        return ticket["rows"]

    def close(self):
        self.worker_stop.set()
        self.pending.clear()
        deadline = time.monotonic() + 2
        for process in self.processes:
            process.join(timeout=max(0, deadline - time.monotonic()))
        for process in self.processes:
            if process.is_alive():
                process.terminate()
        for process in self.processes:
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join()
        for channel in (self.tasks, self.results):
            channel.cancel_join_thread()
            channel.close()
