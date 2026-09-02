"""Semantic maker/reviewer routing over portable dispatch adapters."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from claude_kit.dispatch import (
    Dispatcher,
    DispatchHandle,
    DispatchMessage,
    DispatchRequest,
    DispatchResult,
    ExecutionSlot,
    WaitMode,
    WaitResult,
)

_POLL_SLICE_SECONDS = 0.05


class DispatchRoutingError(RuntimeError):
    """Raised when a child violates routed-dispatch identity semantics."""


@dataclass(frozen=True)
class _OwnedDispatch:
    dispatcher: Dispatcher
    native_handle: DispatchHandle


class RoutedDispatcher:
    """Route semantic execution slots while preserving the six operations.

    Child adapters may return legacy handles without slot/model fields. The router
    enriches those public handles and translates them back to the owning child's
    native identity for every later operation.
    """

    def __init__(self, bindings: Mapping[ExecutionSlot, Dispatcher]) -> None:
        if not bindings:
            raise ValueError("routed dispatcher bindings must not be empty")
        normalized: dict[ExecutionSlot, Dispatcher] = {}
        for raw_slot, dispatcher in bindings.items():
            try:
                slot = (
                    raw_slot
                    if isinstance(raw_slot, ExecutionSlot)
                    else ExecutionSlot(raw_slot)
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "routed dispatcher binding keys must be maker or reviewer"
                ) from exc
            if slot in normalized:
                raise ValueError(f"duplicate routed dispatcher binding: {slot.value}")
            if not isinstance(dispatcher, Dispatcher):
                raise ValueError(
                    f"routed dispatcher binding {slot.value!r} is not a Dispatcher"
                )
            normalized[slot] = dispatcher
        self._bindings = normalized
        self._owners: dict[DispatchHandle, _OwnedDispatch] = {}
        self._native_owners: dict[tuple[int, DispatchHandle], DispatchHandle] = {}

    @property
    def queued_spawn(self) -> bool:
        """Whether every distinct child attests queue-before-wait semantics."""
        return all(
            getattr(dispatcher, "queued_spawn", False) is True
            for dispatcher in self._distinct_dispatchers()
        )

    def _distinct_dispatchers(self) -> tuple[Dispatcher, ...]:
        distinct: list[Dispatcher] = []
        identities: set[int] = set()
        for dispatcher in self._bindings.values():
            identity = id(dispatcher)
            if identity not in identities:
                identities.add(identity)
                distinct.append(dispatcher)
        return tuple(distinct)

    def _dispatcher_for(self, request: DispatchRequest) -> Dispatcher:
        if request.execution_slot is not None:
            try:
                return self._bindings[request.execution_slot]
            except KeyError as exc:
                raise ValueError(
                    "no routed dispatcher is bound for execution_slot "
                    f"{request.execution_slot.value!r}"
                ) from exc
        dispatchers = self._distinct_dispatchers()
        if len(dispatchers) == 1:
            return dispatchers[0]
        raise ValueError(
            "execution_slot is required when multiple routed dispatchers are bound"
        )

    @staticmethod
    def _public_handle(
        native_handle: DispatchHandle,
        *,
        execution_slot: Optional[ExecutionSlot],
        requested_model: Optional[str],
    ) -> DispatchHandle:
        if native_handle.execution_slot not in {None, execution_slot}:
            raise DispatchRoutingError(
                "child returned a handle for a different execution_slot"
            )
        if native_handle.requested_model not in {None, requested_model}:
            raise DispatchRoutingError(
                "child returned a handle for a different requested_model"
            )
        return DispatchHandle(
            native_handle.id,
            native_handle.route,
            native_handle.attempt,
            provider=native_handle.provider,
            required_capabilities=native_handle.required_capabilities,
            attested_capabilities=native_handle.attested_capabilities,
            execution_slot=execution_slot,
            requested_model=requested_model,
        )

    def _register(
        self,
        dispatcher: Dispatcher,
        native_handle: DispatchHandle,
        *,
        execution_slot: Optional[ExecutionSlot],
        requested_model: Optional[str],
    ) -> DispatchHandle:
        public_handle = self._public_handle(
            native_handle,
            execution_slot=execution_slot,
            requested_model=requested_model,
        )
        native_key = (id(dispatcher), native_handle)
        if native_key in self._native_owners:
            raise DispatchRoutingError("child returned a duplicate dispatch handle")
        if public_handle in self._owners:
            raise DispatchRoutingError("routed dispatch handle identity collided")
        self._owners[public_handle] = _OwnedDispatch(dispatcher, native_handle)
        self._native_owners[native_key] = public_handle
        return public_handle

    def _owned(self, handle: DispatchHandle) -> _OwnedDispatch:
        try:
            return self._owners[handle]
        except (KeyError, TypeError) as exc:
            raise DispatchRoutingError(
                f"unknown routed dispatch: {getattr(handle, 'id', '<invalid>')}"
            ) from exc

    def _groups(
        self, handles: Sequence[DispatchHandle]
    ) -> tuple[
        tuple[Dispatcher, tuple[tuple[DispatchHandle, DispatchHandle], ...]], ...
    ]:
        groups: dict[
            int, tuple[Dispatcher, list[tuple[DispatchHandle, DispatchHandle]]]
        ] = {}
        for public_handle in handles:
            owned = self._owned(public_handle)
            identity = id(owned.dispatcher)
            if identity not in groups:
                groups[identity] = (owned.dispatcher, [])
            groups[identity][1].append((public_handle, owned.native_handle))
        return tuple(
            (dispatcher, tuple(pairs)) for dispatcher, pairs in groups.values()
        )

    @staticmethod
    def _completed_from_snapshot(
        pairs: Sequence[tuple[DispatchHandle, DispatchHandle]],
        snapshot: WaitResult,
    ) -> set[DispatchHandle]:
        expected = {native_handle for _public_handle, native_handle in pairs}
        actual = set(snapshot.completed) | set(snapshot.pending)
        if actual != expected:
            raise DispatchRoutingError(
                "child wait snapshot did not cover the requested handles exactly"
            )
        public_by_native = {
            native_handle: public_handle for public_handle, native_handle in pairs
        }
        return {public_by_native[handle] for handle in snapshot.completed}

    @staticmethod
    def _wait_result(
        ordered: Sequence[DispatchHandle],
        completed: set[DispatchHandle],
        *,
        timed_out: bool,
    ) -> WaitResult:
        return WaitResult(
            tuple(handle for handle in ordered if handle in completed),
            tuple(handle for handle in ordered if handle not in completed),
            timed_out,
        )

    def spawn(self, request: DispatchRequest) -> DispatchHandle:
        if not isinstance(request, DispatchRequest):
            raise ValueError("request must be a DispatchRequest")
        dispatcher = self._dispatcher_for(request)
        native_handle = dispatcher.spawn(request)
        return self._register(
            dispatcher,
            native_handle,
            execution_slot=request.execution_slot,
            requested_model=request.requested_model,
        )

    def message(self, handle: DispatchHandle, message: DispatchMessage) -> None:
        owned = self._owned(handle)
        owned.dispatcher.message(owned.native_handle, message)

    def wait(
        self,
        handles: Sequence[DispatchHandle],
        mode: WaitMode = WaitMode.ALL,
        timeout_seconds: Optional[float] = None,
    ) -> WaitResult:
        if not isinstance(mode, WaitMode):
            mode = WaitMode(mode)
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        ordered = tuple(handles)
        if len(set(ordered)) != len(ordered):
            raise ValueError("wait handles must not contain duplicates")
        if not ordered:
            return WaitResult((), (), False)
        try:
            return self._wait_owned(ordered, mode, timeout_seconds)
        except BaseException:
            # A later child can fail after earlier provider groups have already
            # submitted detached work. Best-effort terminalize every routed
            # attempt before preserving the original interruption or adapter
            # failure for the coordinator.
            for handle in ordered:
                try:
                    self.cancel(handle, "routed coordinator interrupted")
                except BaseException:
                    pass
            raise

    def _wait_owned(
        self,
        ordered: Sequence[DispatchHandle],
        mode: WaitMode,
        timeout_seconds: Optional[float],
    ) -> WaitResult:
        completed: set[DispatchHandle] = set()
        # Every child receives a zero-time wait before global completion is
        # evaluated. Queue-backed children therefore submit every provider group
        # even when FIRST_COMPLETED is already satisfied by an earlier group.
        for dispatcher, pairs in self._groups(ordered):
            snapshot = dispatcher.wait(
                tuple(native for _public, native in pairs),
                WaitMode.ALL,
                timeout_seconds=0,
            )
            completed.update(self._completed_from_snapshot(pairs, snapshot))

        if len(completed) == len(ordered) or (
            mode is WaitMode.FIRST_COMPLETED and completed
        ):
            return self._wait_result(ordered, completed, timed_out=False)
        if timeout_seconds == 0:
            return self._wait_result(ordered, completed, timed_out=True)

        deadline = (
            None if timeout_seconds is None else time.monotonic() + timeout_seconds
        )
        while True:
            before = len(completed)
            pending = tuple(handle for handle in ordered if handle not in completed)
            groups = self._groups(pending)
            for index, (dispatcher, pairs) in enumerate(groups):
                if deadline is None:
                    child_timeout = _POLL_SLICE_SECONDS
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return self._wait_result(ordered, completed, timed_out=True)
                    remaining_groups = len(groups) - index
                    child_timeout = min(
                        _POLL_SLICE_SECONDS,
                        remaining / remaining_groups,
                    )
                snapshot = dispatcher.wait(
                    tuple(native for _public, native in pairs),
                    WaitMode.FIRST_COMPLETED,
                    timeout_seconds=child_timeout,
                )
                completed.update(self._completed_from_snapshot(pairs, snapshot))
                if mode is WaitMode.FIRST_COMPLETED and completed:
                    return self._wait_result(ordered, completed, timed_out=False)
            if len(completed) == len(ordered):
                return self._wait_result(ordered, completed, timed_out=False)
            if deadline is not None and time.monotonic() >= deadline:
                return self._wait_result(ordered, completed, timed_out=True)
            if len(completed) == before:
                time.sleep(0.01)

    def collect(self, handles: Sequence[DispatchHandle]) -> tuple[DispatchResult, ...]:
        ordered = tuple(handles)
        if len(set(ordered)) != len(ordered):
            raise ValueError("collect handles must not contain duplicates")
        results: dict[DispatchHandle, DispatchResult] = {}
        for dispatcher, pairs in self._groups(ordered):
            native_handles = tuple(native for _public, native in pairs)
            child_results = dispatcher.collect(native_handles)
            by_native = {result.handle: result for result in child_results}
            if set(by_native) != set(native_handles) or len(child_results) != len(
                pairs
            ):
                raise DispatchRoutingError(
                    "child collect did not return each requested handle exactly once"
                )
            for public_handle, native_handle in pairs:
                child_result = by_native[native_handle]
                results[public_handle] = DispatchResult(
                    public_handle,
                    child_result.status,
                    output=child_result.output,
                    error=child_result.error,
                    evidence=child_result.evidence,
                    human_stop=child_result.human_stop,
                )
        return tuple(results[handle] for handle in ordered)

    def retry(self, handle: DispatchHandle, reason: str) -> DispatchHandle:
        owned = self._owned(handle)
        native_handle = owned.dispatcher.retry(owned.native_handle, reason)
        return self._register(
            owned.dispatcher,
            native_handle,
            execution_slot=handle.execution_slot,
            requested_model=handle.requested_model,
        )

    def cancel(self, handle: DispatchHandle, reason: str) -> None:
        owned = self._owned(handle)
        owned.dispatcher.cancel(owned.native_handle, reason)
