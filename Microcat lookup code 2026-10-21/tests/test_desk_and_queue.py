# -*- coding: utf-8 -*-
r"""
THE DESK BUTTON AND THE QUEUE CONTRACT.  31 Oct 2026 (Morgan).

What a person at the desk is told, and what lands on a job line:
  CONFIRMED fills the number in; PROPOSED never does; NOT_FOUND says so;
  "not searched" is NEVER reported as NOT_FOUND.
Plus each bug fixed on 31 Oct, so it cannot come back quietly.
"""
import json
import sys
import types

import fakes

V1 = "MR0KA3CC007860468"


def job(**over):
    j = {"vin": V1, "make": "TOYOTA", "car": "HILUX",
         "lines": [{"n": 1, "description": "Rear Bumper Cover", "qty": 1}]}
    j.update(over)
    return j


# ---------------------------------------------------------------- desk_finder
def test_desk_confirmed_number_is_filled_in(env, monkeypatch):
    env.world = fakes.World(known={V1})
    df, saved = env.desk(monkeypatch, job())
    out = df.find_numbers("41000", force_microcat=True)
    assert out["confirmed"] == 1 and not out.get("error")
    assert saved["job"]["lines"][0]["pn"] == "52159-0K900"


def test_desk_no_vin_searches_nothing(env, monkeypatch):
    df, _ = env.desk(monkeypatch, job(vin=""))
    out = df.find_numbers("41000", force_microcat=True)
    assert "No VIN" in out["error"] and not env.submitted


def test_desk_other_makes_are_not_asked(env, monkeypatch):
    # job 41604, 23 Sep 2026: a Range Rover came back "40 not found"
    df, _ = env.desk(monkeypatch, job(make="LAND ROVER"))
    out = df.find_numbers("41000", force_microcat=True)
    assert out["asked"] == 0 and "PartsLink24" in out["error"]
    assert not env.submitted


def test_desk_lexus_goes_through_as_lexus(env, monkeypatch):
    env.world = fakes.World(known={V1})
    df, _ = env.desk(monkeypatch, job(make="LEXUS"))
    df.find_numbers("41000", force_microcat=True)
    assert env.submitted[0]["make"] == "LEXUS"


def test_desk_blank_make_is_not_labelled_toyota(env, monkeypatch):
    # 31 Oct 2026 fix: `make or "TOYOTA"` handed an unknown car over as TOYOTA
    env.world = fakes.World(known={V1})
    df, _ = env.desk(monkeypatch, job(make=""))
    df.find_numbers("41000", force_microcat=True)
    assert env.submitted[0]["make"] == ""


def test_desk_busy_is_unanswered_not_not_found(env, monkeypatch):
    # 23 Sep 2026: two clicks 2 s apart - the second was counted NOT_FOUND
    env.world = fakes.World(known={V1})
    env.RunLock.force_busy = True
    df, saved = env.desk(monkeypatch, job())
    out = df.find_numbers("41000", force_microcat=True)
    assert out["unanswered"] == 1 and not out.get("not_found")
    assert "ONE job at a time" in out["error"]
    assert "NOT looked at this line" in saved["job"]["lines"][0]["notes"]["finder"]


def test_desk_signed_out_says_signed_out(env, monkeypatch):
    # 31 Oct 2026 fix: this used to say "busy, press the button again"
    env.world = fakes.World(signed_in=False, known={V1})
    df, saved = env.desk(monkeypatch, job())
    out = df.find_numbers("41000", force_microcat=True)
    assert out["unanswered"] == 1 and not out.get("not_found")
    assert "not signed in" in out["error"]
    assert "press the button again" not in out["error"]


def test_desk_human_flag_is_cleared_after(env, monkeypatch):
    import os
    env.world = fakes.World(known={V1})
    df, _ = env.desk(monkeypatch, job())
    df.find_numbers("41000", force_microcat=True)
    assert not os.path.exists(env.mr.HUMAN_FLAG)


