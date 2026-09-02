# weirdfinder

Finds weird, obscure games on **Steam** and **itch.io**, scores them, and keeps
a **Google Sheet** up to date. Built to run unattended on an always-on Mac.

It is opinionated about one thing: the sheet is *yours*. The tool writes its own
columns and never touches `status` or `notes`, so you can triage rows by hand
and every future run will leave your triage alone.

```
score  src    title                                         why
 91.2  itch   TAPE NINE                                     analog horror, unsettling, liminal
 89.2  steam  Static Bleed                                  psychological horror, analog horror
 50.4  itch   soft machine                                  art game
```

## What it scores

Three axes, each 0-1, folded into a single 0-100 score.

| Axis | What it measures | Where it comes from |
| --- | --- | --- |
| **obscurity** | How few people have found it yet | Steam review count. itch exposes none, so those fall back to `unknown_obscurity` — the itch "newest" feed is the long tail almost by definition. |
| **vibe** | Surreal / horror / analog | Weighted phrase matching over title, blurb and tags: *analog horror, liminal, weirdcore, PSX, found footage, body horror…* |
| **experimental** | Art game / anti-game | Same, different list: *experimental, art game, avant-garde, dada, anti-game, glitch art…* |

Two things stop this from being a naive keyword count:

- **Tags outweigh prose.** A phrase found in a curated tag counts 1.6× what the
  same phrase counts in a marketing blurb, and a phrase is counted once no
  matter how many fields it appears in.
- **Axes saturate.** Ten horror phrases is not ten times weirder than three, so
  raw matched weight is squashed through `1 - exp(-w / saturation)`.

### How the three combine

By default (`combine = "best"`) obscurity is blended with whichever *vibe* axis
is stronger, plus a bonus for scoring on both. A great analog-horror find is not
marked down for failing to also be an art game — but something that is both is
the sweet spot and scores highest.

Set `combine = "mean"` for the strict reading, where a high score requires all
three axes at once.

