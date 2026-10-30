# -*- coding: utf-8 -*-
r"""
THE REAL THING, READ-ONLY.  31 Oct 2026 (Morgan).

    set MICROCAT_LIVE=1
    python -m pytest tests\live -v

Uses microcat_robustness.py's VIN and four parts - every one confirmed by
Brendon on 29 Sep 2026, so a miss here is a real failure, not a bad test.
See conftest.py for what these will and will not touch.
"""
import os

import pytest

pytestmark = pytest.mark.live


@pytest.fixture(scope="session")
def known(mr_live):
    import microcat_robustness as rb
    return rb


@pytest.fixture(scope="session")
def on_vehicle(live_mc, known):
    """Open the test car once; the part tests search inside it."""
    live_mc.vin(known.VIN)
    return live_mc


# ---------------------------------------------------------------- the browser
def test_api_helper_profile_not_brendons(mr_live):
    sub = str(mr_live.api_helper_dir())
    assert sub, "API HELPER profile not found"
    assert os.path.basename(sub.rstrip("\\/")).lower() != "default", \
        "resolved to Default - Brendon's personal profile"


def test_attached_and_inside_the_epc(live_mc):
    assert live_mc.EPC_HINT in (live_mc.page.url or "")


def test_only_one_epc_tab(live_mc):
    # 26 Aug 2026: "you keep open more and more tabs"
    epc_tabs = [p for p in live_mc.ctx.pages if live_mc.EPC_HINT in (p.url or "")]
    assert len(epc_tabs) == 1


def test_queue_is_readable(mr_live):
    q = mr_live.pending()                  # reads requests\ and results\ only
    assert isinstance(q, list)
    for r in q[:5]:
        assert "_job" in r and "_age_h" in r


# ---------------------------------------------------------------- the lookup
def test_vin_opens_that_car_and_no_other(on_vehicle, mr_live, known):
    # the identifier must be in the title MICROCAT renders - the RAV4 lesson
    assert mr_live._norm(known.VIN) in mr_live._norm(on_vehicle.page.title())


def test_search_box_holds_exactly_what_was_typed(on_vehicle):
    on_vehicle._type("#globalSearchInput", "75072")
    assert on_vehicle.page.locator("#globalSearchInput").input_value() == "75072"


@pytest.mark.parametrize("case", range(4), ids=["75072", "67002", "75754-76020", "75720"])
def test_known_part_is_in_the_grid(on_vehicle, known, case):
    term, want, name = known.CASES[case]
    rows = on_vehicle.find(term)
    numbers = {r["number"] for r in rows}
    assert want in numbers, f"{name}: searched {term}, grid had {sorted(numbers)[:8]}"


def test_grid_is_harvested_past_the_first_screen(on_vehicle):
    # the grid is VIRTUAL - ~6 rows in the DOM at once. A section search must
    # come back with more than one screenful, or find() stopped scrolling.
    rows = on_vehicle.find("FRONT DOOR")
    assert len(rows) > 8, f"only {len(rows)} rows - did find() scroll the grid?"


def test_matcher_confirms_the_known_lh_moulding(on_vehicle, mr_live):
    rows = on_vehicle.find("75072")
    pick, cands, why = mr_live.best_match("Front door outside moulding LH", rows)
    assert pick and pick["number"] == "75072-76010", f"{why}; {cands}"


def test_matcher_will_not_give_the_lh_part_to_an_rh_line(on_vehicle, mr_live):
    rows = on_vehicle.find("75072")                    # LH moulding rows
    pick, _c, _w = mr_live.best_match("Front door outside moulding RH", rows)
    assert not pick or mr_live._row_side(pick["description"]) != "LH"


# ---------------------------------------------------------------- side scripts
def test_drawing_is_fetched(on_vehicle, known):
    """Saves the GIF into diagrams\\ - what microcat_diagram.py always does."""
    import microcat_diagram as dg
    r = dg.drawing_for(known.VIN, "75072", mc=on_vehicle)
    assert not r.get("error"), r.get("error")
    assert os.path.exists(r["png"])


def test_cart_only_reads(mr_live):
    import microcat_cart as cart
    r = cart.read()
    if r.get("error"):
        pytest.skip("browser is not on the Microcat Orders page: " + r["error"][:80])
    for p in r["parts"]:
        assert cart.NUM.match(p["number"].upper()) and p["qty"] >= 1


# ---------------------------------------------------------------- last: moves the tab
@pytest.mark.slow
def test_a_vin_microcat_lacks_is_vinnotfound(live_mc, mr_live, monkeypatch):
    """~1 minute: every spelling, then a full EPC re-entry. Run last - it leaves
    the EPC on a fresh tab. CarJam is not asked about a made-up VIN."""
    monkeypatch.setattr(mr_live, "_carjam_chassis", lambda v: "")
    with pytest.raises(mr_live.VinNotFound):
        live_mc.vin("JTZZZZZZZ00000000")
