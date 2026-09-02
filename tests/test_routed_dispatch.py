"""Tests for semantic maker/reviewer dispatch routing."""

from __future__ import annotations

from typing import Optional, Sequence

import pytest

from claude_kit.dispatch import (
    Dispatcher,
    DispatchHandle,
    DispatchMessage,
    DispatchRequest,
    DispatchResult,
    DispatchStatus,
    ExecutionSlot,
    MessageKind,
    WaitMode,
    WaitResult,
)
from claude_kit.routed_dispatch import RoutedDispatcher


class ControlledDispatcher:
    """Queued child fake with independently controlled terminal state."""

    queued_spawn = True

    def __init__(self, provider: str, *, propagate_binding: bool = True) -> None:
        self.provider = provider
        self.propagate_binding = propagate_binding
        self.counter = 0
        self.requests: list[DispatchRequest] = []
        self.statuses: dict[DispatchHandle, DispatchStatus] = {}
        self.messages: list[tuple[DispatchHandle, DispatchMessage]] = []
        self.wait_calls: list[
            tuple[tuple[DispatchHandle, ...], WaitMode, Optional[float]]
        ] = []
        self.cancelled: list[DispatchHandle] = []

    def spawn(self, request: DispatchRequest) -> DispatchHandle:
        self.counter += 1
        self.requests.append(request)
        handle = DispatchHandle(
            f"work-{self.counter}",
            request.route,
            provider=self.provider,
            execution_slot=(request.execution_slot if self.propagate_binding else None),
            requested_model=(
                request.requested_model if self.propagate_binding else None
            ),
        )
        self.statuses[handle] = DispatchStatus.QUEUED
        return handle

    def message(self, handle: DispatchHandle, message: DispatchMessage) -> None:
        assert handle in self.statuses
        self.messages.append((handle, message))

    def wait(
        self,
        handles: Sequence[DispatchHandle],
        mode: WaitMode = WaitMode.ALL,
        timeout_seconds: Optional[float] = None,
    ) -> WaitResult:
        ordered = tuple(handles)
        self.wait_calls.append((ordered, mode, timeout_seconds))
        for handle in ordered:
            if self.statuses[handle] is DispatchStatus.QUEUED:
                self.statuses[handle] = DispatchStatus.RUNNING
        completed = tuple(
            handle for handle in ordered if self.statuses[handle].terminal
        )
        pending = tuple(
            handle for handle in ordered if not self.statuses[handle].terminal
        )
        return WaitResult(completed, pending, bool(pending))

    def collect(self, handles: Sequence[DispatchHandle]) -> tuple[DispatchResult, ...]:
        results = []
        for handle in handles:
            status = self.statuses[handle]
            if not status.terminal:
                raise RuntimeError("dispatch is not terminal")
            results.append(
                DispatchResult(
                    handle,
                    status,
                    output="done" if status is DispatchStatus.SUCCEEDED else None,
                    error="failed" if status is DispatchStatus.FAILED else None,
                )
            )
        return tuple(results)

    def retry(self, handle: DispatchHandle, reason: str) -> DispatchHandle:
        assert reason and self.statuses[handle] is DispatchStatus.FAILED
        retried = DispatchHandle(
            handle.id,
            handle.route,
            handle.attempt + 1,
            provider=handle.provider,
            execution_slot=handle.execution_slot,
            requested_model=handle.requested_model,
        )
        self.statuses[retried] = DispatchStatus.QUEUED
        return retried

    def cancel(self, handle: DispatchHandle, reason: str) -> None:
        assert reason and handle in self.statuses
        self.statuses[handle] = DispatchStatus.CANCELLED
        self.cancelled.append(handle)

    def finish(
        self, handle: DispatchHandle, status: DispatchStatus = DispatchStatus.SUCCEEDED
    ) -> None:
        assert status.terminal
        self.statuses[handle] = status


class InterruptingDispatcher(ControlledDispatcher):
    def wait(
        self,
        handles: Sequence[DispatchHandle],
        mode: WaitMode = WaitMode.ALL,
        timeout_seconds: Optional[float] = None,
    ) -> WaitResult:
        del handles, mode, timeout_seconds
        raise KeyboardInterrupt


