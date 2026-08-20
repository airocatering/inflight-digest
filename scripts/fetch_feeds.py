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
# Вес показывает, насколько слово однозначно указывает на рубрику.
#   3 — почти не ошибается (starlink, amenity kit, gategroup)
#   2 — уверенный признак в отраслевом контексте (galley, seatback, duty free)
#   1 — слабый намёк, работает только если ничего сильнее не нашлось
# Совпадение в заголовке считается вдвое: заголовок точнее анонса.
RUBRIC_WORDS = {
 "catering": {
   3: ["inflight catering", "in-flight catering", "airline catering", "flight kitchen",
       "gategroup", "gate gourmet", "lsg sky chefs", "sky chefs", "dnata", "newrest",
       "do & co", "emirates flight catering", "sats", "servair", "flying food group",
       "journey group", "aerofood", "cathay pacific catering",
       "galley cart", "meal tray", "casserole",
       "buy on board", "onboard menu", "inflight menu", "catering contract"],
   2: ["galley", "catering", "menu", "chef", "beverage", "onboard dining", "tableware",
       "cutlery", "trolley", "coca-cola", "pepsi", "nestle", "nestlé", "lavazza",
       "illy", "heineken", "panini", "sandwich", "water bottle", "juice"],
   1: ["meal", "food", "drink", "coffee", "wine", "snack"],
 },
 "connectivity": {
   3: ["starlink", "inflight connectivity", "in-flight wi-fi", "inflight wi-fi",
       "satellite broadband", "leo constellation", "viasat", "intelsat", "gogo",
       "panasonic avionics", "gps spoofing", "electronically steered antenna"],
   2: ["wi-fi", "wifi", "connectivity", "satellite", "antenna", "broadband", "bandwidth",
       "roaming", "cyber"],
   1: ["network", "signal", "data"],
 },
 "entertainment": {
   3: ["inflight entertainment", "in-flight entertainment", "ifec", "seatback screen",
       "seatback", "wireless ife", "content service provider", "bluetooth audio",
       "cabin headsets", "moving map"],
   2: ["ife", "entertainment", "streaming", "film", "movie", "podcast", "audio",
       "playlist", "games"],
   1: ["content", "media", "screen"],
 },
 "duty-free": {
   3: ["duty free", "duty-free", "travel retail", "inflight retail", "onboard retail",
       "onboard sales", "trbusiness", "moodie", "walkthrough duty free"],
   2: ["ancillary revenue", "boutique", "concession", "merchandis", "perfume",
       "cosmetics", "liquor", "tobacco"],
   1: ["retail", "brand", "shopping", "store"],
 },
 "onboard-service": {
   3: ["cabin crew", "passenger experience", "onboard service", "inflight service",
       "amenity kit", "amenity kits", "sleepwear", "inflight blanket", "cabin pillow",
       "wheelchair", "aisle chair", "accessibility"],
   2: ["service concept", "paxex", "crew training", "boarding", "loyalty", "premium cabin",
       "blanket", "pillow", "slippers"],
   1: ["service", "passenger", "comfort"],
 },
 "cabin-seating": {
   3: ["business class seat", "first class suite", "lie-flat", "cabin retrofit",
       "seat certification", "aircraft interiors", "cabin interior", "overhead bin",
       "lavatory", "galley monument", "seat manufacturer"],
   2: ["seat", "seating", "cabin", "interior", "retrofit", "suite", "berth",
       "recaro", "safran", "collins aerospace", "thompson aero", "expliseat"],
   1: ["airbus", "boeing", "comac", "embraer", "certification", "aircraft"],
 },
}
DEFAULT_RUBRIC = "cabin-seating"


_WORD_RE = {}


def _has(word, text):
    """Ищем по границам слова, иначе «service» находится внутри «in-service»,
    а «ife» — внутри «life» и «different»."""
    rx = _WORD_RE.get(word)
    if rx is None:
        # дефис тоже считаем границей: иначе «service» находится
        # внутри «in-service». Множественное число ловим отдельно:
        # «film» должен срабатывать на «films».
        rx = _WORD_RE[word] = re.compile(
            r"(?<![\w-])" + re.escape(word) + r"(?:e?s)?(?![\w-])")
    return bool(rx.search(text))


def guess_rubric(title, summary=""):
    """Взвешенный подбор рубрики. Заголовок весит вдвое против анонса."""
    t, s = title.lower(), summary.lower()
    best, best_score = DEFAULT_RUBRIC, 0
    for rub, buckets in RUBRIC_WORDS.items():
        score = 0
        for weight, words in buckets.items():
            for w in words:
                if _has(w, t):
                    score += weight * 2
                elif _has(w, s):
                    score += weight
        if score > best_score:
            best, best_score = rub, score
    return best




