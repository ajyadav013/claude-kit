"""Static guards for the package's minimum supported Python runtime."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
PYTHON_FILES = tuple(
    path
    for source_root in (ROOT / "src", ROOT / "scripts", ROOT / "tests")
    for path in sorted(source_root.rglob("*.py"))
)


def _uses_pep604(node: ast.AST | None) -> bool:
    return node is not None and any(
        isinstance(child, ast.BinOp) and isinstance(child.op, ast.BitOr)
        for child in ast.walk(node)
    )


def _defers_annotations(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def _annotations(tree: ast.Module) -> tuple[ast.AST, ...]:
    annotations: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            )
            annotations.extend(
                argument.annotation
                for argument in arguments
                if argument.annotation is not None
            )
            if node.args.vararg and node.args.vararg.annotation is not None:
                annotations.append(node.args.vararg.annotation)
            if node.args.kwarg and node.args.kwarg.annotation is not None:
                annotations.append(node.args.kwarg.annotation)
            if node.returns is not None:
                annotations.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
    return tuple(annotations)


def test_pep604_annotations_are_deferred_for_python_39() -> None:
    offenders: list[str] = []
    for path in PYTHON_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _defers_annotations(tree):
            continue
        if any(_uses_pep604(annotation) for annotation in _annotations(tree)):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_runtime_type_arguments_do_not_evaluate_pep604_on_python_39() -> None:
    offenders: list[str] = []
    for path in PYTHON_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callable_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            argument_index = 0 if callable_name == "cast" else 1
            if callable_name not in {"cast", "isinstance", "issubclass"}:
                continue
            if len(node.args) > argument_index and _uses_pep604(
                node.args[argument_index]
            ):
                relative = path.relative_to(ROOT).as_posix()
                offenders.append(f"{relative}:{node.lineno}")
    assert offenders == []
