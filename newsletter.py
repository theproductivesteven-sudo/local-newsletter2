#!/usr/bin/env python3
"""
Local Birmingham Newsletter Generator
Pulls RSS feeds, gets weather, sends to Claude for drafting, emails the result.

Sources: WVTM 13, Birmingham Watch, Bham Now, CBS 42, Birmingham Times,
         BirminghamMommy, Hoover Sun, Village Living, Vestavia Voice
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

# Load from environment variables (set these in .env or your hosting platform)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_TO = os.getenv("EMAIL_TO", "")  # comma-separated for multiple
EMAIL_FROM = os.getenv("EMAIL_FROM", "newsletter@yourdomain.com")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

# Hoover, AL coordinates for weather
WEATHER_LAT = 33.4054
WEATHER_LON = -86.8114

# How many hours back to look for stories
LOOKBACK_HOURS = 28  # Slightly more than 24 to catch late-published stories

# ---------------------------------------------------------------------------
# RSS SOURCES
# ---------------------------------------------------------------------------

RSS_FEEDS = {
    # Tier 1: Hyperlocal (most important)
    "Hoover Sun": "https://hooversun.com/api/rss/content.rss",
    "Village Living": "https://www.villagelivingonline.com/api/rss/content.rss",
    "Vestavia Voice": "https://vestaviavoice.com/api/rss/content.rss",

    # Tier 2: Metro news sources
    "WVTM 13": "https://www.wvtm13.com/topstories-rss",
    "Birmingham Watch": "https://birminghamwatch.org/feed",
    "Bham Now": "https://bhamnow.com/feed",
    "CBS 42": "https://cbs42.com/feed",
    "Birmingham Times": "https://birminghamtimes.com/feed",
    "BirminghamMommy": "https://birminghammommy.com/feed",
}

# ---------------------------------------------------------------------------
# SYSTEM PROMPT (the newsletter's voice and rules)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the AI writer behind a hyper-local daily email newsletter covering Hoover, Mountain Brook, Vestavia Hills, and Shelby County, Alabama. You work alongside a real dad (the editor) who reviews and refines your drafts before they go out.

## YOUR VOICE & PERSONA

You write like a sharp, friendly neighbor who happens to read every local news source so other busy parents don't have to. You're conversational but never sloppy. You respect people's time — every sentence earns its place.

Key voice traits:
- First person singular ("I" not "we")
- Contractions: yes. Slang: no.
- Warm but efficient — think "smart friend at school pickup" not "local news anchor"
- You explain why something matters to a parent/homeowner/resident, not just what happened
- You occasionally show personality (a dry observation, a relatable aside) but never at the expense of clarity
- You never editorialize on politics — you report what happened and why it matters locally
- You never use corporate jargon, newsletter clichés ("in other news..."), or filler phrases

## SMART BREVITY RULES

Follow Axios-style smart brevity principles:
1. Lead with the news. First sentence = what happened. No throat-clearing.
2. "Why it matters" is mandatory. Every story needs a 1-sentence "why you care" angle tied to daily life in these communities.
3. One idea per sentence. Short paragraphs. No compound-complex sentences.
4. If a story can be told in 2 sentences, don't use 3.
5. Use strong, specific verbs. "The council approved" not "The council voted to move forward with the approval of."
6. Include the source link naturally at the end of each story.

## GEOGRAPHIC FILTER

Only include stories that directly affect residents of:
- Hoover (including Ross Bridge, Greystone, Lake Cyrus, Bluff Park)
- Mountain Brook (including Crestline, English Village, Mountain Brook Village)
- Vestavia Hills
- Shelby County (including Helena, Pelham, Alabaster, Chelsea, Calera when relevant)
- Birmingham metro stories ONLY if they have direct, tangible impact on the above areas

## TOPIC PRIORITIES (ranked)

1. Schools — closings, calendar changes, board decisions, safety incidents, sports highlights
2. Safety — crime reports, traffic incidents, road closures, weather alerts
3. Local government — zoning decisions, city council actions, tax/budget changes
4. Development — new businesses, construction, closings of beloved spots
5. Community — events, volunteer opportunities, things to do with kids
6. Business — local business news, major employer updates
7. Weather — only if actionable (severe weather, unusual conditions)

## NEWSLETTER STRUCTURE

Follow this exact structure for every edition:

### HEADER
The newsletter name and today's date.

### TOP CALLOUT (conditional)
A single short line that flags weather, school, or traffic news in Parent Radar below. Only include this if there's something genuinely actionable. If it's a normal day, skip this entirely.

### THE BIG ONE
The day's most important local story. Bold conversational headline. 3-4 sentences: what happened, context, why it matters to you. Link to source.

### WHAT'S HAPPENING
3-5 additional stories, each as its own mini-block. Bold conversational headline. 2-3 sentences: what happened + why you care. Link to source.

### QUICK HITS
3-4 smaller items as tight one-liners with a link.

### AROUND TOWN (optional)
2-3 upcoming local events. One line each with date, place, and link if available.

### PARENT RADAR (always last content section)
The practical stuff busy parents need. Include whichever are relevant, omit any with nothing to report:
- Weather: One-line forecast with high/low and anything worth planning around
- Schools: Closings, delays, early dismissals, schedule changes
- Traffic/Roads: Lane closures, construction zones, detour routes

### FOOTER
"Thanks for reading. This newsletter is AI-built and dad-refined — because between diaper changes and school drop-offs, this is how we keep up. Got a tip or feedback? Just reply to this email."

## FORMATTING

Output clean HTML suitable for an email newsletter:
- Use <b> for story headlines within sections
- Use <hr> between major sections
- Use <a href="URL"> for source links
- Keep the total newsletter to a 3-4 minute read (roughly 600-900 words)
- Do not use any CSS styling or <style> tags — just clean semantic HTML
- Use <p> tags for paragraphs
- For Quick Hits, use a simple list with <b> for the topic

## TONE EXAMPLES

GOOD: "Mountain Brook's city council quietly approved a rezoning request Monday night that could bring a new mixed-use development to the old Piggly Wiggly site on Cahaba Road. If you drive through English Village, you'll want to watch this one — it could mean more traffic, but also a coffee shop within walking distance."

BAD: "In a significant development for the Mountain Brook community, the city council has voted to approve a rezoning request that will potentially transform the former Piggly Wiggly location."

## THIN NEWS DAYS

Some days there won't be 6-8 strong stories. That's fine. Quality over quantity.
- Minimum viable edition: THE BIG ONE + 2-3 Quick Hits + Parent Radar
- Never pad with state-level or national stories just to fill space
- On slow days, surface a "did you know" local fact or spotlight a local event

## HANDLING SENSITIVE TOPICS

- Crime: Report facts without sensationalizing.
- Schools: Extra care with anything involving minors. Stick to official sources.
- Local politics: Present what happened and what it means. No editorial slant.
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
        try:
            print(f"  Fetching {source_name}...")

            # Use requests to fetch the feed content first (more reliable)
            try:
                resp = requests.get(feed_url, timeout=15, headers={
                    "User-Agent": "LocalNewsletterBot/1.0"
                })
                resp.raise_for_status()
                feed = feedparser.parse(resp.content)
            except requests.RequestException:
                # Fallback to feedparser's built-in fetching
                feed = feedparser.parse(feed_url)

            if feed.bozo and not feed.entries:
                print(f"  ⚠️  {source_name}: Feed error — skipping")
                continue

            count = 0
            for entry in feed.entries[:20]:  # Max 20 per source
                # Parse the publish date
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

                # Filter to recent stories only (if we can determine the date)
                if pub_date and pub_date < cutoff:
                    continue

                # Extract summary/description
                summary = ""
                if hasattr(entry, 'summary'):
                    summary = entry.summary
                elif hasattr(entry, 'description'):
                    summary = entry.description

                # Clean HTML tags from summary (basic cleanup)
                summary = re.sub(r'<[^>]+>', '', summary)
                summary = summary.strip()[:500]  # Truncate long summaries

                story = {
                    "source": source_name,
                    "title": entry.get("title", "No title"),
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
            "cnt": 8,  # Next 24 hours in 3-hour blocks
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # Extract high/low and conditions
        temps = [item["main"]["temp"] for item in data["list"]]
        high = round(max(temps))
        low = round(min(temps))
        conditions = data["list"][0]["weather"][0]["description"].capitalize()

        # Check for rain/snow
        precip = any(
            item["weather"][0]["main"] in ["Rain", "Thunderstorm", "Snow", "Drizzle"]
            for item in data["list"]
        )
        precip_note = " Rain expected — plan accordingly." if precip else ""

        return f"Weather: {conditions}, high {high}°/low {low}°.{precip_note}"

    except Exception as e:
        print(f"  ⚠️  Weather fetch failed: {e}")
        return "Weather data temporarily unavailable."


# ---------------------------------------------------------------------------
# STEP 3: BUILD THE PROMPT AND CALL CLAUDE
# ---------------------------------------------------------------------------

def format_stories_for_prompt(stories):
    """Format all stories into a text block for Claude."""
    if not stories:
        return "No stories were found in the feeds today."

    lines = []
    for s in stories:
        lines.append(
            f"SOURCE: {s['source']}\n"
            f"HEADLINE: {s['title']}\n"
            f"SUMMARY: {s['summary']}\n"
            f"LINK: {s['link']}\n"
            f"DATE: {s['date']}"
        )
    return "\n---\n".join(lines)


def generate_newsletter(stories, weather):
    """Send stories to Claude API and get back a newsletter draft."""
    if not ANTHROPIC_API_KEY:
        print("❌ ANTHROPIC_API_KEY not set!")
        sys.exit(1)

    today = datetime.now().strftime("%A, %B %d, %Y")
    stories_text = format_stories_for_prompt(stories)

    user_message = (
        f"Today's date is {today}.\n\n"
        f"WEATHER DATA:\n{weather}\n\n"
        f"Here are today's raw news stories from Birmingham-area sources. "
        f"Please filter for geographic relevance to Hoover, Mountain Brook, "
        f"Vestavia Hills, and Shelby County, then write today's newsletter "
        f"edition following all the instructions in your system prompt.\n\n"
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
    newsletter_html = result["content"][0]["text"]

    # Estimate token usage for cost tracking
    input_tokens = result.get("usage", {}).get("input_tokens", 0)
    output_tokens = result.get("usage", {}).get("output_tokens", 0)
    print(f"✅ Newsletter generated ({input_tokens} input / {output_tokens} output tokens)")

    return newsletter_html


# ---------------------------------------------------------------------------
# STEP 4: SEND EMAIL VIA RESEND
# ---------------------------------------------------------------------------

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
    subject = f"Your Local Briefing — {today}"

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
    print("📰 LOCAL NEWSLETTER GENERATOR")
    print(f"   {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}")
    print("=" * 60)

    # Step 1: Fetch stories
    print("\n📡 Step 1: Fetching RSS feeds...")
    stories = fetch_all_stories()
    print(f"\n   Total stories collected: {len(stories)}")

    if not stories:
        print("❌ No stories found. Exiting.")
        sys.exit(1)

    # Step 2: Get weather
    print("\n🌤️  Step 2: Getting weather forecast...")
    weather = get_weather()
    print(f"   {weather}")

    # Step 3: Generate newsletter with Claude
    print("\n✍️  Step 3: Generating newsletter with Claude...")
    newsletter = generate_newsletter(stories, weather)

    # Step 4: Send email
    print("\n📧 Step 4: Sending newsletter...")
    send_email(newsletter)

    print("\n✅ Done! Check your inbox.")
    print("=" * 60)


if __name__ == "__main__":
    main()
