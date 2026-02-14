#!/usr/bin/env python3
"""
Local Birmingham Newsletter Generator v2
Pulls RSS feeds, gets weather, sends to Claude for drafting, emails the result.

Sources: 13 feeds across Starnes Media hyperlocals, Patch, and Birmingham metro news.
"""

import feedparser
import requests
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# Load .env file if present (for local development)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not required in production

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_TO = os.getenv("EMAIL_TO", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "newsletter@yourdomain.com")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

WEATHER_LAT = 33.4054
WEATHER_LON = -86.8114
LOOKBACK_HOURS = 28

# ---------------------------------------------------------------------------
# RSS SOURCES — ordered by priority (hyperlocal first)
# ---------------------------------------------------------------------------

RSS_FEEDS = {
    # Tier 1: HYPERLOCAL — Starnes Media Network (all Metro Publisher CMS)
    "Hoover Sun": "https://hooversun.com/api/rss/content.rss",
    "Village Living": "https://www.villagelivingonline.com/api/rss/content.rss",
    "Vestavia Voice": "https://vestaviavoice.com/api/rss/content.rss",
    "280 Living": "https://280living.com/api/rss/content.rss",
    "The Homewood Star": "https://thehomewoodstar.com/api/rss/content.rss",

    # Tier 2: HYPERLOCAL — Patch (community-specific feeds)
    "Patch Hoover": "https://patch.com/alabama/hoover/rss",
    "Patch Vestavia": "https://patch.com/alabama/vestavia-hills/rss",

    # Tier 2.5: GOOGLE NEWS — location-filtered feeds that catch al.com, BBJ,
    # Shelby County Reporter, and any other source mentioning our communities.
    # These act as a safety net for stories the direct feeds miss.
    "GNews Hoover": "https://news.google.com/rss/search?q=%22Hoover%22+Alabama+when:1d&hl=en-US&gl=US&ceid=US:en",
    "GNews Mountain Brook": "https://news.google.com/rss/search?q=%22Mountain+Brook%22+Alabama+when:1d&hl=en-US&gl=US&ceid=US:en",
    "GNews Vestavia Hills": "https://news.google.com/rss/search?q=%22Vestavia+Hills%22+Alabama+when:1d&hl=en-US&gl=US&ceid=US:en",
    "GNews Shelby County AL": "https://news.google.com/rss/search?q=%22Shelby+County%22+Alabama+when:1d&hl=en-US&gl=US&ceid=US:en",

    # Tier 3: METRO — Birmingham-wide (use only if locally relevant)
    "al.com": "https://www.al.com/arc/outboundfeeds/rss/?outputType=xml",
    "WVTM 13": "https://www.wvtm13.com/topstories-rss",
    "Birmingham Watch": "https://birminghamwatch.org/feed",
    "Bham Now": "https://bhamnow.com/feed",
    "CBS 42": "https://cbs42.com/feed",
    "Birmingham Times": "https://birminghamtimes.com/feed",
    "BirminghamMommy": "https://birminghammommy.com/feed",
}

# Which sources are hyperlocal vs metro (used in the prompt)
TIER_1_SOURCES = ["Hoover Sun", "Village Living", "Vestavia Voice", "280 Living", "The Homewood Star"]
TIER_2_SOURCES = ["Patch Hoover", "Patch Vestavia",
                  "GNews Hoover", "GNews Mountain Brook", "GNews Vestavia Hills", "GNews Shelby County AL"]
TIER_3_SOURCES = ["al.com", "WVTM 13", "Birmingham Watch", "Bham Now", "CBS 42",
                  "Birmingham Times", "BirminghamMommy"]

# ---------------------------------------------------------------------------
# EMAIL HTML TEMPLATE
# ---------------------------------------------------------------------------

EMAIL_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#f4f1ec; font-family:Georgia, 'Times New Roman', serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f1ec;">
<tr><td align="center" style="padding:20px 10px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:8px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.08);">

<!-- HEADER -->
<tr><td style="background-color:#1a3a2a; padding:28px 32px; text-align:center;">
<h1 style="margin:0; color:#ffffff; font-size:26px; font-weight:700; letter-spacing:0.5px; font-family:Georgia, serif;">THE LOCAL BRIEFING</h1>
<p style="margin:6px 0 0 0; color:#c5d4c0; font-size:13px; font-family:-apple-system, Arial, sans-serif; letter-spacing:1px; text-transform:uppercase;">{date}</p>
</td></tr>

