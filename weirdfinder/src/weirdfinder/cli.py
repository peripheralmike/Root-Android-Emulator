"""Command line entry point.

    weirdfinder init      write a starter config
    weirdfinder check     validate config, credentials and connectivity
    weirdfinder run       fetch, score, sync to the sheet
    weirdfinder explain   score an ad-hoc title/description, for tuning
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__, config as config_module, scoring
from .config import Config, ConfigError
from .http import Client, FetchError
from .models import Game, Scored
from .sheets import SheetWriter, row_values
from .sources.itch import ItchSource
from .sources.steam import SteamSource
from .state import State, utcnow

log = logging.getLogger("weirdfinder")

EXAMPLE_CONFIG = Path(__file__).resolve().parent / "config.example.toml"


def setup_logging(verbose: bool, log_file: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def collect(cfg: Config, client: Client, state: State) -> list[Game]:
    """Run both sources. One source failing must not lose the other's results."""
    games: list[Game] = []
    for source in (
        SteamSource(client, cfg.steam, cache=state),
        ItchSource(client, cfg.itch, cache=state),
    ):
        try:
            games.extend(source.collect())
        except Exception:  # noqa: BLE001 - an unattended run keeps going
            log.exception("source %s failed entirely; continuing", source.name)
    return games


def cmd_init(args) -> int:
    """Write a starter config file next to the default config path."""
    target = Path(args.config).expanduser() if args.config else config_module.DEFAULT_CONFIG_PATH
    if target.exists() and not args.force:
        print(f"{target} already exists (use --force to overwrite)")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(EXAMPLE_CONFIG.read_text())
    print(f"wrote {target}")
    print("\nNext:")
    print("  1. Create a Google Cloud service account and download its JSON key.")
    print("  2. Save it as ~/.config/weirdfinder/service-account.json")
    print("  3. Share your spreadsheet with the service account's client_email.")
    print("  4. Put the spreadsheet id in sheet.spreadsheet_id.")
    print("  5. Run: weirdfinder check")
    return 0


def cmd_check(args) -> int:
    """Validate everything that could make an unattended run fail silently."""
    try:
        cfg = config_module.load(args.config)
    except ConfigError as exc:
        print(f"config: FAIL - {exc}")
        return 1
    print(f"config: ok ({args.config or config_module.DEFAULT_CONFIG_PATH})")

    problems = config_module.validate(cfg)
    for problem in problems:
        print(f"config: FAIL - {problem}")

    state = State(cfg.state_path, cfg.http.cache_ttl_hours)
    print(f"state:  ok ({cfg.state_path})")
    state.close()

    client = Client(
        cfg.http.user_agent, cfg.http.timeout, cfg.http.delay, retries=1
    )
    for label, url in (
        ("steam", "https://store.steampowered.com/api/appdetails?appids=620"),
        ("itch", "https://itch.io/games/newest"),
    ):
        try:
            client.get(url)
        except FetchError as exc:
            print(f"{label}:  FAIL - {exc}")
            problems.append(f"{label} unreachable")
        else:
            print(f"{label}:  reachable")

    if not problems:
        try:
            writer = SheetWriter.open(
                cfg.credentials_path, cfg.sheet.spreadsheet_id, cfg.sheet.worksheet
            )
            title = writer.worksheet.title
            print(f"sheet:  ok (tab {title!r})")
        except Exception as exc:  # noqa: BLE001 - report, do not traceback
            print(f"sheet:  FAIL - {exc}")
            problems.append("sheet unreachable")

    print("\nall good" if not problems else f"\n{len(problems)} problem(s)")
    return 0 if not problems else 1


