#!/usr/bin/env python3
"""Разворачивает ссылки Google News и забирает у первоисточника картинку и абзац.

Запускается отдельным шагом сразу после fetch_feeds.py. Трогает только
черновики в queue/, у которых в поле link осталась ссылка news.google.com.

Почему отдельный скрипт и почему браузер. В адресе Google News лежит
непрозрачный токен: локально он не декодируется, а по обычному HTTP-запросу
приходит пустая Angular-оболочка — настоящий адрес страница узнаёт сама, уже
после выполнения JavaScript. Проверено: ни редиректа, ни data-n-au, ни meta
refresh в ответе нет. Значит нужен настоящий браузер. Playwright открывает
ссылку, ждёт, пока страница сама уйдёт на сайт издания, и дальше мы уже на
месте — забираем og:image и первый настоящий абзац текста.

Ничего не ломает при сбое. Не установлен Playwright, не открылась страница,
не нашлась картинка — файл остаётся ровно таким, каким был, и прогон идёт
дальше. Скрипт идемпотентен: развёрнутая ссылка больше не содержит
news.google.com, поэтому второй раз файл не берётся.

Локально:
    pip install playwright && python -m playwright install chromium
    DRY_RUN=1 python scripts/resolve_links.py
"""
import os, re, time
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUEUE = os.path.join(ROOT, "queue")

NAV_TIMEOUT = int(os.environ.get("RESOLVE_TIMEOUT") or 20000)   # мс на одну ссылку
MAX_FILES = int(os.environ.get("RESOLVE_MAX") or 40)            # страховка от лавины
MAX_PARA = int(os.environ.get("RESOLVE_PARA") or 250)           # длина второго абзаца
DRY = bool(os.environ.get("DRY_RUN"))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")

# Абзацы, которые выглядят как текст статьи, но ею не являются.
JUNK = re.compile(
    r"cookie|subscribe|sign up|sign in|newsletter|advertisement|advertising"
    r"|all rights reserved|privacy policy|terms of|©|follow us|share this",
    re.I)

# Формулировки защитных экранов — Cloudflare и подобные. Список заведомо
# неполный: у каждого щита свои слова, и завтра будут новые. Поэтому он
# работает только в паре с признаком короткой страницы (см. looks_blocked).
SHIELD = re.compile(
    r"verif(?:y|ying|ies)[^.]{0,30}human|are you a human|not a robot|captcha"
    r"|checking your browser|security service|malicious bots|bot protection"
    r"|ddos protection|cloudflare|access denied|forbidden|unusual traffic"
    r"|enable javascript|javascript is (?:disabled|required)|rate limit",
    re.I)

# Ниже этого объёма текста страница не может быть статьёй.
ARTICLE_MIN_CHARS = 1200

# Параметры слежения: в постоянный адрес статьи им попадать незачем.
DROP_PARAMS = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ito", "cmpid",
               "at_medium", "at_campaign", "smid", "ns_campaign")


# ------------------------------------------------------------------ файлы
def split_front(raw):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.S)
    return (m.group(1), m.group(2)) if m else (None, None)


def field(front, key):
    # [ \t]*, а не \s*: re.M меняет только смысл ^ и $, а \s по-прежнему
    # матчит перевод строки. С \s* пустое поле «image:» перетекало на
    # следующую строку и возвращало её целиком — код считал, что картинка
    # уже есть, и не подставлял найденную.
    m = re.search(rf"^{key}:[ \t]*(.*)$", front, re.M)
    return m.group(1).strip() if m else ""


def set_field(front, key, value):
    # замена функцией, а не строкой: в адресах бывает обратный слэш, и как
    # строка-замена он был бы понят регуляркой как escape-последовательность
    new, n = re.subn(rf"^{key}:.*$", lambda m: f"{key}: {value}", front,
                     count=1, flags=re.M)
    return new if n else front + f"\n{key}: {value}"