<!-- CONTENT -->
<tr><td style="padding:28px 32px; color:#2d2d2d; font-size:16px; line-height:1.65;">
{content}
</td></tr>

<!-- FOOTER -->
<tr><td style="background-color:#f9f7f4; padding:24px 32px; border-top:1px solid #e8e4de;">
<p style="margin:0 0 12px 0; color:#5a5a5a; font-size:14px; line-height:1.6; font-family:-apple-system, Arial, sans-serif;">Thanks for reading. This newsletter is AI-built and dad-refined — because between diaper changes and school drop-offs, this is how we keep up.</p>
<p style="margin:0; color:#5a5a5a; font-size:14px; font-family:-apple-system, Arial, sans-serif;">Got a tip or feedback? Just reply to this email.</p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

# ---------------------------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the AI writer behind THE LOCAL BRIEFING, a hyper-local daily email newsletter covering Hoover, Mountain Brook, Vestavia Hills, and Shelby County, Alabama. You work alongside a real dad (the editor) who reviews and refines your drafts before they go out.

## YOUR VOICE

Write like a sharp, friendly neighbor who reads every local news source so busy parents don't have to. Conversational but never sloppy. Every sentence earns its place.

Voice rules:
- First person singular ("I" not "we")
- Contractions: yes. Slang: no.
- Warm but efficient — "smart friend at school pickup" not "local news anchor"
- Explain why something matters to a parent/homeowner/resident, not just what happened
- Show personality occasionally (dry observation, relatable aside) but never at the expense of clarity
- Never editorialize on politics — report what happened and why it matters locally
- Never use newsletter clichés ("in other news..."), filler phrases, or corporate jargon

## SMART BREVITY

1. Lead with the news. First sentence = what happened. No throat-clearing.
2. "Why it matters" is mandatory — tie every story to daily life in these communities.
3. One idea per sentence. Short paragraphs.
4. If a story can be told in 2 sentences, don't use 3.
5. Strong, specific verbs. "The council approved" not "The council voted to move forward with the approval of."

## GEOGRAPHIC FILTER — THIS IS CRITICAL

ONLY include stories that DIRECTLY affect residents of:
- Hoover (Ross Bridge, Greystone, Lake Cyrus, Bluff Park, Stadium Trace, Riverchase)
- Mountain Brook (Crestline, English Village, Mountain Brook Village, Cherokee Bend)
- Vestavia Hills (Cahaba Heights, Liberty Park)
- Shelby County cities: Helena, Pelham, Alabaster, Chelsea, Calera, Oak Mountain area
- Homewood (adjacent community, include when directly relevant)

REJECT stories that are:
- General Birmingham metro news with no specific local impact
- State/national news unless there's a direct local angle
- Crime in distant Birmingham neighborhoods
- University of Alabama or Auburn sports (unless a local athlete is featured)
- Generic business press releases with no local connection

SOURCE PRIORITY: Stories from Tier 1 sources (Hoover Sun, Village Living, Vestavia Voice, 280 Living, Homewood Star) and Tier 2 (Patch Hoover, Patch Vestavia, Google News location feeds) are almost always relevant. Stories from Tier 3 metro sources (al.com, WVTM, CBS 42, Birmingham Watch, etc.) need a CLEAR local connection to make the cut.

DEDUPLICATION: You will often see the same story from multiple sources (e.g., from both the Hoover Sun direct feed and a Google News result linking to the Hoover Sun). Use the best/most detailed version and link to the original source. Do not repeat the same story twice in the newsletter.

## TOPIC PRIORITIES

1. Schools — closings, calendar changes, board decisions, safety, sports highlights
2. Safety — crime, traffic incidents, road closures, weather alerts
3. Local government — zoning, council actions, tax/budget changes
4. Development — new businesses, construction, closings of beloved spots
5. Community — events, volunteer opportunities, family-friendly activities
6. Business — local business news, major employer updates
7. Weather — only if actionable

## NEWSLETTER STRUCTURE

Output the newsletter body content as HTML using ONLY the formatting specified below. Do NOT include <html>, <head>, <body>, or <style> tags — just the inner content that goes inside the email template.

