#!/usr/bin/env python3
"""
The Local Briefing — v3 (beehiiv paste-in workflow)

Every morning this script:
  1. Pulls stories from local RSS feeds (Starnes Media, Google News, Birmingham metro)
  2. Grabs the weather for Hoover
  3. Has Claude write the day's edition
  4. Emails a "paste-in kit" to the editor only: subject, preview text, editor
     notes, feed health, and the edition body ready to copy into beehiiv
  5. Saves the edition to archive/YYYY-MM-DD.html

Run locally without sending:  python newsletter.py --preview
"""

import base64
import time
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# Override with the ANTHROPIC_MODEL secret when a newer model ships — no code change needed.
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5-5"

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EDITOR_EMAIL = os.getenv("EMAIL_TO", "").split(",")[0].strip()   # draft goes to you only
EMAIL_FROM = os.getenv("EMAIL_FROM") or "The Local Briefing <onboarding@resend.dev>"
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

LOCAL_TZ = ZoneInfo("America/Chicago")
WEATHER_LAT, WEATHER_LON = 33.4054, -86.8114   # Hoover
LOOKBACK_HOURS = 28
MAX_STORIES = 45
ARCHIVE_DIR = Path("archive")
PREVIEW_MODE = "--preview" in sys.argv

# ---------------------------------------------------------------------------
# RSS SOURCES
# ---------------------------------------------------------------------------

GN = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="

RSS_FEEDS = {
    # Tier 1 — hyperlocal (Starnes Media, Metro Publisher CMS)
    "Hoover Sun": "https://hooversun.com/api/rss/content.rss",
    "280 Living": "https://280living.com/api/rss/content.rss",
    "Village Living": "https://www.villagelivingonline.com/api/rss/content.rss",
    "Vestavia Voice": "https://vestaviavoice.com/api/rss/content.rss",
    "The Homewood Star": "https://thehomewoodstar.com/api/rss/content.rss",

    # Tier 2 — Google News location searches (catch al.com, Shelby County Reporter, BBJ, etc.)
    "GNews Hoover": GN + "%22Hoover%22+Alabama+when:1d",
    "GNews Shelby County": GN + "%22Shelby+County%22+Alabama+-Tennessee+-Memphis+when:1d",
    "GNews Pelham Alabaster Helena": GN + "(Pelham+OR+Alabaster+OR+Helena)+Alabama+when:1d",
    "GNews Oak Mountain 280": GN + "(%22Oak+Mountain%22+OR+%22Chelsea+Alabama%22+OR+%22Highway+280%22+Birmingham)+when:1d",
    "GNews Vestavia Mtn Brook": GN + "(%22Vestavia+Hills%22+OR+%22Mountain+Brook%22)+Alabama+when:1d",

    # Tier 3 — Birmingham metro (only if there's a clear local angle)
    "WVTM 13": "https://www.wvtm13.com/topstories-rss",
    "CBS 42": "https://cbs42.com/feed",
    "Bham Now": "https://bhamnow.com/feed",
    "Birmingham Watch": "https://birminghamwatch.org/feed",
    "Birmingham Times": "https://birminghamtimes.com/feed",
    "BirminghamMommy": "https://birminghammommy.com/feed",
}

TIER_1 = {"Hoover Sun", "280 Living", "Village Living", "Vestavia Voice", "The Homewood Star"}
TN_KEYWORDS = ["tennessee", "memphis", "germantown", "bartlett", "collierville",
               "shelby county tn", "shelby county, tn"]

# ---------------------------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the AI behind The Local Briefing — a daily email that scours every local news source in the Birmingham suburbs so busy parents don't have to. Steven, a dad of two young kids in the Hoover/280 corridor, built you to keep his community in the loop.

You write the daily draft. Steven reviews it each morning, tweaks anything he wants, and pastes it into beehiiv to send. Your job is to give him a draft so good he barely has to touch it.

## YOUR IDENTITY & VOICE

You're an AI and that's fine — but this email should NOT read like AI wrote it. It should feel like one real person talking to another. One-to-one energy. Read out loud, it should sound like something a neighbor would actually say. Honest, not polished. Clear and direct, never "corporate content."

Voice rules:
- First person. One person talking to a friend over coffee.
- Contractions always. Slang never.
- ONE TO TWO SENTENCES PER PARAGRAPH. MAX. This is the most important formatting rule. Every paragraph break creates momentum. A single sentence standing alone is great — do it often. If you write 3+ sentences in one paragraph, split it.
- The writing should pull the reader along effortlessly. Zero friction. If someone has to re-read a sentence, you've failed.
- Never editorialize on politics — report what happened and let people draw their own conclusions.
- NEVER use: "in other news," "without further ado," "let's dive in," "here's the scoop," "stay tuned," or any newsletter cliché. If a morning show host or a content marketer would say it, cut it.

