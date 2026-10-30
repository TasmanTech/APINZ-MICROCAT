# -*- coding: utf-8 -*-
r"""
THE STAND-INS FOR THE OFFLINE TESTS.  31 Oct 2026 (Morgan).

The offline tests import the REAL microcat_runner and desk_finder, but every
module they lean on that would touch the live system - partfinder (the queue
and the learned store), runlock, chrome_session, browser_guard,
catalogue_alert, desk_core - is replaced here, and so is the browser.

SAFE ON THE LIVE MACHINE. Nothing in an offline test reads or writes the real
queue, results\, the runner log, the human flag, the busy file or the sign-in
refusal file: every one of those paths is pointed into pytest's tmp_path. The
stand-ins are put in sys.modules with monkeypatch, so the real modules are
back the moment each test ends.

The helper modules the matcher imports opportunistically (trade_words,
part_noun, pnc_lookup, pnc_hints, ...) are BLOCKED rather than stubbed, so the
offline results do not change with whatever Brendon has taught those modules
this week. A test that needs one installs its own.
"""
import importlib
import json
import os
import sys
import types

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# imported inside functions by the real code - None in sys.modules makes
# `import x` raise ImportError, which every one of those call sites tolerates
BLOCKED = ("trade_words", "part_noun", "pnc_lookup", "pnc_hints", "attempt_log",
           "catalogues", "rego_lookup", "desk_frame", "playwright",
           "playwright.sync_api", "websocket")


class RunLock:
    """runlock.RunLock, in memory. force_busy plays another pass holding it."""
    held = set()
    force_busy = False

    def __init__(self, name, **_k):
        self.name, self.acquired = name, False

    def acquire(self):
        if RunLock.force_busy and self.name == "microcat_runner":
            return False
        self.acquired = self.name not in RunLock.held
        if self.acquired:
            RunLock.held.add(self.name)
        return self.acquired

    def release(self):
        RunLock.held.discard(self.name)
        self.acquired = False


# ---------------------------------------------------------------- the browser
class World:
    """What Microcat itself would do.

    known            VINs / chassis numbers Microcat holds
    rows             what the parts grid returns for any search
    expire_on_search the Nth VIN search (1-based) is where the session lapses
    """
    def __init__(self, signed_in=True, known=(), rows=None, expire_on_search=None):
        self.signed_in, self.known = signed_in, set(known)
        self.rows = rows if rows is not None else [
            row("52159", "52159-0K900", "COVER, REAR BUMPER")]
        self.expire_on_search, self.searches = expire_on_search, 0


def row(pnc, number, description):
    """One parts-grid row, keyed the way Microcat's ag-grid names its columns."""
    return {"pncColumnIllustration": pnc, "partNumberColumnIllustration": number,
            "descriptionColumnIllustration": description}


class _Box:
    def __init__(self, page, sel):
        self.p, self.sel = page, sel

    def fill(self, v):
        self.p.boxes[self.sel] = v

    def focus(self):
        self.p.focused = self.sel

    def input_value(self):
        return self.p.boxes.get(self.sel, "")


class _Keyboard:
    def __init__(self, page):
        self.p = page

    def press(self, k):
        if k == "Delete" and self.p.focused:
            self.p.boxes[self.p.focused] = ""

    def type(self, v, delay=0):
        self.p.boxes[self.p.focused] = self.p.boxes.get(self.p.focused, "") + v


class EpcPage:
    """The Microcat EPC tab: two search boxes and a grid."""
    def __init__(self, ctx):
        self.ctx, self.w = ctx, ctx.w
        self.url = "https://microcat-apac.superservice.com/microcat-epc/#/identify"
        self.boxes, self.focused, self._title, self._label = {}, None, "Microcat", ""
        self.keyboard = _Keyboard(self)

    def query_selector(self, sel):
        return object() if sel in ("#genericSearchInput", "#globalSearchInput") else None

    def locator(self, sel):
        return _Box(self, sel)

    def wait_for_timeout(self, ms):
        pass

    def bring_to_front(self):
        pass

    def title(self):
        return self._title

    def eval_on_selector(self, sel, js):
        if sel == "#genericSearchIcon":
            w, v = self.w, self.boxes.get("#genericSearchInput", "")
            w.searches += 1
            if w.expire_on_search and w.searches >= w.expire_on_search:
                w.signed_in = False
            if w.signed_in and v in w.known:
                self._title = f"HILUX (2024 - ) | {v} | 01/2025"
            else:
                # a lapsed session answers nothing - which looks exactly like (0)
                self._label = f"Search Results: {v} (0)"

    def evaluate(self, js):
        if "mat-tab-label-content" in js:
            return self._label
        if "ag-body-viewport" in js:
            return list(self.w.rows) if self.w.signed_in else []
        return None

    def close(self):
        if self in self.ctx.pages:
            self.ctx.pages.remove(self)

    def content(self):
        return ""


