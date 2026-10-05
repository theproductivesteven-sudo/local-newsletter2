#!/usr/bin/env python3
"""
Carpool Line — one-time RSS feed finder.

Visits each local site, discovers its RSS feeds (the way feed readers do, plus
common URL patterns for WordPress, TV station, newspaper, and city-government
platforms), tests every candidate, and writes feed_report.md with ready-to-paste
lines for collect_feeds.py.
"""

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import feedparser
import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

# (name, suggested tier, homepage)
SITES = [
    # Hyperlocal news
    ("Shelby County Reporter", 1, "https://www.shelbycountyreporter.com/"),
    ("Hoover Sun", 1, "https://hooversun.com/"),
    ("280 Living", 1, "https://280living.com/"),
    ("Village Living", 1, "https://www.villagelivingonline.com/"),
    ("Vestavia Voice", 1, "https://vestaviavoice.com/"),
    ("The Homewood Star", 1, "https://thehomewoodstar.com/"),
    ("Over the Mountain Journal", 1, "https://www.otmj.com/"),

    # City governments
    ("City of Hoover", 1, "https://www.hooveralabama.gov/"),
    ("City of Pelham", 1, "https://www.pelhamalabama.gov/"),
    ("City of Alabaster", 1, "https://www.cityofalabaster.com/"),
    ("City of Helena", 1, "https://www.helenaal.org/"),
    ("City of Chelsea", 1, "https://www.cityofchelsea.com/"),
    ("Shelby County (AL) government", 1, "https://www.shelbyal.com/"),
    ("City of Vestavia Hills", 1, "https://www.vhal.org/"),
    ("City of Mountain Brook", 1, "https://www.mtnbrook.org/"),
    ("City of Homewood", 1, "https://www.cityofhomewood.com/"),

    # Schools and libraries
    ("Hoover City Schools", 1, "https://www.hooverschools.org/"),
    ("Shelby County Schools", 1, "https://www.shelbyed.k12.al.us/"),
    ("Alabaster City Schools", 1, "https://www.alabasterschools.org/"),
    ("Pelham City Schools", 1, "https://www.pelhamcityschools.org/"),
    ("Vestavia Hills City Schools", 1, "https://www.vestaviaschools.org/"),
    ("Hoover Public Library", 1, "https://www.hooverlibrary.org/"),

    # Metro TV, radio, and papers
    ("WBRC Fox 6", 3, "https://www.wbrc.com/"),
    ("ABC 33/40", 3, "https://abc3340.com/"),
    ("CBS 42", 3, "https://www.cbs42.com/"),
    ("WVTM 13", 3, "https://www.wvtm13.com/"),
    ("WBHM 90.3", 3, "https://wbhm.org/"),
    ("AL.com", 3, "https://www.al.com/"),
    ("Birmingham Business Journal", 3, "https://www.bizjournals.com/birmingham/"),
    ("Bham Now", 3, "https://bhamnow.com/"),
    ("Birmingham Watch", 3, "https://birminghamwatch.org/"),
    ("Birmingham Times", 3, "https://www.birminghamtimes.com/"),
    ("BirminghamMommy", 3, "https://birminghammommy.com/"),
    ("Alabama NewsCenter", 3, "https://alabamanewscenter.com/"),
]

COMMON_PATHS = [
    "feed/", "rss/", "rss", "feed", "rss.xml", "feed.xml", "index.rss",
    "api/rss/content.rss",                               # Metro Publisher (Starnes)
    "arc/outboundfeeds/rss/?outputType=xml",             # Arc XP (Gray TV, Advance)
    "search/?f=rss&t=article&l=50&s=start_time&sd=desc", # TownNews/BLOX newspapers
    "RSSFeed.aspx?ModID=1&CID=All-newsflash.xml",        # CivicPlus city sites: news
    "RSSFeed.aspx?ModID=58&CID=All-calendar.xml",        # CivicPlus: calendar
]
EXTRA = {  # known feeds that don't live on the homepage domain
    "Birmingham Business Journal": ["https://feeds.bizjournals.com/bizj_birmingham"],
}


def get(url):
    try:
        r = requests.get(url, headers=UA, timeout=15, allow_redirects=True)
        return r if r.status_code == 200 else None
    except Exception:
        return None


def discover(home):
    found = []
    r = get(home)
    if r:
        for tag in re.findall(r"<link[^>]+>", r.text, re.I):
            if re.search(r'type=["\']application/(rss|atom)\+xml', tag, re.I):
                m = re.search(r'href=["\']([^"\']+)', tag, re.I)
                if m:
                    found.append(urljoin(r.url, m.group(1)))
        # CivicPlus lists all its feeds on /rss.aspx
    rp = get(urljoin(home, "rss.aspx"))
    if rp:
        for href in re.findall(r'href=["\']([^"\']*RSSFeed\.aspx[^"\']*)', rp.text, re.I):
            found.append(urljoin(rp.url, href.replace("&amp;", "&")))
    found += [urljoin(home, p) for p in COMMON_PATHS]
    seen, out = set(), []
    for u in found:
        if u not in seen and "comments" not in u.lower():
            seen.add(u); out.append(u)
    return out


def test(url):
    r = get(url)
    if not r:
        return None
    feed = feedparser.parse(r.content)
    if not feed.entries:
        return None
    dates = []
    for e in feed.entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        if t:
            dates.append(datetime(*t[:6], tzinfo=timezone.utc))
    newest = max(dates) if dates else None
    age = (datetime.now(timezone.utc) - newest).days if newest else None
    return {"url": r.url if "news.google" not in url else url, "title": feed.feed.get("title", "").strip(),
            "items": len(feed.entries), "age_days": age}


def main():
    lines = ["# Carpool Line — RSS feed report", f"Run {datetime.now():%Y-%m-%d %H:%M} UTC", ""]
    paste = []
    for name, tier, home in SITES:
        print(f"Checking {name}...")
        good, seen_final = [], set()
        for url in EXTRA.get(name, []) + discover(home):
            res = test(url)
            if res and res["url"] not in seen_final:
                seen_final.add(res["url"]); good.append(res)
            if len(good) >= 4:
                break
        lines.append(f"## {name}")
        if not good:
            lines += ["- ❌ No working feed found (site may block bots or not offer RSS)", ""]
            continue
        for g in good:
            fresh = ("never dated" if g["age_days"] is None else
                     "✅ fresh" if g["age_days"] <= 3 else
                     f"⚠️ newest item {g['age_days']} days old")
            lines.append(f"- {g['url']}  \n  {g['title'] or '(untitled)'} · {g['items']} items · {fresh}")
        best = min(good, key=lambda g: g["age_days"] if g["age_days"] is not None else 9999)
        if best["age_days"] is not None and best["age_days"] <= 14:
            paste.append(f'    ("{name}", {tier}, "{best["url"]}"),')
        lines.append("")
    lines += ["## Ready to paste into FEEDS in collect_feeds.py",
              "(best working feed per site that has posted in the last two weeks)", "", "```python", *paste, "```"]
    open("feed_report.md", "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines[-len(paste) - 3:]))


if __name__ == "__main__":
    main()