# ------------------------------------------------------- «интересно или нет»
# Отраслевые ленты гонят много проходного: анонсы вебинаров, фотогалереи,
# юбилеи, спонсорские материалы. Ниже — попытка отделить события от шума.
SIGNAL_WORDS = {
 3: ["wins contract", "awarded", "signs", "signed", "acquires", "acquisition", "merger",
     "takeover", "joint venture", "tender", "appoints", "appointed", "steps down",
     "resigns", "strike", "lawsuit", "recall", "investigation", "bankruptcy",
     "first delivery", "certification", "approval"],
 2: ["contract", "deal", "partnership", "agreement", "launches", "unveils", "introduces",
     "debuts", "rolls out", "expands", "opens", "invests", "investment", "stake",
     "results", "revenue", "profit", "earnings", "guidance", "retrofit", "orders",
     "selects", "chooses", "replaces", "trials", "pilot programme"],
 1: ["new", "adds", "upgrade", "redesign", "returns", "resumes", "extends"],
}
NOISE_WORDS = ["webinar", "sponsored", "advertorial", "promoted", "in pictures",
               "photo gallery", "gallery", "podcast", "watch:", "video:", "opinion:",
               "comment:", "top 10", "top ten", "best of", "roundup", "round-up",
               "week in review", "newsletter", "subscribe", "anniversary", "celebrates",
               "congratulates", "wishes", "season's greetings"]


def signal_score(title, summary=""):
    """Насколько материал похож на новость, а не на заполнение эфира."""
    t, s = title.lower(), summary.lower()
    score = 0
    for weight, words in SIGNAL_WORDS.items():
        for w in words:
            if _has(w, t):
                score += weight * 2
            elif _has(w, s):
                score += weight
    for w in NOISE_WORDS:
        if w in t:
            score -= 4
        elif w in s:
            score -= 1
    return score


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
    """Адрес страницы на сайте — только латиница, цифры и дефисы."""
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:n].rstrip("-") or "story"


def filename_title(text, n=80):
    """Имя файла — как заголовок, чтобы в колонке Name на GitHub читалось
    глазами. Убираем только то, что запрещено в именах файлов Windows."""
    text = re.sub(r'[\\/:*?"<>|#]', "", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if len(text) > n:
        text = text[:n].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return text or "story"


def split_gnews_title(title, feed_name, entry):
    """У Google News заголовок приходит как «Текст - Издание». Отрезаем хвост
    и подставляем настоящее издание вместо служебного имени ленты."""
    src = feed_name
    if feed_name.lower().startswith("google news"):
        real = (entry.get("source") or {}).get("title") if isinstance(
            entry.get("source"), dict) else None
        if not real and " - " in title:
            head, tail = title.rsplit(" - ", 1)
            if 2 <= len(tail) <= 40:
                title, real = head.strip(), tail.strip()
        elif real and title.endswith(" - " + real):
            title = title[: -(len(real) + 3)].strip()
        src = real or "Google News"
    return title, src


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

    added = 0
    per_feed_default = cfg.get("max_per_feed_per_run", 6)
    age_default = cfg.get("max_age_days", 14)
    total_cap = cfg.get("max_new_per_run", 30)      # страховка от лавины
    min_signal_default = cfg.get("min_signal", 2)   # ниже порога — не берём
    skipped = 0

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

        per_feed = feed.get("max_items", per_feed_default)
        cutoff = dt.date.today() - dt.timedelta(days=feed.get("max_age_days", age_default))

        taken = 0
        for entry in parsed.entries:
            if taken >= per_feed or added >= total_cap:
                break
            link = (entry.get("link") or "").split("?utm")[0].strip()
            title = clean(entry.get("title", ""), 200)
            title, source_name = split_gnews_title(title, feed["name"], entry)
            if not link or not title or link in seen_links:
                continue
            date = entry_date(entry)
            if date < cutoff:
                continue

            stem = f"{date.isoformat()}-{slug(title)}"          # адрес на сайте
            name = f"{date.isoformat()} {filename_title(title)}.md"   # имя файла
            if name in have:
                seen_links.add(link)
                continue

            summary = clean(entry.get("summary", "") or entry.get("description", ""))

            sig = signal_score(title, summary)
            if sig < feed.get("min_signal", min_signal_default):
                skipped += 1
                print(f"  - слабо ({sig}): {title[:64]}")
                continue

            rubric = guess_rubric(title, summary)
            image = pick_image(entry)

            body = f"""---
title: {title}
source: {source_name}
link: {link}
date: {date.isoformat()}
rubric: {rubric}
image: {image}
slug: {stem}
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
            print(f"  + [{rubric}] сигнал {sig}: {title[:60]}")

        print(f"{feed['name']}: взято {taken}")
        if added >= total_cap:
            print(f"  ! достигнут потолок {total_cap} материалов за прогон, остальное в следующий раз")
            break

    seen["links"] = list(seen_links)[-4000:]
    with open(SEEN, "w") as f:
        json.dump(seen, f, ensure_ascii=False, indent=1)

    print(f"\nИтого новых материалов в очереди: {added}")
    print(f"Отсеяно как проходное: {skipped}")


if __name__ == "__main__":
    main()
