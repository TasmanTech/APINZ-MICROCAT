# -*- coding: utf-8 -*-
r"""
WHEN THE SESSION GOES, THE PASS STOPS AND SAYS WHY.  31 Oct 2026 (Morgan).

The rule: a lapsed Microcat session is NEVER an answer about a car. The pass
stops, leaves the unworked jobs in the queue with nothing written, alerts,
and writes no heartbeat. Before this was fixed, a lapse during a VIN search
was recorded as "Microcat has no vehicle" - four times (26 Aug, 1 Sep, 3 Sep,
28 Sep 2026), 5TDBZ3FH00S745311 with all 19 lines.

These run the REAL epc() / sign_in() / vin() / _search_identifier() / find()
/ work_job() / _run_locked() against a scripted browser (fakes.World).
"""
import fakes

V1, V2, V3 = "MR0KA3CC007860468", "5TDBZ3FH00S745311", "JTMBD31V905288807"
FOUND = [("CONFIRMED", "52159-0K900")]


def queue(env, *pairs):
    for rank, (job, vin) in enumerate(pairs):
        env.request(job, vin, age_rank=rank)
    return [job for job, _ in pairs]


def test_signed_in_throughout(env, mr):
    env.world = fakes.World(known={V1, V2})
    rc = mr.run(jobs=queue(env, ("J1", V1), ("J2", V2)))
    assert rc == 0
    assert env.results() == {"J1": FOUND, "J2": FOUND}
    assert env.beats == ["microcat"] and not env.alerts
    assert mr.LAST_STOP == ""


def test_a_vin_microcat_really_lacks_is_still_an_answer(env, mr):
    # VinNotFound is a real answer from the authority - it must keep being
    # recorded, or the job is retried every pass for ever
    env.world = fakes.World(known={V1})
    rc = mr.run(jobs=queue(env, ("J1", "JT000000000000000")))
    assert rc == 0
    assert env.results() == {"J1": [("NOT_FOUND", "")]}
    assert "no vehicle for JT000000000000000" in env.log()
    assert not env.alerts


def test_lapse_during_a_vin_search_is_not_no_vehicle(env, mr):
    """The 28 Sep 2026 case: job 1 done, the session lapses on job 2's search."""
    env.world = fakes.World(known={V1, V2, V3}, expire_on_search=2)
    rc = mr.run(jobs=queue(env, ("J1", V1), ("J2", V2), ("J3", V3)))
    res = env.results()
    assert res.get("J1") == FOUND                    # before the lapse: kept
    assert "J2" not in res, "a signed-out search was written as an answer"
    assert "J3" not in res, "the pass carried on after the session went"
    assert {r["_job"] for r in mr.pending()} == {"J2", "J3"}
    assert "no vehicle for" not in env.log()


def test_lapse_stops_loudly(env, mr):
    env.world = fakes.World(known={V1, V2, V3}, expire_on_search=2)
    rc = mr.run(jobs=queue(env, ("J1", V1), ("J2", V2), ("J3", V3)))
    log = env.log()
    assert rc == 2
    assert env.alerts, "nobody was told"
    assert not env.beats, "heartbeat told Stage 2 all was well"
    assert "SIGNED OUT PART-WAY THROUGH" in log
    assert "2 left in the queue untouched" in log and "J2, J3" in log
    assert "not signed in" in mr.LAST_STOP


def test_signed_out_before_the_pass(env, mr):
    env.world = fakes.World(signed_in=False, known={V1})
    rc = mr.run(jobs=queue(env, ("J1", V1), ("J2", V2)))
    assert rc == 2
    assert env.results() == {}
    assert env.alerts and not env.beats
    assert "CANNOT ENTER THE MICROCAT EPC" in env.log()
    assert "AUTO SIGN-IN SKIPPED" in env.log()       # and it says why


def test_signed_out_is_a_runtimeerror(mr):
    # every existing `except RuntimeError` caller still catches it
    assert issubclass(mr.SignedOut, RuntimeError)


def test_another_pass_holding_the_lock_is_not_a_fault(env, mr):
    env.world = fakes.World(known={V1})
    env.RunLock.force_busy = True
    rc = mr.run(jobs=queue(env, ("J1", V1)))
    assert rc == 0
    assert env.results() == {} and not env.alerts
    assert mr.LAST_STOP == ""                         # busy, not stopped
