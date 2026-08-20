#!/usr/bin/env python3
"""Собирает статический сайт Inflight Digest из одобренных материалов.

Читает queue/*.md и posts/*.md. На сайт попадает только то, где стоит
status: published. Одобренные файлы переезжают из queue/ в posts/.
"""
import os, re, json, base64, shutil, html as H, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUEUE, POSTS = os.path.join(ROOT, "queue"), os.path.join(ROOT, "posts")

SITE_URL = "https://airocatering.github.io/inflight-digest"
NOINDEX = True          # снять, когда наберётся настоящий контент
EDITOR = "Vlad Mazur"

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

/* подсказка, что меню прокручивается вбок */
nav .wrap{position:relative}
nav .links{-webkit-mask-image:linear-gradient(to right,#000 88%,transparent);
mask-image:linear-gradient(to right,#000 88%,transparent)}
@media(min-width:900px){nav .links{-webkit-mask-image:none;mask-image:none}}
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
def parse_md(path):
    raw = open(path, encoding="utf-8").read()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.S)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
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
    items.sort(key=lambda x: (x.get("date", ""), x["file"]), reverse=True)
    return items, promote


def fmt_date(iso):
    try:
        d = dt.date.fromisoformat(iso)
        return d.strftime("%-d %b %Y")
    except Exception:
        return iso or ""


# ---------------------------------------------------------------- каркас
def head(title, path, desc):
    robots = '<meta name="robots" content="noindex,nofollow">\n' if NOINDEX else ""
    url = f"{SITE_URL}/{path}"
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
{robots}<meta name="description" content="{desc}">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="alternate icon" href="favicon-32.png">
<link rel="apple-touch-icon" href="favicon-180.png">
<meta property="og:type" content="website"><meta property="og:site_name" content="Inflight Digest">
<meta property="og:title" content="{title}"><meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}"><meta property="og:image" content="{SITE_URL}/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="{url}">{FONT}<style>{CSS}</style></head><body>'''


def header(active=None):
    links = "".join(f'<a class="{"on" if k == active else ""}" href="{k}.html">{t}</a>'
                    for k, t in NAV)
    today = dt.date.today().strftime("%A, %-d %B %Y")
    return f'''<header><div class="wrap"><a href="index.html">{LOGO}</a>
<div class="hdate"><div class="serif d">{today}</div>
<div class="k">Kyiv &middot; independent trade news</div></div></div></header>
<nav><div class="wrap"><div class="links">{links}</div>
<a class="adv" href="advertise.html">Advertise</a></div></nav>'''


SUBSCRIBE = '''<section class="sub"><div class="wrap">
<div><span class="badge">Free &middot; every Monday</span>
<h2 class="serif">The Monday Digest</h2>
<p>One email a week with everything worth knowing about catering, cabin, IFEC and
duty free &mdash; picked by a human, not a feed reader. No daily noise.</p></div>
<div><form method="POST" action="https://formspree.io/f/YOUR-FORM-ID">
<input type="email" name="email" placeholder="you@airline.com" required>
<button type="submit">Subscribe</button></form>
<div class="fine">Join <b>&mdash;</b> industry readers &middot; unsubscribe in one click &middot;
we never share your address</div></div></div></section>'''


def footer():
    rubs = "".join(f'<li><a href="{k}.html">{t}</a></li>' for k, t, _ in RUBRICS)
    return f'''<footer><div class="wrap">{LOGO_W}
<div class="fcols">
<div><h4>About</h4><ul><li><a href="#">Editorial policy</a></li>
<li><a href="#">Sources &amp; attribution</a></li><li><a href="advertise.html">Advertise</a></li>
<li><a href="contact.html">Contact</a></li></ul></div>
<div><h4>Sections</h4><ul>{rubs}</ul></div>
<div><h4>More</h4><ul><li><a href="jobs.html">Top Jobs Worldwide</a></li>
<li><a href="events.html">Events</a></li><li><a href="#">RSS</a></li></ul></div></div>
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
    return (head("Inflight Digest — airline catering, entertainment, onboard services",
                 "index.html",
                 "Airline catering, inflight entertainment and onboard service news — "
                 "filtered by a human, published daily.")
            + header()
            + f'''<div class="wrap"><div class="lead"><h2>Today's board</h2><div class="l"></div>
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
    return (head(f"{it['title']} — Inflight Digest", it["url"], it["stand"][:180])
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
<figure class="figure">{img_tag(it)}{credit}</figure>
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
    filters = "".join(f'<a class="{"on" if i == 0 else ""}" href="#">{f}</a>'
                      for i, f in enumerate(["All roles", "Catering", "Cabin &amp; seating",
                                             "IFEC", "Duty free", "Remote"]))
    notice = (f'<div class="notice">{jobs["notice"]}</div>' if jobs.get("notice") else "")
    return (head("Top Jobs Worldwide — Inflight Digest", "jobs.html",
                 "Hand-picked senior roles in airline catering, cabin product, IFEC and duty free.")
            + header("jobs")
            + f'''<div class="wrap"><section class="jobhead">
<div><h1 class="serif">Top Jobs Worldwide</h1><p>{jobs['intro']}</p></div>
<div class="postbox"><h3 class="serif">Hiring?</h3>
<p>Reach people already working in this industry. Send the role &mdash; if it clears the bar
below, it runs for 30 days.</p>
<a href="mailto:jobs@inflightdigest.com?subject=Job%20posting">Submit a role</a></div></section>
<div class="criteria"><span><b>Selected on:</b></span><span>seniority &mdash; lead level and up</span>
<span>named employer, no blind agency ads</span><span>salary band or a real market rate</span>
<span>a role you cannot find on every board</span></div>
<div class="jfilter">{filters}</div>{notice}
<div class="jobs">{rows}</div></div>''' + SUBSCRIBE + footer())


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
    write["events.html"] = page_simple(
        "events", "Events",
        "AIX, APEX, WTCE, FTE and the rest of the industry calendar. "
        "This page is compiled by hand — coming soon.", "events")
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

    robots = ("# Draft site — nothing here should be indexed yet.\n"
              "User-agent: *\nDisallow: /\n\n" if NOINDEX else "User-agent: *\nAllow: /\n\n")
    open(os.path.join(ROOT, "robots.txt"), "w").write(robots + f"Sitemap: {SITE_URL}/sitemap.xml\n")
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