## EDITORIAL PHILOSOPHY

This newsletter lives or dies by whether people look forward to it.

LEAD WITH INSIGHT, NOT RECAP: "The council approved a rezoning" is a recap. "That rezoning means the empty lot you drive past every morning is about to become 200 apartments" is insight. Give people observations they haven't named yet.

BE ZERO-CLICK: Readers should get the full value from the email alone. Links are for people who want more, never a requirement to get the point.

CREATE HIGH VALUE: Every item should feel intentional. If a story wouldn't make someone think "oh, interesting" or "I should tell my spouse about this," cut it. Worth forwarding. Noticed if it stopped showing up.

BE CONSISTENT: Same voice, same structure, every day. Trust builds through consistency, not viral one-offs.

## GEOGRAPHIC PRIORITY

PRIMARY audience:
- Hoover (Meadow Brook, Ross Bridge, Greystone, Lake Cyrus, Bluff Park, Stadium Trace, Riverchase)
- The 280 corridor (Oak Mountain, Mt Laurel, Shoal Creek, Brook Highland, Inverness)
- Shelby County cities: Pelham, Helena, Alabaster, Chelsea, Calera

SECONDARY audience:
- Vestavia Hills (Cahaba Heights, Liberty Park), Mountain Brook (Crestline, English Village), Homewood

Filtering rules:
- Primary-area stories: always include if newsworthy
- Secondary-area stories: the best 1-2 per day
- Big Birmingham metro news: only if genuinely major. One per edition at most.
- State/national news: almost never — only with a hyper-specific local impact
- Crime in distant Birmingham neighborhoods: skip
- Generic business press releases: skip

DEDUPLICATION: The same story often appears in several sources. Use the best version, link the original source, never repeat a story.

ALABAMA ONLY: "Shelby County" also exists in Tennessee. Every Shelby County story must be about Shelby County, ALABAMA. If a story mentions Memphis, Germantown, Bartlett, or anything Tennessee, reject it. When in doubt, skip it.

## WHAT TO PRIORITIZE

Readers are busy parents and homeowners. They want to feel connected, not anxious. Every story needs a "why you should care" angle — if you can't say why a Hoover parent would care, skip it.

In rough order:
1. Development & business — new restaurants and shops, construction, closings of places people love. "What's going into that empty space?" is the #1 question neighbors ask.
2. Local government — zoning, council votes, taxes, anything affecting property values or daily life
3. Schools — schedule changes, board decisions, programs, achievements
4. Community — events, family activities, weekend plans, volunteering, human interest
5. Useful parent info — camp signups, rec registrations, library events, seasonal stuff
6. Economy & jobs — local employers, housing market, cost of living
7. Weather — only if it meaningfully affects plans

SKIP OR MINIMIZE:
- SPORTS: Most editions should have ZERO sports. Only a state championship, a record, a notable college signing, or a major coaching change makes the cut — and only as a one-line quick hit, never the lead. Skip routine scores, recaps, playoff updates, and "great season" stories. University sports: always skip.
- Crime and accidents: skip routine crime and crashes. Include only a major incident everyone will be talking about, or directly actionable safety info.

## OUTPUT FORMAT — FOLLOW EXACTLY

Your response must start with this header block, then the body:

