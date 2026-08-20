#!/usr/bin/env python3
"""Разовая миграция: переименовывает файлы очереди в читаемый вид.

Было:  2026-08-19-cartier-celebrates-opening-of-its-relocated-shenzhen-boutiqu.md
Стало: 2026-08-19 Cartier celebrates opening of its relocated Shenzhen boutique.md

Адрес страницы на сайте не меняется — старое имя сохраняется в поле slug.
Запускать один раз, после этого новые файлы робот создаёт уже правильно.
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUEUE = os.path.join(ROOT, "queue")

sys.path.insert(0, HERE)
from fetch_feeds import filename_title


def main(dry_run=False):
    renamed = skipped = 0
    for name in sorted(os.listdir(QUEUE)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(QUEUE, name)
        raw = open(path, encoding="utf-8").read()

        m = re.search(r"^title:\s*(.+)$", raw, re.M)
        d = re.search(r"^date:\s*(\S+)$", raw, re.M)
        if not m or not d:
            print(f"  ! без title/date, пропускаю: {name}")
            skipped += 1
            continue

        stem = name[:-3]
        new_name = f"{d.group(1)} {filename_title(m.group(1).strip())}.md"
        if new_name == name and "slug:" in raw:
            skipped += 1
            continue

        # сохраняем текущее имя как адрес страницы, чтобы уже опубликованные
        # ссылки не поехали
        if not re.search(r"^slug:\s*", raw, re.M):
            raw = re.sub(r"^(status:\s*)", f"slug: {stem}\n\\1", raw, count=1, flags=re.M)

        new_path = os.path.join(QUEUE, new_name)
        if os.path.exists(new_path) and new_path != path:
            print(f"  ! уже существует, пропускаю: {new_name}")
            skipped += 1
            continue

        print(f"  {name}\n    → {new_name}")
        if not dry_run:
            open(path, "w", encoding="utf-8").write(raw)
            os.rename(path, new_path)
        renamed += 1

    print(f"\nпереименовано: {renamed}, пропущено: {skipped}")
    if dry_run:
        print("(пробный прогон, файлы не тронуты)")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
