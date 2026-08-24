from __future__ import annotations
import asyncio
import json
import logging
import re
import typing
from pathlib import Path

logger = logging.getLogger(__name__)

_LANGPACKS_DIR = Path(__file__).parent / "langpacks"

_FALLBACK_LANG = "en"

_MODULE_PREFIX = "kitsune.modules."

SUPPORTED_LANGUAGES = {
    "en": "🇬🇧 English",
    "ru": "🇷🇺 Русский",
    "ua": "🇺🇦 Українська",
    "uk": "🇺🇦 Українська",
    "de": "🇩🇪 Deutsch",
    "jp": "🇯🇵 日本語",
    "tr": "🇹🇷 Türkçe",
    "uz": "🇺🇿 Oʻzbekcha",
    "leet": "🔢 1337",
    "uwu": "🐾 UwU",
}


def fmt(text: str, kwargs: dict) -> str:
    for key, value in kwargs.items():
        placeholder = "{" + str(key) + "}"
        if placeholder in text:
            text = text.replace(placeholder, str(value))
    return text


def _load_yaml(content: str) -> dict:
    try:
        from ruamel.yaml import YAML

        yaml = YAML(typ="safe")
        data = yaml.load(content)
        if isinstance(data, dict):
            return dict(data)
    except Exception:
        pass

    try:
        import yaml as _pyyaml

        data = _pyyaml.safe_load(content)
        if isinstance(data, dict):
            return dict(data)
    except Exception:
        pass

    return _flat_yaml_parse(content)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        if value[0] == '"':
            inner = (
                inner.replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\\\", "\\")
            )
        return inner
    return value


def _flat_yaml_parse(content: str) -> dict:
    result: dict = {}
    current_section: typing.Optional[str] = None
    for raw_line in content.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if indent == 0:
            if value == "":
                current_section = key
                result.setdefault(key, {})
            else:
                current_section = None
                result[key] = _unquote(value)
        else:
            if current_section is not None and isinstance(
                result.get(current_section), dict
            ):
                result[current_section][key] = _unquote(value)
            else:
                result[key] = _unquote(value)
    return result


def _flatten_pack(content: dict, prefix: str = _MODULE_PREFIX) -> dict:
    flat: dict = {}
    for module, strings in content.items():
        if not isinstance(strings, dict):
            flat[module] = strings
            continue
        for key, value in strings.items():
            if key == "name":
                continue
            if module.startswith("$"):
                full = f"{module.strip('$')}.{key}"
            else:
                full = f"{prefix}{module}.{key}"
            flat[full] = value
    return flat


class Translator:
    def __init__(self, db: typing.Any = None) -> None:
        self._db = db
        self._packs: dict[str, dict] = {}
        self._lang: str = "ru"
        self._load_all()

    def _load_all(self) -> None:
        if not _LANGPACKS_DIR.exists():
            logger.warning("Translations: langpacks dir missing: %s", _LANGPACKS_DIR)
            return
        for path in sorted(_LANGPACKS_DIR.glob("*.yml")) + sorted(
            _LANGPACKS_DIR.glob("*.json")
        ):
            lang = path.stem
            try:
                raw = path.read_text(encoding="utf-8")
                if path.suffix == ".json":
                    data = json.loads(raw)
                else:
                    data = _load_yaml(raw)
                if not isinstance(data, dict):
                    continue
                pack = dict(data)
                if any(isinstance(v, dict) for v in pack.values()):
                    pack.update(_flatten_pack(pack))
                self._packs.setdefault(lang, {}).update(pack)
            except Exception:
                logger.exception("Translations: failed to load %s", path.name)
        if self._packs:
            logger.debug("Translations: loaded packs: %s", ", ".join(self._packs))

    def set_language(self, lang: str) -> None:
        self._lang = lang or "ru"

    def _lookup(self, key: str, lang: typing.Optional[str] = None) -> typing.Optional[str]:
        lang = lang or self._lang
        for candidate in (lang, *lang.split(), _FALLBACK_LANG):
            pack = self._packs.get(candidate)
            if pack and key in pack:
                return pack[key]
        return None

    def getkey(self, key: str, lang: typing.Optional[str] = None) -> typing.Any:
        return self._lookup(key, lang)

    def translate(self, key: str, lang: typing.Optional[str] = None, **kwargs: object) -> str:
        text = self._lookup(key, lang)
        if text is None:
            return key
        if kwargs:
            try:
                return str(text).format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return fmt(str(text), dict(kwargs))
        return str(text)

    def get_module_string(
        self,
        module_qualname: str,
        key: str,
        lang: typing.Optional[str] = None,
    ) -> typing.Optional[str]:
        candidates = [
            f"{module_qualname}.{key}",
            f"{_MODULE_PREFIX}{module_qualname}.{key}",
        ]
        short = module_qualname.rsplit(".", 1)[-1]
        candidates.append(f"{_MODULE_PREFIX}{short}.{key}")
        for cand in candidates:
            found = self._lookup(cand, lang)
            if found is not None:
                return found
        return None

    async def dlpack(self, url: str) -> bool:
        try:
            from .net.http_pool import get_shared_session

            session = get_shared_session()
            async with session.get(url) as resp:
                raw = await resp.text()
        except Exception:
            try:
                import urllib.request

                raw = await asyncio.to_thread(
                    lambda: urllib.request.urlopen(url, timeout=15).read().decode("utf-8")
                )
            except Exception:
                logger.exception("Translations: unable to download %s", url)
                return False
        try:
            if url.rstrip().endswith(".json"):
                data = json.loads(raw)
            else:
                data = _load_yaml(raw)
            if not isinstance(data, dict):
                return False
            if all(isinstance(v, dict) for v in data.values()) and all(
                len(k) <= 3 for k in data
            ):
                for lang, pack in data.items():
                    flat = _flatten_pack(pack) if any(
                        isinstance(v, dict) for v in pack.values()
                    ) else pack
                    self._packs.setdefault(lang, {}).update(flat)
            else:
                flat = _flatten_pack(data) if any(
                    isinstance(v, dict) for v in data.values()
                ) else data
                self._packs.setdefault(self._lang, {}).update(flat)
            return True
        except Exception:
            logger.exception("Translations: unable to decode %s", url)
            return False

    def __call__(self, key: str, **kwargs: object) -> str:
        return self.translate(key, **kwargs)
