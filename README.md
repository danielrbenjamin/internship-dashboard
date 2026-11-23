
# Tern

A public internship catalog with a private workspace for tracking applications, reviewing résumé edits, and keeping a copy of what was submitted. The React frontend and FastAPI API share an origin. A Python worker polls job sources and processes owner-requested Codex work. SQLite and the document archive persist across restarts.

<img width="1894" height="969" alt="image" src="https://github.com/user-attachments/assets/a49e8a1e-3fa7-448a-93a9-26aee04dbff2" />


## Windows development

Install Python 3.12, Node 24, and a working TeX distribution with `pdflatex` and `synctex` on PATH. From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev,boards]'
Copy-Item .env.example .env
$dashboardSecret = .\.venv\Scripts\python.exe -c 'import secrets; print(secrets.token_urlsafe(48))'
(Get-Content .env) -replace '^SESSION_SECRET=$', "SESSION_SECRET=$dashboardSecret" | Set-Content .env
Remove-Variable dashboardSecret
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Open [http://localhost:8000](http://localhost:8000). In a second terminal, run `.\.venv\Scripts\python.exe -m backend.discovery`. Add `--once` for a one-time collection check when sources are due. Use `python -m pytest` in the virtual environment for the API and persistence tests. Rebuild the frontend after UI edits. For Windows résumé compilation, finish MiKTeX setup and install dependencies before starting the server.

Public browsing works when the Auth0 fields are blank. The live catalog starts empty until a source succeeds.

## Auth0 and ChatGPT

Use an existing Auth0 Regular Web Application. Enable the Google social connection and set `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET` and `OWNER_SUBJECT` in `.env`. Copy the exact Auth0 user ID from Users, including the provider prefix. Set the app's allowed callback and logout URLs as follows.

| Environment | Callback | Logout return |
|---|---|---|
| Windows | `http://localhost:8000/auth/callback` | `http://localhost:8000` |
| Production | `https://jobs.example.com/auth/callback` | `https://jobs.example.com` |

For ChatGPT, use the Auth0 API with RS256, the deployed MCP URL as the API identifier and the permission `read:applications`. Set `MCP_AUDIENCE` to the exact deployed MCP URL, including `/mcp`. Authorize a user login for ChatGPT and use the exact redirect URI displayed by its connector setup. The machine-to-machine test client has its own subject and cannot read the owner's applications. The server exposes protected-resource metadata at `/.well-known/oauth-protected-resource/mcp`.

Once connected, check that ChatGPT lists `search_applications` and `get_application`. Save a role, retrieve its application ID with search, then look it up. This validates the OAuth flow and retrieval with the actual account.

[ChatGPT OAuth documentation](https://developers.openai.com/plugins/build/auth)

## Discovery

The built-in employer feeds include Google, Apple, Disney, AMD, Amazon, NVIDIA, General Motors, Bosch, Neuralink and Zipline. Apple imports its Students: Internships listing summaries. Google uses its public search results and qualifications, Disney uses its jobs search and linked descriptions, and AMD uses its career-search data. Amazon and Workday searches are bounded samples. Greenhouse and SmartRecruiters fetch descriptions after filtering for internships. The Workday adapter keeps the listing links if the detail endpoint is rate-limited.

SimplifyJobs adds active visible hardware and mechanical-related roles, plus Tesla listings, with links to the original postings. Past labeled terms are excluded, and entries without a recognized term require an update within 60 days. Open the original posting for requirements when its source provides a listing link only.

The worker schedules 45 JobSpy searches every six hours. Indeed, Glassdoor, LinkedIn and Google Jobs each search Canada and the US. ZipRecruiter searches the US. Each board and country searches five phrases independently: mechanical engineering intern, engineering co-op, hardware engineering intern, robotics intern and manufacturing engineering intern. Each search requests up to 40 results from the past 30 days. The Sources view tracks each search separately. Searches returning HTTP 429 wait at least 12 hours before their next scheduled check.

The community sources also import open positions from the 2027 Mechanical Engineering Internships collection (California and Indiana) and the US and Canadian listings in SpeedyApply's SWE and AI internship collections. Jobright adds engineering internships and the Canadian Internship List adds Canadian co-ops. Sources with `discover_boards` enabled learn Greenhouse, Lever, Ashby, Workday and SmartRecruiters boards from application links. Simplify also supplies board links from its historical internship index. Daily directory imports add the employer boards in the Simplify new-grad list, SpeedyApply US new-grad list and JobOps Greenhouse watchlist. Only internship and co-op postings enter the catalog from these boards. A normal cycle checks up to 80 learned boards with recent openings and up to 40 other learned boards, oldest attempt first within each group. Configured feeds and community collections run independently.

To check sources on demand in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m backend.discovery --once --force
.\.venv\Scripts\python.exe -m backend.discovery --once --force --source boards:simplify
```

The Sources view shows which feeds last succeeded. Failed polls keep the prior successful records, and the posting details flag a failed source. A complete feed retires missing roles on the next successful snapshot. A partial feed retires unseen roles after seven days once a successful check confirms they are still missing. The retirement policy preserves saved applications and their posting snapshots. Removing a configured source retires jobs that no other active source observed.

To customize sources, copy `sources.example.json` to `data/sources.json` locally. The file replaces the defaults. Adjust the query, geography, interval and `stale_days` for the relevant sources. Workers without JobSpy installed show setup status for its searches and continue collecting other sources.

Overview shows real catalog counts, discovery activity and source totals. Signed-in owners also see their application pipeline and submission activity. List and Map share the same catalog filters. Pan, zoom, and open cluster pins to inspect city-level postings. Broad or unresolved locations appear below the map. Saved and Applied provide maps with status filters. The Street map layer uses [OpenStreetMap](https://www.openstreetmap.org/copyright) tiles. The local map uses rounded [Natural Earth](https://www.naturalearthdata.com/about/terms-of-use/) boundaries and [GeoNames](https://www.geonames.org/export/) cities5000 data, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Watchlists and saved searches live in the owner workspace. Commas separate alternative required keyword phrases, while preferred keywords rank results. Watchlists and searches with alerts enabled create in-app notifications on the first discovery of a match. In-app alerts are the only notification channel. Browse and Map show active roles with a source-reported posting date in the last 30 UTC calendar days, newest first. Dates missing from a source can be supplied by another observation of the same posting. The discipline filter matches role titles and allows overlapping specialties. Saved applications retain their history.

## Résumé and Codex

In Settings, specify each GitHub template repository as `owner/repository`, its branch, and the exact relative LaTeX filename, including capitalization. For private templates, set a fine-grained `GITHUB_TOKEN` with Contents read access to the selected private résumé and cover-letter repositories. Enter the verified experience and eligibility profile directly in Settings.

Open Application materials → My templates to import your GitHub LaTeX project. Configure the repository, entry file and branch for each template in Settings → Profile. Open a tracked application to make a role-specific copy using Use my saved template. Edit project files in the browser, review individual Codex proposals as side-by-side diffs, and merge the changes you want into your working copy. Save version checkpoints the edited files. Recompile PDF saves and renders them together. A private repository needs read access on the server.

After compiling, choose **Show in PDF** to locate the editor cursor in the preview. Double-click the PDF to jump back to its source. Recompile older PDFs once to generate their SyncTeX data. The Docker image checks the LaTeX packages used by the résumé and cover-letter templates, including XCharter and SVG support. For SVG assets, commit the generated PDF and any LaTeX overlay with the template so pdfLaTeX can include them with shell escape disabled.

Use **Prepare both PDFs** for a tracked application, or enable automatic preparation for strong matches under Where to apply. The worker edits the configured entry in each role-specific project, compiles it, and attempts up to two targeted repairs for compile errors, extra pages, or overfull boxes. Passing PDFs are saved as new versions. The role moves to Ready once both latest versions pass. If a proposal needs manual review, open it in the existing diff editor.

The Cover letter tab can queue a role-specific draft from the saved posting and your verified experience. Edit the response, save a version, and download PDF or text. Drafting uses the same owner-only Codex queue and usage-limit handling as eligibility and résumé work.

Use a dedicated Codex login in the worker. On Ubuntu, run:

```bash
docker compose run --rm worker codex login --device-auth
docker compose run --rm worker codex login status
```

On Windows, run the following from the project folder and finish the browser sign-in. Settings → Codex connection shows the worker's status.

```powershell
.\.venv\Scripts\python.exe -m backend.codex_login
```

This uses the ChatGPT login and can depend on your account's device code policy and usage limits. After sign-in, queue an assessment from a saved application. Reports separate eligibility requirements from engineering fit and display the quoted text. The worker checks the account's Codex limits and pauses at 95% until the reported reset. If the CLI rejects a request for usage and no reset is available, it uses a one-hour fallback. Analytics → Tern AI usage shows worker calls and tokens reported since usage tracking was added. Account-wide usage windows appear there and in Background work.

[Codex CLI authentication](https://developers.openai.com/codex/auth)

## Ubuntu and Cloudflare Tunnel

Copy `.env.example` to `.env`, set `APP_URL` to the public HTTPS origin without a trailing slash, and put the public hostname and `127.0.0.1` in `ALLOWED_HOSTS`. Generate `SESSION_SECRET` with `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` and protect the environment file with `chmod 600 .env`. Configure Auth0 for the production host and run:

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f worker
```

Use a Cloudflare Tunnel managed on the Ubuntu host. Route the public hostname to `http://127.0.0.1:8000`. Leave public browsing open and use the app's Auth0 gate. Do not cache `/api/*`, `/auth/*`, or `/mcp` at the edge. The Compose origin binds to loopback and needs no inbound firewall rule.

[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)

To back up both the SQLite database and document versions as a consistent snapshot, stop both services and archive the data volume:

```bash
mkdir -p backups
chmod 700 backups
docker compose stop app worker
docker compose run --rm --no-deps -T app tar -C /app/data -czf - . > backups/dashboard.tar.gz
docker compose up -d
```

To restore, start with a fresh empty data volume, initialize it with Compose, and stop both services before extracting. Use the same Auth0 owner subject. Review the archive before restoring.

```bash
docker compose stop app worker
docker compose run --rm --no-deps -T app tar -C /app/data -xzf - < backups/dashboard.tar.gz
docker compose up -d
```

Codex login uses a separate private volume. Reauthorize it on the replacement host. Store the backup and environment configuration privately.

## Verification

The catalog tests exercise duplicate imports, alert deduplication, watchlist updates, version history and public field filtering. The API suite covers owner boundaries, logout revocation, failed source preservation, immutable submission exports and MCP token verification with simulated provider signing keys. Production Auth0 login, GitHub résumé import, Codex login, the Cloudflare deployment and live collection are environment checks that need actual accounts or Internet access.

### Application workflows

**Where to apply** ranks current openings against the searches and employers you save in Settings. Enable automatic shortlisting and set the minimum score to save matches when the worker checks. Optional cover letter drafts require verified experience in Settings and a connected Codex worker. Review drafts in Materials.

**Email & deadlines → Manage inboxes** connects Gmail with a Google app password or Outlook with Microsoft device sign-in. The worker looks for employer replies in the last 14 days. Matched mailbox confirmations, interviews and rejections update the application stage with an undo option. Use the legacy MAIL_* settings for a custom IMAP folder. Connected inbox credentials are encrypted with a key derived from SESSION_SECRET. Rotating that secret requires reconnecting inboxes.

**Referrals** uses Exa's people search to find public LinkedIn profiles by employer and team. Set a preferred school, experience keywords, and ranking priority in Settings → Profile. Saved contacts also appear for the selected employer. For in-page results, create an [Exa API key](https://dashboard.exa.ai/api-keys), set `EXA_API_KEY` in `.env`, and restart the app. A direct LinkedIn search is available when in-page results are unavailable.