def test_body_type_lookup_is_switched_off(env, monkeypatch):
    # 31 Oct 2026: commented out - only the VIN path runs
    df, _ = env.desk(monkeypatch, job())
    assert not hasattr(df, "find_numbers_by_body")
    assert not hasattr(env.mr, "run_by_body")


# ---------------------------------------------------------------- work_job
def install_part_noun(monkeypatch, not_understood=()):
    """part_noun as the live one behaves for these lines: every kind is fine,
    and the wordings listed are 'not understood' (-> PROPOSED)."""
    pn = types.ModuleType("part_noun")
    pn.same_kind = lambda desc, row_desc: ""
    pn.comprehended = lambda desc: desc not in not_understood
    monkeypatch.setitem(sys.modules, "part_noun", pn)


def test_proposed_number_still_counts_as_a_duplicate(env, monkeypatch):
    """31 Oct 2026 fix. Hilux PDPQ-12816-PE, 20 Oct: the fan line was PROPOSED
    53112-0K350 and "Radiator" was then CONFIRMED the same number."""
    install_part_noun(monkeypatch, not_understood={"Radiator fan complete with shroud"})
    env.world = fakes.World(known={V1}, rows=[
        fakes.row("16400", "16400-0L999", "RADIATOR ASSY")])
    lines = [{"line": "1", "description": "Radiator fan complete with shroud", "qty": 1},
             {"line": "2", "description": "Radiator", "qty": 1}]
    env.request("J1", V1, lines)
    env.mr.run(jobs=["J1"])
    got = env.results()["J1"]
    assert ("CONFIRMED", "16400-0L999") not in got, got
    assert got == [("NOT_FOUND", ""), ("NOT_FOUND", "")]


def test_one_number_never_answers_two_lines(env, monkeypatch):
    env.world = fakes.World(known={V1})            # every search returns the cover
    lines = [{"line": "1", "description": "Rear Bumper Cover", "qty": 1},
             {"line": "2", "description": "Rear Bar Cover", "qty": 1}]
    env.request("J1", V1, lines)
    env.mr.run(jobs=["J1"])
    assert all(c == "NOT_FOUND" for c, _n in env.results()["J1"])


def test_a_vin_that_is_not_a_vin_is_not_searched(env):
    env.request("J1", "W")                          # NZJ0140329Q2, 26 Aug 2026
    env.mr.run(jobs=["J1"])
    assert env.world.searches == 0
    assert env.results() == {"J1": [("NOT_FOUND", "")]}


def test_other_makes_are_routed_off_the_queue(env):
    env.request("J1", V1, make="VOLKSWAGEN")
    env.mr.run(jobs=["J1"])
    assert env.results() == {}                      # routing is not an answer
    assert (env.req / "J1.routed.json").exists()


# ---------------------------------------------------------------- the busy note
def test_busy_note_names_the_job_and_its_lines(env, monkeypatch):
    # 31 Oct 2026 fix: it held the whole request dict, and the JOB count as lines
    seen = {}

    def peek(q, limit):
        seen.update(json.load(open(env.mr.BUSY_FILE, encoding="utf-8")))
        return 0
    monkeypatch.setattr(env.mr, "_run_locked", peek)
    env.request("J1", V1, [{"line": str(i), "description": "x", "qty": 1} for i in range(3)])
    env.request("J2", V1, age_rank=1)
    env.mr.run(jobs=["J1", "J2"])
    assert seen["job"] == "J1" and seen["lines"] == 3
    msg_job = seen["job"]
    assert "{" not in msg_job


def test_busy_file_is_cleared_after_the_pass(env):
    import os
    env.world = fakes.World(known={V1})
    env.request("J1", V1)
    env.mr.run(jobs=["J1"])
    assert not os.path.exists(env.mr.BUSY_FILE)


def test_missing_chrome_session_says_so(env, monkeypatch):
    # 31 Oct 2026 fix: used to die as "'NoneType' object has no attribute '_park'"
    mc = env.opened()
    monkeypatch.setattr(env.mr, "chrome_session", None)
    try:
        mc.epc()
    except RuntimeError as e:
        assert "chrome_session" in str(e)
    else:
        raise AssertionError("epc() carried on without chrome_session")