def test_routed_dispatcher_satisfies_protocol_and_routes_same_provider_models() -> None:
    maker = ControlledDispatcher("claude", propagate_binding=False)
    reviewer = ControlledDispatcher("claude", propagate_binding=False)
    dispatcher = RoutedDispatcher(
        {
            ExecutionSlot.MAKER: maker,
            ExecutionSlot.REVIEWER: reviewer,
        }
    )

    maker_handle = dispatcher.spawn(
        DispatchRequest(
            "worker",
            "Make the artifact.",
            execution_slot=ExecutionSlot.MAKER,
            requested_model="maker-model",
        )
    )
    reviewer_handle = dispatcher.spawn(
        DispatchRequest(
            "worker",
            "Review the artifact.",
            execution_slot=ExecutionSlot.REVIEWER,
            requested_model="reviewer-model",
        )
    )

    assert isinstance(dispatcher, Dispatcher)
    assert dispatcher.queued_spawn is True
    assert maker.requests[0].requested_model == "maker-model"
    assert reviewer.requests[0].requested_model == "reviewer-model"
    assert maker_handle.id == reviewer_handle.id == "work-1"
    assert maker_handle != reviewer_handle
    assert maker_handle.execution_slot is ExecutionSlot.MAKER
    assert reviewer_handle.execution_slot is ExecutionSlot.REVIEWER

    correction = DispatchMessage(MessageKind.CORRECTION, "Address finding F-1.")
    dispatcher.message(reviewer_handle, correction)
    assert not maker.messages
    assert reviewer.messages[0][1] == correction

    maker_native = next(iter(maker.statuses))
    reviewer_native = next(iter(reviewer.statuses))
    maker.finish(maker_native)
    reviewer.finish(reviewer_native, DispatchStatus.FAILED)
    results = dispatcher.collect((reviewer_handle, maker_handle))
    assert tuple(result.handle for result in results) == (
        reviewer_handle,
        maker_handle,
    )

    retried = dispatcher.retry(reviewer_handle, "bounded reviewer retry")
    assert retried.execution_slot is ExecutionSlot.REVIEWER
    assert retried.requested_model == "reviewer-model"
    dispatcher.cancel(retried, "run stopped")
    assert reviewer.cancelled and not maker.cancelled


def test_first_completed_wait_submits_every_provider_group_before_returning() -> None:
    maker = ControlledDispatcher("claude")
    reviewer = ControlledDispatcher("codex")
    dispatcher = RoutedDispatcher(
        {
            ExecutionSlot.MAKER: maker,
            ExecutionSlot.REVIEWER: reviewer,
        }
    )
    maker_handle = dispatcher.spawn(
        DispatchRequest(
            "maker",
            "Make.",
            execution_slot=ExecutionSlot.MAKER,
        )
    )
    reviewer_handle = dispatcher.spawn(
        DispatchRequest(
            "reviewer",
            "Review.",
            execution_slot=ExecutionSlot.REVIEWER,
        )
    )
    reviewer.finish(reviewer_handle)

    snapshot = dispatcher.wait(
        (maker_handle, reviewer_handle),
        WaitMode.FIRST_COMPLETED,
        timeout_seconds=10,
    )

    assert maker.wait_calls[0][2] == 0
    assert reviewer.wait_calls[0][2] == 0
    assert snapshot == WaitResult((reviewer_handle,), (maker_handle,), False)


def test_all_wait_preserves_global_order_and_timeout_state() -> None:
    maker = ControlledDispatcher("claude")
    reviewer = ControlledDispatcher("codex")
    dispatcher = RoutedDispatcher(
        {
            ExecutionSlot.MAKER: maker,
            ExecutionSlot.REVIEWER: reviewer,
        }
    )
    maker_handle = dispatcher.spawn(
        DispatchRequest("maker", "Make.", execution_slot=ExecutionSlot.MAKER)
    )
    reviewer_handle = dispatcher.spawn(
        DispatchRequest("reviewer", "Review.", execution_slot=ExecutionSlot.REVIEWER)
    )
    maker.finish(maker_handle)

    snapshot = dispatcher.wait(
        (reviewer_handle, maker_handle),
        WaitMode.ALL,
        timeout_seconds=0,
    )

    assert snapshot == WaitResult((maker_handle,), (reviewer_handle,), True)


def test_multi_route_dispatch_requires_a_semantic_execution_slot() -> None:
    dispatcher = RoutedDispatcher(
        {
            ExecutionSlot.MAKER: ControlledDispatcher("claude"),
            ExecutionSlot.REVIEWER: ControlledDispatcher("codex"),
        }
    )

    with pytest.raises(ValueError, match="execution_slot"):
        dispatcher.spawn(DispatchRequest("worker", "Do the work."))


def test_wait_interruption_cancels_work_across_every_started_child() -> None:
    maker = ControlledDispatcher("claude")
    reviewer = InterruptingDispatcher("codex")
    dispatcher = RoutedDispatcher(
        {
            ExecutionSlot.MAKER: maker,
            ExecutionSlot.REVIEWER: reviewer,
        }
    )
    maker_handle = dispatcher.spawn(
        DispatchRequest("maker", "Make.", execution_slot=ExecutionSlot.MAKER)
    )
    reviewer_handle = dispatcher.spawn(
        DispatchRequest("reviewer", "Review.", execution_slot=ExecutionSlot.REVIEWER)
    )

    with pytest.raises(KeyboardInterrupt):
        dispatcher.wait((maker_handle, reviewer_handle), timeout_seconds=10)

    assert maker.cancelled == [maker_handle]
    assert reviewer.cancelled == [reviewer_handle]
