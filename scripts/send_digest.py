#!/usr/bin/env python3
"""Утреннее письмо: что робот принёс в очередь за последние сутки.

Ничего не публикует и не меняет. Только читает queue/ и отправляет письмо
по SMTP. Доступы берутся из переменных окружения (в GitHub — из Secrets):

    SMTP_HOST   smtp.gmail.com
    SMTP_PORT   465 (SSL) или 587 (STARTTLS)
    SMTP_USER   почтовый ящик, от чьего имени отправляем
    SMTP_PASS   пароль приложения, НЕ основной пароль от почты
    MAIL_TO     кому слать, можно несколько через запятую
    MAIL_FROM   необязательно, по умолчанию SMTP_USER

Проверить вёрстку письма, ничего не отправляя:
    DRY_RUN=1 python scripts/send_digest.py
"""
import os, re, sys, json, smtplib, html as H, datetime as dt
from email.message import EmailMessage

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QUEUE = os.path.join(ROOT, "queue")
SENT_MARKER = os.path.join(ROOT, "data", "digest_sent.json")

REPO = os.environ.get("GITHUB_REPOSITORY", "airocatering/inflight-digest")
SITE = "https://airocatering.github.io/inflight-digest"
HOURS = int(os.environ.get("DIGEST_HOURS", "24"))

RUB_TITLE = {
    "catering": "Airline Catering", "entertainment": "Entertainment",
    "connectivity": "Connectivity", "onboard-service": "Onboard Service",
    "cabin-interior": "Cabin Interior", "duty-free": "Duty Free",
}
INK, RED, MUTED, LINE = "#141414", "#E1251B", "#75716A", "#DFDCD5"


def unquote_yaml(v):
    """title: "Country: subtitle" — снимаем кавычки, которые ставит
    fetch_feeds.py, чтобы такой заголовок не ломал YAML на GitHub."""
    if len(v) >= 2 and v[0] == v[-1] == '"':
        v = v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return v


def read_queue():
    items = []
    if not os.path.isdir(QUEUE):
        return items
    for name in sorted(os.listdir(QUEUE)):
        if not name.endswith(".md"):
            continue
        raw = open(os.path.join(QUEUE, name), encoding="utf-8").read()
        m = re.match(r"^---\s*\n(.*?)\n---", raw, re.S)
        if not m:
            continue
        meta = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = unquote_yaml(v.strip())
        meta["file"] = name
        body = raw.split("---", 2)[-1]
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S).strip()
        meta["stand"] = (body.split("\n\n")[0] if body else "")[:280]
        items.append(meta)
    return items


def is_fresh(meta, cutoff):
    stamp = meta.get("added")
    if stamp:
        try:
            return dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=dt.timezone.utc) >= cutoff
        except ValueError:
            pass
    try:                                   # файлы до появления отметки
        return dt.datetime.fromisoformat(meta.get("date", "")).replace(
            tzinfo=dt.timezone.utc) >= cutoff
    except ValueError:
        return False


