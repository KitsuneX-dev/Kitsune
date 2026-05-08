"""
fix_blanks.py — убирает лишние пустые строки из .py файлов Kitsune.

Запуск из корня проекта:
    python fix_blanks.py

Что делает:
  - Убирает одиночные пустые строки между строками импортов
  - Убирает пустые строки между простыми присваиваниями внутри функций/методов
  - Схлопывает 3+ подряд пустых строк до 2 (PEP8: макс 2 между top-level)
  - Схлопывает 2+ пустых строки внутри class/def до 1
  - Не трогает логику, только форматирование
"""
import re
import sys
from pathlib import Path


def _is_definition(line: str) -> bool:
    s = line.strip()
    return s.startswith(("def ", "async def ", "class ")) and s.endswith(":")


def _indent_level(line: str) -> int:
    return len(line) - len(line.lstrip())


def fix_source(source: str) -> str:
    lines = source.splitlines()
    result: list[str] = []
    depth = 0  # rough nesting depth (0 = top-level)

    i = 0
    while i < len(lines):
        line = lines[i]

        # Track nesting depth by indentation of def/class
        if _is_definition(line):
            depth = 1 if _indent_level(line) == 0 else 2

        if line.strip() == "":
            # Count consecutive blank lines
            blank_count = 0
            j = i
            while j < len(lines) and lines[j].strip() == "":
                blank_count += 1
                j += 1

            # Decide how many blanks to keep
            if depth == 0:
                keep = min(blank_count, 2)  # top-level: max 2
            else:
                keep = min(blank_count, 1)  # inside class/func: max 1

            # Special case: single blank between consecutive imports — remove it
            if keep == 1 and blank_count == 1:
                prev = result[-1].strip() if result else ""
                nxt = lines[j].strip() if j < len(lines) else ""
                prev_is_import = prev.startswith(("import ", "from ")) or prev == ""
                next_is_import = nxt.startswith(("import ", "from "))
                if prev_is_import and next_is_import:
                    keep = 0

            result.extend([""] * keep)
            i = j
        else:
            result.append(line)
            i += 1

    # Ensure single trailing newline
    while result and result[-1].strip() == "":
        result.pop()
    return "\n".join(result) + "\n"


def process_dir(root: Path) -> None:
    py_files = [
        p for p in root.rglob("*.py")
        if "__pycache__" not in str(p) and ".git" not in str(p)
    ]
    fixed = 0
    for path in sorted(py_files):
        original = path.read_text(encoding="utf-8")
        cleaned = fix_source(original)
        if cleaned != original:
            path.write_text(cleaned, encoding="utf-8")
            rel = path.relative_to(root)
            before = original.count("\n")
            after = cleaned.count("\n")
            print(f"  fixed  {rel}  ({before} → {after} lines, -{before - after})")
            fixed += 1
    print(f"\nДобавлено: {fixed} файлов исправлено из {len(py_files)} .py файлов.")


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    if not (root / "kitsune").exists():
        print("Запусти из корня проекта Kitsune (там где папка kitsune/)")
        sys.exit(1)
    print(f"Обрабатываю {root.resolve()} ...\n")
    process_dir(root)
