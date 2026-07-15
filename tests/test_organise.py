from __future__ import annotations

import datetime
from pathlib import PurePosixPath

from negative_space.organise import PlanItem, capture_folder, plan_moves

_UTC = datetime.UTC


def test_capture_folder() -> None:
    assert capture_folder(datetime.datetime(2019, 9, 27, tzinfo=_UTC)) == PurePosixPath(
        "2019", "09 - September"
    )
    assert capture_folder(datetime.datetime(2020, 1, 5, tzinfo=_UTC)) == PurePosixPath(
        "2020", "01 - January"
    )
    assert capture_folder(datetime.datetime(2021, 12, 31, tzinfo=_UTC)) == PurePosixPath(
        "2021", "12 - December"
    )


def test_plan_moves_dated_file_lowercases_extension() -> None:
    when = datetime.datetime(2019, 9, 27, 11, 47, 23, tzinfo=_UTC)
    item = PlanItem("src/a.JPG", when, ".JPG", "a.JPG")

    moves = plan_moves([item])

    assert moves == {
        "src/a.JPG": PurePosixPath("2019", "09 - September", "2019-09-27 11-47-23.jpg")
    }


def test_plan_moves_dedupes_same_second() -> None:
    when = datetime.datetime(2019, 9, 27, 11, 47, 23, tzinfo=_UTC)
    items = [
        PlanItem("z", when, ".jpg", "z.jpg"),
        PlanItem("a", when, ".jpg", "a.jpg"),
    ]

    moves = plan_moves(items)

    folder = PurePosixPath("2019", "09 - September")
    assert moves["a"] == folder / "2019-09-27 11-47-23.jpg"  # first by (time, key)
    assert moves["z"] == folder / "2019-09-27 11-47-23 (2).jpg"


def test_plan_moves_undated_to_unsorted() -> None:
    item = PlanItem("src/latest.png", None, ".png", "latest.png")

    moves = plan_moves([item])

    assert moves == {"src/latest.png": PurePosixPath("unsorted", "latest.png")}


def test_plan_moves_dedupes_unsorted_names() -> None:
    items = [
        PlanItem("b", None, ".jpg", "temp.jpg"),
        PlanItem("a", None, ".jpg", "temp.jpg"),
    ]

    moves = plan_moves(items)

    assert moves["a"] == PurePosixPath("unsorted", "temp.jpg")  # first by (name, key)
    assert moves["b"] == PurePosixPath("unsorted", "temp (2).jpg")


def test_plan_moves_is_order_independent() -> None:
    when = datetime.datetime(2019, 1, 1, tzinfo=_UTC)
    first = PlanItem("a", when, ".jpg", "a.jpg")
    second = PlanItem("b", when, ".jpg", "b.jpg")

    assert plan_moves([first, second]) == plan_moves([second, first])
