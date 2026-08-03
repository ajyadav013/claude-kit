"""In-memory order store with optimistic concurrency control.

Mutex variant: a single lock makes each create/read/write individually atomic
(the store is genuinely thread-safe), while adjust_total is an optimistic
snapshot -> hook -> conditional-write retry loop layered on top. The
interleave_hook is always invoked with the lock released so tests can drive
rival writes through the public API deterministically.
"""

import threading


class ConflictError(Exception):
    """A conditional write observed a stale version."""

    def __init__(self, order_id, expected_version, actual_version):
        super().__init__(
            "order %s: expected version %s, found %s"
            % (order_id, expected_version, actual_version)
        )
        self.order_id = order_id
        self.expected_version = expected_version
        self.actual_version = actual_version


class OrderStore:
    """Orders keyed by id, each holding (status, total_cents, version)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._orders = {}
        self.interleave_hook = None

    def create(self, order_id, status, total_cents):
        with self._lock:
            if order_id in self._orders:
                raise ValueError("order %s already exists" % order_id)
            self._orders[order_id] = {
                "status": status,
                "total_cents": int(total_cents),
                "version": 1,
            }
            return 1

    def read(self, order_id):
        with self._lock:
            rec = self._orders[order_id]  # KeyError for unknown ids
            return (rec["status"], rec["total_cents"], rec["version"])

    def write(self, order_id, status, total_cents, expected_version):
        with self._lock:
            rec = self._orders[order_id]  # KeyError for unknown ids
            if rec["version"] != expected_version:
                raise ConflictError(order_id, expected_version, rec["version"])
            rec["status"] = status
            rec["total_cents"] = int(total_cents)
            rec["version"] = expected_version + 1
            return rec["version"]

    def adjust_total(self, order_id, delta_cents, max_attempts=5):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        last_conflict = None
        for _ in range(max_attempts):
            status, total_cents, version = self.read(order_id)
            hook = self.interleave_hook
            if hook is not None:
                hook()  # lock not held: rival API calls from the hook are safe
            try:
                self.write(order_id, status, total_cents + delta_cents, version)
            except ConflictError as exc:
                last_conflict = exc
                continue
            return total_cents + delta_cents
        raise last_conflict
