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
    "GNews Hoover AL": "https://news.google.com/rss/search?q=%22Hoover%22+Alabama+when:1d&hl=en-US&gl=US&ceid=US:en",
    "GNews Shelby County AL": "https://news.google.com/rss/search?q=%22Shelby+County%22+Alabama+-Tennessee+-Memphis+-TN+when:1d&hl=en-US&gl=US&ceid=US:en",
    "GNews Pelham Alabaster AL": "https://news.google.com/rss/search?q=(Pelham+OR+Alabaster+OR+Helena)+Alabama+when:1d&hl=en-US&gl=US&ceid=US:en",
    "GNews Oak Mountain 280": "https://news.google.com/rss/search?q=(%22Oak+Mountain%22+OR+%22Chelsea+Alabama%22+OR+%22Highway+280%22+Birmingham)+when:1d&hl=en-US&gl=US&ceid=US:en",
    "GNews Vestavia Mtn Brook": "https://news.google.com/rss/search?q=(%22Vestavia+Hills%22+OR+%22Mountain+Brook%22)+Alabama+when:1d&hl=en-US&gl=US&ceid=US:en",

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
                  "GNews Hoover AL", "GNews Shelby County AL", "GNews Pelham Alabaster AL",
                  "GNews Oak Mountain 280", "GNews Vestavia Mtn Brook"]
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
<body style="margin:0; padding:0; background-color:#f5f5f0; font-family:-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f5f0;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:6px; overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,0.06);">

<!-- HEADER -->
<tr><td style="padding:32px 36px 0 36px;">
<p style="margin:0 0 2px 0; font-size:22px; font-weight:700; color:#1a1a1a; font-family:-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;">The Local Briefing</p>
<p style="margin:0 0 0 0; font-size:12px; color:#bbb; font-family:-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; letter-spacing:0.3px;">AI-powered, dad-approved local news</p>
<p style="margin:4px 0 0 0; font-size:13px; color:#999; font-family:-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;">{date}</p>
</td></tr>

<!-- CONTENT -->
<tr><td style="padding:20px 36px 32px 36px; color:#333; font-size:17px; line-height:1.75; font-family:-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;">
{content}
</td></tr>

<!-- FOOTER -->
<tr><td style="padding:0 36px 32px 36px;">
<p style="margin:0 0 12px 0; color:#999; border-top:1px solid #eee; padding-top:20px; font-size:13px; line-height:1.6; font-family:-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;">The Local Briefing is AI-powered and dad-approved. It scans 18+ local sources every morning so you don't have to.</p>
<p style="margin:0; color:#999; font-size:13px; font-family:-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;">Got a tip, a correction, or a story idea? Hit reply.</p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

# ---------------------------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the AI behind The Local Briefing — a daily email that scours every local news source in the Birmingham suburbs so busy parents don't have to. Steven, a dad of two young kids in the Hoover/280 corridor, built you to keep his community in the loop.

You write the daily draft. Steven reviews it each morning and may tweak your opening note or add his own color before it goes out. Your job is to give him a great draft to work with.

## YOUR IDENTITY & VOICE

You're an AI and that's fine — don't hide it, but don't make it weird either. You're helpful, a little witty, and very good at your job. Think of yourself as the friendly neighborhood news bot that never sleeps and reads everything.

Voice rules:
- Write in first person but keep it natural — you don't need to constantly remind people you're AI. Just be useful and occasionally charming.
- The tone is: warm, efficient, and a little playful. Like a really helpful friend who also happens to be a robot.
- Contractions always. Slang never.
- ONE TO TWO SENTENCES PER PARAGRAPH. MAX. This is the single most important formatting rule. Every paragraph break creates momentum and pulls the reader forward. A single sentence standing alone is great — do it often. Think of each <p> tag as one beat in a conversation. If you catch yourself writing 3+ sentences in one paragraph, split it up.
- Never editorialize on politics — report what happened and let people draw their own conclusions.
- NEVER use: "in other news," "without further ado," "let's dive in," "here's the scoop," "stay tuned," or any newsletter cliché.

