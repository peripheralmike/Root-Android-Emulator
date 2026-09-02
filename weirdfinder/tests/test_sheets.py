import pytest
from conftest import *  # noqa: F401,F403 - puts src on sys.path

from weirdfinder import sheets
from weirdfinder.models import Game, Scored


def row(key, score=80.0, title="A Game", **overrides):
    values = {name: "" for name in sheets.MANAGED_COLUMNS}
    values.update({"key": key, "score": score, "title": title})
    values.update(overrides)
    return values


def test_a1_conversion_past_column_z():
    assert sheets._a1(1, 1) == "A1"
    assert sheets._a1(2, 26) == "Z2"
    assert sheets._a1(3, 27) == "AA3"
    assert sheets._a1(4, 52) == "AZ4"
    assert sheets._a1(5, 53) == "BA5"


def test_contiguous_runs_groups_neighbours():
    assert sheets.contiguous_runs([0, 1, 2, 5, 6, 9]) == [(0, 2), (5, 6), (9, 9)]
    assert sheets.contiguous_runs([]) == []
    assert sheets.contiguous_runs([3]) == [(3, 3)]


def test_contiguous_runs_sorts_first():
    assert sheets.contiguous_runs([2, 0, 1]) == [(0, 2)]


def test_empty_sheet_gets_the_full_header_and_an_append():
    header, updates, appends, result = sheets.plan_sync([], [row("steam:1")])
    assert header == sheets.HEADER
    assert updates == []
    assert len(appends) == 1
    assert result.added == 1


def test_existing_row_is_updated_not_duplicated():
    grid = [sheets.HEADER, [""] * len(sheets.HEADER)]
    grid[1][sheets.HEADER.index("key")] = "steam:1"
    grid[1][sheets.HEADER.index("score")] = "50"

    _, updates, appends, result = sheets.plan_sync(grid, [row("steam:1", score=91.0)])
    assert appends == []
    assert result.updated == 1 and result.added == 0
    assert updates, "a changed score should produce a write"


def test_user_columns_are_never_written():
    grid = [sheets.HEADER, [""] * len(sheets.HEADER)]
    grid[1][sheets.HEADER.index("key")] = "steam:1"
    grid[1][sheets.HEADER.index("status")] = "PLAYED"
    grid[1][sheets.HEADER.index("notes")] = "streamed 12 Aug, chat loved it"

    header, updates, _, _ = sheets.plan_sync(grid, [row("steam:1", score=99.0)])

    status_col = header.index("status") + 1
    notes_col = header.index("notes") + 1
    for update in updates:
        end_col = _column_number(update["range"].split(":")[1])
        assert end_col < status_col, f"{update['range']} reaches the status column"
        assert end_col < notes_col


def _column_number(a1_cell: str) -> int:
    letters = "".join(ch for ch in a1_cell if ch.isalpha())
    number = 0
    for ch in letters:
        number = number * 26 + (ord(ch) - ord("A") + 1)
    return number


def test_a_user_column_wedged_between_managed_ones_is_skipped():
    # Someone inserts their own column in the middle of the sheet.
    header = sheets.MANAGED_COLUMNS[:3] + ["my_column"] + sheets.MANAGED_COLUMNS[3:] + sheets.USER_COLUMNS
    grid = [header, [""] * len(header)]
    grid[1][header.index("key")] = "steam:1"
    grid[1][header.index("my_column")] = "do not touch"

    _, updates, _, _ = sheets.plan_sync(grid, [row("steam:1", score=77.0, title="New")])

    guarded = header.index("my_column") + 1
    for update in updates:
        start = _column_number(update["range"].split(":")[0])
        end = _column_number(update["range"].split(":")[1])
        assert not (start <= guarded <= end), f"{update['range']} spans my_column"


def test_unchanged_rows_produce_no_writes():
    values = row("steam:1", score=80.0, title="A Game")
    grid = [sheets.HEADER, [str(values.get(name, "")) for name in sheets.HEADER]]

    _, updates, appends, result = sheets.plan_sync(grid, [values])
    assert updates == [] and appends == []
    assert result.unchanged == 1


def test_numbers_compare_numerically_not_as_strings():
    # Sheets hands back "80" for a cell we wrote as 80.0.
    values = row("steam:1", score=80.0)
    grid = [sheets.HEADER, [str(values.get(name, "")) for name in sheets.HEADER]]
    grid[1][sheets.HEADER.index("score")] = "80"

    _, updates, _, result = sheets.plan_sync(grid, [values])
    assert updates == []
    assert result.unchanged == 1


def test_a_sheet_missing_new_columns_gets_them_appended():
    old_header = ["key", "score", "title", "status", "notes"]
    grid = [old_header, ["steam:1", "50", "A Game", "PLAYED", "note"]]

    header, _, _, _ = sheets.plan_sync(grid, [row("steam:1")])
    assert header[: len(old_header)] == old_header  # nothing reordered
    assert set(sheets.HEADER).issubset(header)
    assert header.index("status") < header.index("url")  # existing cols stay put


