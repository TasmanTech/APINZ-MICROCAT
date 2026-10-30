# -*- coding: utf-8 -*-
r"""
THE MATCHER'S HARD RULES, OFFLINE.  31 Oct 2026 (Morgan).

Each case here is a mistake that actually reached a quote, taken from the
dated comments in microcat_runner.py. The point is that none of them can come
back quietly: wrong side, wrong end, a suspension "bumper", a stabilizer
"bar", a coin-toss between two real parts.

trade_words / pnc_lookup / part_noun are blocked (see fakes.py), so this is
the matcher's own logic only - the same on this laptop and on the live machine.
"""
import pytest


def rows(*pairs):
    """[(number, description)] -> grid rows as find() returns them."""
    return [{"pnc": n[:5], "number": n, "description": d} for n, d in pairs]


# ---------------------------------------------------------------- side / end
@pytest.mark.parametrize("text, side", [
    ("L/H/F GUARD", "LH"),              # 22 Aug 2026: the slash form was dropped
    ("R/H Cowl panel extension", "RH"),
    ("Tailamp Bracket RH", "RH"),
    ("left front door", "LH"),
    ("Rear Bar Cover", ""),
])
def test_side_of_a_request(mr, text, side):
    assert mr._side(text) == side


@pytest.mark.parametrize("desc, side", [
    ("COVER, REAR BUMPER, RH", "RH"),
    ("MIRROR ASSY, OUTER REAR VIEW, LH", "LH"),
    ("BRACKET, RHD", ""),                # right-hand DRIVE is not right-hand side
])
def test_side_of_a_catalogue_row(mr, desc, side):
    assert mr._row_side(desc) == side


@pytest.mark.parametrize("text, end", [
    ("Rear Bar Cover", "REAR"),
    ("FR bumper retainer", "FRONT"),
    ("RR door", "REAR"),
    ("Bonnet", ""),
])
def test_end_of_a_request(mr, text, end):
    assert mr._end(text) == end


# ---------------------------------------------------------------- identifiers
def test_frame_number_spellings_compare_equal(mr):
    # PartsCheck sends "ZVW30-5752386", Microcat renders "ZVW30 5752386"
    assert mr._norm("ZVW30-5752386") == mr._norm("ZVW30 5752386")


def test_a_vin_has_one_spelling_a_frame_number_several(mr):
    assert mr._identifier_variants("JTHYBBAH002003206") == ["JTHYBBAH002003206"]
    v = mr._identifier_variants("ZVW30-5752386")
    assert v[0] == "ZVW30-5752386" and "ZVW30 5752386" in v and "ZVW305752386" in v


def test_colour_suffix_is_one_answer(mr):
    assert mr.base_number("52159-47050-J6") == mr.base_number("52159-47050-C0") == "52159-47050"


# ---------------------------------------------------------------- trade English
def test_search_phrase_speaks_toyota(mr):
    assert mr.search_phrase("Tailamp Bracket RH") == "REAR COMBINATION LAMP BRACKET RH"


def test_search_phrase_does_not_stutter(mr):
    # "REAR SPLASH SHIELD SHIELD" went to Microcat and into a note a person reads
    assert mr.search_phrase("Rear Splash Shield") == "REAR SPLASH SHIELD"


def test_translate_keeps_both_spellings(mr):
    t = mr.translate("Rear Bar Cover")
    assert "BAR" in t and "BUMPER" in t and "COVER" in t


# ---------------------------------------------------------------- best_match
def test_rear_cover_never_answered_with_the_front_one(mr):
    pick, _c, _w = mr.best_match("Rear Bar Cover", rows(
        ("52119-47340", "COVER, FRONT BUMPER"),
        ("52159-47340", "COVER, REAR BUMPER")))
    assert pick and pick["number"] == "52159-47340"


def test_front_hint_cannot_win_a_rear_request(mr):
    # 52119 (front) hinted off a mislabelled shelf row - the end rule must win
    pick, _c, _w = mr.best_match("Rear Bar Cover", rows(
        ("52119-47340", "COVER, FRONT BUMPER"),
        ("52159-47340", "COVER, REAR BUMPER")), hint_pncs=["52119"])
    assert pick and pick["number"] == "52159-47340"


def test_wrong_side_is_disqualified_not_scored_down(mr):
    pick, _c, why = mr.best_match("Door Mirror RH", rows(
        ("87940-0K010", "MIRROR ASSY, OUTER REAR VIEW, LH")))
    assert pick is None, why


def test_right_side_wins_when_both_are_there(mr):
    pick, _c, _w = mr.best_match("Door Mirror RH", rows(
        ("87940-0K010", "MIRROR ASSY, OUTER REAR VIEW, LH"),
        ("87910-0K010", "MIRROR ASSY, OUTER REAR VIEW, RH")))
    assert pick and pick["number"] == "87910-0K010"


def test_a_spring_bumper_is_not_a_bumper(mr):
    # job GLN1390, 24 Aug 2026: a rubber bump stop was priced, quoted and learned
    pick, _c, _w = mr.best_match("Front Bumper LH Retainer", rows(
        ("48331-21030", "BUMPER, FRONT SPRING, LH"),
        ("52116-47040", "RETAINER, FRONT BUMPER SIDE, LH")))
    assert pick and pick["number"] == "52116-47040"


def test_bar_is_never_the_stabilizer_bar(mr):
    # 48811-53092 came back CONFIRMED for a grille garnish
    pick, _c, _w = mr.best_match("Front Bar Grille Garnish RH", rows(
        ("48811-53092", "BAR, FRONT STABILIZER"),
        ("53121-53100", "MOULDING, RADIATOR GRILLE")))
    assert not pick or pick["number"] != "48811-53092"


def test_two_real_parts_tie_and_go_to_a_person(mr):
    # the RAV4 problem: two genuinely different numbers, same wording
    pick, cands, why = mr.best_match("Rear Bar Cover", rows(
        ("52159-42938", "COVER, REAR BUMPER"),
        ("52159-42939", "COVER, REAR BUMPER")))
    assert pick is None and "tie" in why and len(cands) == 2


def test_colour_variants_are_not_a_tie(mr):
    pick, _c, _w = mr.best_match("Rear Bar Cover", rows(
        ("52159-47050-J6", "COVER, REAR BUMPER"),
        ("52159-47050-C0", "COVER, REAR BUMPER")))
    assert pick and mr.base_number(pick["number"]) == "52159-47050"


def test_not_applicable_rows_are_not_parts(mr):
    pick, _c, why = mr.best_match("Rear Bar Cover", rows(
        ("00000-00000", "COVER, REAR BUMPER")))
    assert pick is None, why


def test_a_row_that_only_mentions_the_part_is_not_it(mr):
    # "COVER, OUTER MIRROR" mentions a mirror without being one
    pick, _c, why = mr.best_match("Door Mirror RH", rows(
        ("87945-0K010", "COVER, OUTER MIRROR, RH")))
    assert pick is None, why
