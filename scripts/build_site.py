#!/usr/bin/env python3
"""Собирает статический сайт Inflight Digest из одобренных материалов.

Читает queue/*.md и posts/*.md. На сайт попадает только то, где стоит
status: published. Одобренные файлы переезжают из queue/ в posts/.
"""
import os, re, json, base64, shutil, struct, html as H, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUEUE, POSTS = os.path.join(ROOT, "queue"), os.path.join(ROOT, "posts")

SITE_URL = "https://airocatering.github.io/inflight-digest"
NOINDEX = False         # сайт открыт для индексации с 23.08.2026
EDITOR = "Vlad Mazur"
PUBLISHER = "Inflight Digest"
CONTACT_MAIL = "vladyslav.mazur@gmail.com"

# ID формы Formspree. Пока стоит заглушка, форма подписки не рисуется вообще —
# вместо неё кнопка «написать письмом». Лучше честная почта, чем поле ввода,
# которое молча выбрасывает адреса подписчиков.
FORM_ID = "mdenvndy"
FORM_LIVE = bool(FORM_ID) and not FORM_ID.startswith("YOUR-")

# Идентификатор потока Google Analytics 4, вида G-XXXXXXXXXX. Пустая строка —
# счётчик не ставится вообще, ни одной лишней загрузки. Это не секрет: он и так
# виден в исходном коде любой страницы, поэтому лежит в репозитории, а не в
# GitHub Secrets.
GA_ID = "G-W2BDQ3VTLM"

CSS = open(os.path.join(HERE, "style.css"), encoding="utf-8").read()
CSS += """
.credit{font-size:11px;color:var(--muted);margin-top:6px}
.credit a{color:var(--red)}
.empty{background:#fff;border-left:3px solid var(--red);padding:22px 24px;margin:26px 0 46px;
font-size:15px;line-height:1.6;color:#555}
.empty b{color:var(--ink)}

/* узкая сетка: на широком экране не растягиваем одну карточку на всю ширину,
   на планшете и телефоне — наоборот, отдаём всю */
.board.n1{grid-template-columns:1fr;max-width:33.4%}
.board.n2{grid-template-columns:repeat(2,1fr);max-width:66.8%}
@media(max-width:980px){
  .board.n1{max-width:50%}
  .board.n2{max-width:100%}
}
@media(max-width:640px){
  .board.n1,.board.n2{grid-template-columns:1fr;max-width:100%}
}

/* телефон: плитка = фото + заголовок. Анонс убираем, он тут только удлиняет
   бесконечную ленту и всё равно повторяется на странице материала */
@media(max-width:640px){
  .cell p{display:none}
  .cell .bd{padding:14px 16px 16px}
  .cell h3,.cell.big h3{font-size:20px;line-height:1.22}
  .cell .ph,.cell.big .ph{aspect-ratio:16/9}
  .cell.ink{min-height:0;padding:24px 20px}
  .cell.ink .q{font-size:21px}
  .lead{margin-top:22px}
  .board{margin:18px 0 32px}
}
"""

RUBRICS = [
    ("catering", "Airline Catering",
     "Menus, galley equipment, catering contracts and the logistics of feeding a cabin."),
    ("entertainment", "Entertainment",
     "Seatback and streaming IFE, content deals, platforms and the companies behind them."),
    ("connectivity", "Connectivity",
     "Satellite Wi-Fi, LEO constellations, antennas, and cabin network security."),
    ("onboard-service", "Onboard Service",
     "Cabin crew service models, accessibility, amenity and the passenger-facing experience."),
    ("cabin-interior", "Cabin Interior",
     "Seats, galleys and trolleys — new cabin products and the suppliers "
     "behind them."),
    ("duty-free", "Duty Free",
     "Onboard and airport retail, ancillary revenue, travel retail brands and buyers."),
]
RUB_TITLE = {k: t for k, t, _ in RUBRICS}
NAV = [(k, t) for k, t, _ in RUBRICS] + [("jobs", "Top Jobs"), ("events", "Events")]

FONT = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800'
        '&family=Instrument+Serif&display=swap" rel="stylesheet">')


def asset(name):
    p = os.path.join(ROOT, "assets", name)
    s = open(p, encoding="utf-8").read().strip()
    return re.sub(r'\s(width|height)="[^"]*"', "", s, count=2)


LOGO = asset("logo-tagline.svg")
LOGO_W = asset("logo-white.svg")

PALETTES = [("#16202c", "#31465f", "#7ea2c4"), ("#2a1a1e", "#5c2b2f", "#c58b7a"),
            ("#12211d", "#264a3f", "#7fb8a0"), ("#211c2c", "#3f3355", "#9d8dc4"),
            ("#2b2318", "#5a4526", "#c9a066"), ("#1a2430", "#2f4a63", "#96b8d6"),
            ("#241a24", "#4c2f4a", "#b98fb2"), ("#1d2620", "#37503c", "#93bb9a")]


