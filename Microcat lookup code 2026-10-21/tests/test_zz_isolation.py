# -*- coding: utf-8 -*-
r"""
RUNS LAST IN THIS FOLDER: NO STAND-IN MAY OUTLIVE ITS TEST.  31 Oct 2026 (Morgan).

The offline tests swap in a fake partfinder, runlock, desk_core... If any of
them stayed in sys.modules, a live test in the same session would run the
real browser against a fake queue - or worse, the other way round.
"""
import sys


def test_no_stub_left_behind():
    for name in ("partfinder", "runlock", "chrome_session", "browser_guard",
                 "catalogue_alert", "desk_core", "microcat_runner", "desk_finder"):
        mod = sys.modules.get(name)
        if mod is None:
            continue
        assert getattr(mod, "__file__", None), f"{name} is still a test stand-in"
        if name == "microcat_runner":
            assert getattr(mod.partfinder, "__file__", None), \
                "microcat_runner is still wired to the fake partfinder"
