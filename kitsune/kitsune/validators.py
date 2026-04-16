from __future__ import annotations

import functools
import re
import typing

ConfigAllowedTypes = typing.Union[tuple, list, str, int, float, bool, None]

class ValidationError(Exception):
    pass

class Validator:

    def __init__(
        self,
        validator: callable,
        doc: typing.Optional[str] = None,
        _internal_id: typing.Optional[str] = None,
    ):
        self.validate = validator
        self.doc = doc or "any value"
        self.internal_id = _internal_id

class Boolean(Validator):

    def __init__(self):
        super().__init__(
            self._validate,
            doc="boolean (true / false)",
            _internal_id="Boolean",
        )

    @staticmethod
    def _validate(value: ConfigAllowedTypes, /) -> bool:
        true_vals = {"true", "1", "yes", "on", "y", True, 1}
        false_vals = {"false", "0", "no", "off", "n", False, 0}

        normalized = str(value).lower() if isinstance(value, str) else value

        if normalized in true_vals:
            return True
        if normalized in false_vals:
            return False

        raise ValidationError(
            f"Value «{value}» is not boolean. Use: true/false, 1/0, yes/no, on/off"
        )

class Integer(Validator):

    def __init__(
        self,
        *,
        minimum: typing.Optional[int] = None,
        maximum: typing.Optional[int] = None,
        digits: typing.Optional[int] = None,
    ):
        parts = ["integer"]
        if minimum is not None and maximum is not None:
            parts.append(f"from {minimum} to {maximum}")
        elif minimum is not None:
            parts.append(f"≥ {minimum}")
        elif maximum is not None:
            parts.append(f"≤ {maximum}")
        if digits is not None:
            parts.append(f"exactly {digits} digits")

        super().__init__(
            functools.partial(self._validate, minimum=minimum, maximum=maximum, digits=digits),
            doc=", ".join(parts),
            _internal_id="Integer",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        minimum: typing.Optional[int],
        maximum: typing.Optional[int],
        digits: typing.Optional[int],
    ) -> int:
        try:
            value = int(str(value).strip())
        except (ValueError, TypeError):
            raise ValidationError(f"«{value}» is not an integer")

        if minimum is not None and value < minimum:
            raise ValidationError(f"Value {value} is less than minimum ({minimum})")
        if maximum is not None and value > maximum:
            raise ValidationError(f"Value {value} is greater than maximum ({maximum})")
        if digits is not None and len(str(abs(value))) != digits:
            raise ValidationError(f"Value {value} must be exactly {digits} digits")

        return value

class Float(Validator):

    def __init__(
        self,
        *,
        minimum: typing.Optional[float] = None,
        maximum: typing.Optional[float] = None,
    ):
        parts = ["float number"]
        if minimum is not None and maximum is not None:
            parts.append(f"from {minimum} to {maximum}")
        elif minimum is not None:
            parts.append(f"≥ {minimum}")
        elif maximum is not None:
            parts.append(f"≤ {maximum}")

        super().__init__(
            functools.partial(self._validate, minimum=minimum, maximum=maximum),
            doc=", ".join(parts),
            _internal_id="Float",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        minimum: typing.Optional[float],
        maximum: typing.Optional[float],
    ) -> float:
        try:
            value = float(str(value).strip().replace(",", "."))
        except (ValueError, TypeError):
            raise ValidationError(f"«{value}» is not a float")

        if minimum is not None and value < minimum:
            raise ValidationError(f"Value {value} is less than minimum ({minimum})")
        if maximum is not None and value > maximum:
            raise ValidationError(f"Value {value} is greater than maximum ({maximum})")

        return value

class String(Validator):

    def __init__(
        self,
        length: typing.Optional[int] = None,
        min_len: typing.Optional[int] = None,
        max_len: typing.Optional[int] = None,
    ):
        parts = ["string"]
        if length is not None:
            parts.append(f"exactly {length} chars")
        else:
            if min_len is not None and max_len is not None:
                parts.append(f"{min_len}–{max_len} chars")
            elif min_len is not None:
                parts.append(f"at least {min_len} chars")
            elif max_len is not None:
                parts.append(f"up to {max_len} chars")

        super().__init__(
            functools.partial(self._validate, length=length, min_len=min_len, max_len=max_len),
            doc=", ".join(parts),
            _internal_id="String",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        length: typing.Optional[int],
        min_len: typing.Optional[int],
        max_len: typing.Optional[int],
    ) -> str:
        value = str(value)
        vlen = len(value)

        if length is not None and vlen != length:
            raise ValidationError(f"String must be exactly {length} chars (got {vlen})")
        if min_len is not None and vlen < min_len:
            raise ValidationError(f"String too short (min {min_len}, got {vlen})")
        if max_len is not None and vlen > max_len:
            raise ValidationError(f"String too long (max {max_len}, got {vlen})")

        return value

class RegExp(Validator):

    def __init__(
        self,
        regex: str,
        flags: typing.Optional[re.RegexFlag] = None,
        description: typing.Optional[str] = None,
    ):
        flags = flags or 0
        try:
            re.compile(regex, flags=flags)
        except re.error as exc:
            raise ValueError(f"Invalid regex: {regex}") from exc

        super().__init__(
            functools.partial(self._validate, regex=regex, flags=flags),
            doc=description or f"matches pattern {regex}",
            _internal_id="RegExp",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        regex: str,
        flags: typing.Optional[re.RegexFlag],
    ) -> str:
        if not re.match(regex, str(value), flags=flags or 0):
            raise ValidationError(f"«{value}» does not match pattern {regex}")
        return str(value)