def targets():
    """Черновики очереди, у которых ссылка всё ещё ведёт на Google News."""
    out = []
    if not os.path.isdir(QUEUE):
        return out
    for name in sorted(os.listdir(QUEUE)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(QUEUE, name)
        try:
            raw = open(path, encoding="utf-8").read()
        except OSError:
            continue
        front, body = split_front(raw)
        if front is None:
            continue
        # published и hold не трогаем: там уже может быть ваш текст
        if field(front, "status").lower() != "draft":
            continue
        if "news.google.com" not in field(front, "link"):
            continue
        out.append((path, name, front, body))
    return out


# ------------------------------------------------------------------ текст
TAIL_WORDS = ("and", "or", "but", "the", "a", "an", "of", "to", "in", "on", "for",
              "with", "as", "at", "by", "from", "that", "which", "its", "their")


def trim(text, n):
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0]
    # Обрыв на служебном слове читается как ошибка вёрстки: «...screens — or…»
    # выглядит так, будто текст потеряли, а не сократили.
    for _ in range(3):
        cut = re.sub(r"[\s,;:—–-]+$", "", cut)
        stripped = re.sub(r"\s+(?:" + "|".join(TAIL_WORDS) + r")$", "", cut, flags=re.I)
        if stripped == cut:
            break
        cut = stripped
    return re.sub(r"[\s,;:—–-]+$", "", cut) + "…"


def clean_url(url):
    parts = urlsplit(url)
    keep = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not any(k.lower().startswith(p) for p in DROP_PARAMS)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(keep), ""))


