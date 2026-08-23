#!/usr/bin/env python3
"""The Monday Digest — письмо читателям с тем, что вышло на сайте за неделю.

Не путать с send_digest.py: тот служебный, шлёт вам очередь черновиков с
кнопками «одобрить». Этот — читательский, берёт только опубликованное и
никаких внутренних ссылок в нём нет.

Доступы те же, что у утреннего письма, плюс один новый секрет:

    SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS   как у send_digest.py
    NEWSLETTER_TO   адреса подписчиков через запятую
    MAIL_FROM       необязательно, по умолчанию SMTP_USER

Каждому подписчику уходит ОТДЕЛЬНОЕ письмо. Так адреса не видят друг друга —
ни в «Кому», ни в «Копии», ни в служебных заголовках, — и сбой на одном
адресе не срывает рассылку остальным.

Посмотреть вёрстку, ничего не отправляя:
    DRY_RUN=1 python scripts/send_newsletter.py
"""
import os, re, sys, time, smtplib, html as H, datetime as dt
from email.message import EmailMessage
from email.utils import formataddr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
POSTS, QUEUE = os.path.join(ROOT, "posts"), os.path.join(ROOT, "queue")

SITE = "https://airocatering.github.io/inflight-digest"
PUBLISHER = "Inflight Digest"
DAYS = int(os.environ.get("NEWSLETTER_DAYS", "7"))
MAX_ITEMS = int(os.environ.get("NEWSLETTER_MAX", "12"))

RUB_TITLE = {
    "catering": "Airline Catering", "entertainment": "Entertainment",
    "connectivity": "Connectivity", "onboard-service": "Onboard Service",
    "cabin-interior": "Cabin Interior", "duty-free": "Duty Free",
}
INK, RED, MUTED, LINE = "#141414", "#E1251B", "#75716A", "#DFDCD5"


def unquote_yaml(v):
    if len(v) >= 2 and v[0] == v[-1] == '"':
        v = v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return v


def read_published():
    """Только status: published. Черновики и отложенное в письмо не попадают."""
    items = []
    for folder in (POSTS, QUEUE):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".md"):
                continue
            raw = open(os.path.join(folder, name), encoding="utf-8").read()
            m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.S)
            if not m:
                continue
            meta = {}
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = unquote_yaml(v.strip())
            if meta.get("status", "draft").lower() != "published":
                continue
            body = re.sub(r"<!--.*?-->", "", m.group(2), flags=re.S).strip()
            meta["stand"] = (body.split("\n\n")[0] if body else "")[:260]
            stem = meta.get("slug") or re.sub(r"[^a-z0-9]+", "-",
                                              name[:-3].lower()).strip("-")
            meta["url"] = f"{SITE}/{stem}.html"
            items.append(meta)
    return items


def fresh_only(items, cutoff):
    out = []
    for it in items:
        try:
            if dt.date.fromisoformat(it.get("date", "")) >= cutoff:
                out.append(it)
        except ValueError:
            continue
    out.sort(key=lambda x: x.get("date", ""), reverse=True)
    return out[:MAX_ITEMS]


