<h1 align="center">WCA Competition Reminder</h1>

<p align="center">
  Personalized email alerts for newly announced World Cube Association competitions.
</p>

<p align="center">
  <a href="README.zh-CN.md">简体中文</a>
</p>

---

WCA Competition Reminder polls the official WCA API for newly announced competitions and
sends each recipient a personalized email based on their event and region preferences. Each
message includes the competition dates and location. When recipient coordinates are present,
it also includes the straight-line distance; otherwise the distance is shown as `-`.

## Highlights

- Supports all 17 official WCA events.
- Gives every recipient independent event, country/region, continent, and optional distance
  filters.
- Calculates great-circle distance locally from WCA coordinates. Distance calculation needs
  no maps API; the browser map picker is an optional enhancement.
- Persists discovery and delivery state in SQLite, with automatic retries for transient
  failures.
- Establishes a silent baseline on first run, so existing competitions do not generate a
  flood of notifications.
- Runs as a one-shot poller or a supervised, once-per-minute service with PM2.
- Includes a browser subscription desk for registering, editing, and cancelling email alerts.
- Includes a read-only operations console protected by a list of administrator accounts.
- Writes masked user/admin audit events to seven-day, level-separated logs.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- An SMTP account with STARTTLS (usually port `587`) or implicit TLS (usually port `465`)
- Optional: a Google Maps Platform browser API key with Maps JavaScript API enabled for the
  location picker
