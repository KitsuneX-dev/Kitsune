from __future__ import annotations

import ast
import hashlib
import logging
import string
import typing
from collections import OrderedDict

from . import disk_cache as _disk_cache

logger = logging.getLogger(__name__)

_AST_CACHE_MAX_SIZE: int = 128
_BLOCKED_IMPORTS: frozenset[str] = frozenset({
    "subprocess", "pty", "ctypes", "multiprocessing",
    "socket", "pickle", "marshal",
    "code", "codeop", "compileall", "py_compile",
    "shelve", "dbm", "zipimport", "zipapp",
    "runpy", "distutils",
})

_DANGEROUS_OS_ATTRS: frozenset[str] = frozenset({
    "system", "popen", "execv", "execve", "execvp", "execvpe",
    "execl", "execle", "execlp", "execlpe",
    "spawnl", "spawnle", "spawnlp", "spawnlpe",
    "spawnv", "spawnve", "spawnvp", "spawnvpe",
    "fork", "forkpty", "kill",
    "_getframe", "currentframe",
})

_BLOCKED_ATTRS: frozenset[str] = frozenset({
    "__import__", "__loader__", "__builtins__",
    "system", "popen", "Popen", "call", "run",
})

_SOFT_ESCAPE_ATTRS: frozenset[str] = frozenset({
    "__class__",
    "__self__",
    "__func__",
})

_HARD_ESCAPE_ATTRS: frozenset[str] = frozenset({
    "__base__",
    "__bases__",
    "__mro__",
    "__subclasses__",
    "__globals__",
    "func_globals",
    "__code__",
    "func_code",
    "__closure__",
    "__getattribute__",
    "__reduce__",
    "__reduce_ex__",
    "f_globals",
    "f_builtins",
    "f_locals",
    "f_back",
    "gi_frame",
    "cr_frame",
    "tb_frame",
    "__traceback__",
})


_SANDBOX_ESCAPE_ATTRS: frozenset[str] = _SOFT_ESCAPE_ATTRS | _HARD_ESCAPE_ATTRS

_ALIAS_TRACKED_MODULES: frozenset[str] = frozenset({
    "os", "sys", "shutil", "importlib", "operator",
})

_DESTRUCTIVE_ATTRS: dict[str, frozenset[str]] = {
    "os": frozenset({"remove", "unlink"}),
    "shutil": frozenset({"rmtree"}),
}

_ASYNC_SUBPROCESS_ATTRS: frozenset[str] = frozenset({
    "create_subprocess_shell",
    "create_subprocess_exec",
    "subprocess_shell",
    "subprocess_exec",
})

_SENSITIVE_MODULE_KEYS: frozenset[str] = frozenset(
    set(_ALIAS_TRACKED_MODULES)
    | set(_BLOCKED_IMPORTS)
    | {"asyncio", "builtins", "__builtin__", "posix", "nt", "_posixsubprocess"}
)

_INDIRECT_ATTR_HELPERS: frozenset[str] = frozenset({"attrgetter", "methodcaller"})

_SENSITIVE_ATTR_NAMES: frozenset[str] = frozenset(
    set(_DANGEROUS_OS_ATTRS)
    | set(_ASYNC_SUBPROCESS_ATTRS)
    | set(_BLOCKED_ATTRS)
    | set(_SANDBOX_ESCAPE_ATTRS)
    | {attr for attrs in _DESTRUCTIVE_ATTRS.values() for attr in attrs}
)

_WILDCARD_BLOCKED_MODULES: frozenset[str] = _SENSITIVE_MODULE_KEYS

_MODULE_REGISTRY_METHODS: frozenset[str] = frozenset({
    "get", "pop", "setdefault",
})


_FORMAT_METHODS: frozenset[str] = frozenset({
    "format", "format_map", "vformat", "get_field",
})

_SENSITIVE_PATH_HINTS: tuple[str, ...] = ("session", ".key", "config.toml")

