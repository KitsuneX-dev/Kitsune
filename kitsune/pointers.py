from __future__ import annotations
import typing

class Pointer:
    def __init__(
        self,
        db: typing.Any,
        owner: str,
        key: str,
        default: typing.Any = None,
    ) -> None:
        self._db = db
        self._owner = owner
        self._key = key
        self._default = default
    def get(self) -> typing.Any:
        return self._db.get(self._owner, self._key, self._default)
    async def set(self, value: typing.Any) -> None:
        await self._db.set(self._owner, self._key, value)
    async def remove(self) -> None:
        remover = getattr(self._db, "delete", None) or getattr(self._db, "remove", None)
        if remover is None:
            raise AttributeError("database backend has no delete/remove method")
        await remover(self._owner, self._key)
    def __repr__(self) -> str:
        return f"Pointer({self._owner!r}, {self._key!r}) = {self.get()!r}"
class BoolPointer(Pointer):
    def __init__(self, db: typing.Any, owner: str, key: str, default: bool = False) -> None:
        super().__init__(db, owner, key, default)
    def get(self) -> bool:
        return bool(self._db.get(self._owner, self._key, self._default))
    async def toggle(self) -> bool:
        new_val = not self.get()
        await self.set(new_val)
        return new_val
class ListPointer(Pointer):
    def __init__(self, db: typing.Any, owner: str, key: str) -> None:
        super().__init__(db, owner, key, [])
    def get(self) -> list:
        val = self._db.get(self._owner, self._key, [])
        return val if isinstance(val, list) else []
    async def append(self, item: typing.Any) -> None:
        lst = self.get()
        if item not in lst:
            lst.append(item)
            await self.set(lst)
    async def remove(self, item: typing.Any) -> bool:  # type: ignore[override]
        lst = self.get()
        if item in lst:
            lst.remove(item)
            await self.set(lst)
            return True
        return False
    def __contains__(self, item: typing.Any) -> bool:
        return item in self.get()
    def __len__(self) -> int:
        return len(self.get())
    def __iter__(self):
        return iter(self.get())
class IntPointer(Pointer):
    def __init__(self, db: typing.Any, owner: str, key: str, default: int = 0) -> None:
        super().__init__(db, owner, key, default)
        self._int_default: int = default
    def get(self) -> int:
        try:
            return int(self._db.get(self._owner, self._key, self._int_default))
        except (TypeError, ValueError):
            return self._int_default
    async def increment(self, by: int = 1) -> int:
        new_val = self.get() + by
        await self.set(new_val)
        return new_val
    async def decrement(self, by: int = 1) -> int:
        return await self.increment(-by)


def _db_set_sync(db: typing.Any, owner: str, key: str, value: typing.Any) -> None:
    setter = getattr(db, "set_sync", None) or getattr(db, "force_set", None)
    if setter is not None:
        setter(owner, key, value)
        return
    result = db.set(owner, key, value)
    if hasattr(result, "__await__"):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(result)
        else:
            asyncio.new_event_loop().run_until_complete(result)


class PointerList(list):

    def __init__(
        self,
        db: typing.Any,
        module: str,
        key: str,
        default: typing.Optional[typing.Any] = None,
    ) -> None:
        self._db = db
        self._module = module
        self._key = key
        self._default = default
        super().__init__(db.get(module, key, default) or [])

    @property
    def data(self) -> list:
        return list(self)

    @data.setter
    def data(self, value: list) -> None:
        super().clear()
        super().extend(value)
        self._save()

    def __repr__(self) -> str:
        return f"PointerList({list(self)})"

    def __str__(self) -> str:
        return f"PointerList({list(self)})"

    def __delitem__(self, __i: typing.Union[typing.SupportsIndex, slice]) -> None:
        a = super().__delitem__(__i)
        self._save()
        return a

    def __setitem__(self, __i: typing.Any, __v: typing.Any) -> None:
        a = super().__setitem__(__i, __v)
        self._save()
        return a

    def __iadd__(self, __x: typing.Iterable) -> "PointerList":  # type: ignore[misc]
        a = super().__iadd__(__x)
        self._save()
        return a

    def __imul__(self, __x: typing.SupportsIndex) -> "PointerList":
        a = super().__imul__(__x)
        self._save()
        return a

    def append(self, value: typing.Any) -> None:
        super().append(value)
        self._save()

    def extend(self, value: typing.Iterable) -> None:
        super().extend(value)
        self._save()

    def insert(self, index: typing.SupportsIndex, value: typing.Any) -> None:
        super().insert(index, value)
        self._save()

    def remove(self, value: typing.Any) -> None:
        super().remove(value)
        self._save()

    def pop(self, index: typing.SupportsIndex = -1) -> typing.Any:
        a = super().pop(index)
        self._save()
        return a

    def clear(self) -> None:
        super().clear()
        self._save()

    def _save(self) -> None:
        _db_set_sync(self._db, self._module, self._key, list(self))

    def tolist(self) -> list:
        return self._db.get(self._module, self._key, self._default)