def already_sent_today():
    """Второй cron-слот (страховка на случай, если первый не сработает —
    GitHub Actions периодически теряет плановые запуски) не должен слать
    письмо повторно, если первый слот в тот же день уже отправил его."""
    if not os.path.exists(SENT_MARKER):
        return False
    try:
        data = json.load(open(SENT_MARKER, encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return data.get("date") == dt.datetime.now(dt.timezone.utc).date().isoformat()


def mark_sent():
    os.makedirs(os.path.dirname(SENT_MARKER), exist_ok=True)
    json.dump({"date": dt.datetime.now(dt.timezone.utc).date().isoformat()},
              open(SENT_MARKER, "w", encoding="utf-8"))


def edit_url(name):
    from urllib.parse import quote
    return f"https://github.com/{REPO}/edit/main/queue/{quote(name)}"


def build_html(fresh, total_queue, today):
    by_rub = {}
    for it in fresh:
        by_rub.setdefault(it.get("rubric", "cabin-interior"), []).append(it)

    blocks = []
    for rub, items in sorted(by_rub.items(), key=lambda kv: -len(kv[1])):
        rows = []
        for it in items:
            rows.append(f"""
      <tr><td style="padding:16px 0;border-bottom:1px solid {LINE}">
        <div style="font:700 10px/1 -apple-system,Segoe UI,sans-serif;letter-spacing:.12em;
             text-transform:uppercase;color:{RED};padding-bottom:7px">
          {H.escape(it.get('source', ''))} &middot; {H.escape(it.get('date', ''))}</div>
        <div style="font:600 17px/1.3 -apple-system,Segoe UI,sans-serif;color:{INK};
             padding-bottom:6px">{H.escape(it.get('title', ''))}</div>
        <div style="font:400 14px/1.5 -apple-system,Segoe UI,sans-serif;color:#555;
             padding-bottom:10px">{H.escape(it['stand'])}</div>
        <a href="{edit_url(it['file'])}" style="font:600 12px/1 -apple-system,sans-serif;
           color:#fff;background:{INK};padding:8px 14px;text-decoration:none;
           border-radius:2px;display:inline-block">Открыть и одобрить</a>
        <a href="{H.escape(it.get('link', '#'))}" style="font:600 12px/1 -apple-system,sans-serif;
           color:{MUTED};padding:8px 10px;text-decoration:none;display:inline-block">
           Первоисточник</a>
      </td></tr>""")
        blocks.append(f"""
    <tr><td style="padding-top:26px">
      <div style="font:800 12px/1 -apple-system,Segoe UI,sans-serif;letter-spacing:.14em;
           text-transform:uppercase;color:{INK};border-bottom:2px solid {INK};
           padding-bottom:9px">{RUB_TITLE.get(rub, rub)} &middot; {len(items)}</div>
      <table width="100%" cellpadding="0" cellspacing="0">{''.join(rows)}</table>
    </td></tr>""")

    return f"""<!DOCTYPE html><html><body style="margin:0;background:#F3F1EC;padding:24px 12px">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0"
       style="max-width:620px;background:#fff;padding:30px 28px 34px">
  <tr><td>
    <div style="font:800 26px/1 -apple-system,Segoe UI,sans-serif;color:{INK};
         letter-spacing:-.02em">Inflight Digest</div>
    <div style="font:600 10px/1 -apple-system,sans-serif;letter-spacing:.16em;
         text-transform:uppercase;color:{MUTED};padding-top:7px">
      Очередь за последние {HOURS} ч &middot; {today}</div>
    <div style="height:3px;width:52px;background:{RED};margin-top:14px"></div>
  </td></tr>
  <tr><td style="font:400 15px/1.55 -apple-system,Segoe UI,sans-serif;color:#444;
      padding-top:18px">
    Новых материалов: <b style="color:{INK}">{len(fresh)}</b>.
    Всего в очереди: {total_queue}.
  </td></tr>
  {''.join(blocks)}
  <tr><td style="padding-top:28px;border-top:1px solid {LINE}">
    <div style="font:400 12px/1.5 -apple-system,sans-serif;color:{MUTED}">
      Ничего не опубликовано автоматически. Материал попадёт на сайт только после
      того, как вы поменяете <code>status: draft</code> на <code>published</code>.<br>
      <a href="https://github.com/{REPO}/tree/main/queue" style="color:{RED}">Вся очередь</a>
      &nbsp;&middot;&nbsp; <a href="{SITE}" style="color:{RED}">Сайт</a>
    </div>
  </td></tr>
</table></td></tr></table></body></html>"""


def build_text(fresh):
    lines = [f"Inflight Digest — очередь за последние {HOURS} ч", ""]
    for it in fresh:
        lines += [f"[{RUB_TITLE.get(it.get('rubric', ''), '')}] {it.get('title', '')}",
                  f"  {it.get('source', '')} · {it.get('date', '')}",
                  f"  правка: {edit_url(it['file'])}",
                  f"  источник: {it.get('link', '')}", ""]
    return "\n".join(lines)


def main():
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=HOURS)
    queue = read_queue()
    fresh = [i for i in queue if is_fresh(i, cutoff)]
    today = dt.datetime.now(dt.timezone.utc).strftime("%d.%m.%Y")

    print(f"в очереди {len(queue)}, свежих за {HOURS} ч: {len(fresh)}")
    if not fresh:
        print("нечего слать, письмо не отправляем")
        return

    html = build_html(fresh, len(queue), today)

    if os.environ.get("DRY_RUN"):
        open(os.path.join(ROOT, "digest-preview.html"), "w", encoding="utf-8").write(html)
        print("вёрстка письма записана в digest-preview.html, отправка пропущена")
        return

    if already_sent_today():
        print("письмо за сегодня уже отправлено — второй cron-слот, пропускаем")
        return

    # пустой GitHub Secret приходит как "", а не отсутствующая переменная —
    # os.environ.get(..., "465") тогда не подставит дефолт, и int("") упадёт
    # раньше проверки ниже. Поэтому сверяем сырые строки первым делом.
    host = os.environ.get("SMTP_HOST")
    port_raw = os.environ.get("SMTP_PORT") or "465"
    user, pwd = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS")
    to = os.environ.get("MAIL_TO") or user
    if not (host and user and pwd and to):
        sys.exit("не заданы SMTP_HOST / SMTP_USER / SMTP_PASS / MAIL_TO")
    port = int(port_raw)

    msg = EmailMessage()
    msg["Subject"] = f"Inflight Digest — {len(fresh)} в очереди, {today}"
    msg["From"] = os.environ.get("MAIL_FROM", user)
    msg["To"] = to
    msg.set_content(build_text(fresh))
    msg.add_alternative(html, subtype="html")

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            smtp.login(user, pwd)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(user, pwd)
            smtp.send_message(msg)
    print(f"письмо отправлено на {to}")
    mark_sent()


if __name__ == "__main__":
    main()