SUBJECT: [under 50 characters, conversational, about the lead story]
PREVIEW: [one sentence, under 90 characters, that makes someone open the email — complements the subject, doesn't repeat it]
EDITOR NOTES:
- [Anything Steven should double-check before sending: a date you inferred, a detail the source was vague on, a story you almost cut. Max 3 items. Write "- None" if nothing.]
---BODY---
[the edition HTML]

Subject line examples — good: "A new coffee shop is headed to Lee Branch", "That empty lot on 280? Here's what's coming". Bad: "Your Local Briefing — Tuesday" (boring), "BREAKING: Major news in Hoover" (clickbait).

## BODY HTML RULES

The body gets pasted into beehiiv, which applies its own fonts, colors, and footer. So write CLEAN, PLAIN HTML:
- Allowed tags only: <p>, <strong>, <em>, <a href="...">, <hr>
- NO inline styles, NO classes, NO divs, NO tables, NO headings, NO lists, NO emoji-heavy decoration
- No email footer, no unsubscribe text — beehiiv adds those

Structure:

1. STEVEN'S NOTE — 2-3 sentences he'd plausibly say. Dad-at-the-bus-stop energy, not LinkedIn energy. A seasonal observation, the weather, the weekend ahead.
<p><strong>From Steven</strong></p>
<p>First sentence or two.</p>
<p>Another short beat.</p>

2. TRANSITION — one short line, like "Here's what caught my eye this morning:"

3. THE LEAD — the biggest local story, in 3-4 short paragraphs:
<p><strong>Headline in a few words.</strong> What happened, in one sentence.</p>
<p>Why it matters — the insight the reader hasn't thought of yet. Be specific: commutes, property values, school zones, weekend plans, wallets.</p>
<p>What's next or what to watch for. <a href="URL">Full story here.</a></p>

4. <hr>

5. THE MIDDLE — 3-5 stories, each 2-3 short paragraphs:
<p><strong>New coffee shop coming to Lee Branch.</strong> A locally owned cafe is taking over the old Zoës space in The Village at Lee Branch.</p>
<p>They're hoping to open by late March. <a href="URL">280 Living has the details.</a></p>

6. QUICK HITS (optional) — "A few more quick ones:" then one paragraph per item:
<p>→ <strong>Topic:</strong> One sentence. <a href="URL">Link.</a></p>

7. BEFORE YOU HEAD OUT (only if actionable):
<p><strong>Before you head out</strong></p>
<p><strong>Weather:</strong> forecast<br><strong>Schools:</strong> anything relevant<br><strong>Roads:</strong> anything relevant</p>

8. SIGN-OFF — one casual line ("Enjoy the weekend."), then:
<p>— Steven</p>

## THIN NEWS DAYS

Steven's note + a lead + 2 quick hits + weather is plenty. Never pad. A short edition should feel like "not much happened today, which is nice" — not like you ran out of things to say.

## SENSITIVE TOPICS

- Crime: facts only, no sensationalizing
- Schools: extra care with anything involving minors; official sources only
- Politics: what happened and what it means locally, no slant
- Tragedies: brief, respectful, factual
"""

# ---------------------------------------------------------------------------
# STEP 1: FETCH STORIES
# ---------------------------------------------------------------------------

def tier_for(source_name):
    if source_name in TIER_1:
        return "Tier 1 — HYPERLOCAL"
    if source_name.startswith("GNews"):
        return "Tier 2 — HYPERLOCAL"
    return "Tier 3 — METRO (needs local angle)"


def entry_date(entry):
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    if getattr(entry, "published", None):
        try:
            return parsedate_to_datetime(entry.published)
        except Exception:
            pass
    return None


def fetch_all_stories():
    """Returns (stories, feed_health). feed_health lists feeds that look broken."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    stories, broken, seen_titles = [], [], set()

    for source_name, url in RSS_FEEDS.items():
        try:
            resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 LocalBriefingBot/3.0"})
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception as e:
            broken.append(f"{source_name}: couldn't load ({type(e).__name__})")
            print(f"  ❌ {source_name}: {e}")
            continue

        if not feed.entries:
            broken.append(f"{source_name}: feed returned no items")
            print(f"  ⚠️  {source_name}: no items")
            continue

        count = 0
        max_items = 5 if source_name.startswith("GNews") else 20
        for entry in feed.entries[:max_items]:
            pub = entry_date(entry)
            if pub and pub < cutoff:
                continue

            title = entry.get("title", "").strip()
            via = None
            if source_name.startswith("GNews"):
                m = re.match(r"^(.+)\s+-\s+([^-]+)$", title)
                if m:
                    title, via = m.group(1).strip(), m.group(2).strip()

            summary = re.sub(r"<[^>]+>", "", entry.get("summary", "") or entry.get("description", ""))
            summary = re.sub(r"\s+", " ", summary).strip()[:500]

            if any(k in (title + " " + summary).lower() for k in TN_KEYWORDS):
                continue

            key = re.sub(r"[^a-z0-9]", "", title.lower())[:80]
            if not key or key in seen_titles:
                continue
            seen_titles.add(key)

            stories.append({
                "source": f"{source_name} (via {via})" if via else source_name,
                "tier": tier_for(source_name),
                "title": title,
                "summary": summary,
                "link": entry.get("link", ""),
                "date": pub.astimezone(LOCAL_TZ).strftime("%a %b %d, %I:%M %p") if pub else "Unknown",
            })
            count += 1

        print(f"  ✅ {source_name}: {count} recent")

    return stories, broken


# ---------------------------------------------------------------------------
# STEP 2: WEATHER
# ---------------------------------------------------------------------------

def get_weather():
    if not OPENWEATHER_API_KEY:
        return "Weather data unavailable."
    try:
        resp = requests.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={"lat": WEATHER_LAT, "lon": WEATHER_LON, "appid": OPENWEATHER_API_KEY,
                    "units": "imperial", "cnt": 8},
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json()["list"]
        temps = [i["main"]["temp"] for i in items]
        conditions = items[0]["weather"][0]["description"].capitalize()
        wet = any(i["weather"][0]["main"] in ("Rain", "Thunderstorm", "Snow", "Drizzle") for i in items)
        return (f"{conditions}, high {round(max(temps))}°F / low {round(min(temps))}°F."
                + (" Rain likely at some point in the next 24 hours." if wet else ""))
    except Exception as e:
        print(f"  ⚠️  Weather failed: {e}")
        return "Weather data temporarily unavailable."


# ---------------------------------------------------------------------------
# STEP 3: CLAUDE
# ---------------------------------------------------------------------------

def select_stories(stories):
    """All Tier 1 and 2, then fill with Tier 3 up to MAX_STORIES."""
    local = [s for s in stories if not s["tier"].startswith("Tier 3")]
    metro = [s for s in stories if s["tier"].startswith("Tier 3")]
    return (local + metro)[:max(MAX_STORIES, len(local))]


def generate_edition(stories, weather, now):
    if not ANTHROPIC_API_KEY:
        sys.exit("❌ ANTHROPIC_API_KEY not set")

    selected = select_stories(stories)
    stories_text = "\n---\n".join(
        f"SOURCE: {s['source']} [{s['tier']}]\nHEADLINE: {s['title']}\n"
        f"SUMMARY: {s['summary']}\nLINK: {s['link']}\nPUBLISHED: {s['date']}"
        for s in selected
    )
    user_message = (
        f"Today is {now:%A, %B %d, %Y} (Central time).\n\n"
        f"WEATHER FOR HOOVER (next 24 hours): {weather}\n\n"
        f"Here are {len(selected)} raw stories from Birmingham-area sources, labeled by tier. "
        f"Write today's edition following your system prompt exactly, starting with the SUBJECT line.\n\n"
        f"{stories_text}"
    )

    print(f"   Sending {len(selected)} of {len(stories)} stories to {ANTHROPIC_MODEL}...")
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 6000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}],
    }
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}

    resp = None
    for attempt in range(3):
        try:
            resp = requests.post("https://api.anthropic.com/v1/messages",
                                 headers=headers, json=payload, timeout=300)
            if resp.status_code in (429, 500, 502, 503, 529) and attempt < 2:
                print(f"   ⚠️  API returned {resp.status_code}, retrying...")
                time.sleep(15 * (attempt + 1))
                continue
            break
        except requests.exceptions.RequestException as e:
            if attempt == 2:
                sys.exit(f"❌ Claude API failed: {e}")
            print(f"   ⚠️  {e} — retrying...")
            time.sleep(15 * (attempt + 1))

    if resp is None or resp.status_code != 200:
        sys.exit(f"❌ Claude API error {resp.status_code if resp else '?'}: {resp.text if resp else ''}")

    data = resp.json()
    raw = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
    usage = data.get("usage", {})
    print(f"   ✅ Written ({usage.get('input_tokens')} in / {usage.get('output_tokens')} out tokens)")
    return parse_output(raw)