def _key(text, n=40):
    """Отпечаток начала текста для сравнения «это то же самое или нет».

    Сравнивать посимвольно нельзя: анонс из ленты обрезан многоточием, в нём
    другие кавычки и лишние пробелы, а начало то же. Поэтому оставляем только
    буквы и цифры и смотрим на первые сорок."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())[:n]


def pick_para(paras, body):
    """Первый абзац статьи, которого ещё нет в файле.

    Первый абзац в файле — это анонс из ленты, и у большинства изданий он
    дословно повторяет начало текста. Такой абзац пропускаем: второй раз одно
    и то же читателю не нужно."""
    head = _key(body)
    for t in paras:
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) < 80 or JUNK.search(t) or SHIELD.search(t):
            continue
        if head and _key(t) == head:
            continue
        return trim(t, MAX_PARA)
    return ""


def new_body(body, para):
    """Комментарий-подсказку убираем только если есть чем её заменить."""
    if not para:
        return body if body.endswith("\n") else body + "\n"
    stripped = re.sub(r"<!--.*?-->", "", body, flags=re.S).strip()
    if _key(para, 60) in re.sub(r"[^a-z0-9]", "", stripped.lower()):
        return body if body.endswith("\n") else body + "\n"
    return stripped + "\n\n" + para + "\n"


# --------------------------------------------------------------- браузер
EXTRACT = """() => {
  const meta = (sel) => {
    const el = document.querySelector(sel);
    return el ? (el.getAttribute('content') || '').trim() : '';
  };
  const img = meta('meta[property="og:image"]')
           || meta('meta[property="og:image:url"]')
           || meta('meta[name="twitter:image"]')
           || meta('meta[name="twitter:image:src"]');
  const desc = meta('meta[property="og:description"]')
            || meta('meta[name="description"]');
  const scope = document.querySelector(
      'article, [itemprop="articleBody"], .article-body, .story-body, main')
      || document.body;
  const paras = Array.from(scope.querySelectorAll('p'))
      .map(p => (p.innerText || '').replace(/\\s+/g, ' ').trim())
      .filter(t => t.length > 80)
      .slice(0, 8);
  const full = (document.body.innerText || '').replace(/\\s+/g, ' ').trim();
  return {img: img, desc: desc, paras: paras,
          title: document.title || '', size: full.length,
          head: full.slice(0, 900)};
}"""


def looks_blocked(data):
    """Похожа ли страница на защитный экран, а не на статью.

    Одних слов мало: статья про сбой в аэропорту законно содержит «unusual
    traffic», а материал про кибербезопасность — «cloudflare». Но настоящая
    статья при этом длинная. Признаком считаем только совпадение слов НА
    КОРОТКОЙ странице: у экрана проверки текста на пару абзацев, у статьи —
    на несколько тысяч знаков."""
    if int(data.get("size") or 0) >= ARTICLE_MIN_CHARS:
        return False
    probe = f"{data.get('title', '')} {data.get('head', '')}"
    return bool(SHIELD.search(probe))


def wait_off_google(page, ms):
    """Ждём, пока страница сама уйдёт с домена Google на сайт издания."""
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        url = page.url or ""
        host = urlsplit(url).netloc
        if host and "google." not in host and "gstatic." not in host:
            return url
        page.wait_for_timeout(400)
    return ""


def resolve(page, link):
    try:
        page.goto(link, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    except Exception:
        # переход мог оборваться ровно тем редиректом, ради которого мы сюда
        # и пришли. Не сдаёмся на этом месте, а смотрим, где в итоге оказались
        pass
    final = wait_off_google(page, NAV_TIMEOUT)
    if not final:
        return "", {}
    try:
        page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    try:
        data = page.evaluate(EXTRACT)
    except Exception:
        data = {}
    return clean_url(page.url or final), (data or {})


# ------------------------------------------------------------------ ход
def main():
    jobs = targets()
    print(f"черновиков со ссылкой Google News: {len(jobs)}")
    if not jobs:
        return
    if len(jobs) > MAX_FILES:
        print(f"  берём первые {MAX_FILES}, остальные в следующий прогон")
        jobs = jobs[:MAX_FILES]

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright не установлен — ссылки оставляем как есть")
        return

    ok = fail = imgs = paras = blocked = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="en-US",
                                  viewport={"width": 1280, "height": 900})
        # Согласие на куки у Google — иначе вместо статьи приезжает баннер
        ctx.add_cookies([
            {"name": "CONSENT", "value": "YES+", "domain": ".google.com", "path": "/"},
            {"name": "SOCS", "value": "CAI", "domain": ".google.com", "path": "/"},
        ])
        # Картинки, шрифты и видео не грузим: нужны только теги в <head>
        ctx.route("**/*", lambda route: route.abort()
                  if route.request.resource_type in ("image", "media", "font")
                  else route.continue_())
        page = ctx.new_page()

        for path, name, front, body in jobs:
            link = field(front, "link")
            try:
                final, data = resolve(page, link)
            except Exception as e:
                final, data = "", {}
                print(f"  ! {type(e).__name__}: {name[:58]}")
            if not final or "news.google.com" in final:
                fail += 1
                print(f"  . не развернулась: {name[:58]}")
                continue

            front2 = set_field(front, "link", final)
            body2 = body

            if looks_blocked(data):
                # Издание показало не статью, а экран проверки. Адрес всё
                # равно настоящий — его оставляем, а текст и картинку с такой
                # страницы брать нельзя: это текст щита, а не новости.
                blocked += 1
                print(f"  ~ экран проверки, берём только адрес: "
                      f"{urlsplit(final).netloc}")
            else:
                img = (data.get("img") or "").strip()
                if img and not field(front, "image"):
                    front2 = set_field(front2, "image", urljoin(final, img))
                    imgs += 1

                para = pick_para(data.get("paras") or [], body)
                if not para:
                    para = trim(data.get("desc") or "", MAX_PARA)
                    if SHIELD.search(para):
                        para = ""
                body2 = new_body(body, para)
                if body2 != body:
                    paras += 1

            out = f"---\n{front2}\n---\n{body2}"
            if DRY:
                print(f"  → {urlsplit(final).netloc}  {name[:52]}")
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(out)
            ok += 1
            print(f"  + {urlsplit(final).netloc}: {name[:52]}")

        ctx.close()
        browser.close()

    print(f"\nРазвёрнуто ссылок: {ok}, не удалось: {fail}")
    print(f"Добавлено картинок: {imgs}, абзацев из первоисточника: {paras}")
    if blocked:
        print(f"Отдали экран проверки вместо статьи: {blocked} — у них только адрес")
    if DRY:
        print("DRY_RUN — файлы не изменены")


if __name__ == "__main__":
    main()
