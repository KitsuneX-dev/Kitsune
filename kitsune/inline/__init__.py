from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .core import InlineManager

__all__ = ["InlineManager"]

def __getattr__(name: str) -> Any:
    if name == "InlineManager":
        from .core import InlineManager as _InlineManager
        return _InlineManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