Tune any of it without touching code — see [Tuning](#tuning).

## Install

Needs **Python 3.11+**. macOS ships 3.9, which has no `tomllib`, so install a
real one first: `brew install python@3.12`.

```bash
git clone <this repo>
cd Root-Android-Emulator/weirdfinder
./install/install.sh              # installs, schedules daily at 09:00
```

Options: `--hour 7`, `--minute 30`, `--no-schedule`, `--uninstall`.

The script creates a venv in `~/.local/share/weirdfinder/venv`, installs the
package, writes a starter config, and loads a launchd agent.

### Connect the Google Sheet

1. At [console.cloud.google.com](https://console.cloud.google.com): new project →
   enable **Google Sheets API** → **Credentials** → **Create credentials** →
   **Service account** → **Keys** → **Add key** → **JSON**.
2. Save the downloaded file as `~/.config/weirdfinder/service-account.json`.
3. Open it, copy the `client_email` value (it looks like
   `something@project.iam.gserviceaccount.com`), and **share your spreadsheet
   with that address as an Editor**. This is the step everyone forgets — the
   service account is a separate identity and cannot see your files otherwise.
4. Put the spreadsheet id — the long string in its URL, between `/d/` and
   `/edit` — into `sheet.spreadsheet_id` in `~/.config/weirdfinder/config.toml`.

The tool only ever requests the `spreadsheets` scope, so it cannot see anything
in your Drive beyond the sheets you explicitly share with it.

Then:

```bash
weirdfinder check          # config, credentials, connectivity, sheet access
weirdfinder run --dry-run  # print what it would add, write nothing
weirdfinder run            # for real
```

`weirdfinder` lives at `~/.local/share/weirdfinder/venv/bin/weirdfinder`; add
that to your `PATH` or use the full path.

## The sheet

The tab (default `Weird Games`, created on first run) looks like:

| column | written by |
| --- | --- |
| `key`, `score`, `obscurity`, `vibe`, `experimental` | the tool |
| `source`, `title`, `url`, `author`, `price`, `released` | the tool |
| `reviews`, `rating`, `tags`, `why`, `description` | the tool |
| `first_seen`, `last_seen` | the tool |
| **`status`**, **`notes`** | **you — never overwritten** |

- `why` lists the phrases that earned the score, so a surprising row explains
  itself at a glance.
- `first_seen` never moves once set, so sorting by it gives you a "what's new
  since last week" view.
- Rows are **updated in place**, keyed by `<source>:<id>` — a game that keeps
  showing up in the feeds never duplicates.
- Columns you add yourself are left alone, including ones you wedge between the
  tool's own columns.

Sorting is off by default so your row order survives; use a Sheets **filter
view** to sort by score without fighting the tool. Set `sort_by_score = true`
if you would rather it re-sort each run.

## Tuning

Start here — it scores ad-hoc text with no network and no sheet:

```bash
weirdfinder explain "TAPE NINE" \
  -d "Found footage from a hallway that should not be that long." \
  -t "Analog Horror,liminal,PSX" -r 3
```
```
total        93.9 / 100
  obscurity  0.827 (weight 0.35)
  vibe       0.953 (weight 0.35)
  experiment 0.596 (weight 0.30)
  matched    analog horror, found footage, liminal, horror, psx
  threshold  45.0 -> KEEP
```

Common adjustments in `~/.config/weirdfinder/config.toml`:

| Symptom | Fix |
| --- | --- |
| Sheet is too noisy | Raise `scoring.min_score` (default 45) |
| Sheet is too thin | Lower `min_score`, or raise `pages_per_query` / `pages_per_path` |
| Games you have already heard of keep appearing | Lower `popularity_cap` (default 3000) |
| One word keeps causing false positives | Mute it: `[lexicon.vibe]` then `"horror" = 0` |
| A phrase you love is being missed | Add it: `[lexicon.vibe]` then `"kitchen sink horror" = 3.0` |
| Want games strong on *all three* axes only | `combine = "mean"` |
| Junk categories flooding in | Add substrings to `scoring.exclude_terms` |

Change what gets *fetched* by editing `steam.queries` (build a search you like
at `store.steampowered.com/search/` and copy its query-string pairs) and
`itch.browse_paths` (any itch tag works: `games/newest/tag-<name>`).

A typo in a config key is a hard error rather than a silent default — an
unattended job that quietly ignores your tuning is a bug you find weeks later.

## Operating it

```bash
launchctl print gui/$(id -u)/com.weirdfinder.run      # is it loaded?
launchctl kickstart -k gui/$(id -u)/com.weirdfinder.run   # run it now
tail -f ~/Library/Logs/weirdfinder.log
```

Behaviour that matters when nobody is watching:

- **Polite by default.** One request at a time, 1.5s between hits to the same
  host, exponential backoff, and `Retry-After` is honoured. A scheduled run is
  not an excuse to hammer someone else's store.
- **Cached.** Fetched game details are cached in SQLite for a week
  (`cache_ttl_hours`), so re-runs don't re-fetch hundreds of unchanged pages.
- **Partial failure is survivable.** If Steam is down, the itch results still
  land. If both fail and nothing is collected, the sheet is left untouched
  rather than being written with an empty result.
- **Parsers degrade, they don't crash.** Steam and itch change their markup
  without warning; missing fields come through blank.
- **Cells are written raw.** Titles and blurbs come from the open internet, so
  everything is written with `RAW` rather than `USER_ENTERED` — a game called
  `=IMPORTXML(...)` lands as text, not as a live formula in your sheet.

State lives in `~/.local/state/weirdfinder/state.db`. Delete it to make
everything look new again (the sheet rows survive; `first_seen` resets).

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

89 tests, no network needed — the store parsers run against saved fixtures and
the sheet sync runs against a fake worksheet. The merge rules in particular
(never write a user column, never duplicate a row, don't rewrite a header) are
covered directly, since those are the ones that would quietly damage your data.

```
src/weirdfinder/
  cli.py        commands: init, check, run, explain
  config.py     TOML loading, defaults, validation
  scoring.py    the three axes and how they combine
  lexicon.py    the weighted phrase lists
  sources/      steam.py, itch.py — fetch and parse
  sheets.py     the merge rules
  state.py      first-seen tracking and the detail cache
  http.py       polite, retrying client
```

## Caveats

- Both sources are scraped from public pages. Neither offers a documented
  discovery API, so markup changes will eventually break a parser — the tests
  and fixtures are there to make that a five-minute fix.
- itch.io publishes no review counts, so obscurity there is an assumption
  (`unknown_obscurity`), not a measurement.
- The lexicon is a starting point tuned by hand, not a model. Expect to spend
  ten minutes with `weirdfinder explain` making it yours.
