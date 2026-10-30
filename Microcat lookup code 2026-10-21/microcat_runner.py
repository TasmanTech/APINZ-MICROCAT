# -*- coding: utf-8 -*-
r"""
MICROCAT RUNNER - the thing that finally EMPTIES the PartFinder queue.
(Built 19 Aug 2026, after Brendon: "make sure and put in the microcat part as the
automation never miss it".)

WHY THIS EXISTS
---------------
Microcat has been the designed authority since 6 Aug and has never once answered
by itself. Stage 2 files a request, logs "queued for Microcat", and falls through
to PartSouq. Checked tonight:

    partfinder\requests   156 jobs
    partfinder\results      8 jobs      <- newest 11 Aug, EIGHT DAYS OLD
    pending               148 jobs      <- oldest 6 Aug 23:45

Nothing on this machine ever wrote to results\ except a person driving Claude in
Chrome by hand. So step 2 (learned) has 36 mappings to draw on, step 3 (Microcat)
is a no-op, and PartSouq - designed as the LAST resort - became the primary source
by default. That is why NZJ0140246Q1 came out "numbered 1, need a human 5" this
morning: the two steps above PartSouq were dark.

This module is the missing half. It drives Microcat itself, on a schedule, and
writes results\<job>.json in exactly the shape partfinder.validate() already
expects - so every guarantee (rows-out = rows-in, one retry, confidence stamping,
no invented numbers, learned mappings) still applies untouched. Nothing about the
contract changes; the queue just stops being a graveyard.

API HELPER, ENFORCED IN CODE - NOT BY JUDGEMENT
-----------------------------------------------
Brendon, 11 Aug: "make sure you check api helper as other days you were on my web
page brendon stirling logged in". Twice the agent attached to his PERSONAL Chrome
- the one with ASB and BNZ open.

So the profile is NOT a constant here and NOT a number. api_helper_dir() reads
Chrome's own Local State and finds the profile whose display name is "API HELPER"
(currently "Profile 9", but it is looked up by name every run, so it survives
Chrome renumbering profiles). If that profile does not exist, this REFUSES TO
LAUNCH. Fail closed: unknown means no. It can never land on "Default", which is
Person 1 / brendon@apinz.com.

    NOTE for whoever reads this next: partsouq_client.py still launches on
    "Default" - Brendon's personal profile. That predates the guard and should be
    moved onto API HELPER too. Flagged, not silently changed.

TOYOTA AND LEXUS ONLY - the same hard rule as everywhere else. A request for any
other make is left in the queue untouched (partslink24 requests are not ours).

    python microcat_runner.py --check              # is API HELPER signed in?
    python microcat_runner.py --explore <VIN>      # dump the page, pin selectors
    python microcat_runner.py --status             # queue at a glance
    python microcat_runner.py --run                # work the queue (live jobs)
    python microcat_runner.py --run --all          # include expired/backlog
    python microcat_runner.py --run --job NZJ0140246Q1
"""
import argparse
import datetime
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import partfinder                                       # noqa: E402

try:
    import browser_guard
except Exception:                                       # never fatal
    browser_guard = None

import runlock                                          # noqa: E402

# chrome_session MUST be a MODULE-level name (21 Sep 2026).
# epc() calls chrome_session._park() in two places, but the only import was a LOCAL
# one inside open(). So the moment the EPC tab was not already open and epc() had
# to open it from the landing page, the pass died with
#     "CANNOT ENTER THE MICROCAT EPC: name 'chrome_session' is not defined"
# - which reads like a sign-in problem and is nothing of the kind. It stayed hidden
# because most passes find the EPC tab already open and never reach those lines.
try:
    import chrome_session                               # noqa: E402
except Exception:                                       # open() reports it properly
    chrome_session = None

try:
    import attempt_log                                  # noqa: E402
except Exception:                                       # never fatal
    attempt_log = None

CHROME_ROOT = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
PROFILE_NAME = "API HELPER"
BASE = "https://microcat-apac.superservice.com"
CAPTURES = os.path.join(HERE, "partfinder_captures")
LOG = os.path.join(HERE, "partfinder", "microcat_runner.log")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

# A PNC is the 5-digit factory group ("52119"). Microcat searches it directly and
# it is a far better key than English, so it is tried FIRST when Stage 1 found one.
PNC_RX = re.compile(r"\b(\d{5}[A-Z]?)\b")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(msg):
    line = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S ") + str(msg)
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------ the profile
def api_helper_dir():
    """The Chrome profile sub-directory whose DISPLAY NAME is 'API HELPER'.

    THE resolver lives in browser_guard - one answer to "which profile?" for the
    whole system (Microcat here, PartSouq in partsouq_client). Looked up by name
    from Chrome's own Local State on every run: never a hard-coded "Profile 9",
    never a number the operator typed. That is what put the agent on Brendon's
    banking profile twice. Raises if API HELPER is not there - fail closed.
    """
    if browser_guard is None:
        raise RuntimeError("browser_guard unavailable - REFUSING to pick a Chrome "
                           "profile unguarded")
    # 20 Aug 2026: API HELPER is its own Chrome now, not a profile in Brendon's.
    # See chrome_session for why - the short version is that a profile inside his
    # user-data-dir could never get a debug port without closing his whole
    # browser, so it never once ran unattended.
    return browser_guard.api_helper_user_data_dir()


# ------------------------------------------------------------------ the browser
# A PERSON IS WAITING AT THE SCREEN.  29 Sep 2026.
# Written by open(human=True) - i.e. the dashboard's Find numbers button - and
# removed when that pass lets the browser go. Background work checks it with
# a_human_is_waiting() and stands down, because Brendon at a screen beats a
# scheduled task every single time.
HUMAN_FLAG = os.path.join(HERE, "human_wants_browser.flag")


def a_human_is_waiting(max_age_seconds=300):
    """True while someone is using the browser from the dashboard."""
    try:
        import time as _t
        if not os.path.exists(HUMAN_FLAG):
            return False
        if _t.time() - os.path.getmtime(HUMAN_FLAG) > max_age_seconds:
            os.remove(HUMAN_FLAG)       # stale - the pass died without clearing
            return False
        return True
    except Exception:
        return False


# WHAT IS IT BUSY WITH?  29 Sep 2026.
# Brendon: "make it so it does one at a time - if it busy send message back say
# looking up another job so be patient."
#
# Microcat is ONE browser with ONE signed-in seat, so two lookups at once is not
# a thing that can work. It already queued; what it did not do was SAY what it
# was queued behind. "another pass is using the API HELPER browser (the Euro
# chain, or PartSouq)" was both frightening and wrong - the holder was a test of
# mine. A person who is told "looking up job 32764, about 40 seconds in" waits.
# A person told something they cannot act on presses the button again, which
# makes it worse.
BUSY_FILE = os.path.join(HERE, "microcat_busy.json")


def busy_with(job=None, lines=None, clear=False):
    """Record, or clear, what the browser is working on right now."""
    import json as _j
    import time as _t
    try:
        if clear:
            if os.path.exists(BUSY_FILE):
                os.remove(BUSY_FILE)
            return
        with open(BUSY_FILE, "w", encoding="utf-8") as f:
            _j.dump({"job": str(job or "?"), "lines": lines,
                     "since": _t.time(), "pid": os.getpid()}, f)
    except Exception:
        pass


def busy_message():
    """The honest sentence to show someone whose click had to wait."""
    import json as _j
    import time as _t
    try:
        if not os.path.exists(BUSY_FILE):
            return ("Microcat is busy with another lookup. It does ONE job at a "
                    "time - one browser, one signed-in seat. Give it a minute "
                    "and press the button again.")
        d = _j.load(open(BUSY_FILE, encoding="utf-8"))
        secs = int(_t.time() - float(d.get("since") or 0))
        n = d.get("lines")
        return (f"Microcat is looking up job {d.get('job')}"
                + (f" ({n} line(s))" if n else "")
                + f" - {secs}s so far. It does ONE job at a time because there is "
                  f"one browser and one signed-in seat. Please be patient and "
                  f"press the button again shortly - nothing is broken and "
                  f"nothing has been lost.")
    except Exception:
        return ("Microcat is busy with another lookup - one job at a time. "
                "Try again in a minute.")