class PointerDict(dict):

    def __init__(
        self,
        db: typing.Any,
        module: str,
        key: str,
        default: typing.Optional[typing.Any] = None,
    ) -> None:
        self._db = db
        self._module = module
        self._key = key
        self._default = default
        super().__init__(db.get(module, key, default) or {})

    @property
    def data(self) -> dict:
        return dict(self)

    @data.setter
    def data(self, value: dict) -> None:
        super().clear()
        super().update(value)
        self._save()

    def __repr__(self) -> str:
        return f"PointerDict({dict(self)})"

    def __str__(self) -> str:
        return f"PointerDict({dict(self)})"

    def __bool__(self) -> bool:
        return bool(self._db.get(self._module, self._key, self._default))

    def __setitem__(self, key: str, value: typing.Any) -> None:
        super().__setitem__(key, value)
        self._save()

    def __delitem__(self, key: str) -> None:
        super().__delitem__(key)
        self._save()

    def update(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        super().update(*args, **kwargs)
        self._save()

    def setdefault(self, key: str, default: typing.Any = None) -> typing.Any:
        a = super().setdefault(key, default)
        self._save()
        return a

    def pop(self, key: str, default: typing.Any = None) -> typing.Any:
        a = super().pop(key, default)
        self._save()
        return a

    def popitem(self) -> tuple:
        a = super().popitem()
        self._save()
        return a

    def clear(self) -> None:
        super().clear()
        self._save()

    def _save(self) -> None:
        _db_set_sync(self._db, self._module, self._key, dict(self))

    def todict(self) -> dict:
        return self._db.get(self._module, self._key, self._default)


class BaseSerializingMiddlewareDict:
    def __init__(self, pointer: PointerDict) -> None:
        self._pointer = pointer

    def serialize(self, item: typing.Any) -> typing.Any:
        raise NotImplementedError

    def deserialize(self, item: typing.Any) -> typing.Any:
        raise NotImplementedError

    def __getitem__(self, key: typing.Any) -> typing.Any:
        return self.deserialize(self._pointer[key])

    def __setitem__(self, key: typing.Any, value: typing.Any) -> None:
        self._pointer[key] = self.serialize(value)

    def __delitem__(self, key: typing.Any) -> None:
        del self._pointer[key]

    def __iter__(self) -> typing.Iterator[typing.Any]:
        for key, value in self._pointer.items():
            yield (key, self.deserialize(value))

    def __len__(self) -> int:
        return len(self._pointer)

    def __contains__(self, item: typing.Any) -> bool:
        return item in self._pointer

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self._pointer})"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._pointer})"

    def pop(self, key: typing.Any) -> typing.Any:
        return self.deserialize(self._pointer.pop(key))

    def popitem(self) -> typing.Any:
        return self.deserialize(self._pointer.popitem())

    def get(self, key: typing.Any, default: typing.Any = None) -> typing.Any:
        return self.deserialize(self._pointer[key]) if key in self._pointer else default

    def setdefault(self, key: typing.Any, default: typing.Any = None) -> typing.Any:
        return self.deserialize(self._pointer.setdefault(key, self.serialize(default)))

    def clear(self) -> None:
        self._pointer.clear()

    def todict(self) -> dict:
        return {
            key: self.deserialize(value) for key, value in self._pointer.data.items()
        }

    def keys(self) -> typing.KeysView:
        return self._pointer.keys()

    def values(self) -> typing.Iterable[typing.Any]:
        return (self.deserialize(value) for value in self._pointer.values())


class BaseSerializingMiddlewareList:
    def __init__(self, pointer: PointerList) -> None:
        self._pointer = pointer

    def serialize(self, item: typing.Any) -> typing.Any:
        raise NotImplementedError

    def deserialize(self, item: typing.Any) -> typing.Any:
        raise NotImplementedError

    def remove(self, item: typing.Any) -> None:
        self._pointer.remove(self.serialize(item))

    def pop(self, index: int) -> typing.Any:
        return self.deserialize(self._pointer.pop(index))

    def insert(self, index: int, item: typing.Any) -> None:
        self._pointer.insert(index, self.serialize(item))

    def append(self, item: typing.Any) -> None:
        self._pointer.append(self.serialize(item))

    def extend(self, items: typing.Iterable[typing.Any]) -> None:
        self._pointer.extend([self.serialize(item) for item in items])

    def __getitem__(self, key: typing.Any) -> typing.Any:
        return self.deserialize(self._pointer[key])

    def __setitem__(self, key: typing.Any, value: typing.Any) -> None:
        self._pointer[key] = self.serialize(value)

    def __delitem__(self, key: typing.Any) -> None:
        del self._pointer[key]

    def __iter__(self) -> typing.Iterator[typing.Any]:
        return (self.deserialize(item) for item in self._pointer)

    def __len__(self) -> int:
        return len(self._pointer)

    def __contains__(self, item: typing.Any) -> bool:
        return self.serialize(item) in self._pointer

    def __reversed__(self) -> typing.Iterator[typing.Any]:
        return (self.deserialize(item) for item in reversed(self._pointer))

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self._pointer})"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._pointer})"

    def tolist(self) -> list:
        return [self.deserialize(item) for item in self._pointer.data]


class NamedTupleMiddlewareList(BaseSerializingMiddlewareList):
    def __init__(self, pointer: PointerList, item_type: typing.Type[typing.Any]) -> None:
        super().__init__(pointer)
        self._item_type = item_type

    def serialize(self, item: typing.Any) -> typing.Any:
        return item._asdict()

    def deserialize(self, item: typing.Any) -> typing.Any:
        return self._item_type(**item)


class NamedTupleMiddlewareDict(BaseSerializingMiddlewareDict):
    def __init__(self, pointer: PointerDict, item_type: typing.Type[typing.Any]) -> None:
        super().__init__(pointer)
        self._item_type = item_type

    def serialize(self, item: typing.Any) -> typing.Any:
        return item._asdict()

    def deserialize(self, item: typing.Any) -> typing.Any:
        return self._item_type(**item)
