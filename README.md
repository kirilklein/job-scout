# Job Scout

A downloadable personal job-search app: build an editable profile, collect employer listings, inspect fit evidence, and keep a daily shortlist. Each installation belongs to one person. No accounts or shared backend.

## Run

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
./run.sh
```

Open **http://127.0.0.1:8090**. The first launch installs locked Python dependencies. Click **Try the demo** to explore fictional listings; demo and live data use separate databases.

1. Open **Your profile**. Explore projects, responsibilities, outcomes, skills, learning, and preferences through guided questions. Include research, volunteering, and personal projects. Review useful details, add them to your editable profile, and save. A CV is optional (text-based PDF, DOCX, TXT, or Markdown). You can save your experience before choosing target roles.
2. Open **Search sources**. Add employer boards on Greenhouse, Lever, or Ashby. Three example employers are available as starting points; they are not personalized recommendations.
3. **Refresh search**. Save interesting jobs, dismiss others with feedback, and inspect match explanations and missing information.
4. Enable **Daily updates**. The app checks enabled sources every 24 hours while running, and catches up after a missed refresh when restarted. Failed sources keep previous listings and show an error. Only a successful complete feed can mark missing jobs closed.

This is a runnable local MVP, not a packaged desktop installer. The server must stay running for updates; an always-on machine can run it continuously. Use a single server process so the scheduler does not duplicate work.

## Intelligent discovery and reviews with Brigade

The app works without model credentials using transparent role-family and keyword matching. Brigade adds tailored interview follow-ups, suggested experience details, web research, employer discovery, and deeper job assessments backed by exact listing quotes. There is no claim that the basic score predicts hiring outcomes.

Requires Node 22.12+. The helper installs **Brigade 1.39.0** and its extension inside this project; it does not alter an existing global Brigade installation or its memory.

```sh
./brigade.sh setup
./brigade.sh onboard
./brigade.sh extensions doctor
# Keep Job Scout running in another terminal:
./brigade.sh scout
```

During onboarding, choose your model provider and configure web search. These are user-owned credentials; none are bundled. The model receives your confirmed profile, listing text, and dismissal feedback when you run the scout. Raw CV files are not passed to Brigade. Hosted model/search providers may charge for usage.

For daily intelligent research, start Brigade's gateway and add a scheduled job **once** after onboarding:

```sh
./brigade.sh gateway run
# In another terminal:
./brigade.sh cron add --every 24h --message 'Use the job-scout skill to discover employers, refresh the dashboard, and review the best opportunities. Do not apply or contact anyone.'
./brigade.sh cron list
```

Both Job Scout and Brigade must be running. Use Brigade's schedule for daily intelligent research; the dashboard's Daily updates switch is the independent feed-only scheduler. Leaving both enabled can cause extra refreshes, though decisions and listing IDs are preserved. Inspect/remove duplicate Brigade schedules through `./brigade.sh cron list` and `./brigade.sh cron rm <id>`.

The extension exposes seven tools: read profile, add source, refresh feeds, list candidates, write assessments, read an active interview request, and submit interview drafts. It never submits applications or sends CVs. Reviews require quotes from the actual listing and matching profile/listing versions; stale assessments disappear when either changes. Quote validation verifies attribution, not the correctness of the model's interpretation.

To use an existing Brigade installation instead, copy `brigade/extension/` into its extensions directory, run `npm ci` there, and copy `brigade/skills/job-scout/` into its workspace skills directory. Do not symlink outside Brigade's extensions directory; its loader rejects those symlinks.

## Build your experience profile

The guided conversation works without credentials. Each answer becomes an editable draft. **Add to profile draft** selects a detail; **Save my profile** confirms it for job assessments. You can also add details manually. Draft answers and model suggestions never silently change your saved profile or search preferences.

To use your CV as interview context, check **Keep the extracted CV text in my local conversation** before uploading. The binary upload is discarded; opted-in text is kept locally. Without that checkbox, only role/skill suggestions are returned. Uploading another retained CV replaces the previous text and its unconfirmed suggestions.

After Brigade setup/onboarding, reload the page. Explicitly check the sharing checkbox and click **Ask Brigade for a deeper follow-up**. This sends the current conversation, retained CV text, and saved profile to your configured provider. Brigade suggests facts with supporting quotes and asks one tailored question. Check facts before accepting: a matching quote does not prove the interpretation is correct. The app rejects unsupported quotes and results for an outdated conversation. Provider failures leave your answers intact.

**Clear conversation** removes the app's answers, retained CV text, and suggestions; saved profile details stay. Brigade may retain its own local transcripts and the provider has its own data policies; clearing the app conversation does not erase those histories. All local app data, including separate demo conversations, is in `data/`.

If you installed an earlier version, rerun `./brigade.sh setup` to update the extension. Model follow-ups use this project's Brigade installation and provider configuration; a separate installation can still use the search tools, but the dashboard's interview button requires local setup. A live authenticated provider is required for model-generated follow-ups.

## Optional web discovery without Brigade

Copy `.env.example` to `.env`, set `TAVILY_API_KEY`, and restart `./run.sh`. **Discover employers** searches for relevant boards using target roles and locations, then fetches their listings. Daily updates also include this discovery when configured. The profile name, CV, and free-text notes are not included in these queries.

With neither Brigade nor Tavily configured, coverage is limited to manually added employer boards. Search does not cover the whole job market. No LinkedIn scraping, automatic applications, or contact with employers is implemented.

## Data and matching

- SQLite stores confirmed profiles, interview answers/drafts and opted-in CV text, sources, listings, feedback, schedules, and refresh history in `data/`. Back up that folder to preserve the workspace. No telemetry is included.
- The server binds to loopback. Browser requests are origin-checked, writes require a custom header, links/content are rendered safely, and uploads have a 5 MB limit. Optionally configure `SCOUT_TOKEN`; the browser asks for it and Brigade must receive the same environment variable. This is a personal local app, not a public multi-tenant service.
- Location and explicit exclusion terms act as filters. Remote eligibility, salary, and unknown arrangements remain visible uncertainties. Experience filtering only detects explicit junior/senior title conflicts. Free-text notes are context for Brigade, not enforced filters.
- Match ordering currently uses rule-based role/skill/location/interest signals. Confirmed experience details inform Brigade’s qualitative assessments; they do not change the numeric rule-based score. Brigade's qualitative reviews appear alongside them; saved/dismissed feedback is available to Brigade, but there is no trained preference model.
- Resume extraction suggests supported skills and common technical role titles. It does not infer years of experience or authorization; scanned PDFs need an OCR/text export.
- IDs are stable within employer feeds. Cross-platform reposts can still appear separately. Public board coverage depends on the employers you discover or add.

## Development and validation

```sh
uv sync --frozen
uv run pytest -q
uv run ruff check scout tests
uv run ruff format --check scout tests
npm ci
npm ci --prefix brigade/extension
npm run test:bridge
npm run test:browser  # uses installed Google Chrome, isolated port 8091/data
npm run format:check
```

The frontend is plain HTML/CSS/JavaScript served by FastAPI; no frontend build is needed. Backend tests cover conversation persistence, explicit sharing, quote validation, stale updates, model failure recovery, feed normalization, failed-refresh retention, persistence, constraints, resume parsing, quote/version validation, and request guards. Browser tests exercise guided interviews, draft confirmation, local CV retention, profile editing, upload drafts, save/dismiss persistence, demo isolation, keyboard dismissal, and mobile overflow.

Public interfaces: [Brigade](https://github.com/spinabot/brigade), [Greenhouse](https://docs.greenhouse.io/job-board.html), [Lever](https://github.com/lever/postings-api), [Ashby](https://developers.ashbyhq.com/docs/public-job-posting-api).
