"""Delivery pump: pending intents in, confirmed delivery out.

Host-side by design (D1): the kernel exposes ``pending_events`` /
``acknowledge_event`` and never loops on delivery. This module is
transport-only — it does NOT import microflow; the container adapter wires
the kernel faces in as callables:

    pump = EventPump(pending=coordinator.pending_events,
                     acknowledge=lambda intent: coordinator.acknowledge_event(
                         intent["event_id"], intent["content_digest"],
                         request_id=stable_request_id(intent)),
                     stream=record_stream)

Semantics are at-least-once and conservative on the ack side: intents are
acknowledged only when every intent of the page was accepted AND the flush
left a clean outbox with no new failures. Any doubt keeps intents PENDING
in the state store; the next tick redelivers and the host dedups by
``event_id``. Over-acking would drop an undelivered intent; under-acking
only costs a redelivery — so the pump always errs toward under-acking.
"""
import threading
import time


class EventPump:
    def __init__(self, *, pending, acknowledge, stream, limit=100,
                 interval=5.0, sleeper=time.sleep):
        if not callable(pending) or not callable(acknowledge):
            raise ValueError("pending and acknowledge must be callables")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        self._pending = pending
        self._acknowledge = acknowledge
        self._stream = stream
        self._limit = limit
        self._interval = interval
        self._sleeper = sleeper
        self._stop = threading.Event()
        self._thread = None
        self.ticks = self.fetched = self.accepted = self.acked = 0
        self.invalid = self.ack_failures = self.deferred = 0

    # ---- one drain cycle -------------------------------------------------

    def tick(self) -> dict:
        """One page: fetch → enqueue intents → force flush → conservative ack."""
        self.ticks += 1
        intents = list(self._pending(self._limit) or ())
        self.fetched += len(intents)
        accepted = 0
        for intent in intents:
            try:
                if self._stream.accept_intent(intent):
                    accepted += 1
                    self.accepted += 1
                else:
                    self.invalid += 1
            except Exception:  # noqa: BLE001 - one bad intent never stops the page
                self.invalid += 1

        failures_before = self._stream.stats()["failed_flushes"]
        self._stream.flush(force=True)
        after = self._stream.stats()
        clean = (accepted == len(intents)
                 and after["failed_flushes"] == failures_before
                 and after["outbox"] == 0)

        acked = 0
        if clean and intents:
            for intent in intents:
                try:
                    self._acknowledge(intent)
                    acked += 1
                except Exception:  # noqa: BLE001 - ack failure keeps it PENDING
                    self.ack_failures += 1
            self.acked += acked
        elif intents:
            self.deferred += len(intents)
        return {"fetched": len(intents), "accepted": accepted,
                "acked": acked, "clean": clean,
                "outbox": after["outbox"], "tick": self.ticks}

    # ---- lifecycle ---------------------------------------------------------

    def start(self) -> "EventPump":
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop,
                                             name="microflow-event-pump", daemon=True)
            self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the pump must survive its own bugs
                self.ack_failures += 1
            self._stop.wait(self._interval)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 2)
        self.tick()

    def stats(self) -> dict:
        return {"ticks": self.ticks, "fetched": self.fetched,
                "accepted": self.accepted, "invalid": self.invalid,
                "acked": self.acked, "ack_failures": self.ack_failures,
                "deferred": self.deferred, "limit": self._limit}
