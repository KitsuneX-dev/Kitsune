from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kitsune import log as klog


def build_handler() -> klog.KitsuneLogsHandler:
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.CRITICAL)
    console.setFormatter(klog._main_formatter)
    return klog.KitsuneLogsHandler([console], capacity=100)


def main() -> int:
    root = logging.getLogger()
    root.handlers = []
    handler = build_handler()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    logger = logging.getLogger("kitsune.test.logs")

    def tagged_emit() -> None:
        _kitsune_client_id_logging_tag = 123456789
        logger.error("tagged error from client %s", _kitsune_client_id_logging_tag)
        logger.debug("tagged debug from client %s", _kitsune_client_id_logging_tag)

    tagged_emit()
    logger.error("untagged error record")
    logger.debug("untagged debug record")
    logger.info("untagged info record")

    errors = handler.dumps(logging.ERROR)
    debug_all = handler.dumps(0)
    errors_own = handler.dumps(logging.ERROR, client_id=123456789)
    errors_other = handler.dumps(logging.ERROR, client_id=987654321)
    errors_nofilter = handler.dumps(logging.ERROR, client_id=None)
    all_nofilter = handler.dumps(0, client_id=None)

    print("dumps(ERROR)               ->", len(errors))
    print("dumps(0)                   ->", len(debug_all))
    print("dumps(ERROR, own id)       ->", len(errors_own))
    print("dumps(ERROR, foreign id)   ->", len(errors_other))
    print("dumps(ERROR, client=None)  ->", len(errors_nofilter))
    print("dumps(0, client=None)      ->", len(all_nofilter))

    checks = [
        ("errors found", len(errors) == 2),
        ("debug records reach buffer", any("debug" in line for line in debug_all)),
        ("all levels collected", len(all_nofilter) == 5),
        ("own client filter keeps tagged", len(errors_own) == 2),
        ("foreign client filter drops tagged", len(errors_other) == 1),
        ("client_id=None disables caller filter", len(errors_nofilter) == 2),
        (
            "tagged debug visible without caller filter",
            any("tagged debug" in line for line in all_nofilter),
        ),
    ]

    ok = True
    for name, passed in checks:
        print(("PASS " if passed else "FAIL ") + name)
        ok = ok and passed

    from kitsune.modules.logs import LogsModule

    parsed = {
        "all": LogsModule._parse_level("all"),
        "ALL": LogsModule._parse_level("ALL"),
        "error": LogsModule._parse_level("error"),
        "debug": LogsModule._parse_level("debug"),
        "30": LogsModule._parse_level("30"),
        "bogus": LogsModule._parse_level("bogus"),
    }
    print("parse_level:", parsed)
    level_checks = [
        ("all -> 0", parsed["all"] == 0),
        ("ALL -> 0", parsed["ALL"] == 0),
        ("error -> 40", parsed["error"] == logging.ERROR),
        ("debug -> 10", parsed["debug"] == logging.DEBUG),
        ("30 -> 30", parsed["30"] == 30),
        ("bogus -> None", parsed["bogus"] is None),
    ]
    for name, passed in level_checks:
        print(("PASS " if passed else "FAIL ") + name)
        ok = ok and passed

    print("RESULT:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
