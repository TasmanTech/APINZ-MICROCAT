# -*- coding: utf-8 -*-
r"""
LIVE MICROCAT TESTS - ON BRENDON'S MACHINE ONLY, AND ONLY WHEN ASKED.
31 Oct 2026 (Morgan).

Skipped unless MICROCAT_LIVE=1. They use the real API HELPER browser and the
real Microcat session, so they are kept READ-ONLY:

  * never run() / work_job(): those write results\, and partfinder.validate()
    LEARNS every CONFIRMED row - a test must not teach the live system a number
  * never sign in by themselves: epc() would type the stored credentials, and a
    refusal is recorded against the account. Unless MICROCAT_LIVE_ALLOW_SIGNIN=1,
    sign_in() is disabled for the session and a signed-out window SKIPS the lot.
  * never call CarJam (someone else's website) - the chassis fallback is off
  * stand down for a person: skipped if the desk's human flag is up, before
    and between tests
  * the runner's log lines go to tests\live\last_live_run.log, not to
    partfinder\microcat_runner.log, so test traffic never reads as real passes

They hold the shared browser lock ("chrome_user_data") for the whole session,
so a scheduled pass that fires meanwhile waits and then stands down as busy -
exactly as it does behind any other pass. Keep the live run short.
"""
import os
import sys
import threading

import pytest

CODE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIVE = os.environ.get("MICROCAT_LIVE") == "1"
ALLOW_SIGNIN = os.environ.get("MICROCAT_LIVE_ALLOW_SIGNIN") == "1"
HERE = os.path.dirname(os.path.abspath(__file__))


def pytest_collection_modifyitems(config, items):
    if LIVE:
        return
    skip = pytest.mark.skip(reason="live Microcat test - set MICROCAT_LIVE=1 on the live machine")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def mr_live():
    """The REAL microcat_runner, with the real partfinder behind it."""
    if CODE not in sys.path:
        sys.path.insert(0, CODE)
    import partfinder
    if not getattr(partfinder, "__file__", None):
        pytest.exit("partfinder in sys.modules is a test stand-in - run the live "
                    "tests on their own: python -m pytest tests\\live")
    import microcat_runner as mr
    mr.LOG = os.path.join(HERE, "last_live_run.log")
    mr.log(f"==== live tests start (sign-in {'ALLOWED' if ALLOW_SIGNIN else 'disabled'})")
    return mr


@pytest.fixture(scope="session")
def live_mc(mr_live):
    """One attach to API HELPER for the whole session, released however it ends."""
    mr = mr_live
    if mr.a_human_is_waiting():
        pytest.skip("someone is using the desk - live tests stand down")
    mc = mr.Microcat()                    # resolves API HELPER by name - fails closed
    mc.open()                             # raises busy_message() if another pass has it
    if not ALLOW_SIGNIN:
        def _no_sign_in():
            mr.log("  [live tests] auto sign-in is disabled for tests")
            return False
        mc.sign_in = _no_sign_in
    try:
        mc.epc()
    except mr.SignedOut as e:
        _let_go(mr, mc)
        pytest.skip(f"API HELPER is not signed in to Microcat - sign in by hand "
                    f"(or set MICROCAT_LIVE_ALLOW_SIGNIN=1): {str(e)[:120]}")
    except Exception:
        _let_go(mr, mc)
        raise
    yield mc
    _let_go(mr, mc)
    mr.log("==== live tests end")


def _let_go(mr, mc):
    """close() on a thread, never hanging on to the browser (the robustness
    harness once held the lock all night). A person's human flag is put back
    if close() cleared it - it was theirs, not ours."""
    flag = None
    if os.path.exists(mr.HUMAN_FLAG):
        with open(mr.HUMAN_FLAG, encoding="utf-8") as f:
            flag = f.read()
    t = threading.Thread(target=mc.close, daemon=True)
    t.start()
    t.join(20)
    try:
        mc._release_browser()
    except Exception:
        pass
    if flag is not None and not os.path.exists(mr.HUMAN_FLAG):
        with open(mr.HUMAN_FLAG, "w", encoding="utf-8") as f:
            f.write(flag)


@pytest.fixture(autouse=True)
def _stand_down_for_a_person(request):
    if "live" in request.keywords and LIVE:
        mr = request.getfixturevalue("mr_live")
        if mr.a_human_is_waiting():
            pytest.skip("someone pressed a desk button - standing down")
