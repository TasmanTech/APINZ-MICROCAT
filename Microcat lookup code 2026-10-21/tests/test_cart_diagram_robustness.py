# -*- coding: utf-8 -*-
r"""
THE SIDE SCRIPTS, OFFLINE.  31 Oct 2026 (Morgan).

microcat_cart.py   reads the Orders page - and must NEVER place an order
microcat_diagram.py only trusts an illustration off Microcat's own CDN
microcat_robustness.py names its failures correctly
"""
import importlib
import os
import re
import sys
import types

import pytest

import fakes


@pytest.fixture
def cart(monkeypatch):
    monkeypatch.setitem(sys.modules, "websocket", types.ModuleType("websocket"))
    monkeypatch.syspath_prepend(fakes.CODE)
    return fakes.fresh_import(monkeypatch, "microcat_cart")


@pytest.fixture
def plain(monkeypatch):
    """Import one of the dependency-free scripts fresh."""
    monkeypatch.syspath_prepend(fakes.CODE)
    return lambda name: fakes.fresh_import(monkeypatch, name)


# ---------------------------------------------------------------- the cart
ORDER_PAGE = """Orders
HILUX (2024 - ) | MR0KA3CC007860468
Description
Number
Qty
CLIP
90467-07215
4
COVER, REAR BUMPER
52159-0K900-C0
1
CLIP
90467-07215
1
PLACE ORDER
"""


def test_cart_reads_every_part_and_quantity(cart):
    r = cart.parse(ORDER_PAGE)
    assert r["vin"] == "MR0KA3CC007860468"
    got = {p["number"]: p["qty"] for p in r["parts"]}
    # the same clip on two drawings is ONE line - the car takes five, not "4 or 1"
    assert got == {"90467-07215": 5, "52159-0K900-C0": 1}


def test_cart_column_heading_is_not_a_part(cart):
    # "DESCRIPTION" fits [0-9A-Z]{5}-?[0-9A-Z]{5,6} - a PNC is five DIGITS
    assert not cart.NUM.match("DESCRIPTION")
    assert cart.NUM.match("90467-07215")


def test_cart_kit_text(cart):
    assert cart.kit_text([{"number": "90467-07215", "qty": 5}]) == "90467-07215*5"


def test_cart_never_clicks_anything():
    """IT READS. IT NEVER ORDERS. Placing an order spends Brendon's money."""
    src = open(os.path.join(fakes.CODE, "microcat_cart.py"), encoding="utf-8").read()
    code = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    for forbidden in (".click(", "dispatchEvent", "Input.dispatchMouseEvent",
                      "keyboard", ".submit("):
        assert forbidden not in code, f"microcat_cart.py now contains {forbidden!r}"


# ---------------------------------------------------------------- the drawing
def test_diagram_trusts_only_the_microcat_cdn(plain):
    d = plain("microcat_diagram")
    good = "https://cdn.superservice.com/content/live/images/toyota/123.gif"
    assert d.CDN.match(good)
    assert not d.CDN.match("https://evil.example.com/content/live/images/x.gif")


# ---------------------------------------------------------------- robustness
@pytest.mark.parametrize("err, got, mode", [
    ("search box did not take '75730' (got '') - retyping (1/3)", "", "search-race"),
    # epc()'s SignedOut wording, in full
    ("the API HELPER window is not signed in to Microcat and the automatic "
     "sign-in did not work - the log line above says why. Put MICROCAT_USERNAME "
     "and MICROCAT_PASSWORD in .env, or sign in on that window once.",
     "", "signed-out"),
    # busy_message()'s own wording, as open() raises it
    ("Microcat is busy with another lookup. It does ONE job at a time - one "
     "browser, one signed-in seat. Give it a minute and press the button again.",
     "", "browser-taken"),
    ("", "", "no-answer"),
    ("", "75072-76011", "wrong-number"),
])
def test_robustness_names_the_failure(plain, err, got, mode):
    assert plain("microcat_robustness").classify(err, got, "75072-76010") == mode


def test_robustness_cases_are_the_known_good_ones(plain):
    r = plain("microcat_robustness")
    assert len(r.CASES) == 4
    for term, want, _name in r.CASES:
        assert re.fullmatch(r"\d{5}-\d{5}", want)