def parse_output(raw):
    """Split Claude's response into subject, preview, editor notes, and body HTML."""
    if "---BODY---" in raw:
        header, body = raw.split("---BODY---", 1)
    else:
        first_tag = raw.find("<")
        header, body = (raw[:first_tag], raw[first_tag:]) if first_tag > 0 else ("", raw)

    def field(name):
        m = re.search(rf"^\s*{name}:\s*(.+)$", header, re.M)
        return m.group(1).strip() if m else ""

    notes = []
    m = re.search(r"EDITOR NOTES:\s*(.*)", header, re.S)
    if m:
        for line in m.group(1).splitlines():
            line = line.strip().lstrip("-•* ").strip()
            if line and line.lower() not in ("none", "none."):
                notes.append(line)

    body = re.sub(r"^```(?:html)?\s*|\s*```$", "", body.strip())
    return {
        "subject": field("SUBJECT") or "The Local Briefing",
        "preview": field("PREVIEW"),
        "notes": notes,
        "body": body.strip(),
    }


# ---------------------------------------------------------------------------
# STEP 4: PASTE-IN KIT EMAIL + ARCHIVE
# ---------------------------------------------------------------------------

def esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_kit_email(edition, broken_feeds, story_count, now):
    font = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
    label = f"font-size:11px; font-weight:600; letter-spacing:0.6px; text-transform:uppercase; color:#888; margin:14px 0 4px 0;"
    notes = "".join(f"<li style='margin:0 0 4px 0;'>{esc(n)}</li>" for n in edition["notes"]) or "<li>Nothing flagged.</li>"
    health = ("".join(f"<li style='margin:0 0 4px 0;'>{esc(b)}</li>" for b in broken_feeds)
              if broken_feeds else "<li>All feeds loaded.</li>")
    cut = (f"<p style='margin:28px 0; text-align:center; font-size:12px; color:#bbb; "
           f"letter-spacing:1px; font-family:{font};'>{{}}</p>")

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:24px 16px; background:#ffffff; font-family:{font};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;">

