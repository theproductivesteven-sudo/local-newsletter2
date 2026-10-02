# The Local Briefing — v3

Every morning at 5 AM Central, GitHub Actions pulls local news, has Claude write
the edition, and emails **you** a paste-in kit. You review it, paste it into
beehiiv, and schedule the send. beehiiv handles subscribers, unsubscribes,
the archive page, and analytics on its free plan.

## The daily routine (~2 minutes)

1. Open the email titled **[Draft] …**
2. Skim the **Double-check before sending** notes at the top.
3. In beehiiv: **Start writing** → choose your *Local Briefing* template.
4. Copy the subject line into the title/subject field, and the preview text into the preview field.
5. Select everything between the ✂ markers in the email, copy, and paste into the beehiiv editor.
6. Make any edits, then schedule or send.

If a paste ever comes out mangled, the email also has the edition attached as an
`.html` file. In beehiiv, add an **HTML snippet** block and paste the file's contents.

## One-time setup

### 1. beehiiv
- Create a publication on the free plan.
- Build a template once: **Start writing → My templates → New**. In the Style panel,
  pick a clean sans-serif font, ~16px body text, and link color `#2a6b4a`. Leave the
  body empty. Using this template every day keeps editions consistent.

### 2. GitHub secrets (Settings → Secrets and variables → Actions)
| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your Claude API key |
| `RESEND_API_KEY` | your Resend key |
| `EMAIL_TO` | **just your own email** (the one your Resend account uses, if sending from onboarding@resend.dev) |
| `EMAIL_FROM` | optional — defaults to `The Local Briefing <onboarding@resend.dev>` |
| `OPENWEATHER_API_KEY` | your OpenWeatherMap key |
| `ANTHROPIC_MODEL` | optional — set this when a newer model ships |

### 3. Turn the schedule back on
**Actions** tab → **Daily Newsletter Draft** → if you see "This scheduled workflow is disabled," click **Enable workflow**. Then **Run workflow** once to test.

## Maintenance

- **Feed health** shows at the top of every draft. If a source keeps showing up as
  broken, remove or replace it in `RSS_FEEDS` in `newsletter.py`.
- Past editions live in `archive/` in this repo.
- If a run fails, GitHub emails you automatically.

## Local testing
```
pip install -r requirements.txt python-dotenv
cp .env.example .env   # fill in keys
python newsletter.py --preview   # writes draft_preview.html instead of emailing
```