class LandingPage(EpcPage):
    """The Infomedia landing page: a Start tile only while signed in."""
    def __init__(self, ctx):
        super().__init__(ctx)
        self.url = "https://microcat-apac.superservice.com/landingpage"

    def query_selector(self, sel):
        if sel == "button:has-text('Start')" and self.w.signed_in:
            return self
        return None

    def click(self):
        self.ctx.pages.append(EpcPage(self.ctx))

    def goto(self, *_a, **_k):
        pass


class LoginPage(LandingPage):
    """An Infomedia login form. accept=False plays a refused password."""
    def __init__(self, ctx, accept):
        super().__init__(ctx)
        self.url, self.accept, self.typed = "https://login.superservice.com/", accept, {}

    def query_selector(self, sel):
        if sel == "button:has-text('Start')":
            return self if self.w.signed_in else None
        if sel in ("input[type=email]", "input[type=password]", "button[type=submit]"):
            if self.w.signed_in:
                return None
            return _Field(self, sel)
        return None


class _Field:
    def __init__(self, page, sel):
        self.p, self.sel = page, sel

    def fill(self, v):
        self.p.typed[self.sel] = v

    def click(self):
        if self.sel == "button[type=submit]" and self.p.accept:
            self.p.w.signed_in = True


class Ctx:
    def __init__(self, w, first=None):
        self.w = w
        self.pages = [first(self) if first else LandingPage(self)]

    def new_page(self):
        p = LandingPage(self)
        self.pages.append(p)
        return p