<tr><td style="background:#f6f6f3; border-radius:8px; padding:18px 22px; font-size:14px; line-height:1.5; color:#333;">
<p style="margin:0; font-weight:700; font-size:15px;">Today's draft is ready · {now:%A, %B %d}</p>
<p style="{label}">Subject line</p>
<p style="margin:0; font-size:16px; font-weight:600;">{esc(edition['subject'])}</p>
<p style="{label}">Preview text</p>
<p style="margin:0;">{esc(edition['preview']) or '<em>none</em>'}</p>
<p style="{label}">Double-check before sending</p>
<ul style="margin:0; padding-left:18px;">{notes}</ul>
<p style="{label}">Feed health · {story_count} stories pulled</p>
<ul style="margin:0; padding-left:18px; color:#666;">{health}</ul>
</td></tr>

<tr><td>{cut.format("✂ &nbsp;COPY FROM HERE INTO BEEHIIV&nbsp; ✂")}</td></tr>

<tr><td style="font-size:16px; line-height:1.7; color:#222;">
{edition['body']}
</td></tr>

<tr><td>{cut.format("✂ &nbsp;END OF EDITION&nbsp; ✂")}</td></tr>

</table></td></tr></table></body></html>"""


def archive_edition(edition, now):
    ARCHIVE_DIR.mkdir(exist_ok=True)
    path = ARCHIVE_DIR / f"{now:%Y-%m-%d}.html"
    path.write_text(
        f"<!-- SUBJECT: {edition['subject']} -->\n<!-- PREVIEW: {edition['preview']} -->\n\n"
        f"{edition['body']}\n",
        encoding="utf-8",
    )
    print(f"   💾 Archived to {path}")
    return path


def send_kit(kit_html, edition, archive_path):
    if PREVIEW_MODE or not RESEND_API_KEY or not EDITOR_EMAIL:
        Path("draft_preview.html").write_text(kit_html, encoding="utf-8")
        reason = "preview mode" if PREVIEW_MODE else "RESEND_API_KEY or EMAIL_TO missing"
        print(f"   💾 Not sending ({reason}) — open draft_preview.html")
        return

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
        json={
            "from": EMAIL_FROM,
            "to": [EDITOR_EMAIL],
            "subject": f"[Draft] {edition['subject']}",
            "html": kit_html,
            "attachments": [{
                "filename": archive_path.name,
                "content": base64.b64encode(archive_path.read_bytes()).decode(),
            }],
        },
        timeout=30,
    )
    if resp.status_code in (200, 201):
        print(f"   📧 Draft sent to {EDITOR_EMAIL}")
    else:
        Path("draft_preview.html").write_text(kit_html, encoding="utf-8")
        sys.exit(f"❌ Resend error {resp.status_code}: {resp.text}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    now = datetime.now(LOCAL_TZ)
    print(f"📰 The Local Briefing v3 — {now:%A, %B %d, %Y %I:%M %p} CT\n")

    print("📡 Fetching feeds...")
    stories, broken = fetch_all_stories()
    print(f"   {len(stories)} unique recent stories, {len(broken)} feed problem(s)")
    if not stories:
        sys.exit("❌ No stories found — every feed came back empty or broken.")

    print("\n🌤  Weather...")
    weather = get_weather()
    print(f"   {weather}")

    print("\n✍️  Writing edition...")
    edition = generate_edition(stories, weather, now)
    print(f"   Subject: {edition['subject']}")

    print("\n📧 Building paste-in kit...")
    archive_path = archive_edition(edition, now)
    send_kit(build_kit_email(edition, broken, len(stories), now), edition, archive_path)
    print("\n✅ Done.")


if __name__ == "__main__":
    main()
