"""Tests for the provider-neutral dispatch boundary."""

from __future__ import annotations

import inspect
from typing import Optional, Sequence

import pytest

from claude_kit.components import SymbolicRef
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


class MemoryDispatcher:
    """Small semantic fake proving an adapter can satisfy the public protocol."""

    def __init__(self) -> None:
        self.counter = 0
        self.messages: list[tuple[DispatchHandle, DispatchMessage]] = []
        self.cancelled: set[DispatchHandle] = set()

    def spawn(self, request: DispatchRequest) -> DispatchHandle:
        self.counter += 1
        return DispatchHandle(f"work-{self.counter}", request.route)

    def message(self, handle: DispatchHandle, message: DispatchMessage) -> None:
        self.messages.append((handle, message))

    def wait(
        self,
        handles: Sequence[DispatchHandle],
        mode: WaitMode = WaitMode.ALL,
        timeout_seconds: Optional[float] = None,
    ) -> WaitResult:
        del mode, timeout_seconds
        return WaitResult(tuple(handles), (), False)

    def collect(self, handles: Sequence[DispatchHandle]) -> tuple[DispatchResult, ...]:
        return tuple(
            DispatchResult(
                handle,
                (
                    DispatchStatus.CANCELLED
                    if handle in self.cancelled
                    else DispatchStatus.SUCCEEDED
                ),
                output="done" if handle not in self.cancelled else None,
            )
            for handle in handles
        )

    def retry(self, handle: DispatchHandle, reason: str) -> DispatchHandle:
        assert reason
        return DispatchHandle(handle.id, handle.route, handle.attempt + 1)

    def cancel(self, handle: DispatchHandle, reason: str) -> None:
        assert reason
        self.cancelled.add(handle)


def test_adapter_protocol_exposes_exact_neutral_lifecycle() -> None:
    dispatcher = MemoryDispatcher()

    assert isinstance(dispatcher, Dispatcher)
    assert {
        name
        for name, value in Dispatcher.__dict__.items()
        if callable(value) and not name.startswith("_")
    } == {"spawn", "message", "wait", "collect", "retry", "cancel"}


def test_dispatch_lifecycle_and_symbolic_evidence() -> None:
    dispatcher = MemoryDispatcher()
    request = DispatchRequest(
        route="security-review",
        objective="Aggregate cited scanner findings.",
        lane="security",
        dependencies=(SymbolicRef.parse("stage://test-merge"),),
        evidence=(SymbolicRef.parse("artifact://security-report"),),
        retry_budget="review",
    )

    handle = dispatcher.spawn(request)
    dispatcher.message(
        handle,
        DispatchMessage(MessageKind.CORRECTION, "Include the policy scanner result."),
    )
    snapshot = dispatcher.wait((handle,), WaitMode.ALL, timeout_seconds=1.0)
    results = dispatcher.collect(snapshot.completed)
    retried = dispatcher.retry(handle, "transient runtime failure")
    dispatcher.cancel(retried, "retry budget exhausted")

    assert snapshot == WaitResult((handle,), (), False)
    assert results[0].status is DispatchStatus.SUCCEEDED
    assert retried.attempt == 2
    assert dispatcher.collect((retried,))[0].status is DispatchStatus.CANCELLED


@pytest.mark.parametrize(
    "result",
    [
        lambda handle: DispatchResult(handle, DispatchStatus.RUNNING),
        lambda handle: DispatchResult(handle, DispatchStatus.FAILED),
        lambda handle: DispatchResult(
            handle, DispatchStatus.SUCCEEDED, output="done", error="unexpected"
        ),
    ],
)
def test_dispatch_result_fails_closed_on_inconsistent_terminal_state(result) -> None:
    with pytest.raises(ValueError):
        result(DispatchHandle("work-1", "verification"))


def test_wait_snapshot_requires_disjoint_handles() -> None:
    handle = DispatchHandle("work-1", "verification")

    with pytest.raises(ValueError, match="disjoint"):
        WaitResult((handle,), (handle,), False)


def test_dispatch_message_payload_is_bounded() -> None:
    with pytest.raises(ValueError, match="65536 UTF-8 bytes"):
        DispatchMessage(MessageKind.CONTEXT, "x" * 65_537)


def test_dispatch_request_and_handle_preserve_exact_execution_binding() -> None:
    request = DispatchRequest(
        "implementation",
        "Implement the bounded change.",
        execution_slot="maker",  # type: ignore[arg-type]
        requested_model="vendor/model:2026-preview",
    )
    handle = DispatchHandle(
        "work-1",
        request.route,
        provider="claude",
        execution_slot=request.execution_slot,
        requested_model=request.requested_model,
    )

    assert request.execution_slot is ExecutionSlot.MAKER
    assert handle.execution_slot is ExecutionSlot.MAKER
    assert request.requested_model == "vendor/model:2026-preview"
    assert handle.requested_model == request.requested_model


@pytest.mark.parametrize(
    "requested_model",
    (
        "",
        " ",
        " model",
        "model ",
        "model id",
        "-model",
        "mødel",
        "model\n--dangerously-bypass-approvals-and-sandbox",
        "model\x00suffix",
        "x" * 129,
    ),
)
def test_requested_model_is_nonempty_bounded_and_control_free(
    requested_model: str,
) -> None:
    with pytest.raises(ValueError, match="requested_model"):
        DispatchRequest(
            "review",
            "Review the bounded change.",
            execution_slot=ExecutionSlot.REVIEWER,
            requested_model=requested_model,
        )


def test_execution_slot_rejects_unknown_semantic_participant() -> None:
    with pytest.raises(ValueError, match="execution_slot"):
        DispatchRequest(
            "review",
            "Review the bounded change.",
            execution_slot="critic",  # type: ignore[arg-type]
        )


def test_dispatch_contract_contains_no_provider_tool_identifiers() -> None:
    source = inspect.getsource(__import__("claude_kit.dispatch", fromlist=["*"]))

    for forbidden in (
        "spawn_agent",
        "send_message",
        "wait_agent",
        "TaskCreate",
        "AskUserQuestion",
        "CLAUDE_CODE_",
    ):
        assert forbidden not in source