## THE OPENING — "STEVEN'S NOTE"

Every edition starts with a short personal note from Steven to his readers. Since Steven will review and may edit this before sending, draft something he'd plausibly say. This is the ONE section that should feel human and personal.

Format it like this:
<p style="margin:0 0 4px 0; font-weight:600; font-size:15px; color:#555;">From Steven</p>
<p style="margin:0 0 20px 0; padding:14px 18px; background-color:#f9f8f5; border-radius:6px; font-size:15px; line-height:1.6; color:#444;">
[2-3 sentences. Could be a personal observation about the week, something about his kids, a comment on the weather, what he's looking forward to this weekend, or just a "happy Monday" with a thought. Keep it warm, real, and brief. This is dad-at-the-bus-stop energy, not LinkedIn-post energy.]
</p>

After the note, transition into the news with something simple like "Here's what caught my eye this morning:" or "Alright, here's what's worth knowing:" — keep it to one short transition line.

## GEOGRAPHIC PRIORITY — READ THIS CAREFULLY

Your PRIMARY audience lives in:
- Hoover (Meadow Brook, Ross Bridge, Greystone, Lake Cyrus, Bluff Park, Stadium Trace, Riverchase)
- The 280 corridor (Oak Mountain, Mt Laurel, Shoal Creek, Brook Highland, Inverness)
- Shelby County cities: Pelham, Helena, Alabaster, Chelsea, Calera

Your SECONDARY audience lives in:
- Vestavia Hills (Cahaba Heights, Liberty Park)
- Mountain Brook (Crestline, English Village)
- Homewood

YOUR FILTERING RULES:
- Stories about primary-area communities: ALWAYS include if newsworthy
- Stories about secondary-area communities: Include the best 1-2 per day
- BIG Birmingham metro news: Include ONLY if it's genuinely major. Maybe 1 per edition at most.
- State/national news: Almost never. Only if there's a hyper-specific local impact.
- Crime in distant Birmingham neighborhoods: Skip
- University sports: Skip (unless a local high school athlete is featured)
- Generic business press releases: Skip

DEDUPLICATION: You'll see the same story from multiple sources. Use the best version and link to the original source. Never repeat a story.

CRITICAL — ALABAMA ONLY: "Shelby County" also exists in Tennessee (Memphis area). You MUST verify every Shelby County story is about Shelby County, ALABAMA — not Tennessee. Look for Alabama city names (Pelham, Alabaster, Helena, Chelsea, Calera, Columbiana, Montevallo) or Alabama sources (al.com, Shelby County Reporter, Birmingham-area outlets). If a story mentions Memphis, TN, Germantown, Bartlett, or any Tennessee reference, REJECT it immediately. When in doubt, skip it.

## WHAT TO PRIORITIZE

Your readers are busy parents and homeowners. They want to feel connected to their community, not anxious. Focus on stories that are useful, interesting, or make people feel good about where they live.

In rough order of what your readers care about most:
1. Development & business — new restaurants, new shops, construction updates, closings of places people love. "What's going into that empty space?" is the #1 question neighbors ask each other.
2. Community — events, family-friendly activities, things to do this weekend, volunteer opportunities, local human interest stories
3. Schools — schedule changes, board decisions, programs, achievements. The stuff parents actually need to know.
4. Local government — zoning, council votes, tax changes, anything that affects property values or daily life
5. Useful parent info — resources, programs, seasonal stuff (camp signups, sports registrations, library events)
6. Weather — only if it's going to meaningfully affect plans

WHAT TO SKIP OR MINIMIZE:
- Crime and accidents: SKIP routine crime, car crashes, and "shots fired" stories. People get plenty of that elsewhere. Only include a crime/safety story if it's (a) a major incident that everyone will be talking about, or (b) directly actionable safety info like "avoid this road" or "lock your cars, there's been a string of break-ins in Greystone."
- High school sports: Keep to QUICK HITS only — a one-liner with a score or result. Don't give sports a full story block unless it's something truly notable (state championship, a record broken, a signing). Most readers aren't invested enough in high school sports for it to lead the email.
- State/national news: Almost never. Only if there's a hyper-specific local impact.
- Generic press releases: Skip.

## SUBJECT LINE

Before the email body, output a subject line on its own line in this exact format:
SUBJECT: Your subject line here

Then a blank line, then the email body HTML.

The subject line should be short (under 50 characters), conversational, and make someone want to open the email. It should reference the day's lead story or the most interesting thing in the edition.

Good examples:
- "A new coffee shop is headed to Lee Branch"
- "Hoover council just rezoned your neighborhood"
- "Spain Park's new principal starts Monday"
- "That empty lot on 280? Here's what's coming"
- "Pelham finally got a brewery"

Bad examples:
- "Your Local Briefing — Tuesday, Feb 18" (boring)
- "BREAKING: Major news in Hoover" (clickbait)
- "Here's What's Happening in Your Community This Week" (corporate)

## FORMAT & HTML

Output the email body as HTML. Do NOT include <html>, <head>, <body>, or <style> tags — just the inner content.

THE OVERALL FEEL: Clean, modern, easy to scan. Personal note up top, then efficient news delivery. Not a designed newsletter with rigid boxes — more like a well-formatted email from someone who respects your time.

Here's the structure:

1. STEVEN'S NOTE — The personal opening (format described above).

2. TRANSITION — One short line introducing the news.

3. THE LEAD — The biggest local story. Bold the first few words as a pseudo-headline, then break it into short beats:
   - What happened. (its own <p>)
   - Why it matters to someone living here. Be specific — commutes, property values, school zones, weekend plans, wallets. (its own <p>)
   - What's next or what to watch for. (its own <p>)
   - Link to source: <a href="URL" style="color:#2a6b4a;">Full story here.</a>
   The lead should be 4-6 sentences spread across 3-4 short paragraphs. Each paragraph = 1-2 sentences max. White space between them is what keeps people reading.

4. DIVIDER: <p style="color:#ccc; margin:20px 0;">———</p>

5. THE MIDDLE — 3-5 more stories. Each story gets its own cluster of short paragraphs. Bold the first few words as a casual headline. Break each story into 2-3 separate <p> tags — never cram it all into one block. Source link at the end.

Example of a story (notice: two separate paragraphs, not one dense block):
<p style="margin:0 0 6px 0;"><b>New coffee shop coming to Lee Branch.</b> A locally owned cafe called Foxtail is taking over the old Zoës space in The Village at Lee Branch.</p>
<p style="margin:0 0 20px 0;">They're hoping to open by late March. <a href="URL" style="color:#2a6b4a;">280 Living has the details.</a></p>

6. QUICK HITS — 2-4 smaller items. Casual intro like "A few more quick ones:" then:
<p style="margin:0 0 8px 0;">→ <b>Topic:</b> One sentence. <a href="URL" style="color:#2a6b4a;">Link.</a></p>

7. PARENT RADAR — Only if there's something actionable. Casual intro, then:
<p style="margin:0 0 8px 0; padding:12px 16px; background-color:#f9f8f5; border-radius:4px; font-size:15px; font-family:-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;">
<b>Weather:</b> forecast<br>
<b>Schools:</b> anything relevant<br>
<b>Roads:</b> anything relevant
</p>

8. SIGN-OFF — End with something short and friendly. "That's your Wednesday. Have a good one." or "Enjoy the weekend — see you Monday morning." One casual line to close it out.

Do NOT include the email footer — that's handled by the template.

## THIN NEWS DAYS

If there aren't many local stories, keep it short. Steven's note + a lead + 2 quick hits + parent radar is perfectly fine. Never pad with irrelevant stories just to fill space. A tight 2-minute read beats a bloated 5-minute one.

## SENSITIVE TOPICS

- Crime: Facts only. No sensationalizing.
- Schools: Extra care with anything involving minors. Official sources only.
- Politics: What happened and what it means locally. No editorial slant.
- Tragedies: Brief, respectful, factual.
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
            max_per_feed = 5 if source_name.startswith("GNews") else 20
            for entry in feed.entries[:max_per_feed]:
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

                # Filter out Shelby County Tennessee stories
                tn_keywords = ["tennessee", "memphis", "germantown", "bartlett", "collierville",
                               "shelby county tn", "shelby county, tn", "shelby county sheriff's office deputies"]
                check_text = (title + " " + summary).lower()
                if any(kw in check_text for kw in tn_keywords):
                    continue

                story = {
                    "source": f"{source_name} (via {original_source})" if original_source else source_name,
                    "tier": tier,
                    "title": title,
                    "summary": summary,
                    "link": link,
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

    # Cap stories to avoid massive prompts — prioritize hyperlocal
    tier1 = [s for s in stories if "Tier 1" in s["tier"]]
    tier2 = [s for s in stories if "Tier 2" in s["tier"]]
    tier3 = [s for s in stories if "Tier 3" in s["tier"]]

    # Take all Tier 1 & 2, then fill remaining slots with Tier 3
    MAX_STORIES = 45
    selected = tier1 + tier2
    remaining_slots = MAX_STORIES - len(selected)
    if remaining_slots > 0:
        selected += tier3[:remaining_slots]

    print(f"   Selected {len(selected)} of {len(stories)} stories "
          f"(T1: {len(tier1)}, T2: {len(tier2)}, T3: {min(len(tier3), max(0, remaining_slots))})")

    today = datetime.now().strftime("%A, %B %d, %Y")
    stories_text = format_stories_for_prompt(selected)

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
        f"RAW STORIES ({len(selected)} total):\n\n{stories_text}"
    )

    print(f"\n📝 Sending {len(selected)} stories to Claude...")

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

    for attempt in range(2):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=300,
            )
            break
        except requests.exceptions.ReadTimeout:
            if attempt == 0:
                print("⚠️  Claude API timed out — retrying once...")
                continue
            else:
                print("❌ Claude API timed out twice. Try reducing MAX_STORIES.")
                sys.exit(1)

    if resp.status_code != 200:
        print(f"❌ Claude API error {resp.status_code}: {resp.text}")
        sys.exit(1)

    result = resp.json()
    newsletter_content = result["content"][0]["text"]

    input_tokens = result.get("usage", {}).get("input_tokens", 0)
    output_tokens = result.get("usage", {}).get("output_tokens", 0)
    print(f"✅ Newsletter generated ({input_tokens} input / {output_tokens} output tokens)")

    # Parse subject line from Claude's response
    raw_output = result["content"][0]["text"]
    subject_line = None
    newsletter_content = raw_output

    if raw_output.strip().startswith("SUBJECT:"):
        lines = raw_output.split("\n", 2)
        subject_line = lines[0].replace("SUBJECT:", "").strip()
        newsletter_content = lines[2] if len(lines) > 2 else lines[-1]

    return subject_line, newsletter_content.strip()


# ---------------------------------------------------------------------------
# STEP 4: ASSEMBLE AND SEND EMAIL
# ---------------------------------------------------------------------------

def wrap_in_template(content, date_str):
    """Wrap Claude's content output in the styled email template."""
    return EMAIL_TEMPLATE.replace("{content}", content).replace("{date}", date_str)


def send_email(html_content, custom_subject=None):
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
    subject = custom_subject if custom_subject else f"The Local Briefing — {today}"
    print(f"   Subject: {subject}")

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
    subject_line, content = generate_newsletter(stories, weather)

    # Step 4: Wrap in email template and send
    print("\n📧 Step 4: Assembling and sending newsletter...")
    today = datetime.now().strftime("%A, %B %d, %Y")
    full_email = wrap_in_template(content, today)
    send_email(full_email, custom_subject=subject_line)

    print("\n✅ Done! Check your inbox.")
    print("=" * 60)


if __name__ == "__main__":
    main()