### TOP CALLOUT (conditional)
Only if there's genuinely actionable weather, school, or traffic news. Skip on normal days.
Format: <p style="background-color:#fef3cd; border-left:4px solid #d4a843; padding:12px 16px; margin:0 0 24px 0; font-size:14px; color:#664d03; font-family:-apple-system, Arial, sans-serif; border-radius:0 4px 4px 0;">⚡ Your callout text here</p>

### THE BIG ONE
The day's most important local story.
Format:
<p style="color:#888; font-size:12px; text-transform:uppercase; letter-spacing:1.5px; margin:0 0 8px 0; font-family:-apple-system, Arial, sans-serif; font-weight:600;">THE BIG ONE</p>
<h2 style="margin:0 0 12px 0; font-size:22px; color:#1a3a2a; line-height:1.3;">Conversational Headline Here</h2>
Then 3-4 sentences as <p> tags with style="margin:0 0 12px 0;". Include source link as <a href="URL" style="color:#2a6b4a; text-decoration:underline;">Source Name →</a>

### SECTION DIVIDER
Between major sections use: <hr style="border:none; border-top:1px solid #e8e4de; margin:28px 0;">

### WHAT'S HAPPENING
3-5 additional stories.
Section label: <p style="color:#888; font-size:12px; text-transform:uppercase; letter-spacing:1.5px; margin:0 0 16px 0; font-family:-apple-system, Arial, sans-serif; font-weight:600;">WHAT'S HAPPENING</p>
Each story:
<p style="margin:0 0 4px 0;"><b style="color:#1a3a2a; font-size:17px;">Conversational Headline</b></p>
<p style="margin:0 0 16px 0;">Story text with <a href="URL" style="color:#2a6b4a; text-decoration:underline;">Source →</a></p>

### QUICK HITS
3-4 smaller items.
Section label same format as above.
Each item: <p style="margin:0 0 10px 0; padding-left:16px; border-left:3px solid #e8e4de;"><b style="color:#1a3a2a;">Topic:</b> One-liner with <a href="URL" style="color:#2a6b4a; text-decoration:underline;">More →</a></p>

### AROUND TOWN (optional)
2-3 upcoming events on slow days.
Section label same format. Each event as a <p> with the date bolded.

### PARENT RADAR (always last)
Section label: <p style="color:#888; font-size:12px; text-transform:uppercase; letter-spacing:1.5px; margin:0 0 12px 0; font-family:-apple-system, Arial, sans-serif; font-weight:600;">PARENT RADAR</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9f7f4; border-radius:6px; padding:4px;">
One row per item (Weather, Schools, Traffic) that has something to report:
<tr><td style="padding:10px 16px; font-size:14px; font-family:-apple-system, Arial, sans-serif;">
<b style="color:#1a3a2a;">🌤 Weather:</b> One-line forecast
</td></tr>
</table>

Do NOT include the footer — that's already in the email template.

## THIN NEWS DAYS

Quality over quantity. Minimum viable edition: THE BIG ONE + 2-3 Quick Hits + Parent Radar.
Never pad with state/national stories. On slow days, spotlight a local event or share a "did you know" local fact.

## HANDLING SENSITIVE TOPICS

