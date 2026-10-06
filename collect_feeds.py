#!/usr/bin/env python3
"""
Carpool Line — morning feed collector

Pulls every RSS feed below, keeps stories from the last 28 hours, and writes
one digest file that the Cowork task reads:  digest/latest.md
(plus a dated copy in digest/archive/).

To add a source, paste its RSS URL into FEEDS with a name and tier.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests

LOCAL_TZ = ZoneInfo("America/Chicago")
LOOKBACK_HOURS = 28
GN = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="

# (name, tier, url, kind)
#   tier: 1 = hyperlocal, 2 = Google News local search, 3 = Birmingham metro
#   kind: "news"     -> stories from the last 28 hours
#         "agenda"   -> council/commission agendas posted in the last 7 days
#         "calendar" -> events and meetings from 7 days ago through 3 weeks ahead
FEEDS = [
    # Hyperlocal news
    ("Hoover Sun", 1, "https://hooversun.com/api/rss/content.rss", "news"),
    ("280 Living", 1, "https://280living.com/api/rss/content.rss", "news"),
    ("Shelby County Reporter", 1, "https://www.shelbycountyreporter.com/rss.xml", "news"),
    ("Village Living", 1, "https://www.villagelivingonline.com/api/rss/content.rss", "news"),
    ("Vestavia Voice", 1, "https://vestaviavoice.com/api/rss/content.rss", "news"),
    ("The Homewood Star", 1, "https://thehomewoodstar.com/api/rss/content.rss", "news"),
    ("City of Homewood", 1, "https://www.cityofhomewood.com/feed/rss2", "news"),
    ("City of Vestavia Hills", 1, "https://vhal.org/feed/", "news"),

    # City and county government: agendas and calendars
    ("Hoover public meetings", 1, "https://www.hooveralabama.gov/RSSFeed.aspx?ModID=58&CID=Official-Public-Meetings-26", "calendar"),
    ("Hoover city calendar", 1, "https://www.hooveralabama.gov/RSSFeed.aspx?ModID=58&CID=All-calendar.xml", "calendar"),
    ("Pelham city meetings", 1, "https://www.pelhamalabama.gov/RSSFeed.aspx?ModID=58&CID=City-Meetings-Calendar-14", "calendar"),
    ("Chelsea council agendas", 1, "https://www.cityofchelsea.com/RSSFeed.aspx?ModID=65&CID=All-0", "agenda"),
    ("Shelby County agendas", 1, "https://www.shelbyal.com/RSSFeed.aspx?ModID=65&CID=All-0", "agenda"),

    # Google News local searches (catch Helena, schools, and outlets without feeds)
    ("Google News: Hoover", 2, GN + "%22Hoover%22+Alabama+when:1d", "news"),
    ("Google News: Shelby County", 2, GN + "%22Shelby+County%22+Alabama+-Tennessee+-Memphis+when:1d", "news"),
    ("Google News: Pelham/Alabaster/Helena", 2, GN + "(Pelham+OR+Alabaster+OR+Helena)+Alabama+when:1d", "news"),
    ("Google News: Oak Mountain/280", 2, GN + "(%22Oak+Mountain%22+OR+%22Chelsea+Alabama%22+OR+%22Highway+280%22+Birmingham)+when:1d", "news"),
    ("Google News: Vestavia/Mountain Brook", 2, GN + "(%22Vestavia+Hills%22+OR+%22Mountain+Brook%22)+Alabama+when:1d", "news"),
    ("Google News: local schools", 2, GN + "(%22Hoover+City+Schools%22+OR+%22Shelby+County+Schools%22+OR+%22Alabaster+City+Schools%22+OR+%22Pelham+City+Schools%22)+when:2d", "news"),

    # Birmingham metro (use only with a clear local angle)
    ("WBRC Fox 6", 3, "https://www.wbrc.com/arc/outboundfeeds/rss/?outputType=xml", "news"),
    ("AL.com", 3, "https://www.al.com/arc/outboundfeeds/rss/?outputType=xml", "news"),
    ("CBS 42", 3, "https://www.alabamas42.com/feed/", "news"),
    ("WVTM 13", 3, "https://www.wvtm13.com/topstories-rss", "news"),
    ("Bham Now", 3, "https://bhamnow.com/feed/", "news"),
    ("Birmingham Watch", 3, "https://birminghamwatch.org/feed/", "news"),
    ("Birmingham Times", 3, "https://www.birminghamtimes.com/feed/", "news"),
    ("BirminghamMommy", 3, "https://birminghammommy.com/feed/", "news"),
]

TN_WORDS = ["tennessee", "memphis", "germantown", "bartlett", "collierville"]
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def published(entry):
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def clean(html, limit=600):
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()[:limit]


WINDOWS = {  # (days back, days ahead)
    "news": (LOOKBACK_HOURS / 24, 0.5),
    "agenda": (7, 30),
    "calendar": (7, 21),
}
MAX_ITEMS = {"news": 25, "agenda": 6, "calendar": 12}


def collect():
    now = datetime.now(timezone.utc)
    stories, health, seen = [], [], set()

    for name, tier, url, kind in FEEDS:
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
        except Exception as e:
            health.append(f"❌ {name}: couldn't load ({type(e).__name__})")
            continue
        if not feed.entries:
            health.append(f"⚠️ {name}: feed returned nothing")
            continue

        back, ahead = WINDOWS[kind]
        earliest, latest = now - timedelta(days=back), now + timedelta(days=ahead)
        kept = 0
        limit = 8 if tier == 2 else MAX_ITEMS[kind]
        for entry in feed.entries:
            if kept >= limit:
                break
            when = published(entry)
            if when and not (earliest <= when <= latest):
                continue
            if not when and kind == "news":
                continue
            title = (entry.get("title") or "").strip()
            outlet = name
            if tier == 2:  # Google News titles end in " - Outlet"
                m = re.match(r"^(.+)\s+-\s+([^-]+)$", title)
                if m:
                    title, outlet = m.group(1).strip(), m.group(2).strip()
            summary = clean(entry.get("summary") or entry.get("description"))
            if any(w in f"{title} {summary}".lower() for w in TN_WORDS):
                continue
            key = re.sub(r"[^a-z0-9]", "", title.lower())[:80] + (kind if kind != "news" else "")
            if not title or key in seen:
                continue
            seen.add(key)
            stories.append({
                "tier": tier, "kind": kind, "feed": name, "outlet": outlet, "title": title,
                "summary": summary, "link": entry.get("link", ""),
                "when": when.astimezone(LOCAL_TZ).strftime("%a %b %d, %-I:%M %p") if when else "date not listed",
            })
            kept += 1
        health.append(f"✅ {name}: {kept} kept")

    return stories, health


def write_digest(stories, health):
    now = datetime.now(LOCAL_TZ)
    labels = {1: "Tier 1 — Hyperlocal", 2: "Tier 2 — Local search (Google News)",
              3: "Tier 3 — Birmingham metro (use only with a clear local angle)"}
    lines = [f"# Carpool Line news digest — {now:%A, %B %d, %Y}",
             f"Collected {now:%-I:%M %p} CT · {sum(1 for s in stories if s['kind'] == 'news')} news stories from the last {LOOKBACK_HOURS} hours, plus {sum(1 for s in stories if s['kind'] != 'news')} upcoming events and agenda items", ""]
    n = 0
    sections = [(labels[t], [s for s in stories if s["tier"] == t and s["kind"] == "news"]) for t in (1, 2, 3)]
    sections.append(("Upcoming events and public meetings (city calendars and agendas — dates may be the event date or the posting date; open the link to confirm)",
                     [s for s in stories if s["kind"] != "news"]))
    for heading, group in sections:
        if not group:
            continue
        lines += [f"## {heading}", ""]
        for s in group:
            n += 1
            lines += [f"### S{n}. {s['title']}",
                      f"- Outlet: {s['outlet']} (via {s['feed']})",
                      f"- Published: {s['when']}",
                      f"- Link: {s['link']}",
                      f"- Summary: {s['summary'] or '(headline only — open the link for details)'}", ""]
    lines += ["## Feed health", *[f"- {h}" for h in health], ""]

    text = "\n".join(lines)
    Path("digest/archive").mkdir(parents=True, exist_ok=True)
    Path("digest/latest.md").write_text(text, encoding="utf-8")
    Path(f"digest/archive/{now:%Y-%m-%d}.md").write_text(text, encoding="utf-8")
    print(text[-1500:])


if __name__ == "__main__":
    stories, health = collect()
    write_digest(stories, health)