def cmd_run(args) -> int:
    cfg = config_module.load(args.config)
    problems = config_module.validate(cfg) if not args.dry_run else []
    if problems:
        for problem in problems:
            log.error("config: %s", problem)
        return 1

    if args.min_score is not None:
        cfg.scoring.min_score = args.min_score

    state = State(cfg.state_path, cfg.http.cache_ttl_hours)
    client = Client(
        cfg.http.user_agent, cfg.http.timeout, cfg.http.delay, cfg.http.retries
    )

    games = collect(cfg, client, state)
    log.info("collected %d games", len(games))
    if not games:
        log.warning("nothing collected; leaving the sheet untouched")
        return 1

    scored = scoring.score_all(games, cfg.scoring, cfg.lexicon)
    keepers = [item for item in scored if item.total >= cfg.scoring.min_score]
    if args.limit:
        keepers = keepers[: args.limit]
    log.info(
        "%d of %d scored at or above %.1f",
        len(keepers),
        len(scored),
        cfg.scoring.min_score,
    )

    now = utcnow()
    rows = []
    new_count = 0
    for item in keepers:
        key = item.game.key
        if state.is_new(key):
            new_count += 1
        first_seen = state.record(key, item.game.title, item.total)
        rows.append(row_values(item, first_seen, now))

    if args.json:
        payload = [
            {
                "score": item.total,
                "obscurity": item.obscurity,
                "vibe": item.vibe,
                "experimental": item.experimental,
                "matched": item.matched,
                **item.game.__dict__,
            }
            for item in keepers
        ]
        Path(args.json).expanduser().write_text(json.dumps(payload, indent=2))
        log.info("wrote %s", args.json)

    if args.dry_run:
        print_table(keepers[:40])
        print(f"\n(dry run: {len(rows)} rows would be synced, {new_count} of them new)")
        state.close()
        return 0

    writer = SheetWriter.open(
        cfg.credentials_path, cfg.sheet.spreadsheet_id, cfg.sheet.worksheet
    )
    result = writer.sync(rows, sort_by_score=cfg.sheet.sort_by_score)
    log.info("sheet sync: %s (%d never seen before)", result, new_count)

    purged = state.purge_expired()
    if purged:
        log.debug("purged %d stale cache entries", purged)
    state.close()
    return 0


def print_table(items: list[Scored]) -> None:
    if not items:
        print("(nothing scored above the threshold)")
        return
    print(f"{'score':>5}  {'src':<5}  {'title':<44}  why")
    print("-" * 100)
    for item in items:
        title = item.game.title[:44]
        why = ", ".join(item.matched[:4])[:36]
        print(f"{item.total:>5.1f}  {item.game.source:<5}  {title:<44}  {why}")


def cmd_explain(args) -> int:
    """Score arbitrary text, so you can tune the lexicon without a full run."""
    try:
        cfg = config_module.load(args.config)
    except ConfigError:
        cfg = Config()  # tuning should work before the sheet is set up
    game = Game(
        source="manual",
        source_id="0",
        title=args.title,
        url="",
        description=args.description or "",
        tags=[tag.strip() for tag in (args.tags or "").split(",") if tag.strip()],
        popularity=args.reviews,
    )
    result = scoring.score(game, cfg.scoring, cfg.lexicon)
    print(f"total        {result.total:.1f} / 100")
    print(f"  obscurity  {result.obscurity:.3f} (weight {cfg.scoring.weight_obscurity})")
    print(f"  vibe       {result.vibe:.3f} (weight {cfg.scoring.weight_vibe})")
    print(f"  experiment {result.experimental:.3f} (weight {cfg.scoring.weight_experimental})")
    print(f"  matched    {', '.join(result.matched) or '(nothing)'}")
    print(f"  threshold  {cfg.scoring.min_score} -> "
          f"{'KEEP' if result.total >= cfg.scoring.min_score else 'drop'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="weirdfinder",
        description="Find weird, obscure games on Steam and itch.io.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("-c", "--config", help="path to config.toml")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--log-file", help="also append logs to this file")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="write a starter config file")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_check = sub.add_parser("check", help="validate config, auth and connectivity")
    p_check.set_defaults(func=cmd_check)

    p_run = sub.add_parser("run", help="fetch, score and sync to the sheet")
    p_run.add_argument("--dry-run", action="store_true", help="print instead of writing")
    p_run.add_argument("--limit", type=int, help="cap the number of rows synced")
    p_run.add_argument("--min-score", type=float, help="override scoring.min_score")
    p_run.add_argument("--json", help="also dump results to this JSON file")
    p_run.set_defaults(func=cmd_run)

    p_explain = sub.add_parser("explain", help="score ad-hoc text for lexicon tuning")
    p_explain.add_argument("title")
    p_explain.add_argument("-d", "--description")
    p_explain.add_argument("-t", "--tags", help="comma separated")
    p_explain.add_argument("-r", "--reviews", type=int, help="review count")
    p_explain.set_defaults(func=cmd_explain)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose, args.log_file)
    try:
        return args.func(args)
    except ConfigError as exc:
        log.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