def build_html(items, week):
    rows = []
    for it in items:
        rows.append(f"""
      <tr><td style="padding:18px 0;border-bottom:1px solid {LINE}">
        <div style="font:700 10px/1 -apple-system,Segoe UI,sans-serif;letter-spacing:.12em;
             text-transform:uppercase;color:{RED};padding-bottom:8px">
          {H.escape(RUB_TITLE.get(it.get('rubric', ''), 'News'))}</div>
        <a href="{H.escape(it['url'])}" style="font:600 19px/1.3 -apple-system,Segoe UI,sans-serif;
           color:{INK};text-decoration:none;display:block;padding-bottom:7px">
           {H.escape(it.get('title', ''))}</a>
        <div style="font:400 14.5px/1.55 -apple-system,Segoe UI,sans-serif;color:#555;
             padding-bottom:10px">{H.escape(it['stand'])}</div>
        <a href="{H.escape(it['url'])}" style="font:600 12px/1 -apple-system,sans-serif;
           color:{RED};text-decoration:none">Read on Inflight Digest &rarr;</a>
      </td></tr>""")

    return f"""<!DOCTYPE html><html><body style="margin:0;background:#F3F1EC;padding:24px 12px">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0"
       style="max-width:620px;background:#fff;padding:30px 28px 34px">
  <tr><td>
    <a href="{SITE}" style="font:800 26px/1 -apple-system,Segoe UI,sans-serif;color:{INK};
       letter-spacing:-.02em;text-decoration:none">Inflight Digest</a>
    <div style="font:600 10px/1 -apple-system,sans-serif;letter-spacing:.16em;
         text-transform:uppercase;color:{MUTED};padding-top:7px">
      The Monday Digest &middot; {week}</div>
    <div style="height:3px;width:52px;background:{RED};margin-top:14px"></div>
  </td></tr>
  <tr><td style="font:400 15px/1.55 -apple-system,Segoe UI,sans-serif;color:#444;
      padding-top:18px">
    Everything worth knowing from airline catering, cabin, IFEC and duty free
    this week &mdash; {len(items)} {'story' if len(items) == 1 else 'stories'},
    picked by hand.
  </td></tr>
  <tr><td><table width="100%" cellpadding="0" cellspacing="0">{''.join(rows)}</table></td></tr>
  <tr><td style="padding-top:26px">
    <div style="font:400 12px/1.6 -apple-system,sans-serif;color:{MUTED}">
      You are receiving this because you subscribed at
      <a href="{SITE}" style="color:{RED}">{PUBLISHER}</a>.
      To stop receiving it, just reply to this email and say so.<br><br>
      {PUBLISHER} &middot; Kyiv, Ukraine &middot;
      <a href="{SITE}/contact.html" style="color:{RED}">Contact</a>
    </div>
  </td></tr>
</table></td></tr></table></body></html>"""


def build_text(items, week):
    lines = [f"{PUBLISHER} — The Monday Digest · {week}", ""]
    for it in items:
        lines += [f"[{RUB_TITLE.get(it.get('rubric', ''), 'News')}] {it.get('title', '')}",
                  f"  {it['stand']}",
                  f"  {it['url']}", ""]
    lines += ["--",
              "To stop receiving this, just reply to this email and say so.",
              f"{PUBLISHER} · Kyiv, Ukraine · {SITE}"]
    return "\n".join(lines)


def recipients():
    raw = os.environ.get("NEWSLETTER_TO", "")
    return [a.strip() for a in re.split(r"[,;\s]+", raw) if "@" in a]


def main():
    cutoff = dt.date.today() - dt.timedelta(days=DAYS)
    items = fresh_only(read_published(), cutoff)
    week = dt.date.today().strftime("%d %B %Y")

    print(f"опубликовано за {DAYS} дн.: {len(items)}")
    if not items:
        print("за неделю ничего не вышло — письмо не отправляем")
        return

    html, text = build_html(items, week), build_text(items, week)

    if os.environ.get("DRY_RUN"):
        p = os.path.join(ROOT, "newsletter-preview.html")
        open(p, "w", encoding="utf-8").write(html)
        print(f"вёрстка записана в {os.path.basename(p)}, отправка пропущена")
        return

    people = recipients()
    if not people:
        print("список подписчиков пуст (NEWSLETTER_TO) — рассылать некому")
        return

    host, port = os.environ.get("SMTP_HOST"), int(os.environ.get("SMTP_PORT") or 465)
    user, pwd = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS")
    if not (host and user and pwd):
        sys.exit("не заданы SMTP_HOST / SMTP_USER / SMTP_PASS")
    # не get(..., user): неопределённый секрет GitHub приходит ПУСТОЙ СТРОКОЙ,
    # а не отсутствует — значение по умолчанию в get() тогда не срабатывает
    sender = os.environ.get("MAIL_FROM") or user
    subject = f"The Monday Digest — {len(items)} " + ("story" if len(items) == 1 else "stories")

    smtp = (smtplib.SMTP_SSL(host, port, timeout=30) if port == 465
            else smtplib.SMTP(host, port, timeout=30))
    with smtp:
        if port != 465:
            smtp.starttls()
        smtp.login(user, pwd)
        sent = failed = 0
        for addr in people:
            # Отдельное письмо каждому: подписчики не видят друг друга,
            # и падение одного адреса не срывает рассылку остальным.
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = formataddr((PUBLISHER, sender))
            msg["To"] = addr
            msg["Reply-To"] = sender
            msg.set_content(text)
            msg.add_alternative(html, subtype="html")
            try:
                smtp.send_message(msg)
                sent += 1
            except Exception as e:
                failed += 1
                print(f"  ! не ушло на {addr}: {e}")
            time.sleep(0.4)          # не долбим сервер очередью подряд
    print(f"отправлено: {sent}, не доставлено: {failed}, всего в списке: {len(people)}")


if __name__ == "__main__":
    main()
