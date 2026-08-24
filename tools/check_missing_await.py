#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from pathlib import Path

_ASYNC_DB_METHODS: frozenset[str] = frozenset({
    "set", "delete", "remove", "force_save", "save", "load",
})

_DB_RECEIVER_NAMES: frozenset[str] = frozenset({
    "db", "_db", "database", "_database",
})

_TASK_WRAPPERS: frozenset[str] = frozenset({
    "create_task", "ensure_future", "gather", "wait", "wait_for",
    "shield", "run", "run_until_complete", "run_coroutine_threadsafe",
})

ALLOWLIST: frozenset[tuple[str, int]] = frozenset()


def _is_db_receiver(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _DB_RECEIVER_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in _DB_RECEIVER_NAMES
    return False


class _Visitor(ast.NodeVisitor):

    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self.violations: list[tuple[int, str]] = []

    def visit_Expr(self, node: ast.Expr) -> None:
        value = node.value
        if isinstance(value, ast.Await):
            self.generic_visit(node)
            return
        if isinstance(value, ast.Call):
            self._check_bare_call(value)
        self.generic_visit(node)

    def _check_bare_call(self, node: ast.Call) -> None:
        func = node.func
        wrapper_name = None
        if isinstance(func, ast.Attribute):
            wrapper_name = func.attr
        elif isinstance(func, ast.Name):
            wrapper_name = func.id
        if wrapper_name in _TASK_WRAPPERS:
            return
        if not isinstance(func, ast.Attribute):
            return
        if func.attr not in _ASYNC_DB_METHODS:
            return
        if not _is_db_receiver(func.value):
            return
        if (self.rel_path, node.lineno) in ALLOWLIST:
            return
        recv = ast.unparse(func.value) if hasattr(ast, "unparse") else "<db>"
        self.violations.append(
            (node.lineno, f"{recv}.{func.attr}(...) вызван как statement без await")
        )


def check_file(path: Path, root: Path) -> list[str]:
    rel = str(path.relative_to(root))
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        return [f"{rel}: не удалось разобрать ({exc})"]
    visitor = _Visitor(rel)
    visitor.visit(tree)
    return [f"{rel}:{line}: {msg}" for line, msg in sorted(visitor.violations)]


def main(argv: list[str]) -> int:
    targets = argv[1:] or ["kitsune"]
    root = Path(__file__).resolve().parent.parent
    errors: list[str] = []
    for target in targets:
        base = (root / target).resolve()
        if base.is_file():
            files = [base]
        else:
            files = sorted(base.rglob("*.py"))
        for file in files:
            errors.extend(check_file(file, root))
    if errors:
        print("Обнаружены пропущенные await у асинхронных методов БД:")
        for err in errors:
            print(f"  {err}")
        print(
            "\nОберни вызов в await, либо в asyncio.create_task/ensure_future, "
            "либо добавь обоснованное исключение в ALLOWLIST."
        )
        return 1
    print("check_missing_await: пропущенных await не найдено.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
