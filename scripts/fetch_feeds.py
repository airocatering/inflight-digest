#!/usr/bin/env python3
"""Читает отраслевые RSS-ленты и складывает новое в queue/ на модерацию.

Ничего не публикует. Каждая новость становится отдельным файлом со статусом
status: draft — пока вы не поменяете его на published, на сайте её нет.
"""
import json, os, re, html, hashlib, datetime as dt
import feedparser

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUEUE = os.path.join(ROOT, "queue")
POSTS = os.path.join(ROOT, "posts")
SEEN = os.path.join(ROOT, "data", "seen.json")

# ---------------------------------------------------------------- рубрикация
RUBRIC_WORDS = [
    ("catering", ["catering", "galley", "meal", "menu", "food", "chef", "beverage",
                  "drink", "gategroup", "dnata", "trolley", "cutlery", "onboard dining"]),
    ("connectivity", ["wi-fi", "wifi", "connectivity", "starlink", "satellite", "leo",
                      "antenna", "broadband", "bandwidth", "gogo", "viasat", "panasonic avionics",
                      "gps", "spoofing", "cyber", "network"]),
    ("entertainment", ["entertainment", "ife", "ifec", "seatback", "streaming", "content",
                       "film", "movie", "audio", "podcast", "moment", "bluetooth"]),
    ("duty-free", ["duty free", "duty-free", "retail", "travel retail", "ancillary",
                   "shopping", "brand", "merchandis", "buy on board", "onboard sales"]),
    ("onboard-service", ["cabin crew", "service", "passenger experience", "paxex",
                         "accessibility", "wheelchair", "amenity", "boarding", "loyalty"]),
    ("cabin-seating", ["seat", "cabin", "interior", "retrofit", "berth", "suite",
                       "business class", "first class", "lie-flat", "galley monument",
                       "lavatory", "overhead bin", "certification", "airbus", "boeing", "comac"]),
]
DEFAULT_RUBRIC = "cabin-seating"


def guess_rubric(text):
    t = text.lower()
    best, score = DEFAULT_RUBRIC, 0
    for rub, words in RUBRIC_WORDS:
        n = sum(1 for w in words if w in t)
        if n > score:
            best, score = rub, n
    return best


# ---------------------------------------------------------------- утилиты
def clean(text, limit=260):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*\[[.…]+\]\s*$", "", text)
    if len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = cut.rstrip(",.;:—-") + "…"
    return text


def slug(text, n=60):
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:n].rstrip("-") or "story"


def pick_image(entry):
    """Ссылка на картинку у издателя. Мы её не копируем — только показываем
    со ссылкой на первоисточник. Если ничего нет, вернём пустую строку и на
    сайте встанет цветная плитка."""
    for key in ("media_content", "media_thumbnail"):
        for m in entry.get(key, []) or []:
            url = m.get("url")
            if url and re.search(r"\.(jpe?g|png|webp)(\?|$)", url, re.I):
                return url
    for enc in entry.get("enclosures", []) or []:
        if "image" in (enc.get("type") or "") and enc.get("href"):
            return enc["href"]
    blob = ""
    if entry.get("content"):
        blob = entry["content"][0].get("value", "")
    blob += entry.get("summary", "")
    m = re.search(r'<img[^>]+src="([^"]+)"', blob)
    if m and not m.group(1).startswith("data:"):
        return m.group(1)
    return ""


def entry_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        v = entry.get(key)
        if v:
            return dt.date(v[0], v[1], v[2])
    return dt.date.today()


def load_seen():
    if os.path.exists(SEEN):
        with open(SEEN) as f:
            return json.load(f)
    return {"links": []}


def existing_keys():
    """Всё, что уже лежит в очереди или опубликовано — второй раз не приносим."""
    keys = set()
    for folder in (QUEUE, POSTS):
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if name.endswith(".md"):
                keys.add(name)
    return keys


def main():
    cfg = json.load(open(os.path.join(HERE, "feeds.json")))
    seen = load_seen()
    seen_links = set(seen["links"])
    have = existing_keys()
    os.makedirs(QUEUE, exist_ok=True)
    os.makedirs(os.path.dirname(SEEN), exist_ok=True)

    cutoff = dt.date.today() - dt.timedelta(days=cfg.get("max_age_days", 14))
    added, per_feed = 0, cfg.get("max_per_feed_per_run", 6)

    for feed in cfg["feeds"]:
        if not feed.get("enabled") or not feed.get("url"):
            continue
        try:
            parsed = feedparser.parse(feed["url"])
        except Exception as e:                       # лента упала — не роняем весь прогон
            print(f"  ! {feed['name']}: {e}")
            continue
        if parsed.bozo and not parsed.entries:
            print(f"  ! {feed['name']}: лента не разобралась")
            continue

        taken = 0
        for entry in parsed.entries:
            if taken >= per_feed:
                break
            link = (entry.get("link") or "").split("?utm")[0].strip()
            title = clean(entry.get("title", ""), 200)
            if not link or not title or link in seen_links:
                continue
            date = entry_date(entry)
            if date < cutoff:
                continue

            name = f"{date.isoformat()}-{slug(title)}.md"
            if name in have:
                seen_links.add(link)
                continue

            summary = clean(entry.get("summary", "") or entry.get("description", ""))
            rubric = guess_rubric(title + " " + summary)
            image = pick_image(entry)

            body = f"""---
title: {title}
source: {feed['name']}
link: {link}
date: {date.isoformat()}
rubric: {rubric}
image: {image}
status: draft
---

{summary}

<!-- Ваш абзац. Что это значит для отрасли — два-три предложения.
     Без него материал выглядит как перепечатка. Строку с комментарием
     можно удалить. -->
"""
            with open(os.path.join(QUEUE, name), "w", encoding="utf-8") as f:
                f.write(body)
            have.add(name)
            seen_links.add(link)
            taken += 1
            added += 1
            print(f"  + [{rubric}] {title[:70]}")

        print(f"{feed['name']}: взято {taken}")

    seen["links"] = list(seen_links)[-4000:]
    with open(SEEN, "w") as f:
        json.dump(seen, f, ensure_ascii=False, indent=1)

    print(f"\nИтого новых материалов в очереди: {added}")


if __name__ == "__main__":
    main()
