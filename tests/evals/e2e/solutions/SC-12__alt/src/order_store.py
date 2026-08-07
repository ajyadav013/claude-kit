"""In-memory order store with optimistic concurrency control.

Lock-free variant: each order's state is an immutable snapshot tuple that is
swapped wholesale by a compare-and-swap on the version (a single dict item
assignment, atomic under CPython). adjust_total retries recursively; the
interleave_hook runs between the snapshot read and the CAS so tests can
schedule rival writers deterministically.
"""

from collections import namedtuple

_Snapshot = namedtuple("_Snapshot", ("status", "total_cents", "version"))


class ConflictError(Exception):
    """A conditional write observed a stale version."""

    def __init__(self, order_id, expected_version, actual_version):
        detail = "conflict on order %s: version %s is stale (current is %s)" % (
            order_id,
            expected_version,
            actual_version,
        )
        super().__init__(detail)
        self.order_id = order_id
        self.expected_version = expected_version
        self.actual_version = actual_version


class OrderStore:
    """Orders keyed by id, each holding (status, total_cents, version)."""

    def __init__(self):
        self._snapshots = {}
        self.interleave_hook = None

    def create(self, order_id, status, total_cents):
        if order_id in self._snapshots:
            raise ValueError("order %s already exists" % order_id)
        snap = _Snapshot(status, int(total_cents), 1)
        self._snapshots[order_id] = snap
        return snap.version

    def read(self, order_id):
        snap = self._snapshots[order_id]  # KeyError for unknown ids
        return (snap.status, snap.total_cents, snap.version)

    def write(self, order_id, status, total_cents, expected_version):
        current = self._snapshots[order_id]  # KeyError for unknown ids
        if current.version != expected_version:
            raise ConflictError(order_id, expected_version, current.version)
        replacement = _Snapshot(status, int(total_cents), expected_version + 1)
        self._snapshots[order_id] = replacement  # the atomic swap
        return replacement.version

    def adjust_total(self, order_id, delta_cents, max_attempts=5):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        return self._attempt(order_id, delta_cents, max_attempts)

    def _attempt(self, order_id, delta_cents, attempts_left):
        status, total_cents, version = self.read(order_id)
        if self.interleave_hook is not None:
            self.interleave_hook()
        try:
            self.write(order_id, status, total_cents + delta_cents, version)
        except ConflictError:
            if attempts_left <= 1:
                raise
            return self._attempt(order_id, delta_cents, attempts_left - 1)
        return total_cents + delta_cents