- Crime: Facts only, no sensationalizing
- Schools: Extra care with minors. Official sources only.
- Local politics: What happened + what it means. No editorial slant.
- Tragedies: Brief, respectful, factual. Include resources if relevant.
"""

# ---------------------------------------------------------------------------
# STEP 1: FETCH RSS STORIES
# ---------------------------------------------------------------------------

def fetch_all_stories():
    """Pull stories from all RSS feeds, filtered to last LOOKBACK_HOURS."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    all_stories = []

    for source_name, feed_url in RSS_FEEDS.items():
        # Determine source tier
        if source_name in TIER_1_SOURCES:
            tier = "Tier 1 — HYPERLOCAL"
        elif source_name in TIER_2_SOURCES:
            tier = "Tier 2 — HYPERLOCAL"
        else:
            tier = "Tier 3 — METRO (needs local angle)"

        try:
            print(f"  Fetching {source_name}...")

            try:
                resp = requests.get(feed_url, timeout=15, headers={
                    "User-Agent": "LocalNewsletterBot/1.0"
                })
                resp.raise_for_status()
                feed = feedparser.parse(resp.content)
            except requests.RequestException:
                feed = feedparser.parse(feed_url)

            if feed.bozo and not feed.entries:
                print(f"  ⚠️  {source_name}: Feed error — skipping")
                continue

            count = 0
            for entry in feed.entries[:20]:
                pub_date = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    pub_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'published') and entry.published:
                    try:
                        pub_date = parsedate_to_datetime(entry.published)
                    except Exception:
                        pub_date = None

                if pub_date and pub_date < cutoff:
                    continue

                summary = ""
                if hasattr(entry, 'summary'):
                    summary = entry.summary
                elif hasattr(entry, 'description'):
                    summary = entry.description

                summary = re.sub(r'<[^>]+>', '', summary)
                summary = summary.strip()[:500]

                # Google News appends " - Source Name" to titles — extract it
                original_source = None
                title = entry.get("title", "No title")
                if source_name.startswith("GNews"):
                    title_match = re.match(r'^(.+)\s+-\s+(.+)$', title)
                    if title_match:
                        title = title_match.group(1).strip()
                        original_source = title_match.group(2).strip()

                # Google News uses redirect URLs — try to get the real URL
                link = entry.get("link", "")
                if "news.google.com" in link:
                    # The real URL is sometimes in the entry's source or links
                    if hasattr(entry, 'links'):
                        for l in entry.links:
                            if l.get('href') and 'news.google.com' not in l.get('href', ''):
                                link = l['href']
                                break

                story = {
                    "source": f"{source_name} (via {original_source})" if original_source else source_name,
                    "tier": tier,
                    "title": title,
                    "summary": summary,
                    "link": entry.get("link", ""),
                    "date": pub_date.strftime("%Y-%m-%d %H:%M") if pub_date else "Unknown",
                }
                all_stories.append(story)
                count += 1

            print(f"  ✅ {source_name}: {count} recent stories")

        except Exception as e:
            print(f"  ❌ {source_name}: Error — {e}")
            continue

    return all_stories


# ---------------------------------------------------------------------------
# STEP 2: GET WEATHER
# ---------------------------------------------------------------------------

def get_weather():
    """Fetch today's weather forecast for Hoover, AL."""
    if not OPENWEATHER_API_KEY:
        return "Weather data unavailable (no API key configured)."

    try:
        url = "https://api.openweathermap.org/data/2.5/forecast"
        params = {
            "lat": WEATHER_LAT,
            "lon": WEATHER_LON,
            "appid": OPENWEATHER_API_KEY,
            "units": "imperial",
            "cnt": 8,
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        temps = [item["main"]["temp"] for item in data["list"]]
        high = round(max(temps))
        low = round(min(temps))
        conditions = data["list"][0]["weather"][0]["description"].capitalize()

        precip = any(
            item["weather"][0]["main"] in ["Rain", "Thunderstorm", "Snow", "Drizzle"]
            for item in data["list"]
        )
        precip_note = " Rain expected — plan accordingly." if precip else ""

        return f"Weather: {conditions}, high {high}°F / low {low}°F.{precip_note}"

    except Exception as e:
        print(f"  ⚠️  Weather fetch failed: {e}")
        return "Weather data temporarily unavailable."


# ---------------------------------------------------------------------------
# STEP 3: BUILD PROMPT AND CALL CLAUDE
# ---------------------------------------------------------------------------

def format_stories_for_prompt(stories):
    """Format stories with tier labels so Claude knows which to prioritize."""
    if not stories:
        return "No stories were found in the feeds today."

    lines = []
    for s in stories:
        lines.append(
            f"SOURCE: {s['source']} [{s['tier']}]\n"
            f"HEADLINE: {s['title']}\n"
            f"SUMMARY: {s['summary']}\n"
            f"LINK: {s['link']}\n"
            f"DATE: {s['date']}"
        )
    return "\n---\n".join(lines)


def generate_newsletter(stories, weather):
    """Send stories to Claude API and get back newsletter HTML content."""
    if not ANTHROPIC_API_KEY:
        print("❌ ANTHROPIC_API_KEY not set!")
        sys.exit(1)

    today = datetime.now().strftime("%A, %B %d, %Y")
    stories_text = format_stories_for_prompt(stories)

    user_message = (
        f"Today's date is {today}.\n\n"
        f"WEATHER DATA:\n{weather}\n\n"
        f"Here are today's raw news stories from Birmingham-area sources. "
        f"Each story is labeled with its source tier. Prioritize Tier 1 and Tier 2 "
        f"(hyperlocal) stories. Only include Tier 3 (metro) stories if they have a "
        f"CLEAR, DIRECT impact on Hoover, Mountain Brook, Vestavia Hills, or "
        f"Shelby County residents.\n\n"
        f"Write today's newsletter edition following your system prompt. "
        f"Output ONLY the inner HTML content — no <html>, <head>, <body>, or "
        f"<style> tags. The content will be inserted into an email template.\n\n"
        f"RAW STORIES ({len(stories)} total):\n\n{stories_text}"
    )

    print(f"\n📝 Sending {len(stories)} stories to Claude...")

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": user_message}
        ],
    }

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=120,
    )

    if resp.status_code != 200:
        print(f"❌ Claude API error {resp.status_code}: {resp.text}")
        sys.exit(1)

    result = resp.json()
    newsletter_content = result["content"][0]["text"]

    input_tokens = result.get("usage", {}).get("input_tokens", 0)
    output_tokens = result.get("usage", {}).get("output_tokens", 0)
    print(f"✅ Newsletter generated ({input_tokens} input / {output_tokens} output tokens)")

    return newsletter_content


