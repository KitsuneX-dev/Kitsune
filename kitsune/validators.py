# 🦊 Kitsune Userbot — validators.py
# Валидаторы для ConfigValue. Подключи в loader.py и config-модуле.

import functools
import re
import typing

ConfigAllowedTypes = typing.Union[tuple, list, str, int, float, bool, None]


class ValidationError(Exception):
    """
    Поднимается когда значение конфига не прошло валидацию.
    Сообщение ошибки отображается пользователю в .config.
    """


class Validator:
    """
    Базовый класс валидатора.

    :param validator: Синхронная функция — принимает значение,
                      поднимает ValidationError если неверное,
                      возвращает приведённое значение если верное.
    :param doc: Строка-описание для пользователя (что ожидается).
    :param _internal_id: Идентификатор типа (используется в .config UI).
    """

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
    """
    Логическое значение.
    Принимает: True/False, 1/0, "yes"/"no", "on"/"off", "y"/"n" и т.д.
    Автоматически приводит к bool.
    """

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
            f"Значение «{value}» не является логическим. "
            "Используй: true/false, 1/0, yes/no, on/off"
        )


class Integer(Validator):
    """
    Целое число с опциональными ограничениями.

    :param minimum: Минимальное допустимое значение.
    :param maximum: Максимальное допустимое значение.
    :param digits: Точное количество цифр.
    """

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
            functools.partial(
                self._validate,
                minimum=minimum,
                maximum=maximum,
                digits=digits,
            ),
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
            raise ValidationError(f"«{value}» не является целым числом")

        if minimum is not None and value < minimum:
            raise ValidationError(
                f"Значение {value} меньше минимального ({minimum})"
            )
        if maximum is not None and value > maximum:
            raise ValidationError(
                f"Значение {value} больше максимального ({maximum})"
            )
        if digits is not None and len(str(abs(value))) != digits:
            raise ValidationError(
                f"Значение {value} должно содержать ровно {digits} цифр"
            )

        return value


class Float(Validator):
    """
    Число с плавающей точкой.

    :param minimum: Минимальное допустимое значение.
    :param maximum: Максимальное допустимое значение.
    """

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
            raise ValidationError(f"«{value}» не является числом с плавающей точкой")

        if minimum is not None and value < minimum:
            raise ValidationError(f"Значение {value} меньше минимального ({minimum})")
        if maximum is not None and value > maximum:
            raise ValidationError(f"Значение {value} больше максимального ({maximum})")

        return value


class String(Validator):
    """
    Строка с опциональными ограничениями длины.

    :param length: Точная длина строки.
    :param min_len: Минимальная длина.
    :param max_len: Максимальная длина.
    """

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
            functools.partial(
                self._validate, length=length, min_len=min_len, max_len=max_len
            ),
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
            raise ValidationError(
                f"Строка должна быть ровно {length} символов (получено {vlen})"
            )
        if min_len is not None and vlen < min_len:
            raise ValidationError(
                f"Строка слишком короткая (минимум {min_len}, получено {vlen})"
            )
        if max_len is not None and vlen > max_len:
            raise ValidationError(
                f"Строка слишком длинная (максимум {max_len}, получено {vlen})"
            )

        return value


class RegExp(Validator):
    """
    Проверяет что значение соответствует регулярному выражению.

    :param regex: Регулярное выражение.
    :param flags: Флаги для re.compile.
    :param description: Описание для пользователя.
    """

    def __init__(
        self,
        regex: str,
        flags: typing.Optional[re.RegexFlag] = None,
        description: typing.Optional[str] = None,
    ):
        flags = flags or 0
        try:
            re.compile(regex, flags=flags)
        except re.error as e:
            raise ValueError(f"Невалидное регулярное выражение: {regex}") from e

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
            raise ValidationError(
                f"Значение «{value}» не соответствует паттерну {regex}"
            )
        return str(value)


class Choice(Validator):
    """
    Значение должно быть одним из разрешённых.

    :param possible_values: Список допустимых значений.
    """

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
            raise ValidationError(
                f"«{value}» не является допустимым значением. Выбери из: {options}"
            )
        return value


class MultiChoice(Validator):
    """
    Список значений, каждое из которых должно быть из допустимых.

    :param possible_values: Список допустимых значений.
    """

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
                raise ValidationError(
                    f"«{item}» не является допустимым значением. Выбери из: {options}"
                )

        return list(set(value))


class Series(Validator):
    """
    Список значений (разделённых запятой если передана строка).

    :param validator: Валидатор для каждого элемента списка.
    :param min_len: Минимальное количество элементов.
    :param max_len: Максимальное количество элементов.
    :param fixed_len: Точное количество элементов.
    """

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

        # Убираем пустые строки
        value = [item for item in value if item != ""]

        if fixed_len is not None and len(value) != fixed_len:
            raise ValidationError(
                f"Список должен содержать ровно {fixed_len} элементов (получено {len(value)})"
            )
        if min_len is not None and len(value) < min_len:
            raise ValidationError(
                f"Список слишком короткий (минимум {min_len}, получено {len(value)})"
            )
        if max_len is not None and len(value) > max_len:
            raise ValidationError(
                f"Список слишком длинный (максимум {max_len}, получено {len(value)})"
            )

        if validator is not None:
            validated = []
            for item in value:
                try:
                    validated.append(validator.validate(item))
                except ValidationError as e:
                    raise ValidationError(
                        f"Элемент «{item}» невалиден: {e}"
                    )
            value = validated

        return value


class Link(Validator):
    """Валидная HTTP/HTTPS ссылка."""

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
            raise ValidationError(f"«{value}» не является валидной ссылкой (http/https)")
        return str(value)


class TelegramID(Validator):
    """Валидный Telegram ID (числовой, без -100 префикса)."""

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
            raise ValidationError(f"«{value}» не является Telegram ID")

        # Убираем -100 префикс для супергрупп/каналов
        s = str(value)
        if s.startswith("-100"):
            value = int(s[4:])

        if value <= 0 or value > 2**63:
            raise ValidationError(f"«{value}» не является валидным Telegram ID")

        return value


class Hidden(Validator):
    """
    Оборачивает другой валидатор — значение скрывается в UI (для токенов/паролей).

    :param validator: Внутренний валидатор (по умолчанию String).
    """

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
    """
    Значение должно пройти хотя бы один из переданных валидаторов.

    Пример: Union(Integer(), String()) — принимает и числа и строки.
    """

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

        raise ValidationError(
            f"«{value}» не прошло ни один из допустимых валидаторов"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Использование в модуле:
#
#   from ..validators import Boolean, Integer, String, Choice, Series, Link, Hidden
#
#   class MyMod(loader.Module):
#       strings = {"name": "MyMod"}
#
#       def __init__(self):
#           self.config = loader.ModuleConfig(
#               loader.ConfigValue(
#                   "enabled",
#                   True,
#                   "Включить модуль",
#                   validator=Boolean(),
#               ),
#               loader.ConfigValue(
#                   "delay",
#                   5,
#                   "Задержка в секундах",
#                   validator=Integer(minimum=1, maximum=60),
#               ),
#               loader.ConfigValue(
#                   "api_token",
#                   "",
#                   "API токен",
#                   validator=Hidden(),
#               ),
#               loader.ConfigValue(
#                   "mode",
#                   "auto",
#                   "Режим работы",
#                   validator=Choice(["auto", "manual", "silent"]),
#               ),
#           )
# ──────────────────────────────────────────────────────────────────────────────