def test_a_sheet_without_a_key_column_is_refused():
    grid = [["title", "notes"], ["something", "mine"]]
    with pytest.raises(ValueError, match="key"):
        sheets.plan_sync(grid, [row("steam:1")])


def test_short_rows_from_sheets_do_not_crash_the_diff():
    # Sheets truncates trailing empty cells, so rows come back ragged.
    grid = [sheets.HEADER, ["steam:1"]]
    _, updates, appends, result = sheets.plan_sync(grid, [row("steam:1")])
    assert appends == []
    assert result.updated == 1


def test_duplicate_keys_already_in_the_sheet_target_the_first_row():
    grid = [sheets.HEADER, [""] * len(sheets.HEADER), [""] * len(sheets.HEADER)]
    grid[1][0] = grid[2][0] = "steam:1"

    _, updates, appends, _ = sheets.plan_sync(grid, [row("steam:1", score=42.0)])
    assert appends == []
    assert all(update["range"].split(":")[0].endswith("2") for update in updates)


def test_row_values_maps_a_scored_game():
    game = Game(
        source="itch",
        source_id="3344556",
        title="TAPE NINE",
        url="https://vhsghost.itch.io/tape-nine",
        description="Found footage.",
        tags=["Analog Horror", "liminal"],
        author="vhsghost",
        price="$2.00",
        popularity=None,
        rating=90.0,
    )
    scored = Scored(game=game, obscurity=0.75, vibe=0.9, experimental=0.2, total=84.1,
                    matched=["analog horror", "liminal"])
    values = sheets.row_values(scored, "2026-09-01 10:00:00", "2026-09-02 10:00:00")

    assert values["key"] == "itch:3344556"
    assert values["score"] == 84.1
    assert values["reviews"] == ""  # None becomes blank, not the string "None"
    assert values["rating"] == 90.0
    assert values["tags"] == "Analog Horror, liminal"
    assert values["why"] == "analog horror, liminal"
    assert values["first_seen"] == "2026-09-01 10:00:00"
    assert set(values) == set(sheets.MANAGED_COLUMNS)


def test_row_values_truncates_a_runaway_description():
    game = Game(source="itch", source_id="1", title="x", url="", description="y" * 5000)
    values = sheets.row_values(Scored(game=game), "", "")
    assert len(values["description"]) == 500


class FakeWorksheet:
    """Minimal stand-in for a gspread worksheet."""

    def __init__(self, grid):
        self.grid = grid
        self.batches = []
        self.appended = []
        self.header_writes = []
        self.row_count = 1000

    def get_all_values(self):
        return self.grid

    def batch_update(self, updates, raw=None):
        self.batches.extend(updates)
        self.batch_raw = raw

    def append_rows(self, rows, value_input_option=None):
        self.appended.extend(rows)
        self.append_option = value_input_option

    def update(self, values=None, range_name=None):
        self.header_writes.append((range_name, values))

    def sort(self, *args, **kwargs):
        self.sorted = (args, kwargs)


def test_sync_writes_the_header_only_when_it_changes():
    values = row("steam:1")
    grid = [sheets.HEADER, [str(values.get(name, "")) for name in sheets.HEADER]]
    worksheet = FakeWorksheet(grid)

    sheets.SheetWriter(worksheet).sync([values])
    assert worksheet.header_writes == []
    assert worksheet.batches == []
    assert worksheet.appended == []


def test_sync_appends_new_games_and_reports_counts():
    worksheet = FakeWorksheet([])
    result = sheets.SheetWriter(worksheet).sync([row("steam:1"), row("itch:2")])

    assert result.added == 2
    assert len(worksheet.appended) == 2
    assert worksheet.header_writes  # a fresh sheet gets its header
    assert str(result) == "2 added, 0 updated, 0 unchanged"


def test_sync_skips_sorting_when_nothing_changed():
    values = row("steam:1")
    grid = [sheets.HEADER, [str(values.get(name, "")) for name in sheets.HEADER]]
    worksheet = FakeWorksheet(grid)

    sheets.SheetWriter(worksheet).sync([values], sort_by_score=True)
    assert not hasattr(worksheet, "sorted")


def test_values_are_written_raw_so_titles_cannot_become_formulas():
    # A game really could be called "=IMPORTXML(...)"; USER_ENTERED would
    # evaluate it inside the user's spreadsheet.
    worksheet = FakeWorksheet([])
    sheets.SheetWriter(worksheet).sync([row("itch:1", title="=IMPORTXML(\"evil\",\"//a\")")])
    assert worksheet.append_option == "RAW"
    assert worksheet.appended[0][sheets.HEADER.index("title")].startswith("=IMPORTXML")


def test_updates_are_written_raw_too():
    grid = [sheets.HEADER, [""] * len(sheets.HEADER)]
    grid[1][sheets.HEADER.index("key")] = "steam:1"
    worksheet = FakeWorksheet(grid)
    sheets.SheetWriter(worksheet).sync([row("steam:1", title="=HYPERLINK(1)")])
    assert worksheet.batch_raw is True