# ---------------------------------------------------------------------------
# STEP 4: ASSEMBLE AND SEND EMAIL
# ---------------------------------------------------------------------------

def wrap_in_template(content, date_str):
    """Wrap Claude's content output in the styled email template."""
    return EMAIL_TEMPLATE.replace("{content}", content).replace("{date}", date_str)


def send_email(html_content):
    """Send the newsletter via Resend API."""
    if not RESEND_API_KEY:
        print("⚠️  RESEND_API_KEY not set — saving to file instead.")
        save_to_file(html_content)
        return

    if not EMAIL_TO:
        print("⚠️  EMAIL_TO not set — saving to file instead.")
        save_to_file(html_content)
        return

    today = datetime.now().strftime("%A, %B %d")
    subject = f"The Local Briefing — {today}"

    recipients = [e.strip() for e in EMAIL_TO.split(",")]

    payload = {
        "from": EMAIL_FROM,
        "to": recipients,
        "subject": subject,
        "html": html_content,
    }

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    if resp.status_code == 200:
        print(f"📧 Email sent to {', '.join(recipients)}")
    else:
        print(f"❌ Email send failed ({resp.status_code}): {resp.text}")
        save_to_file(html_content)


def save_to_file(html_content):
    """Save newsletter to a local HTML file as fallback."""
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"newsletter_{today}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"💾 Newsletter saved to {filename}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("📰 THE LOCAL BRIEFING — Newsletter Generator v2")
    print(f"   {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}")
    print("=" * 60)

    # Step 1: Fetch stories
    print("\n📡 Step 1: Fetching RSS feeds...")
    stories = fetch_all_stories()

    tier1_count = sum(1 for s in stories if "Tier 1" in s["tier"])
    tier2_count = sum(1 for s in stories if "Tier 2" in s["tier"])
    tier3_count = sum(1 for s in stories if "Tier 3" in s["tier"])
    print(f"\n   Total: {len(stories)} stories "
          f"(Tier 1: {tier1_count}, Tier 2: {tier2_count}, Tier 3: {tier3_count})")

    if not stories:
        print("❌ No stories found. Exiting.")
        sys.exit(1)

    # Step 2: Get weather
    print("\n🌤️  Step 2: Getting weather forecast...")
    weather = get_weather()
    print(f"   {weather}")

    # Step 3: Generate newsletter with Claude
    print("\n✍️  Step 3: Generating newsletter with Claude...")
    content = generate_newsletter(stories, weather)

    # Step 4: Wrap in email template and send
    print("\n📧 Step 4: Assembling and sending newsletter...")
    today = datetime.now().strftime("%A, %B %d, %Y")
    full_email = wrap_in_template(content, today)
    send_email(full_email)

    print("\n✅ Done! Check your inbox.")
    print("=" * 60)


if __name__ == "__main__":
    main()