class _ASTScanner(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.soft_findings: list[str] = []
        self._aliases: dict[str, str] = {}
        self._registry_aliases: set[str] = set()
        self._import_callables: set[str] = {"__import__"}
        self._attr_helpers: dict[str, str] = {}

    @staticmethod
    def _is_dynamic_arg(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant):
            return False
        return True

    @staticmethod
    def _const_value(node: ast.expr) -> typing.Any:
        return node.value if isinstance(node, ast.Constant) else None

    @classmethod
    def _folded_str(cls, node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant):
            return node.value if isinstance(node.value, str) else None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = cls._folded_str(node.left)
            right = cls._folded_str(node.right)
            if left is not None and right is not None:
                return left + right
            return None
        if isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                else:
                    return None
            return "".join(parts)
        return None

    @staticmethod
    def _field_path_sensitive_attr(field_name: str) -> str | None:
        normalized = field_name.replace("[", ".").replace("]", ".")
        for part in normalized.split("."):
            part = part.strip().strip("'\"")
            if part in _SENSITIVE_ATTR_NAMES:
                return part
        return None

    @classmethod
    def _format_template_sensitive_attr(cls, template: str, depth: int = 0) -> str | None:
        if depth > 4:
            return None
        try:
            parsed = list(string.Formatter().parse(template))
        except (ValueError, IndexError):

            return None
        for _literal, field_name, format_spec, _conversion in parsed:
            if field_name:
                hit = cls._field_path_sensitive_attr(field_name)
                if hit is not None:
                    return hit
            if format_spec and "{" in format_spec:
                nested = cls._format_template_sensitive_attr(format_spec, depth + 1)
                if nested is not None:
                    return nested
        return None

    def _check_format_call(self, node: ast.Call, method: str) -> None:
        if method == "get_field":

            field = self._folded_str(node.args[0]) if node.args else None
            if field is None:
                return
            hit = self._field_path_sensitive_attr(field)
            if hit is not None:
                self.errors.append(
                    f"Blocked sandbox escape attribute via Formatter.get_field: "
                    f"{hit} (line {node.lineno})"
                )
            return

        template: str | None = None
        if method == "vformat":

            template = self._folded_str(node.args[0]) if node.args else None
        if template is None and isinstance(node.func, ast.Attribute):

            template = self._folded_str(node.func.value)
        if template is None:
            return
        hit = self._format_template_sensitive_attr(template)
        if hit is not None:
            self.errors.append(
                f"Blocked sandbox escape attribute via format string: {hit} "
                f"(line {node.lineno})"
            )

    def _is_module_registry(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Attribute) and node.attr == "modules":
            return self._resolve_module(node.value) == "sys"
        if isinstance(node, ast.Name):
            return node.id in self._registry_aliases
        return False

    @staticmethod
    def _sensitive_module_key(key: str | None) -> str | None:
        if not key:
            return None
        root = key.split(".")[0]
        return root if root in _SENSITIVE_MODULE_KEYS else None

    def _registry_lookup_module(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Subscript) and self._is_module_registry(node.value):
            slice_node = node.slice
            if isinstance(slice_node, ast.Index):
                slice_node = getattr(slice_node, "value", slice_node)
            return self._sensitive_module_key(self._folded_str(slice_node))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _MODULE_REGISTRY_METHODS
            and self._is_module_registry(node.func.value)
            and node.args
        ):
            return self._sensitive_module_key(self._folded_str(node.args[0]))
        return None

    def _resolve_module(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return self._aliases.get(node.id, node.id)
        if isinstance(node, ast.Subscript):
            return self._registry_lookup_module(node)
        if isinstance(node, ast.Call):
            registry = self._registry_lookup_module(node)
            if registry is not None:
                return registry
            module = self._import_call_module(node)
            if isinstance(module, str):
                root = module.split(".")[0]
                if root in _ALIAS_TRACKED_MODULES:
                    return root
        return None

    @staticmethod
    def _static_str(node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
            return "".join(parts) if parts else None
        return None

    def _is_import_callable(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self._import_callables
        if isinstance(node, ast.Attribute) and node.attr == "import_module":
            return self._resolve_module(node.value) == "importlib"
        return False

    def _resolve_attr_helper(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return self._attr_helpers.get(node.id)
        if isinstance(node, ast.Attribute) and node.attr in _INDIRECT_ATTR_HELPERS:
            if self._resolve_module(node.value) == "operator":
                return node.attr
        return None

    def _import_call_module(self, node: ast.Call) -> typing.Any:
        func = node.func
        if not node.args:
            return None
        if isinstance(func, ast.Name) and func.id in self._import_callables:
            return self._const_value(node.args[0])
        if isinstance(func, ast.Attribute) and func.attr == "import_module":
            return self._const_value(node.args[0])
        return None

    def _bind_import_alias(self, node: ast.expr, target: ast.expr) -> None:
        if not isinstance(target, ast.Name):
            return
        if self._is_module_registry(node):
            self._registry_aliases.add(target.id)
            return
        if self._is_import_callable(node):
            self._import_callables.add(target.id)
            return
        helper = self._resolve_attr_helper(node)
        if helper is not None:
            self._attr_helpers[target.id] = helper
            return
        module: str | None = None
        if isinstance(node, ast.Call):
            module = self._registry_lookup_module(node) or self._import_call_module(node)
        elif isinstance(node, ast.Subscript):
            module = self._registry_lookup_module(node)
        elif isinstance(node, ast.Name):
            resolved = self._aliases.get(node.id)
            if resolved:
                module = resolved
        if isinstance(module, str):
            root = module.split(".")[0]
            if root in _ALIAS_TRACKED_MODULES or root in _SENSITIVE_MODULE_KEYS:
                self._aliases[target.id] = root

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in _BLOCKED_IMPORTS:
                self.errors.append(f"Blocked import: {alias.name} (line {node.lineno})")
            if root in _ALIAS_TRACKED_MODULES:
                self._aliases[alias.asname or root] = root
        self.generic_visit(node)
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root = node.module.split(".")[0]
            if root in _BLOCKED_IMPORTS:
                self.errors.append(f"Blocked import: {node.module} (line {node.lineno})")
            if root in _WILDCARD_BLOCKED_MODULES:
                for alias in node.names:
                    if alias.name == "*":
                        self.errors.append(
                            f"Blocked wildcard import from {node.module} (line {node.lineno})"
                        )
                        break
            if root == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        self._import_callables.add(alias.asname or alias.name)
            if root == "operator":
                for alias in node.names:
                    if alias.name in _INDIRECT_ATTR_HELPERS:
                        self._attr_helpers[alias.asname or alias.name] = alias.name
            if root == "os":
                for alias in node.names:
                    if alias.name in _DANGEROUS_OS_ATTRS:
                        self.errors.append(
                            f"Blocked from-import of {root}.{alias.name} (line {node.lineno})"
                        )
            if root == "asyncio":
                for alias in node.names:
                    if alias.name in _ASYNC_SUBPROCESS_ATTRS:
                        self.errors.append(
                            f"Blocked from-import of asyncio.{alias.name} (line {node.lineno})"
                        )
            destructive = _DESTRUCTIVE_ATTRS.get(root, frozenset())
            for alias in node.names:
                if alias.name in destructive:
                    self.errors.append(
                        f"Blocked from-import of {root}.{alias.name} (line {node.lineno})"
                    )
        self.generic_visit(node)

    def _check_import_call(self, node: ast.Call, label: str) -> None:
        if not node.args:
            self.errors.append(
                f"Blocked {label} without arguments (line {node.lineno})"
            )
            return
        if self._is_dynamic_arg(node.args[0]):
            self.errors.append(
                f"Blocked dynamic {label} call (line {node.lineno})"
            )
            return
        const_arg = self._const_value(node.args[0])
        root = str(const_arg).split(".")[0]
        if root in _BLOCKED_IMPORTS:
            self.errors.append(
                f"Blocked {label}: {const_arg!r} (line {node.lineno})"
            )

    def _check_attr_helper_call(self, node: ast.Call, helper: str) -> None:
        if not node.args:
            self.errors.append(
                f"Blocked operator.{helper}() without arguments (line {node.lineno})"
            )
            return
        folded = self._folded_str(node.args[0])
        if folded is None:
            self.errors.append(
                f"Blocked dynamic operator.{helper}() attribute name (line {node.lineno})"
            )
            return
        for part in folded.split("."):
            if part in _SENSITIVE_ATTR_NAMES:
                self.errors.append(
                    f"Blocked operator.{helper}() access to {part!r} (line {node.lineno})"
                )
                return

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._bind_import_alias(node.value, target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._bind_import_alias(node.value, node.target)
        self.generic_visit(node)
    def visit_Call(self, node: ast.Call) -> None:

        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _MODULE_REGISTRY_METHODS
            and self._is_module_registry(node.func.value)
            and node.args
        ):
            sensitive = self._sensitive_module_key(self._folded_str(node.args[0]))
            if sensitive is not None:
                self.errors.append(
                    f"Blocked module registry lookup of {sensitive!r} (line {node.lineno})"
                )

        helper = self._resolve_attr_helper(node.func)
        if helper is not None:
            self._check_attr_helper_call(node, helper)

        if isinstance(node.func, ast.Attribute) and node.func.attr in _FORMAT_METHODS:
            self._check_format_call(node, node.func.attr)

        if isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
            if self._resolve_module(node.func.value) == "importlib":
                self._check_import_call(node, "importlib.import_module")
        elif isinstance(node.func, ast.Name) and node.func.id in self._import_callables:
            label = (
                "__import__"
                if node.func.id == "__import__"
                else f"import_module (bound as {node.func.id!r})"
            )
            self._check_import_call(node, label)
        if isinstance(node.func, ast.Name) and node.func.id in ("exec", "eval"):
            for arg in node.args:
                if isinstance(arg, ast.Call):
                    if isinstance(arg.func, ast.Attribute) and arg.func.attr in (
                        "b64decode", "b32decode", "b16decode", "decode",
                        "decompress", "decodestring",
                    ):
                        self.errors.append(
                            f"Blocked obfuscated {node.func.id}() with encoded payload (line {node.lineno})"
                        )
                    if isinstance(arg.func, ast.Attribute) and isinstance(arg.func.value, ast.Call):
                        inner = arg.func.value
                        if isinstance(inner.func, ast.Name) and inner.func.id in self._import_callables:
                            self.errors.append(
                                f"Blocked obfuscated {node.func.id}() via __import__ chain (line {node.lineno})"
                            )

        if isinstance(node.func, ast.Name) and node.func.id == "getattr":


            folded_attr = (
                self._folded_str(node.args[1]) if len(node.args) >= 2 else None
            )
            if folded_attr is not None:
                attr = folded_attr
                if attr in _SANDBOX_ESCAPE_ATTRS:
                    self.errors.append(
                        f"Blocked sandbox escape attribute via getattr: {attr} "
                        f"(line {node.lineno})"
                    )
                elif (
                    attr in _BLOCKED_ATTRS
                    or attr in _DANGEROUS_OS_ATTRS
                    or attr in _ASYNC_SUBPROCESS_ATTRS
                ):
                    self.errors.append(
                        f"Blocked getattr access to {attr!r} (line {node.lineno})"
                    )
            elif len(node.args) >= 2 and not isinstance(node.args[1], ast.Constant):


                target_module = self._resolve_module(node.args[0])
                if target_module in _ALIAS_TRACKED_MODULES:
                    self.errors.append(
                        f"Blocked getattr with computed attribute name on {target_module} "
                        f"(line {node.lineno})"
                    )
        if isinstance(node.func, ast.Name) and node.func.id == "open" and node.args:
            hinted = self._static_str(node.args[0])
            if hinted is not None:
                lowered = hinted.lower()
                for hint in _SENSITIVE_PATH_HINTS:
                    if hint in lowered:
                        self.warnings.append(
                            f"Suspicious open() of path containing {hint!r}: "
                            f"{hinted!r} (line {node.lineno})"
                        )
                        break
        if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec", "compile"):
            if not node.args:
                self.errors.append(
                    f"Blocked {node.func.id} without arguments (line {node.lineno})"
                )
            elif self._is_dynamic_arg(node.args[0]):

                self.errors.append(
                    f"Blocked dynamic {node.func.id} call (line {node.lineno})"
                )
            else:
                src = str(self._const_value(node.args[0]))
                low = src.lower()
                bad_tokens = list(_BLOCKED_IMPORTS) + ["__import__", "__builtins__", "os.system", "os.popen", "os.exec"]
                for blocked in bad_tokens:
                    if blocked in low:
                        self.errors.append(
                            f"Blocked {node.func.id}() containing {blocked!r} (line {node.lineno})"
                        )
                        break
        if isinstance(node.func, ast.Attribute) and node.func.attr in _ASYNC_SUBPROCESS_ATTRS:
            self.errors.append(
                f"Blocked asyncio subprocess spawn (line {node.lineno})"
            )
        if isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            base_module = self._resolve_module(node.func.value)
            if base_module == "os" and attr_name in _DANGEROUS_OS_ATTRS:
                self.errors.append(
                    f"Blocked os.{attr_name}() call (line {node.lineno})"
                )
            if base_module and attr_name in _DESTRUCTIVE_ATTRS.get(base_module, frozenset()):
                self.errors.append(
                    f"Blocked destructive {base_module}.{attr_name}() call (line {node.lineno})"
                )
        self.generic_visit(node)
    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _BLOCKED_ATTRS:
            if isinstance(node.value, ast.Name) and node.value.id in _BLOCKED_IMPORTS:
                self.errors.append(
                    f"Blocked attribute access: {node.value.id}.{node.attr} (line {node.lineno})"
                )
        base_module = self._resolve_module(node.value)
        if base_module == "os" and node.attr in _DANGEROUS_OS_ATTRS:
            self.errors.append(
                f"Blocked os.{node.attr} access (line {node.lineno})"
            )
        if base_module and node.attr in _DESTRUCTIVE_ATTRS.get(base_module, frozenset()):
            self.errors.append(
                f"Blocked destructive {base_module}.{node.attr} access (line {node.lineno})"
            )
        if base_module in _ALIAS_TRACKED_MODULES and node.attr == "__dict__":
            self.errors.append(
                f"Blocked {base_module}.__dict__ access (line {node.lineno})"
            )
        if node.attr in ("__builtins__", "__loader__", "__import__"):
            self.errors.append(
                f"Blocked dunder attribute access: {node.attr} (line {node.lineno})"
            )
        if node.attr in _HARD_ESCAPE_ATTRS:
            self.errors.append(
                f"Blocked sandbox escape attribute access: {node.attr} "
                f"(line {node.lineno})"
            )
        elif node.attr in _SOFT_ESCAPE_ATTRS:
            msg = (
                f"Sandbox escape attribute requires confirmation: {node.attr} "
                f"(line {node.lineno})"
            )
            self.soft_findings.append(msg)
            self.warnings.append(msg)
        self.generic_visit(node)
    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._is_module_registry(node.value):
            slice_node = node.slice
            if isinstance(slice_node, ast.Index):
                slice_node = getattr(slice_node, "value", slice_node)
            folded = self._folded_str(slice_node)
            sensitive = self._sensitive_module_key(folded)
            if sensitive is not None:
                self.errors.append(
                    f"Blocked module registry access to {sensitive!r} (line {node.lineno})"
                )
            elif folded is None and isinstance(node.ctx, ast.Load):
                self.warnings.append(
                    f"Module registry accessed with a computed key (line {node.lineno})"
                )


        slice_node = node.slice
        if isinstance(slice_node, ast.Index):
            slice_node = getattr(slice_node, "value", slice_node)
        subscript_key: str | None = self._folded_str(slice_node)
        if (
            subscript_key is None
            and isinstance(slice_node, ast.Constant)
            and isinstance(slice_node.value, str)
        ):
            subscript_key = slice_node.value
        if isinstance(node.value, ast.Name) and node.value.id == "__builtins__":
            self.errors.append(
                f"Blocked __builtins__ subscript access (line {node.lineno})"
            )
        elif subscript_key is not None:
            if subscript_key in _SANDBOX_ESCAPE_ATTRS:
                self.errors.append(
                    f"Blocked sandbox escape attribute via subscript "
                    f"[{subscript_key!r}] (line {node.lineno})"
                )
            elif subscript_key in ("__builtins__", "__import__", "__loader__"):
                self.errors.append(
                    f"Blocked {subscript_key} subscript access (line {node.lineno})"
                )
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            ns_func = node.value.func.id
            if ns_func in ("globals", "locals", "vars"):
                slice_node = node.slice
                if isinstance(slice_node, ast.Index):
                    slice_node = getattr(slice_node, "value", slice_node)
                key = self._folded_str(slice_node)
                if key is None and isinstance(slice_node, ast.Constant):
                    key = str(slice_node.value)
                if key is not None:


                    if key in _SANDBOX_ESCAPE_ATTRS:
                        self.errors.append(
                            f"Blocked sandbox escape attribute via {ns_func}()"
                            f"[{key!r}] (line {node.lineno})"
                        )
                    elif (
                        key in _BLOCKED_IMPORTS
                        or key in _BLOCKED_ATTRS
                        or key in _DANGEROUS_OS_ATTRS
                        or key in _ASYNC_SUBPROCESS_ATTRS
                        or key in ("os", "sys", "builtins", "__builtins__", "__import__")
                    ):
                        self.errors.append(
                            f"Blocked {ns_func}()[{key!r}] subscript access (line {node.lineno})"
                        )
                else:
                    self.errors.append(
                        f"Blocked dynamic {ns_func}()[...] subscript access (line {node.lineno})"
                    )
        self.generic_visit(node)
def _scan_ast(
    source: str,
    filename: str = "<module>",
    _out_findings: list[str] | None = None,
) -> ast.AST:
    from . import ASTSecurityError, ModuleLoadError

    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise ModuleLoadError(f"Syntax error: {exc}") from exc
    scanner = _ASTScanner()
    scanner.visit(tree)
    for warning in scanner.warnings:
        logger.warning("AST scan: %s: %s", filename, warning)
    if scanner.errors:
        raise ASTSecurityError(
            "Security scan failed:\n" + "\n".join(f"  • {e}" for e in scanner.errors)
        )
    if _out_findings is not None:
        _out_findings.extend(scanner.soft_findings)
    return tree

_ast_cache: OrderedDict[str, ast.AST] = OrderedDict()


_ast_soft_findings_cache: OrderedDict[str, list[str]] = OrderedDict()

def _scan_ast_with_cache(source: str, filename: str = "<module>") -> list[str]:
    key = hashlib.sha256(source.encode()).hexdigest()
    cached = _ast_cache.get(key)
    if cached is not None:
        _ast_cache.move_to_end(key)
        cached_findings = _ast_soft_findings_cache.get(key, [])
        if key in _ast_soft_findings_cache:
            _ast_soft_findings_cache.move_to_end(key)
        return list(cached_findings)
    if not _disk_cache._ast_scan_ok_loaded:
        _disk_cache._load_ast_scan_cache()
    if key in _disk_cache._ast_scan_ok_hashes:


        return list(_ast_soft_findings_cache.get(key, []))
    findings: list[str] = []
    tree = _scan_ast(source, filename, _out_findings=findings)
    _ast_cache[key] = tree
    _ast_cache.move_to_end(key)
    _ast_soft_findings_cache[key] = list(findings)
    _ast_soft_findings_cache.move_to_end(key)
    while len(_ast_cache) > _AST_CACHE_MAX_SIZE:
        evicted, _ = _ast_cache.popitem(last=False)
        _ast_soft_findings_cache.pop(evicted, None)
    while len(_ast_soft_findings_cache) > _AST_CACHE_MAX_SIZE:
        _ast_soft_findings_cache.popitem(last=False)
    _disk_cache._remember_ast_scan_ok(key)
    return list(findings)

def _ast_cache_clear() -> None:
    _ast_cache.clear()
    _ast_soft_findings_cache.clear()
    _disk_cache._ast_scan_ok_hashes.clear()
    _disk_cache._ast_scan_ok_pending = 0

    _disk_cache._ast_scan_ok_loaded = True


_LEGACY_RELATIVE_NAMES = frozenset({"loader"})
_LEGACY_DECORATOR_ATTRS = frozenset({"command", "watcher", "loop", "raw_handler"})


_LEGACY_LOADER_ATTRS_EXTRA = frozenset({"Module", "tds", "unrestricted"})


_LEGACY_TOP_PACKAGES = frozenset(
    {"hikka", "hikkatl", "hikkamods", "heroku", "herokutl", "hikkapyro"}
)


def detect_legacy_api(source: str) -> str | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):


            if node.level and node.level >= 2:
                imported = {alias.name for alias in node.names}
                for name in imported:
                    if name in _LEGACY_RELATIVE_NAMES:
                        return f"from {'.' * node.level} import {name}"
                if node.module in _LEGACY_RELATIVE_NAMES:
                    return f"from {'.' * node.level}{node.module} import ..."
            elif not node.level and node.module:
                top = node.module.split(".")[0]
                if top in _LEGACY_TOP_PACKAGES:
                    return f"from {node.module} import ..."
                if top in _LEGACY_RELATIVE_NAMES:
                    return f"from {node.module} import ..."
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _LEGACY_TOP_PACKAGES or top in _LEGACY_RELATIVE_NAMES:
                    return f"import {alias.name}"
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "loader":
                if node.attr in _LEGACY_DECORATOR_ATTRS:
                    return f"@loader.{node.attr}"
                if node.attr in _LEGACY_LOADER_ATTRS_EXTRA:
                    return f"loader.{node.attr}"
    return None


LEGACY_API_BLOCK_MESSAGE = (
    "🦊 Kitsune: ой-ой, чужой модуль не подошёл!\n"
    "Kitsune — независимый юзербот со своим загрузчиком, а не форк "
    "Hikka, поэтому модули от других юзерботов не приживутся: "
    "Hikka/Heroku/Legacy-модули не поддерживаются.\n"
    "❌ Лапки опущены: установка отменена, модуль не совместим с Kitsune."
)