# ---------------------------------------------------------------- the system
class Env:
    """Everything one offline test needs, wired to tmp_path."""

    def __init__(self, monkeypatch, tmp_path):
        self.tmp = tmp_path
        self.req, self.res = tmp_path / "requests", tmp_path / "results"
        self.req.mkdir()
        self.res.mkdir()
        self.alerts, self.beats, self.submitted = [], [], []
        RunLock.held.clear()
        RunLock.force_busy = False
        self.RunLock = RunLock

        for name in BLOCKED:
            monkeypatch.setitem(sys.modules, name, None)
        for name, mod in self._stubs().items():
            monkeypatch.setitem(sys.modules, name, mod)
        monkeypatch.syspath_prepend(CODE)
        for k in ("MICROCAT_USERNAME", "MICROCAT_PASSWORD"):
            monkeypatch.delenv(k, raising=False)

        mr = fresh_import(monkeypatch, "microcat_runner")
        # EVERY file the runner writes, moved off the live system
        monkeypatch.setattr(mr, "HERE", str(tmp_path))      # .env + refusal stamp
        monkeypatch.setattr(mr, "LOG", str(tmp_path / "microcat_runner.log"))
        monkeypatch.setattr(mr, "HUMAN_FLAG", str(tmp_path / "human.flag"))
        monkeypatch.setattr(mr, "BUSY_FILE", str(tmp_path / "busy.json"))
        monkeypatch.setattr(mr, "SIGNIN_REFUSED", str(tmp_path / "refused.json"))
        monkeypatch.setattr(mr, "CAPTURES", str(tmp_path / "captures"))
        monkeypatch.setattr(mr, "_carjam_chassis", lambda v: "")   # never call CarJam
        self.mr = mr
        self.world = World()
        env = self

        class FakeMicrocat(mr.Microcat):
            """The real Microcat, minus Playwright: open() hands it a fake tab."""
            first_page = None

            def __init__(self, **_k):
                self.sub = "API HELPER"
                self._pw = None
                self._browser_lock = None

            def open(self, wait_seconds=30, human=False):
                self.ctx = Ctx(env.world, FakeMicrocat.first_page)
                self.page = self.ctx.pages[0]
                return self

            def close(self):
                self._release_browser()

            def capture(self, name):
                return name

        monkeypatch.setattr(mr, "Microcat", FakeMicrocat)
        self.Microcat = FakeMicrocat

    def _stubs(self):
        env = self

        def validate(job):
            p = env.res / (job + ".json")
            if not p.exists():
                return {}, [], [f"{job}: no result yet"]
            d = json.loads(p.read_text(encoding="utf-8"))
            rows = {str(r["line"]): r for r in d["rows"]}
            return rows, [r for r in d["rows"] if r["confidence"] != "CONFIRMED"], []

        def submit_request(job, vin, lines, make="", model="", source=""):
            env.submitted.append({"job": job, "vin": vin, "make": make})
            env.request(job, vin, lines, make)

        partfinder = _module("partfinder", REQ_DIR=str(self.req), RES_DIR=str(self.res),
                             validate=validate, submit_request=submit_request,
                             looks_like_oem=lambda n, cat: True,
                             lookup_learned=lambda *a, **k: ("", ""),
                             lookup_not_on_vehicle=lambda *a, **k: "",
                             _read_json=lambda p: json.load(open(p, encoding="utf-8")))
        return {
            "partfinder": partfinder,
            "runlock": _module("runlock", RunLock=RunLock),
            "chrome_session": _module("chrome_session", _park=lambda: None,
                                      detach=lambda ctx: None, ensure=lambda: (False, "")),
            "browser_guard": _module("browser_guard", beat=lambda ch: env.beats.append(ch),
                                     api_helper_user_data_dir=lambda: "API HELPER"),
            "catalogue_alert": _module("catalogue_alert",
                                       alert=lambda *a, **k: env.alerts.append((a, k)),
                                       clear=lambda *a: None),
        }

    # ---- helpers the tests use
    def request(self, job, vin, lines=None, make="TOYOTA", age_rank=0):
        """Put a request in the queue. Higher age_rank = older (pending() works
        newest first, so rank 0, 1, 2 come out in that order)."""
        lines = lines or [{"line": "1", "description": "Rear Bumper Cover", "qty": 1}]
        p = self.req / (job + ".json")
        p.write_text(json.dumps({"vin": vin, "make": make, "model": "", "lines": lines}),
                     encoding="utf-8")
        t = 1_000_000 - age_rank
        os.utime(p, (t, t))

    def results(self):
        out = {}
        for p in sorted(self.res.glob("*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            out[p.stem] = [(r["confidence"], r["oem_no"]) for r in d["rows"]]
        return out

    def log(self):
        p = self.tmp / "microcat_runner.log"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def opened(self):
        """A Microcat already attached to the fake browser."""
        return self.mr.Microcat().open()

    def desk(self, monkeypatch, job):
        """desk_finder, on a stub desk_core that holds this one job."""
        saved = {}
        core = _module("desk_core", ROOT=CODE, log=lambda *a: None,
                       run_system=lambda j: None,
                       save_job=lambda j: saved.update(job=j),
                       load_job=lambda _id: json.loads(json.dumps(job)),
                       vehicle_make=lambda j: j.get("make", ""),
                       pn_of=lambda l: l.get("pn", ""),
                       set_pn_text=lambda l, n: l.__setitem__("pn", n),
                       apply_proposal=lambda l, n, why: l.__setitem__("proposed", n))
        monkeypatch.setitem(sys.modules, "desk_core", core)
        df = fresh_import(monkeypatch, "desk_finder")
        return df, saved


def fresh_import(monkeypatch, name):
    """Import `name` anew for one test, and put back whatever was in
    sys.modules before - including nothing. A plain delitem + import would
    leave the stub-wired copy behind for the next test, or for the live tests
    run in the same session."""
    monkeypatch.setitem(sys.modules, name, None)      # records the original
    del sys.modules[name]
    return importlib.import_module(name)


def _module(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    return m