- Node.js and [PM2](https://pm2.keymetrics.io/) for the production deployment described below

## Quick Start

### 1. Install dependencies

```bash
uv sync --frozen --group dev --python 3.12
cp config.example.toml config.toml
```

On Windows, use `Copy-Item config.example.toml config.toml` instead of `cp`. The virtual
environment interpreter is `.venv/bin/python` on Linux and macOS, and
`.venv\Scripts\python.exe` on Windows.

### 2. Configure the application

Edit `config.toml`. At minimum:

1. Replace the contact address in `wca.user_agent` with an address that WCA can reach.
2. Set the SMTP host, port, security mode, username, and sender address.
3. Optionally add `[[recipients]]` entries for recipients managed in TOML. The list may be
   omitted when all recipients will use the browser subscription desk.
4. Add at least one `[[admins]]` entry with a unique username and strong password.
5. To enable Google Maps location selection, set a browser API key in `[web]`.

See [`config.example.toml`](config.example.toml) for every available setting.

```toml
[web]
google_maps_api_key = "your-browser-api-key"

[[admins]]
username = "admin"
password = "replace-with-a-strong-admin-password"

[[recipients]]
name = "Example recipient"
email = "recipient@example.com"
latitude = 31.2304
longitude = 121.4737
max_distance_km = 300
events = "333,minx,pyram"
countries = ["China", "Hong Kong, China"]
continents = ["Asia"]
```

TOML recipient coordinates are also optional: set both values or omit both. Set the optional
positive `max_distance_km` value to receive only competitions within that great-circle
distance. Coordinates are required when the distance filter is set. Without coordinates,
email distance is shown as `-`.

### 3. Provide the SMTP password

For an interactive shell, use the environment variable named by `smtp.password_env` (the
default is `WCA_REMINDER_SMTP_PASSWORD`):

```bash
export WCA_REMINDER_SMTP_PASSWORD='your-app-password'
```

Do not put the SMTP password in `config.toml` or commit it to Git. The application reads the
SMTP password from, in priority order:

1. `--smtp-password-file PATH`
2. The configured environment variable
3. A systemd credential named `smtp_password`

### 4. Validate and test

```bash
.venv/bin/python -m wca_competition_reminder --config config.toml check-config
.venv/bin/python -m wca_competition_reminder --config config.toml send-test
.venv/bin/python -m wca_competition_reminder --config config.toml poll
```

`check-config` does not read the SMTP password, access the network, or send email. `send-test`
sends one test message to every configured recipient. The first successful `poll` records all
existing future competitions as a silent baseline; only competitions announced after that
baseline can generate reminders.

## Browser Subscription Desk

Start the browser service alongside the poller:

```bash
.venv/bin/python -m wca_competition_reminder \
  --config config.toml \
  --smtp-password-file smtp_password \
  web --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080/`. The form supports registering, modifying, and cancelling a
subscription. Registration requires explicit consent to receive WCA competition notification
emails and a six-digit email code that expires after five minutes. Code delivery is limited to
once per email every 50 seconds, while the browser uses a 60-second countdown. Email is the
only subscription identifier: current settings, updates, and cancellation do not use a token.
Recipient coordinates are optional and must either both be set or both be empty. An optional
positive maximum distance requires coordinates. Cancellation blocks pending deliveries for
that address. Changes apply to competitions that have not already been queued.

When `[web].google_maps_api_key` is configured, the coordinate fields include a Google Maps
picker. Clicking the map and confirming the selection fills both coordinates to six decimal
places. Enable the [Maps JavaScript API](https://developers.google.com/maps/documentation/javascript/cloud-setup)
for the Google Cloud project, then apply [HTTP referrer and API restrictions](https://developers.google.com/maps/api-security-best-practices)
for the deployed domains. Browser API keys are sent to clients and must not be treated as
server-side secrets.

The browser's country and continent choices are loaded from the WCA country catalog through
the server-side `/api/options` endpoint and cached for six hours. Keep the Web service bound
to localhost when placing it behind a reverse proxy, and terminate HTTPS at that proxy.

### Admin console

Open `http://127.0.0.1:8080/admin` and sign in with any `[[admins]]` username/password pair
from `config.toml`. The read-only console shows processing checkpoints, subscribers,
competitions, and mail deliveries. Authentication uses an HttpOnly, SameSite session cookie
that expires after eight hours and is invalidated by a Web service restart. Public deployments
must use HTTPS, and `config.toml` should be readable only by the service account. Administrator
usernames must be unique; add more `[[admins]]` tables when multiple operators need access.

Schema v4 automatically and transactionally migrates an existing v3 SQLite state database on
startup. Existing subscriptions keep `max_distance_km = NULL`, so their behavior is unchanged.
Schema v2 and earlier are still rejected because their layouts cannot be upgraded safely.

## Recipient Filters

### Events

`events` is a comma-separated list of WCA event IDs. Leave it empty or omit it to subscribe to
all official events.

```text
333, 222, 444, 555, 666, 777, 333bf, 333fm, 333oh,
clock, minx, pyram, skewb, sq1, 444bf, 555bf, 333mbf
```

### Regions

`countries` and `continents` are TOML string arrays:

- Country/region values must exactly match WCA's English display names. You can find them in
  the [WCA countries API](https://www.worldcubeassociation.org/api/v0/countries).
- Continent values are read from the current WCA catalog; use the labels returned by
  `/api/options` (or the WCA countries API) rather than maintaining a local enum.
- If both arrays are empty or omitted, all regions match.
- If either array has values, a competition matches when its country/region **or** continent
  appears in the configured arrays.

### Distance

`max_distance_km` is an optional positive number. When set, `latitude` and `longitude` are
required, and a competition matches only when its locally calculated great-circle distance is
less than or equal to the configured radius. If WCA coordinates remain unavailable after the
normal retry window, distance-filtered recipients are skipped; recipients without a distance
filter retain the existing degraded notification behavior.

Event, region, and distance filters are combined: a recipient is notified only when every
configured filter matches.

## CLI Reference

Global options must appear **before** the subcommand:

```bash
.venv/bin/python -m wca_competition_reminder \
  --config config.toml \
  --state ./state.sqlite3 \
  --lock ./runner.lock \
  --log-level INFO \
  poll
```

### Subcommands

| Command | Description |
| --- | --- |
| `check-config` | Validate configuration without reading the SMTP password or sending email. |
| `send-test` | Send one test email to each configured recipient. |
| `poll` | Run one discovery, enrichment, and delivery cycle. |
| `run` | Poll immediately, then continue serially at one-minute intervals. |
| `web` | Serve the subscription page and JSON API (`--host`, `--port`). |
| `status` | Print baseline, competition, and delivery counts from SQLite. |
| `retry-blocked` | Move permanently blocked deliveries back to the pending queue after the underlying SMTP issue is fixed. |

### Global Options

| Option | Description |
| --- | --- |
| `--config PATH` | TOML configuration path; defaults to `./config.toml`. |
| `--state PATH` | Override the SQLite state path from the configuration. |
| `--lock PATH` | Override the process lock path from the configuration. |
| `--smtp-password-file PATH` | Read the SMTP password from a UTF-8 text file. |
| `--log-level LEVEL` | Set `DEBUG`, `INFO`, `WARNING`, or `ERROR`; defaults to `INFO`. |
| `--version` | Print the application version. |
| `-h`, `--help` | Show the generated command help. |

Run `python -m wca_competition_reminder --help` for the generated command help.

## Logging and audit trail

`log_dir` defaults to `logs` beside the configuration file. Each command writes separate
`<command>.out.log` and `<command>.err.log` files. Levels below `ERROR` go to stdout and the
out file; `ERROR` and `CRITICAL` go to stderr and the error file without duplication. Files
rotate at midnight, retaining the current file plus six daily archives for seven calendar
days.

The Web service audits verification requests, registration, lookup, update, cancellation,
administrator login/logout, and admin data views. Email addresses are masked; passwords and
verification codes are never logged. The PM2 configuration discards PM2's duplicate log copy,
so production diagnostics should read `logs/run.*.log` and `logs/web.*.log` directly.

## Deployment with PM2

The repository includes [`ecosystem.config.js`](ecosystem.config.js) for a Linux deployment.
It starts both the continuous `run` poller and the localhost Web subscription service with the
project-local `.venv/bin/python`.

### Install and start

Run these commands as the dedicated, non-root account that will own the service:

```bash
git clone <repository-url> wca-competition-reminder
cd wca-competition-reminder

uv sync --frozen --no-dev --python python3.12
cp config.example.toml config.toml

install -m 600 /dev/null smtp_password
# Edit config.toml and place only the SMTP password in smtp_password.

.venv/bin/python -m wca_competition_reminder \
  --config config.toml \
  --smtp-password-file smtp_password \
  check-config
.venv/bin/python -m wca_competition_reminder \
  --config config.toml \
  --smtp-password-file smtp_password \
  send-test

pm2 start ecosystem.config.js
pm2 save
```

For automatic startup after reboot, run `pm2 startup` and execute the command it prints, then
run `pm2 save` again. PM2 should run under the same account that owns the project files.

### Operate the service

```bash
pm2 status wca-competition-reminder
pm2 status wca-competition-reminder-web
tail -F logs/run.out.log logs/run.err.log
tail -F logs/web.out.log logs/web.err.log
pm2 restart wca-competition-reminder
pm2 restart wca-competition-reminder-web
pm2 stop wca-competition-reminder
pm2 stop wca-competition-reminder-web
```

Upgrade the checked-out application without replacing its state or secrets:

```bash
git pull --ff-only
uv sync --frozen --no-dev --python python3.12
pm2 restart wca-competition-reminder
pm2 restart wca-competition-reminder-web
```

Keep `config.toml`, `smtp_password`, `state.sqlite3`, and `runner.lock` out of Git. Back up
`state.sqlite3`: it is application state, not a disposable cache. Do not run multiple PM2
instances or another scheduler against the same state file; the process lock intentionally
allows only one active poller.

## State and Recovery

Inspect the current state:

```bash
.venv/bin/python -m wca_competition_reminder --config config.toml status
```

After fixing a permanent SMTP error, requeue blocked deliveries:

```bash
.venv/bin/python -m wca_competition_reminder --config config.toml retry-blocked
```

To erase all competition and delivery state, stop the service first and run:

```bash
.venv/bin/python clear_database.py --config config.toml
```

The script requires typing `CLEAR` before it deletes anything. The next successful poll will
create a new silent baseline.

Email delivery uses at-least-once semantics. A crash after the SMTP server accepts a message
but before SQLite records it as sent can produce a duplicate. Stable `Message-ID` values help
mail servers deduplicate messages, but cannot guarantee it.

## Development

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

On Windows, replace `.venv/bin/python` with `.venv\Scripts\python.exe` and invoke Ruff as
`.venv\Scripts\ruff.exe`.

## License

This project is licensed under the [MIT License](LICENSE).