def image_size(path):
    """Ширина и высота растрового файла — читаем только заголовок, не весь
    файл, без внешних библиотек. Понимает JPEG, PNG, WEBP (VP8/VP8L/VP8X).
    Не получилось разобрать — None, вызывающий код тогда просто не применяет
    портретную рамку к статье, ничего не падает."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return w, h
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                tag = head[12:16]
                if tag == b"VP8 ":
                    w, h = struct.unpack("<HH", head[26:30])
                    return w & 0x3FFF, h & 0x3FFF
                if tag == b"VP8L":
                    b0, b1, b2, b3 = head[21], head[22], head[23], head[24]
                    w = 1 + (((b1 & 0x3F) << 8) | b0)
                    h = 1 + (((b3 & 0xF) << 10) | (b2 << 2) | (b1 >> 6))
                    return w, h
                if tag == b"VP8X":
                    w = 1 + (head[24] | (head[25] << 8) | (head[26] << 16))
                    h = 1 + (head[27] | (head[28] << 8) | (head[29] << 16))
                    return w, h
                return None
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    marker = f.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None
                    if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        f.read(3)
                        h, w = struct.unpack(">HH", f.read(4))
                        return w, h
                    seg_len = struct.unpack(">H", f.read(2))[0]
                    f.seek(seg_len - 2, 1)
    except (OSError, struct.error, IndexError):
        return None
    return None


def is_portrait(image_field):
    """Портретная ли фотография — только для своих файлов в assets/.
    Внешние (hotlink) картинки не трогаем: это был бы сетевой запрос на
    этапе сборки ради проверки ориентации, и почти всегда это готовые
    landscape og:image 1200×630 — рамка 16:9 для них и так подходит."""
    if not image_field or not image_field.startswith("assets/"):
        return False
    dims = image_size(os.path.join(ROOT, image_field))
    return bool(dims and dims[1] > dims[0])


def placeholder(seed, w=1200, h=800):
    i = sum(ord(c) for c in seed)
    a, b, c = PALETTES[i % len(PALETTES)]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
           f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1" '
           f'gradientTransform="rotate({12 + i % 60} .5 .5)">'
           f'<stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/>'
           f'</linearGradient><radialGradient id="r">'
           f'<stop offset="0" stop-color="{c}" stop-opacity=".5"/>'
           f'<stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient></defs>'
           f'<rect width="{w}" height="{h}" fill="url(#g)"/>'
           f'<circle cx="{(20 + i % 60) * w / 100:.0f}" cy="{(25 + i % 45) * h / 100:.0f}" '
           f'r="{(26 + i % 22) * w / 100:.0f}" fill="url(#r)"/>'
           f'<g fill="none" stroke="{c}" stroke-opacity=".2" stroke-width="3">'
           f'<rect x="{w*.62:.0f}" y="{h*.18:.0f}" width="{w*.10:.0f}" height="{h*.30:.0f}" rx="{w*.05:.0f}"/>'
           f'<rect x="{w*.76:.0f}" y="{h*.18:.0f}" width="{w*.10:.0f}" height="{h*.30:.0f}" rx="{w*.05:.0f}"/>'
           f'</g><path d="M0 {h*.86:.0f} L{w} {h*.70:.0f} L{w} {h} L0 {h} Z" '
           f'fill="{a}" fill-opacity=".45"/></svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


# ---------------------------------------------------------------- материалы
def unquote_yaml(v):
    """title: "Country: subtitle" — сама сборка не ломается на кавычках
    (это упрощённый парсер, не настоящий YAML), но снять их всё равно надо,
    иначе на сайте заголовок будет буквально в кавычках."""
    if len(v) >= 2 and v[0] == v[-1] == '"':
        v = v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return v


def parse_md(path):
    raw = open(path, encoding="utf-8").read()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.S)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = unquote_yaml(v.strip())
    body = re.sub(r"<!--.*?-->", "", m.group(2), flags=re.S).strip()
    meta["body"] = body
    meta["file"] = os.path.basename(path)
    # адрес страницы берём из поля slug; если его нет (старые файлы) —
    # выводим из имени файла, как раньше
    stem = meta.get("slug") or re.sub(r"[^a-z0-9]+", "-", meta["file"][:-3].lower()).strip("-")
    meta["url"] = stem + ".html"
    meta.setdefault("rubric", "cabin-interior")
    meta.setdefault("image", "")
    if meta.get("rubric") not in RUB_TITLE:
        meta["rubric"] = "cabin-interior"
    meta["img"] = meta["image"] or placeholder(meta["file"])
    meta["hotlink"] = bool(meta["image"])
    meta["portrait"] = is_portrait(meta["image"])
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    meta["stand"] = paras[0] if paras else ""
    meta["rest"] = paras[1:]
    return meta


def load_all():
    items, promote = [], []
    for folder in (POSTS, QUEUE):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".md"):
                continue
            it = parse_md(os.path.join(folder, name))
            if not it:
                print(f"  ! пропущен (сломанный формат): {name}")
                continue
            if it.get("status", "draft").lower() != "published":
                continue
            items.append(it)
            if folder == QUEUE:
                promote.append(name)
    # Порядок на доске: свежее — первым, то есть слева вверху; самое старое
    # оказывается последним, справа внизу. Когда у двух материалов одна и та же
    # дата (а так бывает почти всегда — за день приходит несколько новостей),
    # решает `added` — отметка робота о том, когда материал попал в очередь.
    # Раньше на этом месте стояло имя файла, и порядок получался алфавитный,
    # то есть случайный: первым мог встать материал, опубликованный раньше всех.
    def order(x):
        date = x.get("date", "")
        # `added` ставит робот. У материала, написанного руками, этой строки
        # обычно нет — считаем его самым свежим за свой день: вы его только что
        # написали, значит на доске он должен стоять впереди роботных за ту же
        # дату, а не проваливаться в конец. "T99" не время, а заведомо большая
        # строка: любое реальное "…T23:59:59Z" сортируется раньше неё.
        return (date, x.get("added") or date + "T99", x["file"])

    items.sort(key=order, reverse=True)
    return items, promote


def fmt_date(iso):
    try:
        d = dt.date.fromisoformat(iso)
        return d.strftime("%-d %b %Y")
    except Exception:
        return iso or ""


# ---------------------------------------------------------------- каркас
def ld_json(*blocks):
    """Разметка schema.org. Именно из неё Google строит расширенные сниппеты —
    дату, автора, издателя. Без неё новость выглядит в выдаче как обычная
    страница."""
    out = [b for b in blocks if b]
    if not out:
        return ""
    data = out[0] if len(out) == 1 else {"@context": "https://schema.org", "@graph":
                                         [{k: v for k, v in b.items() if k != "@context"}
                                          for b in out]}
    return ('<script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            + "</script>")


def org_ld():
    return {"@context": "https://schema.org", "@type": "NewsMediaOrganization",
            "@id": f"{SITE_URL}/#org", "name": PUBLISHER, "url": f"{SITE_URL}/",
            "logo": {"@type": "ImageObject", "url": f"{SITE_URL}/favicon-180.png"},
            "email": CONTACT_MAIL,
            "description": "Independent trade news on airline catering, inflight "
                           "entertainment, cabin interiors and onboard service.",
            "address": {"@type": "PostalAddress", "addressLocality": "Kyiv",
                        "addressCountry": "UA"}}


def robots_tag():
    """Один тег для всего сайта — и для собранных страниц, и для advertise.html,
    который свёрстан руками. max-image-preview:large даёт крупную картинку в
    выдаче и в Discover, для новостного сайта это заметная разница в кликах."""
    if NOINDEX:
        return '<meta name="robots" content="noindex,nofollow">'
    return ('<meta name="robots" content="index,follow,max-image-preview:large,'
            'max-snippet:-1,max-video-preview:-1">')


SITE_JS = """
(function(){
  var ID="GA_MEASUREMENT_ID", MAIL="CONTACT_EMAIL";
  function ready(fn){
    if(document.readyState!=="loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }
  /* ---------- аналитика ---------- */
  if(ID){
    var s=document.createElement("script");
    s.async=true; s.src="https://www.googletagmanager.com/gtag/js?id="+ID;
    document.head.appendChild(s);
    window.dataLayer=window.dataLayer||[];
    window.gtag=function(){window.dataLayer.push(arguments);};
    gtag("js", new Date());
    gtag("config", ID);
  }
  /* ---------- формы: отправка без ухода со страницы ---------- */
  function bindForm(f){
    f.addEventListener("submit", function(e){
      e.preventDefault();
      var btn=f.querySelector('button[type="submit"]'), was=btn?btn.textContent:"";
      if(btn){ btn.disabled=true; btn.textContent="Sending…"; }
      fetch(f.action, {method:"POST", body:new FormData(f),
                       headers:{"Accept":"application/json"}})
        .then(function(r){ if(!r.ok) throw new Error("http"); return r; })
        .then(function(){
          var d=document.createElement("div");
          d.className="fdone";
          d.innerHTML=f.getAttribute("data-done")||"Thank you — message sent.";
          f.parentNode.replaceChild(d, f);
        })
        .catch(function(){
          if(btn){ btn.disabled=false; btn.textContent=was; }
          var w=f.querySelector(".ferr");
          if(!w){ w=document.createElement("div"); w.className="ferr"; f.appendChild(w); }
          w.textContent="Could not send just now. Please email "+MAIL+" instead.";
        });
    });
  }
  ready(function(){
    var fs=document.querySelectorAll("form[data-ajax]");
    for(var i=0;i<fs.length;i++) bindForm(fs[i]);
  });
})();
"""
def site_js():
    """Один скрипт на все страницы: аналитика и отправка форм без ухода со
    страницы. Обёрнут маркерами, чтобы сборка могла заменить блок во вручную
    свёрстанной advertise.html. GA грузится сразу, без баннера согласия —
    отключено по решению пользователя 2026-08-23, см. CLAUDE.md."""
    if not (GA_ID or FORM_LIVE):
        return ""
    return ("<!-- js --><script>"
            + SITE_JS.replace("GA_MEASUREMENT_ID", GA_ID)
                     .replace("CONTACT_EMAIL", CONTACT_MAIL).strip()
            + "</script><!-- /js -->")


def head(title, path, desc, ld="", og_type="website", extra=""):
    robots = robots_tag() + "\n"
    url = f"{SITE_URL}/{path}"
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
{robots}<meta name="description" content="{desc}">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="alternate icon" href="favicon-32.png">
<link rel="apple-touch-icon" href="favicon-180.png">
<link rel="alternate" type="application/rss+xml" title="Inflight Digest" href="{SITE_URL}/feed.xml">
<meta property="og:type" content="{og_type}"><meta property="og:site_name" content="Inflight Digest">
<meta property="og:locale" content="en_GB">{extra}
<meta property="og:title" content="{title}"><meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}"><meta property="og:image" content="{SITE_URL}/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="{url}">{ld}{FONT}<style>{CSS}</style>
{site_js()}</head><body>'''


def header(active=None):
    links = "".join(f'<a class="{"on" if k == active else ""}" href="{k}.html">{t}</a>'
                    for k, t in NAV)
    today = dt.date.today().strftime("%A, %-d %B %Y")
    return f'''<header><div class="wrap"><a href="index.html">{LOGO}</a>
<div class="hdate"><div class="serif d">{today}</div>
<div class="k">Kyiv &middot; independent trade news</div></div></div></header>
<nav><div class="wrap"><div class="links">{links}</div>
<a class="adv" href="advertise.html">Advertise</a></div></nav>'''


_SUB_CTA = (f'''<form method="POST" data-ajax
action="https://formspree.io/f/{FORM_ID}"
data-done="Thank you &mdash; you are on the list. The first Monday Digest arrives next Monday.">
<input type="email" name="email" placeholder="you@airline.com" required>
<input type="hidden" name="_subject" value="Monday Digest — new subscriber">
<input type="text" name="_gotcha" tabindex="-1" autocomplete="off" aria-hidden="true">
<button type="submit">Subscribe</button></form>
<div class="fine">One email a week, never more &middot; leave any time by replying
&middot; we never share your address</div>''' if FORM_LIVE else f'''<a class="mailbtn"
href="mailto:{CONTACT_MAIL}?subject=Subscribe%20to%20The%20Monday%20Digest">Email to subscribe</a>
<div class="fine">One line is enough &mdash; we add you by hand and you can leave any time.</div>''')

SUBSCRIBE = f'''<section class="sub"><div class="wrap">
<div><span class="badge">Free &middot; every Monday</span>
<h2 class="serif">The Monday Digest</h2>
<p>One email a week with everything worth knowing about catering, cabin, IFEC and
duty free &mdash; picked by a human, not a feed reader. No daily noise.</p></div>
<div>{_SUB_CTA}</div></div></section>'''


def footer():
    rubs = "".join(f'<li><a href="{k}.html">{t}</a></li>' for k, t, _ in RUBRICS)
    return f'''<footer><div class="wrap">{LOGO_W}
<div class="fcols">
<div><h4>About</h4><ul><li><a href="editorial-policy.html">Editorial policy</a></li>
<li><a href="sources.html">Sources &amp; attribution</a></li>
<li><a href="advertise.html">Advertise</a></li>
<li><a href="contact.html">Contact</a></li></ul></div>
<div><h4>Sections</h4><ul>{rubs}</ul></div>
<div><h4>More</h4><ul><li><a href="jobs.html">Top Jobs Worldwide</a></li>
<li><a href="events.html">Events</a></li>
<li><a href="feed.xml">RSS feed</a></li></ul></div></div>
<div class="fb"><span>&copy; {dt.date.today().year} Inflight Digest &middot;
headlines link to the original publishers</span><span>Kyiv, Ukraine</span></div>
</div></footer></body></html>'''


def img_tag(it, cls=""):
    """Чужое фото показываем ссылкой на сервер издателя. Если оно не отдастся —
    защита от хотлинка, переезд, удаление — молча подставляем свою плитку,
    чтобы на сайте никогда не было «сломанной картинки»."""
    if not it["hotlink"]:
        return f'<img src="{it["img"]}" alt="">'
    fallback = placeholder(it["file"]).replace("'", "%27")
    return (f'<img src="{it["img"]}" alt="" loading="lazy" referrerpolicy="no-referrer" '
            f'onerror="this.onerror=null;this.src=\'{fallback}\'">')


def cell(it, cls=""):
    return f'''<a class="cell {cls}" href="{it['url']}"><div class="ph">{img_tag(it)}</div>
<div class="bd"><div class="cat">{RUB_TITLE[it['rubric']]}</div><h3>{it['title']}</h3>
<p>{it['stand']}</p><div class="m"><b>{it.get('source','')}</b> &middot;
{fmt_date(it.get('date',''))}</div></div></a>'''


def board(items, quotes=True):
    if not items:
        return ('<div class="empty"><b>Nothing here yet.</b> Stories land in this section '
                'as soon as they are published. Check back shortly, or take '
                '<a href="index.html" style="color:var(--red)">today\'s board</a>.</div>')
    out, n = [], 0
    lead = len(items) >= 4
    for i, it in enumerate(items):
        out.append(cell(it, "big" if (lead and i == 0) else ("alt" if i % 2 else "")))
        n += 1
        if quotes and n == 4:
            out.append('<div class="cell ink"><div class="q serif">Every story here was read '
                       'by a human before it went live.</div>'
                       '<div class="who">Editorial policy</div></div>')
    # узкая сетка задаётся классом, а не инлайн-стилем: инлайн перебивает
    # медиазапросы и ломает вёрстку на телефоне
    cls = f" n{len(items)}" if len(items) < 3 else ""
    return f'<div class="board{cls}">{"".join(out)}</div>'


# ---------------------------------------------------------------- страницы
def page_index(items):
    site_ld = {"@context": "https://schema.org", "@type": "WebSite",
               "@id": f"{SITE_URL}/#site", "url": f"{SITE_URL}/", "name": PUBLISHER,
               "inLanguage": "en", "publisher": {"@id": f"{SITE_URL}/#org"}}
    return (head("Inflight Digest — airline catering, entertainment, onboard services",
                 "index.html",
                 "Airline catering, inflight entertainment and onboard service news — "
                 "filtered by a human, published daily.",
                 ld=ld_json(org_ld(), site_ld))
            + header()
            # h1 на главной был вообще: заголовок сайта — это логотип в SVG, а его
            # поисковик как текст не читает. Скрываем визуально, но отдаём роботу
            # и экранным читалкам — дизайн доски при этом не меняется.
            + f'''<div class="wrap"><h1 class="vh">Inflight Digest &mdash; airline catering,
inflight entertainment and onboard service news</h1>
<div class="lead"><h2>Today's board</h2><div class="l"></div>
<span class="note">{len(items)} published &middot; newest first</span></div>{board(items)}</div>'''
            + SUBSCRIBE + footer())


def page_rubric(key, title, blurb, items):
    n = len(items)
    return (head(f"{title} — Inflight Digest", f"{key}.html", re.sub("<[^>]+>", "", blurb))
            + header(key)
            + f'''<div class="wrap"><section class="rubhead"><h1 class="serif">{title}</h1>
<p>{blurb}</p></section>
<div class="count">{n} stor{"y" if n == 1 else "ies"}</div>{board(items, quotes=False)}</div>'''
            + SUBSCRIBE + footer())


def page_article(it, items):
    rel = [x for x in items if x["rubric"] == it["rubric"] and x is not it][:3]
    rel += [x for x in items if x not in rel and x is not it][:max(0, 3 - len(rel))]
    relhtml = "".join(f'''<a class="rel" href="{r['url']}">{img_tag(r)}
<div><h4>{r['title']}</h4><div class="m">{r.get('source','')} &middot;
{fmt_date(r.get('date',''))}</div></div></a>''' for r in rel)
    credit = (f'<div class="credit">Photo: {it.get("source","")} &mdash; '
              f'<a href="{it.get("link","#")}" target="_blank" rel="noopener">see original</a></div>'
              if it["hotlink"] else
              '<figcaption>Illustration by Inflight Digest &mdash; no photograph '
              'was supplied in the source feed.</figcaption>')
    rest = "".join(f"<p>{p}</p>" for p in it["rest"])
    img = it["img"] if it["hotlink"] else f"{SITE_URL}/og-image.png"
    art_ld = {"@context": "https://schema.org", "@type": "NewsArticle",
              "headline": it["title"][:110], "description": it["stand"][:300],
              "datePublished": it.get("date", ""), "dateModified": it.get("date", ""),
              "inLanguage": "en", "image": [img],
              "mainEntityOfPage": {"@type": "WebPage", "@id": f"{SITE_URL}/{it['url']}"},
              "author": {"@type": "Person", "name": EDITOR},
              "publisher": {"@id": f"{SITE_URL}/#org"},
              "articleSection": RUB_TITLE[it["rubric"]]}
    if it.get("link"):
        art_ld["isBasedOn"] = it["link"]
    crumb_ld = {"@context": "https://schema.org", "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home",
                     "item": f"{SITE_URL}/index.html"},
                    {"@type": "ListItem", "position": 2,
                     "name": RUB_TITLE[it["rubric"]],
                     "item": f"{SITE_URL}/{it['rubric']}.html"},
                    {"@type": "ListItem", "position": 3, "name": it["title"]}]}
    pub = (f'<meta property="article:published_time" content="{it["date"]}">'
           if it.get("date") else "")
    return (head(f"{it['title']} — Inflight Digest", it["url"], it["stand"][:180],
                 ld=ld_json(org_ld(), art_ld, crumb_ld), og_type="article", extra=pub)
            + header(it["rubric"])
            + f'''<div class="wrap">
<div class="crumb"><a href="index.html">Home</a> &nbsp;/&nbsp;
<a href="{it['rubric']}.html">{RUB_TITLE[it['rubric']]}</a></div>
<div class="art"><article>
<div class="cat">{RUB_TITLE[it['rubric']]}</div><h1>{it['title']}</h1>
<p class="stand">{it['stand']}</p>
<div class="byline"><span>Filed by <b>{EDITOR}</b></span><span class="dot"></span>
<span>{fmt_date(it.get('date',''))}</span><span class="dot"></span>
<span>Source: <b>{it.get('source','')}</b></span></div>
<figure class="figure{' portrait' if it.get('portrait') else ''}">{img_tag(it)}{credit}</figure>
<div class="body">{rest}
<div class="srcbox"><div class="l">Read the original</div>
<a href="{it.get('link','#')}" target="_blank" rel="noopener">{it.get('source','')} &rarr;</a>
<p>Inflight Digest summarises and links. Full text and photographs remain the property of the
original publisher.</p></div></div></article>
<aside class="rail"><section><h3>More in {RUB_TITLE[it['rubric']]}</h3>{relhtml}</section>
</aside></div></div>''' + footer())


def page_jobs():
    jobs = json.load(open(os.path.join(ROOT, "data", "jobs.json"), encoding="utf-8"))
    rows = "".join(f'''<a class="job" href="{j.get('link','#')}"><div><h3>{j['title']}</h3>
<div class="meta"><span>{j['company']}</span><span class="dot"></span><span>{j['location']}</span>
<span class="dot"></span><span>{j['level']}</span><span class="dot"></span>
<span>{fmt_date(j.get('date',''))}</span></div>
<div class="why"><b>Why it made the list:</b> {j['why']}</div></div>
<span class="tag{' new' if j.get('new') else ''}">{'New' if j.get('new') else j['level']}</span></a>'''
                   for j in jobs["roles"])
    notice = (f'<div class="notice">{jobs["notice"]}</div>' if jobs.get("notice") else "")
    return (head("Top Jobs Worldwide — Inflight Digest", "jobs.html",
                 "Hand-picked senior roles in airline catering, cabin product, IFEC and duty free.")
            + header("jobs")
            + f'''<div class="wrap"><section class="jobhead">
<div><h1 class="serif">Top Jobs Worldwide</h1><p>{jobs['intro']}</p></div>
<div class="postbox"><h3 class="serif">Hiring?</h3>
<p>Reach people already working in this industry. Send the role &mdash; if it clears the bar
below, it runs for 30 days.</p>
<a href="mailto:{CONTACT_MAIL}?subject=Job%20posting">Submit a role</a></div></section>
<div class="criteria"><span><b>Selected on:</b></span><span>seniority &mdash; lead level and up</span>
<span>named employer, no blind agency ads</span><span>salary band or a real market rate</span>
<span>a role you cannot find on every board</span></div>
{notice}
<div class="jobs">{rows}</div></div>''' + SUBSCRIBE + footer())


MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def ev_dates(start, end):
    """«8–10 Sep 2026», «27 Sep – 1 Oct 2026», «2 Feb 2027»."""
    a = dt.date.fromisoformat(start)
    b = dt.date.fromisoformat(end) if end else a
    if a == b:
        return f"{a.day} {MONTHS[a.month - 1].title()} {a.year}"
    if (a.month, a.year) == (b.month, b.year):
        return f"{a.day}–{b.day} {MONTHS[a.month - 1].title()} {a.year}"
    if a.year == b.year:
        return (f"{a.day} {MONTHS[a.month - 1].title()} – "
                f"{b.day} {MONTHS[b.month - 1].title()} {a.year}")
    return (f"{a.day} {MONTHS[a.month - 1].title()} {a.year} – "
            f"{b.day} {MONTHS[b.month - 1].title()} {b.year}")


def page_events():
    data = json.load(open(os.path.join(ROOT, "data", "events.json"), encoding="utf-8"))
    today = dt.date.today()

    # Прошедшее уходит со страницы само: сравниваем с датой окончания, поэтому
    # выставка висит до последнего своего дня включительно, а не пропадает
    # утром первого. Сборка идёт каждые 4 часа, так что страница не устареет.
    upcoming = []
    for e in data["events"]:
        end = dt.date.fromisoformat(e.get("end") or e["start"])
        if end >= today:
            upcoming.append(e)
    upcoming.sort(key=lambda e: (e["start"], e["name"]))

    if not upcoming:
        rows = ('<div class="notice">The calendar is being rebuilt — '
                'next season\'s dates go up as organisers confirm them.</div>')
    else:
        cells = []
        for e in upcoming:
            start = dt.date.fromisoformat(e["start"])
            days = (start - today).days
            if days <= 0:
                soon = '<span class="soon now">On now</span>'
            elif days == 1:
                soon = '<span class="soon next">Tomorrow</span>'
            elif days <= 45:
                soon = f'<span class="soon next">In {days} days</span>'
            else:
                soon = ""
            # «Singapore · Singapore» — город-государство, страну не повторяем
            place = [e.get("venue"), e.get("city")]
            if e.get("country") and e.get("country") != e.get("city"):
                place.append(e["country"])
            where = " &middot; ".join(x for x in place if x)
            tags = "".join(f'<span class="et">{t}</span>' for t in e.get("tags", []))
            if e.get("unconfirmed"):
                tags += '<span class="et tbc">Dates to confirm</span>'
            name = e["name"]
            if e.get("url"):
                name = (f'<a href="{e["url"]}" target="_blank" '
                        f'rel="noopener">{name}</a>')
            cells.append(f'''<div class="ev{' big' if e.get('featured') else ''}">
<div class="when"><span class="m">{MONTHS[start.month - 1]}</span>
<span class="d">{start.day}</span><span class="y">{start.year}</span></div>
<div class="what"><h3>{name}</h3>
<div class="meta">{ev_dates(e["start"], e.get("end"))} &middot; {where}</div>
<p>{e.get("note", "")}</p><div class="tags">{tags}</div></div>
<div class="flag">{soon}</div></div>''')
        rows = f'<div class="evs">{"".join(cells)}</div>'

    checked = data.get("checked", "")
    foot = (f'<p class="evnote">Checked against the organisers&rsquo; own sites'
            f'{" on " + fmt_date(checked) if checked else ""}. Entries marked '
            f'<b>dates to confirm</b> come from trade databases only &mdash; the '
            f'organiser publishes no English page we could read, so treat those '
            f'dates as indicative. Organisers move things: check before you book a '
            f'flight. Running something we have missed? '
            f'<a href="contact.html">Tell us</a>.</p>')

    ev_ld = {"@context": "https://schema.org", "@type": "ItemList",
             "name": "Airline catering, cabin and travel retail trade shows",
             "itemListElement": [
                 {"@type": "ListItem", "position": i,
                  "item": {"@type": "Event", "name": e["name"],
                           "startDate": e["start"], "endDate": e.get("end") or e["start"],
                           "eventStatus": "https://schema.org/EventScheduled",
                           "eventAttendanceMode":
                               "https://schema.org/OfflineEventAttendanceMode",
                           "location": {"@type": "Place",
                                        "name": e.get("venue") or e.get("city", ""),
                                        "address": {"@type": "PostalAddress",
                                                    "addressLocality": e.get("city", ""),
                                                    "addressCountry": e.get("country", "")}},
                           **({"url": e["url"]} if e.get("url") else {})}}
                 for i, e in enumerate(upcoming, 1)]} if upcoming else None
    return (head("Events — Inflight Digest", "events.html",
                 "Trade shows and conferences in airline catering, cabin interiors, "
                 "IFEC and travel retail. Past events drop off automatically.",
                 ld=ld_json(org_ld(), ev_ld))
            + header("events")
            + f'''<div class="wrap"><section class="jobhead evhead">
<div><h1 class="serif">Events</h1><p>{data["intro"]}</p></section>
{rows}{foot}</div>''' + SUBSCRIBE + footer())


def write_feed(items):
    """RSS. Для отраслевого издания это рабочий канал: по ленте вас забирают
    агрегаторы, читалки и чужие рассылки — тот же механизм, которым мы сами
    собираем чужие новости."""
    now = dt.datetime.now(dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    parts = []
    for it in items[:40]:
        try:
            d = dt.date.fromisoformat(it.get("date", ""))
            pub = d.strftime("%a, %d %b %Y 08:00:00 +0000")
        except Exception:
            pub = now
        parts.append(
            "  <item>\n"
            f"    <title>{H.escape(it['title'])}</title>\n"
            f"    <link>{SITE_URL}/{it['url']}</link>\n"
            f"    <guid isPermaLink=\"true\">{SITE_URL}/{it['url']}</guid>\n"
            f"    <category>{H.escape(RUB_TITLE[it['rubric']])}</category>\n"
            f"    <pubDate>{pub}</pubDate>\n"
            f"    <description>{H.escape(it['stand'])}</description>\n"
            "  </item>\n")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>\n'
           f"  <title>{PUBLISHER}</title>\n"
           f"  <link>{SITE_URL}/</link>\n"
           f'  <atom:link href="{SITE_URL}/feed.xml" rel="self" type="application/rss+xml"/>\n'
           "  <description>Independent trade news on airline catering, inflight "
           "entertainment, cabin interiors and onboard service.</description>\n"
           "  <language>en</language>\n"
           f"  <lastBuildDate>{now}</lastBuildDate>\n"
           + "".join(parts) + "</channel>\n</rss>\n")
    open(os.path.join(ROOT, "feed.xml"), "w", encoding="utf-8").write(xml)
    return len(parts)


def page_doc(key, title, lead, body):
    """Текстовая страница с подзаголовками — редполитика, источники."""
    return (head(f"{title} — Inflight Digest", f"{key}.html",
                 re.sub("<[^>]+>", " ", lead)[:180], ld=ld_json(org_ld()))
            + header() + f'''<div class="wrap"><section class="rubhead">
<h1 class="serif">{title}</h1><p>{lead}</p></section>
<div class="doc">{body}</div></div>''' + SUBSCRIBE + footer())


EDITORIAL_POLICY = """
<h2>Who publishes this</h2>
<p>Inflight Digest is written and edited by Vlad Mazur in Kyiv, Ukraine, and published by
him as a registered sole trader. It is not owned by an airline, a caterer, a supplier or a
trade association. There is one person here, and his name is on every story.</p>

<h2>How stories are chosen</h2>
<p>Headlines arrive automatically: a script reads the RSS feeds of industry publications
and a set of standing searches several times a day, and drops candidates into a queue.
Nothing reaches the site from that queue on its own. Every item is read, judged and
either published or deleted by hand. Roughly four out of five are deleted &mdash;
anniversaries, photo galleries, reprinted press releases and &ldquo;top ten&rdquo; lists
do not make the page.</p>
<p>What does make it: contracts and tenders, appointments at director level and above,
new onboard product, incidents and regulatory action, and the supplier side of the
business that the mainstream aviation press ignores.</p>

<h2>What we publish and what we do not</h2>
<p>We publish a headline, a short summary in our own words, our own comment where we
have something to add, and a link to the original. We do not reprint full articles.
See <a href="sources.html">Sources &amp; attribution</a> for the detail.</p>

<h2>Corrections</h2>
<p>If something here is wrong, write to <a href="mailto:{mail}">{mail}</a> and it gets
fixed. Corrections are made on the story itself, with a note saying what changed &mdash;
we do not quietly edit a page and pretend it always read that way. A subject of a story
who disputes it gets their reply published alongside it.</p>

<h2>Advertising and independence</h2>
<p>Advertising is sold separately from editorial and marked as advertising. No advertiser
sees a story before it runs, and no advertiser has ever been given, or will be given, a
say in what is covered. If a story concerns a company that advertises here, that fact is
stated in the story.</p>
""".replace("{mail}", CONTACT_MAIL)

SOURCES_DOC = """
<h2>Summary and link, never the full text</h2>
<p>Every story on this site credits its source publication by name and links to the
original article. We publish a headline, a short factual summary written in our own
words, and our own analysis. We do not republish full articles, and we do not reproduce
long passages of someone else&rsquo;s reporting. If you want the whole story, the link
takes you to the people who did the work.</p>

<h2>Photographs</h2>
<p>Where a source supplies a photograph, it is displayed from the publisher&rsquo;s own
server &mdash; we do not copy images onto ours. If the publisher removes or blocks the
image, the tile falls back to a plain coloured panel generated here. Illustrations marked
as ours are generated by this site and free to reuse with credit.</p>

<h2>Where the headlines come from</h2>
<p>Industry publications whose feeds we read: Runway Girl Network, Aircraft Interiors
International, PaxEx.aero, APEX, Inflight, TRBusiness, The Moodie Davitt Report and
TheDesignAir. Alongside them run standing searches on airline catering, inflight
entertainment and connectivity, executive appointments, food and drink brand deals,
low-cost carrier menus, and onboard product manufacturing.</p>

<h2>If you are a publisher</h2>
<p>If you would rather we did not summarise or link to your material, say so at
<a href="mailto:{mail}">{mail}</a> and we will remove it and stop reading your feed.
No argument, no delay. If we have credited you incorrectly, tell us and it is corrected
the same day.</p>
""".replace("{mail}", CONTACT_MAIL)


def page_simple(key, title, text, active=None):
    # для description режем по границе слова, иначе можно разрубить &mdash;
    plain = " ".join(re.sub("<[^>]+>", " ", text).split())
    if len(plain) > 180:
        plain = plain[:180].rsplit(" ", 1)[0] + "…"
    return (head(f"{title} — Inflight Digest", f"{key}.html", plain)
            + header(active) + f'''<div class="wrap"><section class="rubhead">
<h1 class="serif">{title}</h1><p>{text}</p></section></div>'''
            + SUBSCRIBE + footer())


# ---------------------------------------------------------------- сборка
def main():
    items, promote = load_all()
    print(f"опубликованных материалов: {len(items)}")

    write = {"index.html": page_index(items)}
    for key, title, blurb in RUBRICS:
        write[f"{key}.html"] = page_rubric(key, title, blurb,
                                           [i for i in items if i["rubric"] == key])
    for it in items:
        write[it["url"]] = page_article(it, items)
    write["jobs.html"] = page_jobs()
    write["events.html"] = page_events()
    write["editorial-policy.html"] = page_doc(
        "editorial-policy", "Editorial policy",
        "Who writes this, how stories are chosen, and what happens when we get "
        "something wrong.", EDITORIAL_POLICY)
    write["sources.html"] = page_doc(
        "sources", "Sources &amp; attribution",
        "We summarise and link. Here is exactly what that means, and how to reach us "
        "if you are the publisher.", SOURCES_DOC)
    write["contact.html"] = page_simple(
        "contact", "Contact",
        'Inflight Digest is written and edited by Vlad Mazur in Kyiv, Ukraine. '
        'Story tips, corrections, a right of reply, press releases and '
        'advertising enquiries all reach the same desk &mdash; and get an answer.'
        '<br><br>'
        '<b>Email</b> &mdash; <a href="mailto:vladyslav.mazur@gmail.com" '
        'style="color:var(--red)">vladyslav.mazur@gmail.com</a><br>'
        '<b>Phone</b> &mdash; <a href="tel:+380913057585" '
        'style="color:var(--red)">+380 91 305 7585</a> '
        '(also WhatsApp, Viber, Telegram)<br>'
        '<b>Advertising</b> &mdash; rates and formats on the '
        '<a href="advertise.html" style="color:var(--red)">Advertise</a> page<br>'
        '<b>Jobs</b> &mdash; send the role, see the bar on the '
        '<a href="jobs.html" style="color:var(--red)">Top Jobs Worldwide</a> page'
        '<br><br>'
        '<b>Publisher</b><br>'
        'Vladyslav Mazur, individual entrepreneur (FOP), registered in Ukraine<br>'
        '14A Polovetska St, Kyiv 04107, Ukraine'
        '<br><br>'
        'Spotted a mistake? Write in &mdash; corrections are published on the '
        'story itself, not buried.')
    write["404.html"] = page_simple(
        "404", "404",
        'That page has taken off without us. Try <a href="index.html" '
        'style="color:var(--red)">today\'s board</a> or pick a section above.')

    for name, htmlsrc in write.items():
        with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
            f.write(htmlsrc)

    # подчищаем страницы, которые сборка делала раньше, а теперь не делает
    # (материал сняли с публикации или удалили) — чтобы на сайте не оставалось
    # висящих страниц без ссылок на них
    manifest = os.path.join(ROOT, "data", "generated.json")
    old = []
    if os.path.exists(manifest):
        old = json.load(open(manifest)).get("files", [])
    for name in old:
        if name not in write and os.path.exists(os.path.join(ROOT, name)):
            os.remove(os.path.join(ROOT, name))
            print(f"  - удалена устаревшая страница: {name}")
    json.dump({"files": sorted(write)}, open(manifest, "w"), indent=1)

    urls = "".join(f"  <url><loc>{SITE_URL}/{p}</loc></url>\n"
                   for p in sorted(write) if p != "404.html")
    open(os.path.join(ROOT, "sitemap.xml"), "w").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n")

    n_feed = write_feed(items)
    print(f"в RSS-ленте материалов: {n_feed}")

    # advertise.html свёрстан руками и сборкой не создаётся, поэтому запрет
    # индексации в нём пришлось бы снимать отдельно — и о нём легко забыть.
    # Синхронизируем автоматически: одна строка, тот же флаг NOINDEX.
    adv = os.path.join(ROOT, "advertise.html")
    if os.path.exists(adv):
        html = open(adv, encoding="utf-8").read()
        # Раньше здесь умели только добавить или убрать noindex. Открытая
        # advertise.html оставалась вообще без тега: индексировалась, но без
        # max-image-preview — единственная страница сайта не как все.
        # Теперь просто выставляем ровно тот же тег, что и в head().
        cleaned = re.sub(r'[ \t]*<meta name="robots"[^>]*>\n?', "", html)
        # \n? в конце обязателен: без него перевод строки, добавленный при
        # вставке, остаётся в файле, и каждая пересборка копит по пустой
        # строке — файл меняется всегда, значит коммитится каждые 4 часа
        cleaned = re.sub(r"<!-- (?:ga|js) -->.*?<!-- /(?:ga|js) -->\n?", "", cleaned, flags=re.S)
        fixed = cleaned.replace("<title>", robots_tag() + "\n<title>", 1)
        if site_js():
            fixed = fixed.replace("</head>", site_js() + "\n</head>", 1)
        # подчищаем пустые строки перед </head>: и как страховка от накопления,
        # и чтобы разово убрать то, что уже успело накопиться до этой правки
        fixed = re.sub(r"\n{2,}(?=</head>)", "\n", fixed)
        if fixed != html:
            open(adv, "w", encoding="utf-8").write(fixed)
            print(f"  → advertise.html: "
                  f"{'закрыт от' if NOINDEX else 'открыт для'} индексации")

    robots = ("# Draft site — nothing here should be indexed yet.\n"
              "User-agent: *\nDisallow: /\n\n" if NOINDEX else
              "User-agent: *\nAllow: /\n\n")
    open(os.path.join(ROOT, "robots.txt"), "w").write(
        robots + f"Sitemap: {SITE_URL}/sitemap.xml\n")
    open(os.path.join(ROOT, ".nojekyll"), "w").write("")

    for src in ("favicon.svg", "favicon-32.png", "favicon-180.png", "og-image.png"):
        s = os.path.join(ROOT, "assets", src)
        if os.path.exists(s):
            shutil.copy(s, os.path.join(ROOT, src))

    os.makedirs(POSTS, exist_ok=True)
    for name in promote:
        shutil.move(os.path.join(QUEUE, name), os.path.join(POSTS, name))
        print(f"  → опубликовано: {name}")

    print(f"собрано страниц: {len(write) + 2}")


if __name__ == "__main__":
    main()