class Choice(Validator):

    def __init__(self, possible_values: typing.List[ConfigAllowedTypes], /):
        options = " / ".join(str(v) for v in possible_values)
        super().__init__(
            functools.partial(self._validate, possible_values=possible_values),
            doc=f"one of: {options}",
            _internal_id="Choice",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        possible_values: typing.List[ConfigAllowedTypes],
    ) -> ConfigAllowedTypes:
        if value not in possible_values:
            options = " / ".join(str(v) for v in possible_values)
            raise ValidationError(f"«{value}» is not valid. Choose from: {options}")
        return value

class MultiChoice(Validator):

    def __init__(self, possible_values: typing.List[ConfigAllowedTypes], /):
        options = " / ".join(str(v) for v in possible_values)
        super().__init__(
            functools.partial(self._validate, possible_values=possible_values),
            doc=f"list of: {options}",
            _internal_id="MultiChoice",
        )

    @staticmethod
    def _validate(
        value: typing.Union[typing.List[ConfigAllowedTypes], ConfigAllowedTypes],
        /,
        *,
        possible_values: typing.List[ConfigAllowedTypes],
    ) -> typing.List[ConfigAllowedTypes]:
        if not isinstance(value, (list, tuple)):
            value = [value]

        for item in value:
            if item not in possible_values:
                options = " / ".join(str(v) for v in possible_values)
                raise ValidationError(f"«{item}» is not valid. Choose from: {options}")

        return list(set(value))

class Series(Validator):

    def __init__(
        self,
        validator: typing.Optional[Validator] = None,
        min_len: typing.Optional[int] = None,
        max_len: typing.Optional[int] = None,
        fixed_len: typing.Optional[int] = None,
    ):
        parts = ["list of values"]
        if validator is not None:
            parts.append(f"each: {validator.doc}")
        if fixed_len is not None:
            parts.append(f"exactly {fixed_len} items")
        elif min_len is not None and max_len is not None:
            parts.append(f"{min_len}–{max_len} items")
        elif min_len is not None:
            parts.append(f"at least {min_len} items")
        elif max_len is not None:
            parts.append(f"up to {max_len} items")

        super().__init__(
            functools.partial(
                self._validate,
                validator=validator,
                min_len=min_len,
                max_len=max_len,
                fixed_len=fixed_len,
            ),
            doc=", ".join(parts),
            _internal_id="Series",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        validator: typing.Optional[Validator],
        min_len: typing.Optional[int],
        max_len: typing.Optional[int],
        fixed_len: typing.Optional[int],
    ) -> typing.List[ConfigAllowedTypes]:
        if not isinstance(value, (list, tuple, set)):
            value = [item.strip() for item in str(value).split(",")]
        else:
            value = list(value)

        value = [item for item in value if item != ""]

        if fixed_len is not None and len(value) != fixed_len:
            raise ValidationError(f"List must have exactly {fixed_len} items (got {len(value)})")
        if min_len is not None and len(value) < min_len:
            raise ValidationError(f"List too short (min {min_len}, got {len(value)})")
        if max_len is not None and len(value) > max_len:
            raise ValidationError(f"List too long (max {max_len}, got {len(value)})")

        if validator is not None:
            validated = []
            for item in value:
                try:
                    validated.append(validator.validate(item))
                except ValidationError as exc:
                    raise ValidationError(f"Item «{item}» is invalid: {exc}")
            value = validated

        return value

class Link(Validator):

    def __init__(self):
        super().__init__(
            self._validate,
            doc="valid URL (http/https)",
            _internal_id="Link",
        )

    @staticmethod
    def _validate(value: ConfigAllowedTypes, /) -> str:
        import urllib.parse
        try:
            result = urllib.parse.urlparse(str(value))
            if result.scheme not in ("http", "https") or not result.netloc:
                raise ValueError
        except Exception:
            raise ValidationError(f"«{value}» is not a valid URL (http/https)")
        return str(value)

class TelegramID(Validator):

    def __init__(self):
        super().__init__(
            self._validate,
            doc="Telegram ID (number)",
            _internal_id="TelegramID",
        )

    @staticmethod
    def _validate(value: ConfigAllowedTypes, /) -> int:
        try:
            value = int(str(value).strip())
        except (ValueError, TypeError):
            raise ValidationError(f"«{value}» is not a Telegram ID")

        s = str(value)
        if s.startswith("-100"):
            value = int(s[4:])

        if value <= 0 or value > 2**63:
            raise ValidationError(f"«{value}» is not a valid Telegram ID")

        return value

class Hidden(Validator):

    def __init__(self, validator: typing.Optional[Validator] = None):
        if validator is None:
            validator = String()

        super().__init__(
            functools.partial(self._validate, validator=validator),
            doc=f"hidden: {validator.doc}",
            _internal_id="Hidden",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        validator: Validator,
    ) -> ConfigAllowedTypes:
        return validator.validate(value)

class Union(Validator):

    def __init__(self, *validators: Validator):
        doc = "one of:\n" + "\n".join(f"  - {v.doc}" for v in validators)
        super().__init__(
            functools.partial(self._validate, validators=validators),
            doc=doc,
            _internal_id="Union",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        validators: typing.Tuple[Validator, ...],
    ) -> ConfigAllowedTypes:
        for v in validators:
            try:
                return v.validate(value)
            except ValidationError:
                pass

        raise ValidationError(f"«{value}» did not pass any validator")
