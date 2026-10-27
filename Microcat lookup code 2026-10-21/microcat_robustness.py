# -*- coding: utf-8 -*-
r"""
====  IS THE MICROCAT LOOKUP ACTUALLY RELIABLE?  ====
Brendon, 29 Sep 2026: "make sure Microcat lookup now is robust and good to work
100% of the time."

You cannot fix what you have not measured, and "it worked when I tried it" is
what got a bumper BRACKET quoted as a clip. This runs the real lookup, on a real
VIN, many times, and writes down every failure with its mode - so the fixes can
be aimed at what actually breaks instead of what I imagine breaks.

KNOWN FAILURE MODES seen in the logs on 29 Sep 2026
    search-race     "search box did not take '75730' (got '') - retyping (1/3)"
    wrong-tab       mc.page still on the Infomedia login tab after open()
    browser-taken   another pass (or the PNC enrich task) holds the browser
    no-answer       the grid returns nothing for a term that does exist
    signed-out      the session expired

    python microcat_robustness.py            10 rounds, the standard set
    python microcat_robustness.py 25         25 rounds
"""
import collections
import json
import os
import re
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "microcat_robustness.log")

VIN = "JTHYBBAH002003206"
# every one of these was confirmed by Brendon on 29 Sep, so a miss is a real
# failure and not a bad test
CASES = [
    ("75072", "75072-76010", "MOULDING SUB-ASSY, FRONT DOOR, OUTSIDE LH"),
    ("67002", "67002-79115", "PANEL SUB-ASSY, FRONT DOOR, LH"),
    ("75754-76020", "75754-76020", "MOULDING, FRONT DOOR WINDOW FRAME, UPPER LH"),
    ("75720", "75720-76030", "MOULDING ASSY, FRONT DOOR BELT, LH"),
]


def classify(err, got, want):
    e = (err or "").lower()
    if "did not take" in e or "retyping" in e:
        return "search-race"
    if "login" in e or "sign" in e:
        return "signed-out"
    if "lock" in e or "another pass" in e or "browser" in e:
        return "browser-taken"
    if err:
        return "error:" + (err.split(":")[0][:22] or "?")
    if not got:
        return "no-answer"
    return "wrong-number"


def one(mc, term, want):
    """(ok, got, err). Reads the labelled Part Data block, never by proximity."""
    try:
        mc.find(term)
        mc.page.wait_for_timeout(1200)
        txt = mc.page.evaluate("() => document.body.innerText")
        L = [re.sub(r"\s+", " ", x).strip() for x in txt.splitlines()]
        L = [x for x in L if x]
        got = ""
        for i, x in enumerate(L):
            if x == "Number" and i + 1 < len(L):
                got = L[i + 1]
                break
        return (got.upper() == want.upper()), got, ""
    except Exception as e:
        return False, "", f"{type(e).__name__}: {str(e)[:90]}"


def _safe_close(mc):
    try:
        mc.close()
    except Exception:
        pass


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    sys.path.insert(0, HERE)
    import microcat_runner as mr
    modes = collections.Counter()
    ok = bad = 0
    started = time.time()
    lines = []
    # STAND DOWN FOR A PERSON.  29 Sep 2026.
    # This harness is the thing that took the browser off Brendon at 12:48 while
    # he was pressing Find numbers on a Prius - the exact crime I had fixed in
    # pnc_table an hour earlier, repeated in my own test. It checks before it
    # starts AND between rounds, because a run of 20 takes a long time and
    # somebody can arrive in the middle of it.
    if mr.a_human_is_waiting():
        print("STANDING DOWN - somebody is using the dashboard.")
        return 1
    mc = mr.Microcat().open()
    try:
        mc.vin(VIN)
        for r in range(1, rounds + 1):
            if mr.a_human_is_waiting():
                print(f"  stopping after round {r - 1} - somebody is using the dashboard")
                break
            for term, want, name in CASES:
                t0 = time.time()
                good, got, err = one(mc, term, want)
                dt = time.time() - t0
                if good:
                    ok += 1
                    lines.append(f"  round {r:>3} {term:<14} OK   {dt:5.1f}s  {got}")
                else:
                    bad += 1
                    m = classify(err, got, want)
                    modes[m] += 1
                    lines.append(f"  round {r:>3} {term:<14} FAIL {dt:5.1f}s  "
                                 f"wanted {want} got {got or '(nothing)'} [{m}] {err[:60]}")
                    print(lines[-1])
    except Exception:
        traceback.print_exc()
    finally:
        # CLOSE, BUT NEVER HANG HOLDING THE BROWSER.  29 Sep 2026.
        # The 5-round run printed its result and then stayed alive, still
        # holding the 'chrome_user_data' lock - so the next run was refused with
        # "Microcat is busy". Overnight that would have held the browser until
        # morning and blocked Brendon's first lookup of the day. close() is given
        # a short window on its own thread; if it does not come back, we let go
        # of the lock anyway and leave.
        import threading as _th
        t = _th.Thread(target=lambda: _safe_close(mc), daemon=True)
        t.start()
        t.join(20)
        if t.is_alive():
            print("  (close() did not return in 20s - releasing the lock and leaving)")
        try:
            mc._release_browser()
        except Exception:
            pass
    total = ok + bad
    pct = (100.0 * ok / total) if total else 0
    head = (f"\n{'='*66}\nMICROCAT LOOKUP: {ok}/{total} = {pct:.1f}%   "
            f"({rounds} rounds x {len(CASES)} parts, {time.time()-started:.0f}s)")
    print(head)
    if modes:
        print("failure modes:")
        for m, n in modes.most_common():
            print(f"   {n:>4}  {m}")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"\n\n==== {time.strftime('%Y-%m-%d %H:%M')} ====\n")
        f.write("\n".join(lines) + head + "\n")
        for m, n in modes.most_common():
            f.write(f"   {n:>4}  {m}\n")
    # os._exit, not return: playwright/CDP threads have kept this process alive
    # after main() finished. A test harness that will not die is a test harness
    # that holds the browser.
    sys.stdout.flush()
    os._exit(0 if pct == 100 else 1)


if __name__ == "__main__":
    sys.exit(main())
