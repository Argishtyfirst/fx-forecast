"""Sentence splitter, sentence diff and rate parsing from statement text (FR-05, FR-06)."""

import pytest

from fxf.events.text import (
    parse_cba_rates,
    parse_ecb_rates,
    parse_fed_target_range,
    parse_fraction,
    sentence_diff,
    split_sentences,
    statement_diff,
)


def test_splitter_keeps_us_and_decimal_numbers_together():
    text = (
        "The U.S. economy expanded at a solid pace. The Committee decided to maintain the "
        "target range at 4-1/4 to 4.25 percent. Inflation, at 2.7 percent, remains elevated!"
    )
    assert split_sentences(text) == [
        "The U.S. economy expanded at a solid pace.",
        "The Committee decided to maintain the target range at 4-1/4 to 4.25 percent.",
        "Inflation, at 2.7 percent, remains elevated!",
    ]


def test_splitter_handles_abbreviations_initials_and_paragraphs():
    text = (
        "Voting for the action were Jerome H. Powell, Chair; and Mr. Williams, e.g. as "
        "required.\nThe CBA Board Resolution No. 197A was adopted at 2 p.m. on Tuesday. "
        "Rates rose 0.25 pp to 6.75%. The next meeting is in Nov. 2026."
    )
    assert split_sentences(text) == [
        "Voting for the action were Jerome H. Powell, Chair; and Mr. Williams, e.g. as required.",
        "The CBA Board Resolution No. 197A was adopted at 2 p.m. on Tuesday.",
        "Rates rose 0.25 pp to 6.75%.",
        "The next meeting is in Nov. 2026.",
    ]


def test_splitter_handles_quotes_and_empty_text():
    assert split_sentences("") == []
    assert split_sentences('He said "prices will fall." Then he left.') == [
        'He said "prices will fall."',
        "Then he left.",
    ]


def test_sentence_diff_reports_added_and_removed_in_text_order():
    prev = "Inflation remains elevated. The Committee is attentive to risks. Growth is solid."
    cur = "Inflation has eased somewhat. The Committee is  attentive to risks. Growth is solid."
    added, removed = sentence_diff(prev, cur)
    assert added == ["Inflation has eased somewhat."]
    assert removed == ["Inflation remains elevated."]
    d = statement_diff(prev, cur, previous_event_id=7)
    assert d == {"added": added, "removed": removed, "previous_event_id": 7}


def test_sentence_diff_without_previous_statement_marks_all_added():
    added, removed = sentence_diff(None, "One. Two.")
    assert added == ["One.", "Two."] and removed == []


@pytest.mark.parametrize(
    ("raw", "value"), [("3-3/4", 3.75), ("1/4", 0.25), ("4", 4.0), ("0", 0.0), ("5-1/2", 5.5)]
)
def test_parse_fraction(raw, value):
    assert parse_fraction(raw) == value


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "The Committee decided to raise the target range for the federal funds rate by "
            "1/4 percentage point to 3-3/4 to 4 percent, in support of",
            (3.75, 4.0),
        ),
        (
            "the Committee decided to maintain the target range for the federal funds rate at "
            "0 to 1/4 percent.",
            (0.0, 0.25),
        ),
        (
            "decided today to establish a target range for the federal funds rate of 0 to 1/4 percent.",
            (0.0, 0.25),
        ),
        (
            "decided to lower the target range for the federal funds rate by 1/2 percentage "
            "point to 4-3/4 to 5 percent.",
            (4.75, 5.0),
        ),
        (
            "The Federal Open Market Committee decided today to lower its target for the federal "
            "funds rate 75 basis points to 1-1/2 percent.",
            (1.5, 1.5),
        ),
        ("No rate in this text.", None),
    ],
)
def test_parse_fed_target_range(text, expected):
    assert parse_fed_target_range(text) == expected


def test_parse_ecb_rates_respectively_form_any_order():
    t = (
        "Accordingly, the interest rates on the deposit facility, the main refinancing "
        "operations and the marginal lending facility will be increased to 2.50%, 2.65% and "
        "2.90% respectively, with effect from 16 September 2026."
    )
    assert parse_ecb_rates(t) == {"deposit": 2.5, "mro": 2.65, "mlf": 2.9}
    t2 = (
        "At today's meeting the Governing Council of the ECB decided that the interest rate on "
        "the main refinancing operations and the interest rates on the marginal lending "
        "facility and the deposit facility will remain unchanged at 0.00%, 0.25% and -0.40% "
        "respectively."
    )
    assert parse_ecb_rates(t2) == {"mro": 0.0, "mlf": 0.25, "deposit": -0.4}


def test_parse_ecb_rates_single_deposit_sentence():
    t = "The interest rate on the deposit facility will be decreased by 10 basis points to -0.50%."
    assert parse_ecb_rates(t) == {"deposit": -0.5}
    assert parse_ecb_rates("Nothing here.") == {}


def test_parse_cba_rates_new_and_old_wording():
    new = (
        "At its September 15, 2026 meeting, the Board of the Central Bank of Armenia decided "
        "to: Raise the Policy Rate by 25 basis points, setting it at 6.75% Set the Lombard Repo "
        "Facility Rate at 8.25%. Set the Deposit Facility Rate at 5.25%."
    )
    assert parse_cba_rates(new) == {"refinancing": 6.75, "lombard": 8.25, "deposit": 5.25}
    old = (
        "In the February 10 2009 meeting the Board of CBA lowered the Refinancing Rate of CBA "
        "by 0.25 percentage points to 6.75 percent."
    )
    assert parse_cba_rates(old) == {"refinancing": 6.75}
    assert parse_cba_rates("The Board of the CBA lowered the refinancing rate by 0.25%") == {}
    hold = "the Board decided to leave the refinancing rate unchanged at 6.75 %."
    assert parse_cba_rates(hold) == {"refinancing": 6.75}
