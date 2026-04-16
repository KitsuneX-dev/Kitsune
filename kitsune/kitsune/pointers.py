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
        await self._db.remove(self._owner, self._key)

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

    async def remove(self, item: typing.Any) -> bool:
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

    def get(self) -> int:
        try:
            return int(self._db.get(self._owner, self._key, self._default))
        except (TypeError, ValueError):
            return self._default

    async def increment(self, by: int = 1) -> int:
        new_val = self.get() + by
        await self.set(new_val)
        return new_val

    async def decrement(self, by: int = 1) -> int:
        return await self.increment(-by)
