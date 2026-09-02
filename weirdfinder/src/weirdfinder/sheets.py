"""Google Sheets sync.

Rules this module exists to enforce:

  1. A game appears exactly once, keyed by "<source>:<id>". Re-runs update
     that row in place rather than appending a duplicate.
  2. Columns you own -- `status` and `notes` -- are never written by the tool.
     Mark something "played" or "nope" and it survives every future run.
  3. Columns you add yourself are left alone too, and a header row that has
     drifted gets the missing columns appended rather than rewritten.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .models import Scored

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Written by the tool on every run.
MANAGED_COLUMNS = [
    "key",
    "score",
    "obscurity",
    "vibe",
    "experimental",
    "source",
    "title",
    "url",
    "author",
    "price",
    "released",
    "reviews",
    "rating",
    "tags",
    "why",
    "description",
    "first_seen",
    "last_seen",
]

# Yours. Created with the sheet, then never touched again.
USER_COLUMNS = ["status", "notes"]

HEADER = MANAGED_COLUMNS + USER_COLUMNS
KEY_COLUMN = "key"


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    unchanged: int = 0

    def __str__(self) -> str:
        return (
            f"{self.added} added, {self.updated} updated, "
            f"{self.unchanged} unchanged"
        )


def row_values(scored: Scored, first_seen: str, last_seen: str) -> dict[str, object]:
    """Flatten a Scored into the managed cell values for its row."""
    game = scored.game
    return {
        "key": game.key,
        "score": scored.total,
        "obscurity": round(scored.obscurity, 3),
        "vibe": round(scored.vibe, 3),
        "experimental": round(scored.experimental, 3),
        "source": game.source,
        "title": game.title,
        "url": game.url,
        "author": game.author,
        "price": game.price,
        "released": game.released,
        "reviews": "" if game.popularity is None else game.popularity,
        "rating": "" if game.rating is None else game.rating,
        "tags": ", ".join(game.tags[:20]),
        "why": ", ".join(scored.matched[:8]),
        "description": (game.description or "")[:500],
        "first_seen": first_seen,
        "last_seen": last_seen,
    }


def contiguous_runs(indices: list[int]) -> list[tuple[int, int]]:
    """Group sorted column indices into (start, end) inclusive runs.

    Used so a row update becomes one range per run of managed columns rather
    than one range per cell -- and so user columns sitting between them are
    never included in a write.
    """
    runs: list[tuple[int, int]] = []
    for index in sorted(indices):
        if runs and index == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], index)
        else:
            runs.append((index, index))
    return runs


def _a1(row: int, col: int) -> str:
    """1-indexed row/col to A1. Sheets columns go A..Z, AA..AZ, ..."""
    letters = ""
    while col > 0:
        col, remainder = divmod(col - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return f"{letters}{row}"


def _same(existing: str, incoming: object) -> bool:
    """Compare a cell's current string against a value we are about to write."""
    if incoming is None:
        incoming = ""
    left = str(existing).strip()
    right = str(incoming).strip()
    if left == right:
        return True
    # Sheets rounds and reformats numbers on the way out; compare numerically
    # so an unchanged score does not look like a diff on every run.
    try:
        return abs(float(left) - float(right)) < 1e-9
    except (TypeError, ValueError):
        return False


def plan_sync(
    grid: list[list[str]],
    rows: list[dict[str, object]],
) -> tuple[list[str], list[dict], list[list[object]], SyncResult]:
    """Work out what to write. Pure function over the sheet's current values.

    Returns (header, cell updates, rows to append, counts). Kept free of any
    network calls so the merge rules can be tested exactly.
    """
    header = list(grid[0]) if grid else []
    if not header:
        header = list(HEADER)
        grid = [header]

    if KEY_COLUMN not in header:
        raise ValueError(
            f"worksheet has no '{KEY_COLUMN}' column; refusing to write into it. "
            "Point sheet.worksheet at an empty tab, or add the header row."
        )

    # Forward compatibility: a sheet written by an older version gets the new
    # columns appended instead of being rewritten.
    for column in HEADER:
        if column not in header:
            header.append(column)

    position = {name: index for index, name in enumerate(header)}
    key_index = position[KEY_COLUMN]

    existing: dict[str, int] = {}
    for offset, row in enumerate(grid[1:], start=2):
        if len(row) > key_index and row[key_index].strip():
            existing.setdefault(row[key_index].strip(), offset)

    updates: list[dict] = []
    appends: list[list[object]] = []
    result = SyncResult()

    for values in rows:
        key = str(values[KEY_COLUMN])
        row_number = existing.get(key)

        if row_number is None:
            appends.append([values.get(name, "") for name in header])
            result.added += 1
            continue

        current = grid[row_number - 1]
        changed = [
            position[name]
            for name in MANAGED_COLUMNS
            if name in position
            and not _same(
                current[position[name]] if len(current) > position[name] else "",
                values.get(name, ""),
            )
        ]
        if not changed:
            result.unchanged += 1
            continue

        for start, end in contiguous_runs(changed):
            updates.append(
                {
                    "range": f"{_a1(row_number, start + 1)}:{_a1(row_number, end + 1)}",
                    "values": [
                        [values.get(header[index], "") for index in range(start, end + 1)]
                    ],
                }
            )
        result.updated += 1

    return header, updates, appends, result


class SheetWriter:
    """Thin wrapper over a gspread worksheet, with the merge logic above."""

    def __init__(self, worksheet) -> None:
        self.worksheet = worksheet

    @classmethod
    def open(cls, credentials_path, spreadsheet_id: str, worksheet_name: str):
        """Authenticate and get (or create) the target tab."""
        import gspread  # imported lazily so parsing/scoring work without it

        client = gspread.service_account(filename=str(credentials_path), scopes=SCOPES)
        spreadsheet = client.open_by_key(spreadsheet_id)
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            log.info("creating worksheet %r", worksheet_name)
            worksheet = spreadsheet.add_worksheet(
                title=worksheet_name, rows=1000, cols=len(HEADER) + 4
            )
            worksheet.update(values=[HEADER], range_name="A1")
            worksheet.freeze(rows=1)
            worksheet.format(
                f"A1:{_a1(1, len(HEADER))}", {"textFormat": {"bold": True}}
            )
        return cls(worksheet)

    def sync(self, rows: list[dict[str, object]], sort_by_score: bool = False) -> SyncResult:
        """Apply the plan to the live sheet."""
        grid = self.worksheet.get_all_values()
        header, updates, appends, result = plan_sync(grid, rows)

        # Header may have grown (new columns, or a brand new empty sheet).
        if not grid or grid[0] != header:
            self.worksheet.update(values=[header], range_name="A1")

        # RAW on both paths, deliberately. Game titles and blurbs come from
        # the open internet, and USER_ENTERED would happily turn a title like
        # "=IMPORTXML(...)" into a live formula in your spreadsheet.
        if updates:
            self.worksheet.batch_update(updates, raw=True)
        if appends:
            self.worksheet.append_rows(appends, value_input_option="RAW")

        if sort_by_score and (updates or appends):
            score_column = header.index("score") + 1
            last_column = len(header)
            self.worksheet.sort(
                (score_column, "des"),
                range=f"A2:{_a1(self.worksheet.row_count, last_column)}",
            )

        return result