class Microcat:
    """ATTACH ONLY. THIS CLASS CANNOT START A BROWSER.

    Brendon, 19 Aug, twice: "you still opening a new microcat - fix code so you do
    not do that, use api helper".

    The first fix added attach with a LAUNCH FALLBACK, and the fallback is what he
    kept seeing: no debug port yet, so every pass quietly fell through and opened
    yet another signed-out Microcat window. A fallback that does the exact thing
    you were told not to do is not a fallback, it is the bug with a longer path to
    it. So the launch code is GONE - not disabled, deleted. There is no
    launch_persistent_context in this module any more, no profile snapshot, no
    --headless, no profile lock (nothing to lock: we never own a browser).

    Attach to the API HELPER window, or do nothing at all and say why.
    """

    def __init__(self, **_ignored):
        # **_ignored keeps old call sites (headless=, profile_copy=) working while
        # meaning nothing - there is no browser of ours to configure.
        self.sub = api_helper_dir()
        self._pw = self.ctx = self.page = None

    def open(self, wait_seconds=30, human=False):
        """Attach to the API HELPER browser.

        wait_seconds / human added 29 Sep 2026. Brendon pressed Find numbers on a
        Prius and got "another pass is using the API HELPER browser" after 30
        seconds - the holder was a BACKGROUND test of mine. A person waiting at a
        screen must not lose the browser to a background job, so:
            human=True   waits much longer AND plants a flag that every
                         background tool checks before it takes the lock
        The flag is a file, not a variable, because the background tools are
        separate processes started by the scheduler.
        """
        from playwright.sync_api import sync_playwright
        import chrome_session
        # The PartsCheck chain drives MICROCAT. Stated once in catalogues.py and
        # checked here, so a future "just add a fallback" trips over the rule
        # instead of quietly opening a second tab and racing for the debug port.
        try:
            import catalogues
            ok, why = catalogues.check("partscheck", "microcat")
            if not ok:
                raise RuntimeError(why)
        except ImportError:
            pass
        # SELF-HEALING, and still not a violation of ATTACH ONLY. start() can
        # only ever launch the dedicated API HELPER directory - Brendon's profile
        # is not in it - so "open a browser" here cannot mean "open Brendon's
        # browser", which is the thing the rule exists to prevent. Without this a
        # reboot silently stopped the queue for ten days and nobody was told.
        try:
            started, swhy = chrome_session.ensure()
            if started:
                log("  API HELPER was not running - started it (" + str(swhy) + ")")
        except Exception as e:
            log("  could not start API HELPER: " + str(e)[:120])
        # THE SHARED BROWSER LOCK (20 Aug 2026). One window now serves Microcat,
        # PartSouq and the Euro chain's partslink24 work, and they run on
        # different clocks - PartsCheck every 15 minutes, Euro every 30. When the
        # Euro pass had the browser, our attach sat there and timed out, twice,
        # and reported "nothing to attach to" against a browser that was open,
        # signed in and perfectly healthy. Which sends someone off to restart a
        # browser that never needed restarting.
        #
        # "chrome_user_data" is the name everything else that touches Chrome
        # already uses. Taking it here makes the three of them queue instead of
        # collide, and turns a mystifying timeout into one honest line.
        self._browser_lock = None
        try:
            import runlock as _rl
            self._browser_lock = _rl.RunLock("chrome_user_data", stale_minutes=20,
                                             directory=HERE, log=log)
            import time as _t
            if human:
                try:
                    with open(HUMAN_FLAG, "w", encoding="utf-8") as _f:
                        _f.write(str(_t.time()))
                except Exception:
                    pass
            # A PERSON AT THE SCREEN GETS MORE PATIENCE THAN A CRON JOB.
            # 30s was the old fixed wait and it is what lost Brendon his Prius
            # lookup to a background test. A human click now waits 2.5 minutes.
            if human or a_human_is_waiting():
                wait_seconds = max(wait_seconds, 150)
            for _ in range(max(1, int(wait_seconds // 5))):
                if self._browser_lock.acquire():
                    break
                _t.sleep(5)
            if not self._browser_lock.acquired:
                self._browser_lock = None
                raise RuntimeError(busy_message())
        except RuntimeError:
            raise
        except Exception as e:
            log(f"  (browser lock unavailable: {str(e)[:60]})")
        self._pw = sync_playwright().start()
        try:
            self.ctx, self.page, why = chrome_session.attach(
                self._pw, want="superservice")
        except Exception:
            try:
                self._pw.stop()
            except Exception:
                pass
            raise
        log(f"  ATTACHED to the live {PROFILE_NAME} window ({why}) "
            f"- no new browser opened")
        return self

    def _release_browser(self):
        try:
            if os.path.exists(HUMAN_FLAG):
                os.remove(HUMAN_FLAG)
        except Exception:
            pass
        if getattr(self, "_browser_lock", None):
            try:
                self._browser_lock.release()
            except Exception:
                pass
            self._browser_lock = None

    def close(self):
        # NEVER CLOSE THE WINDOW. It is Brendon's own browser and closing it throws
        # away the signed-in Microcat session that is the entire point of
        # attaching. Drop our end of the CDP wire and nothing else.
        try:
            import chrome_session
            chrome_session.detach(self.ctx)
        except Exception:
            pass
        try:
            self._pw.stop()
        except Exception:
            pass
        self._release_browser()

    # ---------------------------------------------------------------- session
    def text(self):
        try:
            return self.page.inner_text("body") or ""
        except Exception:
            return ""

    def signed_in(self):
        """True if the page looks signed in to Microcat, False on a login screen.

        This only detects; it never signs in. Since 1 Oct 2026 the runner does
        type credentials itself - sign_in() fills the Infomedia form from
        microcat_credentials.json. Only when that file is missing or the login
        is refused does a person have to sign in; then report it and stop, do
        not half-run the queue."""
        t = self.text().lower()
        if any(k in t for k in ("sign in", "log in", "username", "password")) \
                and "vin" not in t:
            return False
        return bool(t.strip())

    def _credentials(self):
        """The Infomedia sign-in, from microcat_credentials.json. () if absent."""
        import json as _j
        f = os.path.join(HERE, "microcat_credentials.json")
        try:
            d = _j.load(open(f, encoding="utf-8"))
            u, w = str(d.get("username") or "").strip(), str(d.get("password") or "")
            if u and w and not u.startswith("your "):
                return u, w
        except Exception:
            pass
        return ()

    def sign_in(self):
        """Sign the API HELPER browser in to Infomedia. True if it worked.

        1 Oct 2026. Brendon: "on Microcat just log in, do not ask me, ok, in API
        helper page - or slows down process."

        The old house rule was that a person signs in and the runner never types
        credentials. He has now asked for the opposite, on his own system, with
        his own login - so it signs in, from a file that is git-ignored and never
        passes through a conversation. PartsLink24 has worked this way for weeks.

        It still refuses to guess: no credentials file, no attempt, and it says
        so rather than sitting on a login screen pretending to work.
        """
        cred = self._credentials()
        if not cred:
            # SAY SO.  An absent file used to return False without a word, so
            # the feature looked built and was inert while a person kept the
            # window signed in by hand.
            log("  sign-in SKIPPED: no microcat_credentials.json beside "
                "microcat_runner.py (only the EXAMPLE?) - Microcat works only "
                "while a person keeps API HELPER signed in")
            return False
        user, pwd = cred
        lp = self.page
        try:
            lp.goto(BASE, wait_until="domcontentloaded", timeout=90000)
            lp.wait_for_timeout(5000)
            # the form is the ordinary Infomedia one: an identifier, a password,
            # a submit. Found by type first, by name second - their markup moves.
            u = (lp.query_selector("input[type=email]")
                 or lp.query_selector("input[name*=user i]")
                 or lp.query_selector("input[name*=email i]")
                 or lp.query_selector("input[type=text]"))
            if not u:
                log("  sign-in: no username box on the page - already signed in?")
                return self.signed_in()
            self._type_like_a_person(u, user)
            w = lp.query_selector("input[type=password]")
            if not w:
                # some tenants ask for the password on a second step
                for sel in ("button[type=submit]", "button:has-text('Next')",
                            "button:has-text('Continue')"):
                    b = lp.query_selector(sel)
                    if b:
                        b.click()
                        lp.wait_for_timeout(4000)
                        break
                w = lp.query_selector("input[type=password]")
            if not w:
                log("  sign-in: no password box appeared")
                return False
            self._type_like_a_person(w, pwd)
            for sel in ("button[type=submit]", "button:has-text('Sign in')",
                        "button:has-text('Log in')", "button:has-text('Login')"):
                b = lp.query_selector(sel)
                if b:
                    b.click()
                    break
            else:
                lp.keyboard.press("Enter")
            lp.wait_for_timeout(9000)
            ok = self.signed_in()
            log("  signed in to Microcat automatically" if ok else
                "  sign-in did not take - Infomedia rejected it. Check the "
                "password in microcat_credentials.json (it returned errorCode=1 "
                "on 29 Sep, which means the credentials were refused).")
            return ok
        except Exception as e:
            log("  sign-in failed: %s %s" % (type(e).__name__, str(e)[:90]))
            return False

    def _type_like_a_person(self, el, value):
        """Real keystrokes, 35 ms apart - the same as _type() - instead of
        fill(), which sets the value in one go with no key events at all."""
        el.focus()
        self.page.keyboard.press("Control+a")
        self.page.keyboard.press("Delete")
        self.page.keyboard.type(value, delay=35)
        self.page.wait_for_timeout(300)

    def check(self):
        self.page.goto(BASE, wait_until="domcontentloaded", timeout=90000)
        self.page.wait_for_timeout(6000)
        ok = self.signed_in()
        print("profile :", f"{PROFILE_NAME} ({self.sub})")
        print("url     :", self.page.url)
        print("title   :", self.page.title())
        print("signed in:", ok)
        print("auto sign-in:", "credentials file present" if self._credentials()
              else "OFF - no microcat_credentials.json (only a person can sign in)")
        print("--- first 500 chars ---")
        print(re.sub(r"\s+", " ", self.text())[:500])
        return ok

    def capture(self, name):
        os.makedirs(CAPTURES, exist_ok=True)
        p = os.path.join(CAPTURES, datetime.datetime.now().strftime("%Y%m%d_%H%M%S_")
                         + re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:60] + ".html")
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.page.content())
        except Exception:
            pass
        return p

    # ---------------------------------------------------------------- lookup
    EPC_HINT = "microcat-epc"

    def epc(self):
        """The Microcat EPC tab - launched from the landing page if it is gone.

        LEARNED THE HARD WAY, night of 19/20 Aug 2026. You cannot navigate
        straight to the EPC. https://microcat-apac.superservice.com bounces to
        the Infomedia homescreen, and the EPC is only entered through the 'Start'
        tile, which opens it in a tab of its own. The old code did page.goto(BASE)
        and then looked for a VIN box on whatever it landed on - a landing page
        that has never had one. That is the whole of "no VIN/search box found on
        the Microcat page": the code was never in Microcat.

        The EPC tab also vanishes on its own - it did twice tonight - so this
        re-launches rather than assuming last pass's tab is still there.
        """
        for p in self.ctx.pages:
            if self.EPC_HINT in (p.url or ""):
                self.page = p
                self._tidy_tabs(keep=p)
                return p
        lp = next((p for p in self.ctx.pages
                   if "superservice" in (p.url or "").lower()), None)
        if lp is None:
            lp = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
            lp.goto(BASE, wait_until="domcontentloaded", timeout=90000)
            lp.wait_for_timeout(6000)
        lp.bring_to_front()
        chrome_session._park()
        lp.wait_for_timeout(1500)
        btn = lp.query_selector("button:has-text('Start')")
        if not btn:
            # SIGN IN RATHER THAN STOP.  1 Oct 2026.
            # Brendon: "on Microcat just log in, do not ask me - or slows down
            # process." It used to raise here and the whole pass died waiting
            # for a human.
            self.page = lp
            if self.sign_in():
                lp.wait_for_timeout(3000)
                btn = lp.query_selector("button:has-text('Start')")
            if not btn:
                raise RuntimeError(
                    "the API HELPER window is not signed in to Microcat and the "
                    "automatic sign-in did not work. Put the login in "
                    "microcat_credentials.json, or sign in on that window once.")
        btn.click()
        for _ in range(20):
            lp.wait_for_timeout(1500)
            for p in self.ctx.pages:
                if self.EPC_HINT in (p.url or ""):
                    self.page = p
                    p.bring_to_front()
                    chrome_session._park()
                    p.wait_for_timeout(4000)
                    log("  opened the Microcat EPC from the landing page")
                    self._tidy_tabs(keep=p)
                    return p
        raise RuntimeError("clicked Start but no Microcat EPC tab appeared")

    def _tidy_tabs(self, keep):
        """Leave exactly ONE Microcat tab open - the one we are working in.

        Brendon, 26 Aug 2026: "on partscheck microcat you keep open more and
        more tabs, please sort it out so you just use one tab."

        He is right, and it is this method's own fault. epc() cannot navigate
        straight to the EPC - it has to click the 'Start' tile - and Start opens
        the EPC in a NEW tab every single time. Any pass that found the old EPC
        tab missing (it closes itself, and a restart loses it) clicked Start and
        left the previous one behind. Three tabs by this morning, and it only
        ever grows: more tabs mean more memory, a slower CDP handshake, and a
        real chance of driving the wrong one.

        ONLY Microcat tabs are touched. The API HELPER window is shared with
        Partslink24 and PartSouq, and closing their tabs would drop a logged-in
        Partslink24 seat that the Euro chain is using - a much worse bug than
        the one being fixed. Anything that is not a superservice URL is left
        exactly where it is.
        """
        closed = 0
        keep_landing = [False]        # list so the loop below can set it
        for pg in list(self.ctx.pages):
            if pg is keep:
                continue
            try:
                u = (pg.url or "").lower()
            except Exception:
                continue
            if "superservice" not in u:
                continue          # Partslink24 / PartSouq / anything else - leave it
            # KEEP THE LANDING / LOGIN TAB TOO  (26 Aug 2026, same day, my own
            # bug). The first version of this kept ONLY the EPC tab, and the
            # very next pass logged:
            #
            #   re-entering the Microcat EPC and trying once more
            #   re-entry failed: no 'Start' tile on the Infomedia landing page
            #
            # because the EPC can only be re-entered by clicking 'Start' on the
            # landing page, and I had just closed the one tab showing it. That
            # traded a cosmetic problem for a broken recovery path.
            #
            # So the rule is: at most ONE EPC tab and at most ONE landing tab.
            # Steady state is two, not one - which is the honest answer, because
            # the second one is load-bearing.
            if ("login.superservice" in u or "landingpage" in u
                    or "homescreen" in u):
                if not keep_landing[0]:
                    keep_landing[0] = True
                    continue      # keep the first landing tab, close any others
            try:
                pg.close()
                closed += 1
            except Exception:
                pass
        if closed:
            log("  closed %d spare Microcat tab(s) - one tab is all we need"
                % closed)
        return closed

    def _search_tab_label(self):
        """The 'Search Results: <what> (N)' tab. Microcat's own count - the only
        honest answer to 'did that find anything', and how we tell a VIN that
        resolved from a VIN this catalogue has never heard of."""
        try:
            return self.page.evaluate(
                "() => { const t=[...document.querySelectorAll("
                "'.mat-tab-label-content')].map(e=>(e.innerText||'')"
                ".replace(/\\s+/g,' ').trim()).find(s=>s.startsWith("
                "'Search Results')); return t || ''; }") or ""
        except Exception:
            return ""

    def _type(self, sel, value):
        """Type into an Angular Material input.

        .click() loses to epc-split-mainview, which lies over the whole layout
        and eats pointer events, and .fill() alone does not always raise the
        events the app listens for. Focus plus real keystrokes works, and is what
        a person does anyway.
        """
        p = self.page
        # A TAB IN THE SEARCH TERM PRESSES TAB  (25 Aug 2026).
        #
        # keyboard.type() types the string as KEYSTROKES, so a tab character in
        # the term is the Tab KEY: focus jumps out of the search box and the
        # rest of the term is typed into whatever control comes next. The box
        # keeps whatever it held before, the read-back below sees the old text,
        # and the whole job is abandoned with "something else is writing into
        # this window" - which was never true.
        #
        # It happened because a term arrived as a whole tab-separated sheet row,
        # "11 	 L/H/F Guard flare with clips 	 Other 	 1", so the very
        # first tab threw the focus away. Three jobs in one pass, ten times
        # tonight. Newlines would do the same by submitting the form early.
        #
        # A catalogue search box has no use for a tab or a newline, so they are
        # collapsed to spaces here rather than at each call site. The read-back
        # guard below still does its real job - catching another writer - and
        # now it stops firing on our own keystrokes.
        value = re.sub(r"\s+", " ", str(value)).strip()
        # DO NOT USE wait_for_selector HERE  (26 Aug 2026).
        #
        # It timed out after 30 seconds on an element it had already found, and
        # said so in the same breath:
        #
        #   waiting for locator("#genericSearchInput") to be visible
        #     - locator resolved to visible <input id="genericSearchInput" ...>
        #
        # Microcat is Angular, and it re-creates that input as the page settles.
        # Every poll resolves a BRAND NEW element, so Playwright's stability
        # requirement is never satisfied and it spins until the timeout - while
        # a perfectly usable box sits on screen the whole time. The job died
        # before a single keystroke was sent, which is most of why the runner
        # has been answering nothing.
        #
        # query_selector asks a simpler question - "is it in the DOM right
        # now?" - and does not care that it is a different element each time.
        # That is the right question: we re-locate it on every use below
        # anyway.
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if p.query_selector(sel):
                    break
            except Exception:
                pass
            p.wait_for_timeout(400)
        else:
            raise RuntimeError("%s never appeared on the Microcat page" % sel)

        # TYPE, READ IT BACK, AND RETYPE IF IT DID NOT LAND  (26 Aug 2026).
        #
        # The read-back below was written to catch a SECOND WRITER, and it does.
        # But most of what it actually caught was us. Today's failures:
        #
        #   wanted 'TOP RADIATOR COVER OTHER'  box held ' RADIATOR COVER OTHER'
        #   wanted 'RADIATOR GRILLE'           box held '...OTHERRILLE'
        #
        # The first lost its opening characters; the second kept the previous
        # term and took only the tail of the new one. Nobody else is typing -
        # this is an Angular Material input that re-renders while the keystrokes
        # are going in, so the clear does not stick and the first letters land
        # nowhere. Treating that as "something else is writing into this window"
        # abandoned the whole job: eight times today, zero jobs answered.
        #
        # So: clear, type, read back, and if it does not match, do it again.
        # The guard is not weakened - we still refuse to search unless the box
        # holds exactly what we meant - it just stops being fatal on the first
        # try. fill() is used for the clear because it sets the value through
        # the DOM in one go rather than as keystrokes that can be dropped.
        last = ""
        for attempt in range(3):
            try:
                p.locator(sel).fill("")
            except Exception:
                pass
            p.locator(sel).focus()
            p.keyboard.press("Control+a")
            p.keyboard.press("Delete")
            p.wait_for_timeout(250)
            p.keyboard.type(value, delay=35)
            p.wait_for_timeout(900)
            try:
                last = p.locator(sel).input_value()
            except Exception:
                last = ""
            if _norm(last) == _norm(value):
                break
            log("  search box did not take %r (got %r) - retyping (%d/3)"
                % (value, last, attempt + 1))
            p.wait_for_timeout(600)
        # READ IT BACK BEFORE TRUSTING IT.
        #
        # On the night this was built, two runner passes drove the same tab at
        # once and both typed into this box. Microcat received the two VINs
        # interleaved letter by letter - "N1H0P21407-72447757475" out of
        # NHP10-2477475 and 2477475 - answered (0) to the nonsense, and forty
        # jobs were recorded as "Microcat has no vehicle for X" when the VIN had
        # never actually been searched. A false "this car does not exist" is
        # indistinguishable from a real one in the results file, which makes it
        # exactly the kind of wrong answer that gets believed.
        #
        # The run lock stops two passes. This stops anything else that can write
        # into the box - a stale lock cleared by hand, a person typing in the
        # window, an autocomplete that rewrites the field - because the check is
        # on what the box HOLDS, not on who might have touched it.
        got = last
        if _norm(got) != _norm(value):
            raise RuntimeError(
                "the search box does not contain what was typed - wanted "
                + repr(str(value)) + ", box holds " + repr(got) + " after 3 "
                "attempts. NOT searching, because the answer would be about "
                "the wrong text.")

    def _goto_identify(self):
        """Back to the Identify Vehicle screen, whatever the tab is showing.

        Once a vehicle is loaded the app sits on #/partSearch and there is no VIN
        box on the page at all. Two of the three jobs on the first clean run died
        here - not on anything to do with Microcat, purely on not being able to
        get back to the screen that starts a lookup. Setting location.hash alone
        does not always re-render, so the real UI path is tried first: click the
        'Identify Vehicle' item in the header. It is clicked through JS because
        epc-split-mainview lies over the layout and swallows real pointer events.
        """
        p = self.page
        if p.query_selector("#genericSearchInput"):
            return
        for _ in range(2):
            try:
                # Click the DEEPEST element whose whole text is the label, not
                # the first. The header nests the label inside wrappers, and the
                # first match is an outer div whose click does nothing at all -
                # which is why every job was falling through to the reopen-the-tab
                # fallback and paying 20 seconds for it. Falls back to dispatching
                # a real mouse event, since this header ignores a bare .click()
                # on some of its items.
                p.evaluate(
                    "() => {"
                    " const hits = [...document.querySelectorAll('a,span,div,li,button')]"
                    "   .filter(e => (e.innerText||'').trim() === 'Identify Vehicle'"
                    "             && e.getBoundingClientRect().width > 0);"
                    " if (!hits.length) return;"
                    " const el = hits[hits.length - 1];"
                    " el.click();"
                    " const r = el.getBoundingClientRect();"
                    " for (const t of ['mousedown','mouseup','click']) {"
                    "   el.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true,"
                    "     clientX: r.left + r.width/2, clientY: r.top + r.height/2}));"
                    " }"
                    "}")
            except Exception:
                pass
            p.wait_for_timeout(3500)
            if p.query_selector("#genericSearchInput"):
                return
            try:
                p.evaluate("() => { location.hash = '#/identify'; }")
            except Exception:
                pass
            p.wait_for_timeout(4000)
            if p.query_selector("#genericSearchInput"):
                return
        # Still nothing: the tab is wedged or the session dropped. Reopening the
        # EPC from the landing page is cheap and is the one thing that has always
        # worked - better than failing a job over a stuck route.
        try:
            self.page.close()
        except Exception:
            pass
        self.epc()
        p = self.page
        # THE SECOND ONE. Same bug as in _type(), missed on the first pass.
        #
        # 27 Aug 2026, Brendon asked whether the wait_for_selector fix had been
        # applied everywhere it was needed. It had not - _type() was fixed and
        # this one was left, so a job that came through the re-entry path could
        # still hang 45 seconds on an input that was already on screen, for the
        # same reason: Angular re-creates the element and Playwright's stability
        # check never settles. Asking whether it is in the DOM is the right
        # question in both places.
        deadline = time.time() + 45
        while time.time() < deadline:
            try:
                if p.query_selector("#genericSearchInput"):
                    return
            except Exception:
                pass
            p.wait_for_timeout(400)
        raise RuntimeError("#genericSearchInput never appeared after re-entering "
                           "the Microcat EPC")

    def vin(self, v):
        """Identify the vehicle, and PROVE it is the one that was asked for.

        Build date and production period applied BY MICROCAT, never guessed by us
        - the whole reason it is the authority (the Hiace lesson: our own
        catalogue copy returned 52119-26800 and 81130-26580; Microcat corrected
        both).

        THE CHECK THAT MATTERS. The first version accepted "the title has a
        pipe in it" as proof the vehicle had loaded. It always does - the
        PREVIOUS vehicle's title has a pipe in it too. So on the night this was
        built it searched three RAV4 parts against a RAV4 that was still on
        screen from an earlier test, for a job about a different car entirely,
        and wrote the answers out. Nothing in the result would have looked wrong.
        The identifier now has to appear in the title Microcat itself renders, or
        this raises. Wrong-car part numbers are the one failure this queue exists
        to prevent.

        Raises VinNotFound when Microcat answers (0) - a real answer that no
        retry will change, so it is recorded rather than thrown at the log.
        """
        p = self.epc()
        ident, last, tried = str(v), "", []
        for round_no in (1, 2):
            got = self._search_identifier(p, ident, tried)
            if got:
                return got
            if round_no == 1:
                # THE JDM FALLBACK (Brendon, 20 Aug 2026): "vin no first, if it
                # does not work go to carjam, put the vin and get the chassis
                # number and use it - true for all JDM cars." A New Zealand
                # compliance VIN is not a number Toyota ever issued, so the
                # factory catalogue cannot know it; CarJam holds both and hands
                # back the chassis the catalogue does know.
                chassis = _carjam_chassis(v)
                if chassis and _norm(chassis) != _norm(ident):
                    log(f"      {v} unknown to Microcat - CarJam says chassis "
                        f"{chassis}, trying that")
                    ident = chassis
                    continue
            break
        raise VinNotFound(
            "Microcat has no vehicle for " + str(v)
            + " (tried " + ", ".join(tried) + ")")

    def _search_identifier(self, p, ident, tried):
        """One identifier, every spelling of it. Returns the vehicle URL or None."""
        want = _norm(ident)
        last = ""
        for variant in _identifier_variants(ident):
            tried.append(variant)
            # WHAT THE SCREEN SAID BEFORE WE SEARCHED.
            #
            # The second search in a session was not submitting. The box took the
            # text, the icon was clicked, and the Search Results tab went on
            # showing the PREVIOUS vehicle - so the loop waited out its 24 tries
            # against a stale page and reported "Microcat has no vehicle for X"
            # about a VIN the catalogue knows perfectly well. It cost a full day
            # of jobs, because every job after the first in a pass failed.
            #
            # Remembering the label lets us tell "no result" apart from "no
            # search happened", which are opposite problems.
            _before = self._search_tab_label()
            self._goto_identify()
            # _goto_identify can REPLACE the tab (it reopens the EPC when the
            # route is wedged), so the local handle from the top of this method
            # may now point at a closed page. Re-read it, or the next call dies
            # with TargetClosedError - which is exactly what job three did.
            p = self.page
            self._type("#genericSearchInput", variant)
            # Clicked through JS for the same reason as _type. And note: Enter
            # does NOT submit this box - tested, it does nothing at all.
            p.eval_on_selector("#genericSearchIcon", "el => el.click()")
            # DO NOT SECOND-GUESS THE SEARCH ON A TIMER.
            #
            # A 2.5s "did it submit?" check fired on almost every job, because
            # the Search Results tab keeps the PREVIOUS pass's label until the
            # new results land - and a real search often takes longer than that.
            # Both recoveries it triggered made things worse: a page reload
            # logged the session out, and a route reset left the identify screen
            # never rebuilding.
            #
            # The loop below already waits ~36s for the label or title to name
            # THIS identifier, which is the only honest test. Stale labels simply
            # never match, so they cost time and nothing else. If it really did
            # not submit, _recover_epc() below re-enters the EPC cleanly - the
            # one recovery that has always worked.
            for _ in range(24):
                p.wait_for_timeout(1500)
                if want and want in _norm(p.title()):
                    return p.url
                last = self._search_tab_label()
                m = re.search(r"\((\d+)\)\s*$", last)
                if not m:
                    continue
                if int(m.group(1)) == 0:
                    break                      # this spelling found nothing
                # Microcat found candidates but has not loaded one. Take the
                # single unambiguous hit; anything else is a person's call.
                if int(m.group(1)) == 1:
                    try:
                        p.eval_on_selector(".ag-row", "el => el.click()")
                        p.wait_for_timeout(6000)
                    except Exception:
                        pass
                    if want and want in _norm(p.title()):
                        return p.url
                break
        # Nothing matched for any spelling. Before giving up, re-enter the EPC
        # once and try the original identifier again: a stale single-page app is
        # the difference between "Microcat has never heard of this VIN" and "the
        # screen was still showing the last car", and those must not look alike.
        if not getattr(self, "_reentered", False):
            self._reentered = True
            try:
                log("      re-entering the Microcat EPC and trying once more")
                try:
                    self.page.close()
                except Exception:
                    pass
                self.epc()
                got = self._search_identifier(self.page, ident, tried)
                if got:
                    return got
            except Exception as e:
                log(f"      re-entry failed: {str(e)[:70]}")
            finally:
                self._reentered = False
        return None

    def find(self, term):
        """Search the identified vehicle. Returns the result rows as dicts.

        THE GRID IS VIRTUAL. About six rows of a hundred-and-twenty exist in the
        DOM at any moment, so reading the document once returns six rows and
        looks like a narrow, confident answer - the most dangerous shape a wrong
        answer can take here, because six rows holding exactly one part number
        would be stamped CONFIRMED. So it scrolls the grid and harvests until it
        stops yielding new rows, and the caller judges all of them.
        """
        p = self.page
        self._type("#globalSearchInput", term)
        try:
            p.eval_on_selector("#globalSearchIcon", "el => el.click()")
        except Exception:
            p.keyboard.press("Enter")
        p.wait_for_timeout(7000)
        rows = p.evaluate("""
        async () => {
          const box = [...document.querySelectorAll('.ag-body-viewport')]
              .sort((a,b) => b.scrollHeight - a.scrollHeight)[0];
          const seen = new Map();
          const grab = () => {
            for (const r of document.querySelectorAll('.ag-row')) {
              const o = {};
              for (const c of r.querySelectorAll('[col-id]')) {
                const v = (c.innerText || '').replace(/\\s+/g, ' ').trim();
                if (v) o[c.getAttribute('col-id')] = v;
              }
              const num = o.partNumberColumnIllustration;
              if (num) seen.set(num + '|' + (o.descriptionColumnIllustration||''), o);
            }
          };
          const sleep = ms => new Promise(r => setTimeout(r, ms));
          if (!box) { grab(); return [...seen.values()]; }
          box.scrollTop = 0; await sleep(400); grab();
          for (let i = 0; i < 120; i++) {
            box.scrollTop += box.clientHeight * 0.8;
            await sleep(280); grab();
            if (box.scrollTop + box.clientHeight >= box.scrollHeight - 5) break;
          }
          return [...seen.values()];
        }""")
        out = []
        for r in rows or []:
            out.append({
                "pnc": r.get("pncColumnIllustration", ""),
                "number": r.get("partNumberColumnIllustration", ""),
                "description": r.get("descriptionColumnIllustration", ""),
                "models": r.get("modelCodesColumnIllustration", ""),
                "qty": r.get("qtyColumnIllustration", ""),
                "from": r.get("fromDateColumnIllustration", ""),
                "to": r.get("toDateColumnIllustration", ""),
            })
        return out


class VinNotFound(Exception):
    """Microcat answered, and the answer was 'no such vehicle'."""


# ------------------------------------------------------------------ matching
# Words that carry no identity. Dropped from the request before scoring so that
# "Front Door Mirror Assy RH" and "MIRROR ASSY, OUTER REAR VIEW, RH" can meet.
NOISE = {"ASSY", "ASSEMBLY", "NEW", "GENUINE", "OEM", "PART", "AND", "THE",
         "FOR", "WITH", "OF", "TO"}
SIDE_WORDS = {"RH": "RH", "RIGHT": "RH", "RHS": "RH",
              "LH": "LH", "LEFT": "LH", "LHS": "LH"}
NOT_APPLICABLE = "00000-00000"

# FALSE FRIENDS: words that mean one thing in the trade and something else
# entirely in Toyota's catalogue. They may be SEARCHED on (the glossary turns
# "bar" into "bumper" for that), but they must never be taken as the head noun,
# because the row they match starts the wrong argument.
#
# "Front Bar Grille Garnish RH" is a grille garnish. Nothing in the results began
# with GRILLE or GARNISH, so the head noun fell back to BAR - and Toyota's BAR is
# a STABILIZER bar. It came back CONFIRMED as 48811-53092, a suspension part,
# for a front-end cosmetic repair, on a margin of 1.9 to 0.4. Being wrong quietly
# and confidently is the one thing this matcher must not do.
HEAD_NEVER = {"BAR"}

# TRADE ENGLISH -> TOYOTA ENGLISH.
#
# The queue is fed by PartsCheck, where a panel shop writes what a panel shop
# says: "Rear Bar Cover", "Tailamp Bracket RH", "Rear Qtr Flare". Toyota's
# catalogue says "COVER, REAR BUMPER", "BRACKET, REAR COMBINATION LAMP, RH",
# "MOULDING, QUARTER PANEL". These are the same parts in two dialects, and no
# amount of token scoring bridges "bar" to "bumper" - the words share nothing.
# Every NOT_FOUND on the first real run tonight was this, not a scoring problem.
#
# Kept deliberately small and literal. A wrong entry here would send a confident
# search after the wrong part, so it holds only terms where the trade word has
# exactly one meaning on a Toyota body.
GLOSSARY = {
    "BAR": "BUMPER",
    "TAILAMP": "REAR COMBINATION LAMP",
    "TAILLAMP": "REAR COMBINATION LAMP",
    "TAILLIGHT": "REAR COMBINATION LAMP",
    "TAILLIGHTS": "REAR COMBINATION LAMP",
    "HEADLAMP": "HEADLAMP UNIT",
    "HEADLIGHT": "HEADLAMP UNIT",
    "QTR": "QUARTER",
    "MOULD": "MOULDING",
    "MOULDING": "MOULDING",
    "FLARE": "FLARE MOULDING",
    "GUARD": "FENDER",
    "MUDGUARD": "FENDER",
    "BONNET": "HOOD",
    "WINDSCREEN": "WINDSHIELD",
    "INDICATOR": "SIGNAL LAMP",
    "FOGLAMP": "FOG LAMP",
    "FOGLIGHT": "FOG LAMP",
    "SILL": "ROCKER PANEL",
    "BOOT": "LUGGAGE COMPARTMENT",
    "TAILGATE": "BACK DOOR",
    # GARNISH is trade for what Toyota calls a MOULDING. The Lexus IS350 grille
    # garnish is "MOULDING, RADIATOR GRILLE" (53121-53100) - searching "garnish"
    # returns nothing at all, which is why that line sat unidentified until
    # Brendon looked it up by hand on 21 Aug 2026.
    "GARNISH": "MOULDING",
    "SURROUND": "MOULDING",
    "REO": "REINFORCEMENT",
    "REINFO": "REINFORCEMENT",
    "RAD": "RADIATOR",
    "SUPPORT": "SUPPORT",
    "APRON": "APRON",
    "SPLASH": "SPLASH SHIELD",
    "LINER": "LINER",
    "WIRE": "WIRE",
}


def _norm(s):
    """Strip everything that is not a letter or digit. Microcat renders a frame
    number as "ZVW30 5752386" and PartsCheck sends "ZVW30-5752386"; they are the
    same car and must compare equal."""
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def _carjam_chassis(v):
    """The Japanese chassis number for a VIN, via CarJam. "" if unavailable.

    Imported lazily and never allowed to be fatal: CarJam is someone else's
    website, and a Microcat pass must not fail because it was slow or down.
    """
    try:
        import sys as _sys
        pc = os.path.join(os.path.dirname(HERE), "Automation_System",
                          "Partscheck Automation")
        pc = pc if os.path.isdir(pc) else os.path.join(HERE, "Partscheck Automation")
        if pc not in _sys.path:
            _sys.path.insert(0, pc)
        import rego_lookup
        return rego_lookup.chassis_for(v)
    except Exception as e:
        log(f"      (CarJam lookup unavailable: {str(e)[:70]})")
        return ""


def _identifier_variants(v):
    """The spellings of one identifier, in the order worth trying.

    A 17-character VIN has exactly one spelling. A Japanese frame number does
    not: the quote carries "ZVW30-5752386", Microcat's own vehicle history shows
    "ZVW30 5752386", and searching the dashed form returns nothing at all. Two
    jobs failed tonight for no reason other than the punctuation.
    """
    raw = str(v).strip().upper()
    out = [raw]
    if len(_norm(raw)) != 17:
        for alt in (raw.replace("-", " "), raw.replace("-", ""),
                    raw.replace(" ", "-"), raw.replace(" ", "")):
            if alt and alt not in out:
                out.append(alt)
    return out


def _tokens(s):
    return [t for t in re.findall(r"[A-Z0-9]+", str(s).upper()) if len(t) > 1]


def _side(s):
    """LH or RH, or "".

    THE SLASHED FORMS COUNT (22 Aug 2026). _tokens() drops anything shorter than
    two characters, so "L/H/F GUARD" became L, H, F - all discarded - and the
    side came back EMPTY. With no side, the hard side rule never ran, and the
    line matched "APRON SUB-ASSY, FRONT FENDER, RH": a right-hand part quoted
    against a left-hand request. That is the exact failure the side rule exists
    to prevent, and it was silently switched off by a punctuation style.
    """
    up = " " + str(s or "").upper().replace("-", "/") + " "
    if re.search(r"[\s/(]L\s*/\s*H\b|\bL/H/F\b|\bLHF\b", up):
        return "LH"
    if re.search(r"[\s/(]R\s*/\s*H\b|\bR/H/F\b|\bRHF\b", up):
        return "RH"
    for t in _tokens(s):
        if t in SIDE_WORDS:
            return SIDE_WORDS[t]
    return ""


ENDS = ("FRONT", "REAR")


def _end(s):
    """FRONT or REAR from a description, or "". """
    for t in _tokens(s):
        if t in ENDS:
            return t
        if t in ("FR", "FRT"):
            return "FRONT"
        if t in ("RR",):
            return "REAR"
    return ""


def _row_side(desc):
    """Toyota writes the side as its own comma field: ', RH' / ', LH'. Matching a
    bare RH anywhere in the string would catch RHD - right-hand DRIVE - and put a
    left mirror on a right-hand quote."""
    u = " " + str(desc).upper().replace(",", " , ") + " "
    if re.search(r"[\s,]RH[\s,]", u):
        return "RH"
    if re.search(r"[\s,]LH[\s,]", u):
        return "LH"
    return ""


def group_phrase(description):
    """The PART GROUP, without the qualifier. "" when there is nothing to drop.

    Brendon, 22 Aug 2026 - how a person actually finds a part:

        "if it says for example front bumper retainer rh and you search that you
         will not find anything. But if you see FRONT BUMPER, and then know to go
         and click body, then bumper, then find the retainer - you will find it
         every time."

    He is describing navigation, not searching. You never look for the whole
    phrase; you go to the group the part lives in and then read the illustration
    for the piece you want.

    Searching the group words alone has the same effect through the search box:
    Microcat returns that section's parts, and the retainer is among them. The
    qualifier is not thrown away - it is what the matcher then scores on, exactly
    like reading down the illustration.

    "Front bumper retainer RH" -> "FRONT BUMPER"
    "Rear bumper cover"        -> "REAR BUMPER"
    "Tailamp bracket LH"       -> "REAR COMBINATION LAMP"
    """
    try:
        import trade_words as tw
    except Exception:
        return ""
    # THE LAST NOUN NAMES THE PART, THE FIRST NAMES WHERE IT SITS.  9 Oct 2026.
    # "RF GUARD HYBRID BADGE" took its group from "guard" -> FENDER and searched the fender
    # drawing for a badge. Brendon: "you gone back to old think search names only".
    # A badge / emblem lives in EMBLEM & NAME PLATE, whatever it is stuck on.
    try:
        import part_noun as _pn
        if _pn.noun_of(description) in ("badge", "emblem", "nameplate"):
            return "EMBLEM"
    except Exception:
        pass
    try:                                    # a taught group beats the first-noun guess
        _sec = tw.section_for(description)
        if _sec in ("FRONT TURN SIGNAL LAMP",):
            return _sec
    except Exception:
        pass
    end = tw.end(description)
    words = [w for w in re.findall(r"[A-Z]+", str(description).upper())
             if w not in tw.SIDE_WORDS]
    part = ""
    for w in words:
        c = tw.canonical(w)
        alts = tw.TRADE_TO_CATALOGUE.get(w)
        cand = alts[0] if alts else (c if c in tw.PART_NOUNS else
                                     (w if w in tw.PART_NOUNS else ""))
        if cand:
            part = cand
            break                       # the FIRST part noun is the group
    if not part:
        return ""
    if end and end not in part:
        return (end + " " + part).strip()
    return part


def search_phrase(description):
    """The description in Toyota's words, for the search box itself.

    Scoring the results in both dialects is not enough - Microcat's own search
    has to be given words it knows. "Tailamp Bracket RH" returns twenty unrelated
    brackets because nothing in the catalogue is called a tailamp; "REAR
    COMBINATION LAMP BRACKET RH" returns the bracket. Substituted in place here,
    unlike translate(), which keeps both spellings because scoring can afford to.
    """
    out = []
    for t in _tokens(description):
        if t in NOISE:
            continue
        for w in GLOSSARY.get(t, t).split():
            # "Rear Splash Shield" expands to "SPLASH SHIELD" + "SHIELD" and went
            # to Microcat as "REAR SPLASH SHIELD SHIELD". Harmless to the search,
            # but it is printed in the note a person reads, and a tool that talks
            # like that is not one you trust with a part number.
            if not out or out[-1] != w:
                out.append(w)
    return " ".join(out)


def translate(description):
    """Trade English -> the words Toyota actually prints. Returns the token list.

    Both spellings are kept: "bar" becomes BUMPER but BAR stays, because some
    descriptions do mean a bar. Extra words cost nothing - scoring is by how rare
    a word is, and a word that appears in no row scores zero rather than misleading.
    """
    out = []
    for t in _tokens(description):
        if t in NOISE:
            continue
        out.append(t)
        if t in GLOSSARY:
            out.extend(w for w in GLOSSARY[t].split() if w not in out)
    return out


def base_number(num):
    """52159-47050-J6 and 52159-47050-C0 are the same bumper cover in two
    colours. For a quote they are one answer, so the colour suffix is dropped
    when deciding whether the top rows really disagree."""
    m = re.match(r"^([0-9A-Z]{5}-[0-9A-Z]{5,6})", str(num).upper())
    return m.group(1) if m else str(num).upper()


def _pnc_hints(desc, make="", model=""):
    """Candidate factory groups for this description, off our own stock. Never
    fatal: the Elephant being unreachable must not stop a Microcat pass."""
    try:
        import pnc_hints
        return pnc_hints.hints(desc, make=make or "", model=model or "")
    except Exception as e:
        log(f"      (Elephant PNC hint unavailable: {str(e)[:60]})")
        return []


def best_match(description, rows, hint_pncs=()):
    """(row_or_None, candidates, why). CONFIRMED IS EARNED.

    Toyota does not name parts the way a panel shop does, so an
    all-words-must-match rule answers nothing and a most-words-win rule answers
    confidently and wrongly. Between those:

      * the request is TRANSLATED first (see GLOSSARY) or the words never meet.
      * the SIDE must agree. A wrong-side mirror is not a near miss, it is a
        wrong part that gets fitted, so the opposite side is disqualified
        outright rather than scored down.
      * NOT APPLICABLE rows (00000-00000) are not parts.
      * words are weighted by HOW RARE they are in what came back. In 260 rows
        about a Prius, REAR and COVER are worth almost nothing and BUMPER is
        worth a great deal - which is the entire difference between "COVER, REAR
        BUMPER" and twenty-one other rows that also start with COVER. Counting
        words equally is what made every line tonight a tie.
      * the head noun - the request word some row description STARTS with - is
        what the part IS. "COVER, OUTER MIRROR, RH" mentions the mirror; it is
        not the mirror.
      * and the winner must be CLEAR of the runner-up, after colour variants of
        one part number are collapsed together. Two genuinely different rows is
        the RAV4 problem that started all this (5215942938 vs ...39): it goes
        back as NOT_FOUND naming both, so a person sees the real choice instead
        of a coin-toss landing in a quote.
    """
    want = translate(description)
    side = _side(description)
    core = [t for t in want if t not in SIDE_WORDS]
    live = [r for r in rows
            if r.get("number") and r["number"] != NOT_APPLICABLE
            and partfinder.looks_like_oem(r["number"].replace("-", ""), "microcat")]
    # FRONT AND REAR ARE AS HARD A RULE AS LEFT AND RIGHT.
    #
    # A rear bumper cover is 52159 and a front one is 52119. On the first run
    # with the Elephant hints switched on, a mislabelled row on our own shelves
    # ("YARIS CROSS REAR BUMPER COVER" carrying a 52119 number) hinted the front
    # group, the hint bonus carried it, and "Rear Bar Cover" came back CONFIRMED
    # as 52119-47340-A1 - a front bumper cover, quoted for a rear-end repair.
    # Nothing about that result looked wrong. So the end has to be checked
    # against Microcat's own wording, which is never mislabelled, exactly the way
    # the side already is - and the hint may narrow the search but can never win
    # an argument with it.
    end = _end(description)
    if end:
        other = "REAR" if end == "FRONT" else "FRONT"
        same = [r for r in live if _end(r["description"]) == end]
        if same:
            live = same
        else:
            live = [r for r in live if _end(r["description"]) != other]
    if not live:
        return None, [], f"no row on the {end or 'right'} end of the car"
    if side:
        sided = [r for r in live if _row_side(r["description"]) == side]
        if sided:
            live = sided
        else:
            live = [r for r in live if not _row_side(r["description"])]
    if not live:
        return None, [], "no usable rows (side " + (side or "n/a") + ")"

    # How rare is each word among the rows that came back? A word in every row
    # tells us nothing; a word in one row tells us almost everything.
    n = len(live)
    df = {}
    for t in core:
        rx = re.compile(r"\b" + re.escape(t) + r"\b")
        df[t] = sum(1 for r in live if rx.search(str(r["description"]).upper()))
    weight = {t: math.log((n + 1.0) / (df[t] + 1.0)) + 0.2 for t in core}

    # THE HEAD NOUN IS POSITIONAL, NOT STATISTICAL.
    #
    # A panel shop writes the head noun LAST - "Rear Bar Cover" is a cover,
    # "Tailamp Bracket RH" is a bracket. Toyota writes it FIRST - "COVER, REAR
    # BUMPER". That is a reliable rule in both dialects, and it is the whole
    # match.
    #
    # The first version picked the RAREST word instead, on the theory that rare
    # means important. It does not mean "is". For "Rear Bar Cover" it chose
    # BUMPER, handed the head bonus to "BUMPER, REAR SPRING, NO.1 RH" - a
    # suspension bumper stop - and left the actual rear bumper cover tied with a
    # bracket. Scanning from the end for the first word some row STARTS with also
    # skips trailing qualifiers for free: "Front Door Mirror Assy RH 10wire" tries
    # 10WIRE, finds no row beginning with it, and settles on MIRROR.
    # THE HEAD NOUN, THROUGH THE SHARED GLOSSARY (21 Aug 2026).
    #
    # Brendon: "well share the glossary for both". Partslink24 got trade_words
    # first; this is the other half. It matters here because the trade word and
    # the catalogue word are often not the same TOKEN at all - "Tailamp RH" has
    # no row starting with TAILAMP, so every candidate was rejected and the line
    # came back NOT_FOUND against six perfectly good rows. Canonicalised,
    # TAILAMP is LAMP, and LAMP starts half of them.
    #
    # Both spellings are tried: the word he wrote, and what a catalogue calls it.
    try:
        import trade_words as _tw
    except Exception:
        _tw = None
    head = ""
    for t in reversed(core):
        if t in HEAD_NEVER:
            continue
        forms = [t]
        if _tw is not None:
            c = _tw.canonical(t)
            if c != t:
                forms.append(c)
            for alt in _tw.TRADE_TO_CATALOGUE.get(t, ()):
                forms.extend(alt.split())
        for f in forms:
            if any(str(r["description"]).upper().startswith(f) for r in live):
                head = f
                break
        if head:
            break

    # A SPRING BUMPER IS A SUSPENSION STOP, NOT A BUMPER (24 Aug 2026).
    #
    # The head-noun rule above already knew about "BUMPER, REAR SPRING" and it
    # still was not enough. On job GLN1390 "Front Bumper LH Retainer" found no
    # row starting with RETAINER, fell back to BUMPER as the head, and handed
    # the bonus to "BUMPER, FRONT SPRING, LH" - 48331-21030, a rubber bump stop
    # - which was priced, quoted and learned. Brendon caught it: the retainer
    # is 52116-47040.
    #
    # Toyota's "BUMPER" in a suspension row always carries SPRING with it, and
    # a panel shop asking about a bumper never wants one. Those rows are
    # removed outright rather than merely out-scored, unless the request is
    # itself about springs or suspension. Removed only when something survives,
    # so a genuine spring enquiry is never left with nothing.
    _asks_suspension = any(w in " ".join(core)
                           for w in ("SPRING", "SUSPENSION", "SHOCK", "STRUT"))
    if not _asks_suspension:
        _no_spring = [r for r in live
                      if not re.search(r"\bSPRING\b",
                                       str(r["description"]).upper())]
        if _no_spring:
            live = _no_spring

    # A NUMBER FROM THE RIGHT AREA BUT THE WRONG KIND OF THING (25 Aug 2026).
    #
    # Brendon caught two of these on one morning's approval emails:
    #   "Rear Bar Lower (Texture)"  -> 90159-60477, a screw
    #   "Front Bar Grille Centre"   -> 75310-75010, the grille BADGE
    # Both scored well because the words overlap - a screw that fastens the
    # rear bar has "rear bar" all over its description, and the badge lives on
    # the grille. Neither is the panel the repairer asked for. The rule lives
    # in trade_words so both chains share it, and a line that ASKS for a clip
    # or a badge is unaffected.
    try:
        import trade_words as _twk
        _clean = [r for r in live
                  if not _twk.pnc_is_wrong_kind(description, r.get("number"))]
        if _clean:
            live = _clean
    except Exception:
        pass

    # THE PNC OUR OWN SHELVES ALREADY KNOW  (25 Aug 2026)
    #
    # Where Brendon has settled a wording outright, the illustration is not
    # asked to work it out from the words. "Rear Bar Lower (Texture)" is the
    # rear valance MOULDING - Toyota's own description says neither "bar" nor
    # "lower", so every scoring pass on those words was always going to lose to
    # whatever fastener happened to mention them.
    #
    # Filtered, not merely boosted, and only when the PNC is actually present
    # in the illustration - so a car whose valance sits under a different
    # number is left to the scorer rather than answered with nothing.
    try:
        import trade_words as _twp
        # PREFERENCE ORDER, not a single answer - the same trade wording is a
        # different PNC on a different generation of the same model, and the
        # car itself settles which. First PNC with rows in THIS illustration
        # wins; if none of them are here, the scorer is left alone.
        for _want in _twp.pnc_by_phrase(description):
            _hit = [r for r in live
                    if str(r.get("pnc") or r.get("number") or "")[:5] == _want]
            if _hit:
                live = _hit
                break
    except Exception:
        pass

    scored = []
    for r in live:
        d = str(r["description"]).upper()
        s = sum(weight[t] for t in core
                if re.search(r"\b" + re.escape(t) + r"\b", d))
        if head and d.startswith(head):
            s += 1.5
        if side and _row_side(d) == side:
            s += 0.8
        # Our own shelves said this part lives in that group. Worth real weight -
        # it is evidence from a part we have actually sold, not another reading
        # of the same words - but not decisive on its own, because a group holds
        # the cover, the bracket and the lamp alike.
        if hint_pncs and str(r.get("pnc", ""))[:5] in hint_pncs:
            s += 1.2
        scored.append((s, r))
    scored.sort(key=lambda x: -x[0])
    cands = [r["number"] + " " + r["description"][:48] for _, r in scored[:5]]
    top = scored[0][0]
    rival = next((s for s, r in scored[1:]
                  if base_number(r["number"]) != base_number(scored[0][1]["number"])),
                 -99.0)
    if not head:
        # OUR OWN SHELVES CAN STAND IN FOR THE HEAD NOUN.
        #
        # The head-noun rule exists because "COVER, OUTER MIRROR" mentions a
        # mirror without being one. But it only works when the catalogue and the
        # repairer share a word, and often they do not: "Tailamp RH" has no row
        # beginning with TAILAMP, so every candidate was thrown away even though
        # the Elephant had already said the part lives in group 81550/81560 and
        # Microcat had returned rows from exactly there.
        #
        # When the group came off a part WE have sold against THIS description,
        # that is independent evidence - not another reading of the same words -
        # and it is the strongest signal available on these lines. Side and end
        # have already been enforced as hard rules above, so a wrong-side or
        # wrong-end row cannot reach here.
        #
        # Still not a free pass: the winner must be clear of the runner-up by the
        # usual margin, and the note says plainly that the group came from stock,
        # so a person reviewing the quote can see how it was decided.
        # ...BUT A ROW THAT NAMES A DIFFERENT PART IS STILL A DIFFERENT PART.
        #
        # Brendon, 22 Aug: "how did you get to guard when we on front bumper."
        # Fair question. "L/H/F GUARD" took 53701 "APRON SUB-ASSY, FRONT FENDER"
        # - the Elephant offered that group because our own apron rows carry the
        # word FENDER, and the relaxation below accepted it on that shared word.
        # But the row STARTS with APRON. An apron is not a guard; the head-noun
        # rule had already rejected it correctly and the relaxation overrode it.
        #
        # So the relaxation may skip a MISSING head noun - never a CONFLICTING
        # one. If a row opens with a part noun we did not ask for, it is that
        # part, and no amount of group evidence changes it.
        def _names_another_part(desc_text):
            first = re.split(r"[ ,]", str(desc_text).upper().strip(), 1)[0]
            if not first:
                return False
            try:
                import trade_words as _tw
                nouns = set(_tw.PART_NOUNS)
            except Exception:
                nouns = set()
            if first not in nouns:
                return False
            return first not in {c.upper() for c in core} and first != head

        if hint_pncs:
            in_group = [(sc, r) for sc, r in scored
                        if str(r.get("pnc", ""))[:5] in hint_pncs
                        and not _names_another_part(r["description"])]
            if in_group:
                best_sc, best_r = in_group[0]
                other = next((sc for sc, r in scored
                              if base_number(r["number"])
                              != base_number(best_r["number"])), -99.0)
                if best_sc - other >= 0.9:
                    return best_r, cands, (
                        "no catalogue word matched, but our own stock puts this "
                        "part in group " + str(best_r.get("pnc", ""))[:5]
                        + " and this is the clear winner there ("
                        + ("%.1f" % best_sc) + " vs " + ("%.1f" % other) + ")")
        return None, cands, ("no row is actually this part - every hit only "
                             "mentions it in passing")
    if top - rival < 0.9:
        tied = sum(1 for s, _ in scored if abs(s - top) < 1e-9)
        return None, cands, (str(tied) + " rows tie at the top - needs the "
                             "drawing read by a person")
    return scored[0][1], cands, ("clear on '" + head + "' ("
                                 + ("%.1f" % top) + " vs " + ("%.1f" % rival) + ")")


# ------------------------------------------------------------------ the queue
def pending(only_microcat=True):
    """Requests with no result. This is the backlog nobody was watching."""
    req_dir, res_dir = partfinder.REQ_DIR, partfinder.RES_DIR
    have = {f[:-5] for f in os.listdir(res_dir) if f.endswith(".json")}
    out = []
    for f in sorted(os.listdir(req_dir)):
        if not f.endswith(".json"):
            continue
        job = f[:-5]
        if job in have:
            continue
        try:
            r = partfinder._read_json(os.path.join(req_dir, f))
        except Exception:
            continue
        if only_microcat and r.get("catalog", "microcat") != "microcat":
            continue
        r["_job"] = job
        r["_age_h"] = (datetime.datetime.now().timestamp()
                       - os.path.getmtime(os.path.join(req_dir, f))) / 3600.0
        out.append(r)
    out.sort(key=lambda r: r["_age_h"])          # newest first - freshest quotes
    return out


def status():
    p = pending()
    print(f"Microcat queue: {len(p)} request(s) with no result")
    if not p:
        return 0
    print(f"  newest {p[0]['_age_h']:.1f}h old, oldest {p[-1]['_age_h']:.1f}h old")
    for r in p[:15]:
        print(f"   {r['_job']:16} {r.get('make',''):8} {r.get('vin',''):18} "
              f"{len(r.get('lines',[]))} line(s)  {r['_age_h']:.1f}h")
    if browser_guard:
        print("  guard:", browser_guard.channel_ok("microcat")[1])
    return 0


def _route_off_microcat(req, make, ident, price):
    """Stamp a non-Toyota request with the catalogue that actually owns it.

    Written beside the request as <job>.routed.json, NOT into results\\, because
    this is not an answer - no part number has been found. It records who the
    request belongs to so it stops counting against Microcat, and so a person or
    the euro chain can see at a glance what is waiting on what.
    partfinder.validate() only ever reads results\\, so nothing downstream can
    mistake a routing note for a result.
    """
    import datetime as _dt
    import json as _j
    import os as _o
    try:
        d = partfinder.REQ_DIR
        if not d or not _o.path.isdir(d):
            return
        p = _o.path.join(d, "%s.routed.json" % str(req.get("_job")))
        if _o.path.exists(p):
            return                      # already routed - say it once, not every pass
        with open(p, "w", encoding="utf-8") as fh:
            _j.dump({"job": req.get("_job"), "make": make,
                     "identification": ident, "price": price,
                     "reason": "Microcat is Toyota/Lexus only",
                     "routed_at": _dt.datetime.now().isoformat()}, fh, indent=1)
    except Exception:
        pass                            # routing is bookkeeping, never a blocker


def work_job(mc, req):
    """One request -> results\\<job>.json -> partfinder.validate().

    CONFIDENCE IS EARNED, NEVER ASSUMED. best_match() decides, and it only
    CONFIRMS when one row is clearly the part and the side agrees. Everything
    else goes back as NOT_FOUND carrying the candidates it saw, so a person sees
    the real choice instead of a coin-toss on a quote. partfinder.validate() then
    files the retry.
    """
    job = req["_job"]
    make = str(req.get("make", "")).upper()
    # ROUTE BY MAKE, DO NOT ABANDON  (Brendon, 18 Sep 2026: "change the microcat
    # lookup to partslink24 if it is one of those makes, if not wiuse or
    # partsouq").
    #
    # This used to say "not our make, left in the queue" and return. Correct as
    # far as Microcat goes - it is Toyota and Lexus only - but the request then
    # sat there for ever because nothing else was watching it. Two thirds of the
    # 191 unanswered requests were Volkswagen, Audi, BMW, Peugeot and Renault
    # waiting on a catalogue that was never going to read them, which made the
    # queue look like a graveyard while Microcat was in fact doing its job.
    #
    # The make now decides the owner, using the same table the euro chain uses
    # (catalogues.euro_source), and the request is stamped with it and taken off
    # Microcat's list. Nothing is discarded - the stamp names who it is for.
    if make and not any(m in make for m in ("TOYOTA", "LEXUS")):
        try:
            import catalogues
            ident, price = catalogues.euro_source(make)
        except Exception:
            ident, price = "partslink24", "wiuse"
        _route_off_microcat(req, make, ident, price)
        log(f"  {job}: {make} -> {ident}"
            + (f", price via {price}" if price else ", numbers only")
            + " - routed off Microcat's queue")
        return None
    # A VIN THAT IS NOT A VIN COSTS A MINUTE ON EVERY PASS  (26 Aug 2026).
    #
    # NZJ0140329Q2 arrived with a VIN of the single letter "W". Microcat was
    # asked for it every pass, spent ~60 seconds failing through every search
    # variant and a full EPC re-entry, and left the job in the queue to do it
    # all again ten minutes later. With a handful of these the runner can burn
    # its whole window before reaching a job it could actually answer.
    #
    # A real VIN is 11-17 characters of the VIN alphabet (no I, O or Q). Less
    # than that is a broken record, not a car - so it is reported once, taken
    # out of the queue, and left for a person to correct on the quote.
    _vin = re.sub(r"[^A-HJ-NPR-Z0-9]", "", str(req.get("vin") or "").upper())
    if len(_vin) < 11:
        log(f"  {job}: VIN {req.get('vin')!r} is not a VIN - nothing to look "
            f"up. Needs a human to fix the VIN on the quote.")
        rows = [{"line": l.get("line"), "description": l.get("description"),
                 "oem_no": "", "confidence": "NOT_FOUND",
                 "note": "the VIN on this quote (%r) is not a valid VIN, so no "
                         "catalogue can identify the vehicle - correct it on "
                         "PartsCheck" % (req.get("vin"),)}
                for l in req.get("lines", [])]
        return _write_result(job, req, "", rows)

    log(f"  {job}: VIN {req.get('vin')} ({len(req.get('lines', []))} line(s))")
    _jobwit = (attempt_log.Line("partscheck", job, "job")
               if attempt_log else None)
    try:
        vurl = mc.vin(req["vin"])
        log(f"      vehicle: {mc.page.title()[:80]}")
        if _jobwit:
            _jobwit.ok("vin", mc.page.title()[:70], value=req.get("vin"))
    except VinNotFound as e:
        if _jobwit:
            _jobwit.miss("vin", str(e)[:120])
        # A real answer from the authority. Recorded as NOT_FOUND on every line
        # so the job leaves the queue instead of being retried nightly for ever -
        # which is how 148 requests piled up unnoticed.
        log(f"      {e}")
        vurl = ""
        rows = [{"line": l.get("line"), "description": l.get("description", ""),
                 "oem_no": "", "confidence": "NOT_FOUND",
                 "note": f"Microcat does not have VIN {req.get('vin')} - "
                         f"check the VIN on the quote, or look this one up by "
                         f"model and build date by hand"}
                for l in req.get("lines", [])]
        return _write_result(job, req, vurl, rows)

    rows = []
    _used_numbers = {}          # part number -> the description that claimed it
    for l in req.get("lines", []):
        desc = str(l.get("description", ""))

        # WHAT BRENDON HAS ALREADY SETTLED, THE RUNNER MUST NOT RE-DERIVE.
        #
        # 27 Aug 2026. He told me on the 26th that this Land Cruiser has no
        # front bumper lower grille and no lower valance, and I recorded both -
        # but only Stage 2 reads those stores. The runner went on searching the
        # catalogue from scratch and answered the lower grille with 52021-60280,
        # the bumper REINFORCEMENT, on the very next pass. Being told something
        # and then ignoring it is worse than never having asked.
        #
        # Both stores are checked here, before any searching:
        #   not_on_vehicle - the part does not exist on this car. Say so and
        #                    stop; searching harder cannot find what is not there.
        #   learned        - a number he has confirmed for this wording. Use it.
        try:
            _nil = partfinder.lookup_not_on_vehicle(
                req.get("vin", ""), desc, model=req.get("model", ""))
        except Exception:
            _nil = ""
        if _nil:
            log(f"      {desc.strip()[:44]:46} -> NOT ON THIS VEHICLE")
            rows.append({"line": l.get("line"), "description": desc,
                         "oem_no": "", "confidence": "NOT_FOUND",
                         "note": "not a part on this vehicle - %s" % _nil})
            continue
        try:
            _known, _how = partfinder.lookup_learned(
                req.get("vin", ""), desc, model=req.get("model", ""))
        except Exception:
            _known, _how = "", ""
        if _known:
            log(f"      {desc.strip()[:44]:46} -> {_known}   ({_how[:40]})")
            rows.append({"line": l.get("line"), "description": desc,
                         "oem_no": _known, "confidence": "CONFIRMED",
                         "note": _how})
            _used_numbers[_known] = desc
            continue

        wit = (attempt_log.Line("partscheck", job, l.get("line", "?"))
               if attempt_log else None)
        if wit:
            # steps 1-3 happened back in Stage 2 before this job was queued -
            # reaching Microcat at all means they did not answer.
            wit.skip("given", "no number from the repairer, or Stage 2 used it")
            wit.miss("learned", "no learned mapping for this wording")
            wit.ok("vin", "vehicle resolved") if vurl else wit.miss("vin", "no vehicle")
        m = PNC_RX.search(desc)
        # A PNC is the 5-digit factory group ("52119"). Microcat searches it
        # directly and it is a far better key than English, so it goes first.
        # PNC first (the 5-digit factory group is a far better key than any
        # English), then the description in Toyota's words, then the shop's own
        # words as written - each one only if the one before it came back empty.
        phrase = search_phrase(desc)
        # ASK OUR OWN SHELVES WHAT THIS IS (Brendon, 20 Aug): the Elephant holds
        # what we have sold, with the OEM number beside our own wording, and the
        # first five digits of that number are the factory group. A PNC search in
        # Microcat is exact where an English one is a guess - "Rear Qtr Flare LH
        # Textured" finds nothing by words and lands on 76908 MUDGUARD, QUARTER
        # PANEL, LH through the shelves.
        _hints = _pnc_hints(desc, req.get("make"), req.get("model"))
        hint_pncs = [h[0] for h in _hints]
        # THE PNC GOES IN FIRST.  29 Sep 2026.
        #
        # Brendon, the first instruction of the day: "search part number first."
        # And after a MIRROR was quoted at $902.95 against a line reading RF
        # DOOR: "so you know PNC 67001, so why did you not use it first search,
        # fuck around with 87910 mirror."
        #
        # A PNC search is exact - one number, one family, no wording to misread.
        # An English search on "RF DOOR" matched the word DOOR inside DOOR
        # MIRROR and returned a mirror. So anything pnc_lookup can VERIFY goes to
        # the front of the queue, ahead of the Elephant's shelf hints and far
        # ahead of the repairer's wording.
        #
        # pnc_lookup returns nothing when it does not know - and nothing means
        # "fall through to the word search", never a guess.
        try:
            import pnc_lookup as _pl
            _first = [c for c, _why in _pl.pncs_for(desc)]
            if _first:
                log(f"      {desc[:34]:36} -> PNC first: {', '.join(_first[:3])}")
                hint_pncs = _first + [h for h in hint_pncs if h not in _first]
        except Exception as _e:
            log(f"      (pnc_lookup unavailable: {str(_e)[:60]})")
        if wit:
            if _hints:
                wit.ok("elephant_hint", f"{len(_hints)} group(s) off our shelves",
                       value=",".join(hint_pncs[:3]))
            else:
                wit.miss("elephant_hint", "nothing of ours reads like this")
        # ORDER: exact keys first, then translated words, then HIS OWN WORDING
        # last - and the last one must never be cut off.
        #
        # This was terms[:4] against a list that reaches six when the Elephant
        # offers three groups, so `desc` - the repairer's own words - was
        # silently dropped on exactly the hard lines where it might have been the
        # one that worked. The attempt log caught it: plain_search recorded
        # "this step never reported - it did not run".
        # GROUP FIRST, THEN NARROW - the way a person uses the catalogue.
        # "front bumper retainer rh" finds nothing; "FRONT BUMPER" lands on the
        # section and the retainer is in it. See group_phrase().
        # THE SECTION NAME FIRST - it is how the catalogue is indexed.
        #
        # Brendon walked this through on 22 Aug: a part is not found by its own
        # name, it is found by opening the illustration it lives in. "lhf guard"
        # is in HOOD & FRONT FENDER; "front bumper retainer rh" is in FRONT
        # BUMPER, on the side at the top. Searching the SECTION name lands on
        # that drawing, and the part is then simply in the list.
        #
        # Tried before the looser group phrase because a section name is what
        # Toyota actually calls the drawing, so it hits precisely.
        try:
            import trade_words as _tw
            sec = _tw.section_for(desc)
        except Exception:
            sec = ""
        grp = group_phrase(desc)
        terms = ([m.group(1)] if m else [])
        terms += [pnc for pnc in hint_pncs[:3] if pnc != (m.group(1) if m else None)]
        terms += [phrase] if phrase and phrase.upper() != desc.upper() else []
        if sec and sec.upper() not in [str(t).upper() for t in terms]:
            terms.append(sec)
        if grp and grp.upper() not in [str(t).upper() for t in terms]:
            terms.append(grp)
        terms += [desc]

        # ONE WORD, WHEN THE WHOLE LINE SAYS TOO MUCH  (Brendon, 26 Aug 2026:
        # "when search sometimes search one word ie radar").
        #
        # Proven on the Land Cruiser the same day. The line
        #   "16 <tab> Front Radar sensor and bracket <tab> Other <tab> 1"
        # returned NOTHING, because Microcat is matching that whole string. The
        # single word "radar" returned exactly one row - 88210-62020, SENSOR
        # ASSY, MILLIMETER WAVE RADAR - which is the part. Same for "air guide":
        # the full line gave 167 rows and a tie, one word gave 7 rows all of
        # which were radiator air guides.
        #
        # So the distinctive nouns are tried on their own, AFTER the fuller
        # phrasings. Order matters: a specific phrase that works should win
        # first, and the single word is the fallback that rescues the line
        # rather than the opening move - one word can also be too broad.
        #
        # Only words that actually name something are used. "front", "other",
        # "complete" and the line number identify nothing, and searching them
        # returns half the catalogue.
        _NOISE_ONE = {"FRONT", "REAR", "OTHER", "COMPLETE", "ALL", "BOTH",
                      "SIDE", "WITH", "AND", "THE", "ASSY", "ASSEMBLY", "NEW",
                      "OEM", "LH", "RH", "LEFT", "RIGHT", "UPPER", "LOWER",
                      "INNER", "OUTER", "NO", "PART", "PLS", "EACH"}
        for _w in re.findall(r"[A-Za-z]{4,}", str(desc)):
            _u = _w.upper()
            if _u in _NOISE_ONE:
                continue
            if _u not in [str(t).upper() for t in terms]:
                terms.append(_w)

        # KEEP LOOKING UNTIL ONE OF THEM ACTUALLY ANSWERS.
        #
        # This used to stop at the first term that returned ANY rows, which is
        # not the same as the first that returned the right ones. A hint PNC that
        # points at the wrong group still returns two hundred rows, and stopping
        # there threw away the terms that would have worked: "Rear Bar Cover"
        # searched a front-bumper hint, matched nothing on the rear end, and came
        # back NOT_FOUND while the plain description would have found it.
        #
        # So a term is only good enough if it CONFIRMS. Otherwise we move on, and
        # keep the most informative failure to report if none of them do.
        pick, cands, why, used, hits = None, [], "", "", []
        # A VERIFIED PNC THAT ANSWERS IS THE ANSWER.  29 Sep 2026.
        #
        # PNC 67001 returned 67001-47111 PANEL SUB-ASSY, FRONT DOOR, RH - the
        # correct part, on screen - and best_match threw it away with "no row is
        # actually this part, every hit only mentions it in passing". It scores
        # on wording, and "RF DOOR" does not read like "PANEL SUB-ASSY, FRONT
        # DOOR, RH" however obviously they are the same thing. The pass then fell
        # through to a word search and found a MIRROR.
        #
        # When the term is a PNC we have VERIFIED (pnc_lookup, taught by Brendon
        # or confirmed on screen with him) and a row carries exactly that PNC and
        # passes the noun gate, the wording does not get a vote. That is what a
        # PNC is FOR: it identifies the family, so the family's part is the part.
        _verified = []
        try:
            import pnc_lookup as _pl
            _verified = [c for c, why_ in _pl.pncs_for(desc) if why_.startswith("verified")]
        except Exception:
            pass
        for t in _verified:
            got = mc.find(t)
            if not got:
                continue
            import part_noun as _pn2
            for r in got:
                if str(r.get("pnc", "")).upper() != str(t).upper():
                    continue
                if _pn2.same_kind(desc, r.get("description", "")):
                    continue
                pick = r
                used, hits = t, got
                why = (f"verified PNC {t} - the family for this part; "
                       f"{r.get('description','')}")
                log(f"      {desc[:34]:36} -> PNC {t} answered: {r.get('number')}")
                break
            if pick:
                break
        for t in ([] if pick else terms):
            got = mc.find(t)
            if not got:
                continue
            p2, c2, w2 = best_match(desc, got, hint_pncs)
            if not p2 and t in hint_pncs:
                # A PNC SEARCH THAT RETURNS ONE ROW HAS ALREADY ANSWERED.
                #
                # The group came off our own shelves for this exact description,
                # and Microcat found a single part in it. There is nothing left to
                # disambiguate, so the English rules have no work to do - and they
                # were actively harmful here: "Number Plate Base" searched 52114,
                # got back the one row 52114-42150, and the head-noun rule threw
                # it away because no row began with PLATE or BASE. Brendon knew
                # that group off the top of his head and asked why we had not
                # found it.
                #
                # The side and end rules still applied inside best_match, so a
                # wrong-side or wrong-end row has already been dropped before we
                # get here.
                sole = [r for r in got
                        if r.get("number") and r["number"] != NOT_APPLICABLE
                        and partfinder.looks_like_oem(
                            r["number"].replace("-", ""), "microcat")]
                if len(sole) == 1:
                    p2 = sole[0]
                    w2 = ("the only part in group " + str(t) + ", and that group "
                          "came from our own stock for this description")
            if wit:
                kind = ("pnc_search" if t in hint_pncs or (m and t == m.group(1))
                        else "glossary_search" if t != desc else "plain_search")
                wit.ok(kind, f"{len(got)} row(s)", value=str(t)[:40])
            if p2:
                pick, cands, why, used, hits = p2, c2, w2, t, got
                break
            if not cands:
                cands, why, used, hits = c2, w2, t, got
        if wit:
            if pick:
                wit.ok("match", why[:120], value=pick["number"])
            elif hits:
                wit.fail("match", why[:150])
            else:
                wit.miss("match", "no rows came back from any search")
            wit.finish()
        # ONE PART NUMBER CANNOT ANSWER TWO DIFFERENT LINES.
        #
        # "L/H/F GUARD" and "L/H/F GUARD BADGE" both came back 53701-52200. A
        # guard and its badge are different parts, so at least one of those was
        # wrong - and a duplicate is the cheapest possible signal that the
        # matcher has reached for whatever was nearest. Rather than pick between
        # them, both go back for a person: a wrong number on a quote costs more
        # than an unanswered line.
        # THE NOUN IS THE PART. THE REST IS ADJECTIVES.  29 Sep 2026.
        #
        # Brendon: "read description - noun is rivet, rest is adjective."
        #
        # This check goes BEFORE the duplicate check on purpose. On job 32764 the
        # matcher answered "LR Door mould clips" with 75720-76030, the mould
        # itself - because "door" and "mould" are in the line, and they are the
        # LOCATION, not the part. The duplicate rule then saw the same number on
        # the mould line and the clip line and threw BOTH away. Six of seven
        # lines came back not-found that way.
        #
        # Checking the kind first means the mould line keeps its correct number
        # and only the clip line is left open - one honest question instead of
        # two lost answers.
        if pick:
            try:
                import part_noun as _pn
                _bad = _pn.same_kind(desc, pick.get("description", ""))
            except Exception:
                _bad = ""
            # DID WE UNDERSTAND THE LINE AT ALL?  29 Sep 2026.
            # Brendon: "noun is about English language comprehension." When no
            # word in the line is one we know names a part, the noun came from a
            # shortcut - so the answer is a SUGGESTION for a person, never a
            # CONFIRMED number that gets priced and sent.
            try:
                _sure = _pn.comprehended(desc)
            except Exception:
                _sure = True
            if not _bad and not _sure:
                log(f"      {desc[:34]:36} -> PROPOSED {pick['number']} "
                    f"(wording not understood - left for a person)")
                rows.append({"line": l.get("line"), "description": desc,
                             "oem_no": pick["number"], "confidence": "PROPOSED",
                             "note": f"Microcat offered {pick['number']} "
                                     f"({pick.get('description','')}), but nothing in "
                                     f"'{desc}' is a part word we know, so this was "
                                     f"NOT filled in. Check it and type it if right."})
                if wit:
                    wit.finish()
                continue
            if _bad:
                log(f"      {desc[:34]:36} -> WRONG KIND: {_bad[:60]}")
                rows.append({"line": l.get("line"), "description": desc,
                             "oem_no": "", "confidence": "NOT_FOUND",
                             "note": f"Microcat offered {pick['number']} "
                                     f"({pick.get('description','')}) but {_bad}."})
                if wit:
                    wit.fail("match", _bad[:60])
                    wit.finish()
                continue
        if pick and pick["number"] in _used_numbers:
            other = _used_numbers[pick["number"]]
            log(f"      {desc[:34]:36} -> DUPLICATE of '{other[:24]}' "
                f"({pick['number']}) - both left for a person")
            rows.append({"line": l.get("line"), "description": desc, "oem_no": "",
                         "confidence": "NOT_FOUND",
                         "note": f"matcher returned {pick['number']} for this line "
                                 f"AND for '{other}'. Two different parts cannot "
                                 f"share one number, so neither is trusted."})
            for prev in rows:
                if prev.get("oem_no") == pick["number"]:
                    prev["oem_no"] = ""
                    prev["confidence"] = "NOT_FOUND"
                    prev["note"] = (f"matcher returned {pick['number']} for this "
                                    f"line AND for '{desc}' - not trusted")
            if wit:
                wit.fail("match", f"duplicate number with '{other[:30]}'")
                wit.finish()
            continue
        if pick:
            _used_numbers[pick["number"]] = desc
            rows.append({"line": l.get("line"), "description": desc,
                         "oem_no": pick["number"], "confidence": "CONFIRMED",
                         "note": f"Microcat on this VIN: {pick['description']} "
                                 f"(PNC {pick['pnc']}) - {why}"})
        else:
            note = f"{why}; searched '{used}', {len(hits)} row(s)"
            if cands:
                note += " - closest: " + "; ".join(cands[:4])
            rows.append({"line": l.get("line"), "description": desc, "oem_no": "",
                         "confidence": "NOT_FOUND", "note": note})
        log(f"      {desc[:34]:36} -> {rows[-1]['oem_no'] or rows[-1]['confidence']}")
    return _write_result(job, req, vurl, rows)


def _write_result(job, req, vurl, rows):
    out = {"job": job, "vin": req.get("vin"), "catalog": "microcat",
           "looked_up_by": f"microcat_runner.py on {PROFILE_NAME}, "
                           + datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "vehicle_url": vurl, "rows": rows}
    os.makedirs(partfinder.RES_DIR, exist_ok=True)
    with open(os.path.join(partfinder.RES_DIR, job + ".json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    _r, misses, problems = partfinder.validate(job)
    if problems:
        log(f"      REJECTED by partfinder: {'; '.join(problems[:3])}")
    else:
        log(f"      accepted: {len(rows) - len(misses)} confirmed, "
            f"{len(misses)} not found (retry filed)")
    return out


# How many backlog jobs a scheduled pass may take once the fresh work is done.
# Small on purpose: the point is that the tail drains without anyone driving it,
# not that one pass tries to eat 250 hours of it.
BACKLOG_PER_PASS = 3


def run(limit=8, jobs=None, everything=False, **_ignored):
    q = pending()
    if jobs:
        q = [r for r in q if r["_job"] in set(jobs)]
    elif not everything:
        # FRESH WORK FIRST, BUT THE TAIL MUST STILL DRAIN.
        #
        # The 24-hour cut is right: working a 250-hour backlog oldest-first would
        # spend the whole budget on quotes that expired a week ago - the same dead
        # work that produced 213 consecutive Stage 2 timeouts. But a cut alone
        # means the backlog is never touched by anything on a schedule, so it can
        # only ever grow, and clearing it needs someone to remember --all. It has
        # sat at 70-plus jobs on that basis.
        #
        # So: every fresh job, then a HANDFUL of the oldest as a top-up. Fresh
        # work is never delayed - the top-up only uses what is left of the limit -
        # and the tail drains a few jobs an hour without anyone driving it. Old
        # quotes are usually expired by now, but partfinder.validate() LEARNS every
        # CONFIRMED row, so the number found on a dead quote is free and instant on
        # the next live one for that car.
        fresh = [r for r in q if r["_age_h"] <= 24]
        backlog = [r for r in q if r["_age_h"] > 24]
        backlog.sort(key=lambda r: -r["_age_h"])          # oldest first, so it ends
        room = max(0, limit - len(fresh))
        q = fresh + backlog[:min(room, BACKLOG_PER_PASS)]
    if not q:
        log("nothing to do - queue is clear (or all of it is older than 24h; "
            "add --all to work the backlog)")
        return 0
    # ONE RUNNER AT A TIME. Not a nicety - every runner drives the SAME browser
    # tab, so two passes overlapping do not run twice as fast, they interleave
    # inside one window: pass A identifies its vehicle, pass B navigates the tab
    # away, and pass A then reads part numbers off pass B's car. That happened on
    # the night this was written (the 15-minute task fired into a manual run) and
    # it produced results files that looked completely normal. Silent wrong
    # answers are the worst thing this queue can emit, so overlapping runs are
    # made impossible rather than merely unlikely.
    lock = runlock.RunLock("microcat_runner", stale_minutes=45, log=log)
    if not lock.acquire():
        log("  another Microcat pass is already running - leaving the queue to it")
        return 0
    try:
        busy_with(job=(q[0] if q else "?"), lines=len(q) if q else None)
        return _run_locked(q, limit)
    finally:
        busy_with(clear=True)
        lock.release()


def _run_locked(q, limit):
    log(f"MICROCAT RUNNER START - {len(q)} job(s) to work, limit {limit}")
    try:
        mc = Microcat().open()
    except Exception as e:
        # NO BROWSER IS OPENED HERE. Not being able to attach is a normal, quiet
        # outcome - the API HELPER window is not up yet - and the answer is to say
        # so and leave the queue alone, NOT to open a signed-out Microcat that can
        # never answer anything.
        log(f"*** NOT WORKING THE QUEUE: {str(e)[:150]}")
        log("    Nothing opened. Run START_API_HELPER.bat, sign in to Microcat "
            "once, leave that window open - the next pass attaches to it.")
        # AND TELL SOMEBODY (Brendon, 25 Aug 2026: "if microcat logged out
        # e-mail us"). Quiet was the whole problem: this same refusal repeated
        # every ten minutes for four hours with four jobs queued behind it, and
        # the pass still reported "all stages completed cleanly". The queue is
        # stuck until this is cleared, so someone has to be told.
        # ONLY SHOUT WHEN IT IS ACTUALLY LOGGED OUT.
        #
        # 26 Aug 2026: this alerted on ANY failure to open, and the commonest
        # failure by far is the run lock - "another pass is using the API HELPER
        # browser" - which is not a fault at all, it is two passes taking turns
        # exactly as designed. Brendon got an email headed "MICROCAT IS LOGGED
        # OUT - quoting has stopped" because the browser was busy for ninety
        # seconds. An alert that fires when nothing is wrong trains you to
        # ignore the one that matters.
        _busy = ("another pass" in str(e) or "runlock" in str(e).lower()
                 or "already running" in str(e).lower())
        if not _busy:
            try:
                import catalogue_alert
                catalogue_alert.alert("Microcat", str(e)[:180],
                                      detail="%d job(s) waiting in the queue" % len(q))
            except Exception:
                pass
        return 2
    worked = 0
    try:
        # Enter the EPC. NOT page.goto(BASE) - that lands on the Infomedia
        # homescreen, which has no VIN box, which is exactly how every previous
        # pass failed. epc() clicks Start and waits for the real application.
        try:
            mc.epc()
            try:
                import catalogue_alert
                catalogue_alert.clear("Microcat")   # working again - all clear
            except Exception:
                pass
        except Exception as e:
            mc.capture("microcat_NO_EPC")
            # "no Start tile" means the window is not signed in and the automatic
            # sign-in did not work (no credentials file, or the login was refused).
            try:
                import catalogue_alert
                catalogue_alert.alert("Microcat", str(e)[:180],
                                      detail="the EPC would not open")
            except Exception:
                pass
            log(f"*** CANNOT ENTER THE MICROCAT EPC: {str(e)[:160]}")
            log("    If it says not signed in: the automatic sign-in failed. "
                "Check microcat_credentials.json, or sign in once by hand in "
                "the API HELPER window.")
            return 2
        for req in q[:limit]:
            try:
                if work_job(mc, req) is not None:
                    worked += 1
            except Exception:
                log(f"  {req['_job']}: ERROR\n" + traceback.format_exc())
    finally:
        mc.close()
    if worked and browser_guard:
        browser_guard.beat("microcat")       # Stage 2 reads this
        log("  heartbeat written - Stage 2 will stop warning")
    log(f"MICROCAT RUNNER END - {worked} job(s) answered")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--explore", metavar="VIN")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--job", action="append", dest="jobs")
    ap.add_argument("--all", action="store_true", help="include the old backlog")
    ap.add_argument("--limit", type=int, default=8)
    # --headless / --live-profile / --profile-copy are GONE (19 Aug 2026). They
    # only ever configured a browser of our own, and this module no longer starts
    # one. Leaving dead flags in would invite someone to "fix" the login problem by
    # launching again, which is the exact loop we just got out of.
    a = ap.parse_args()
    if a.status:
        return status()
    if a.check or a.explore:
        try:
            mc = Microcat().open()
        except Exception as e:
            print("CANNOT ATTACH - nothing opened.")
            print(" ", str(e)[:200])
            return 2
        try:
            ok = mc.check()
            if a.explore and ok:
                print("\nvehicle:", mc.vin(a.explore))
                print("capture:", mc.capture("microcat_vehicle"))
            return 0 if ok else 2
        finally:
            mc.close()
    if a.run:
        return run(limit=a.limit, jobs=a.jobs, everything=a.all)
    return status()


if __name__ == "__main__":
    sys.exit(main())
