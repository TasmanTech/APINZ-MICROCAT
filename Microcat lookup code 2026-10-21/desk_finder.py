# -*- coding: utf-8 -*-
r"""
====  PARTLY DESK - FIND THE OEM NUMBER (Microcat, through PartFinder)  ====
Brendon, 21 Sep 2026: "can you build an OEM finder with Microcat in API HELPER."

IT ALREADY EXISTS - this file only plugs the desk into it. partfinder.py +
microcat_runner.py are the shared VIN -> OEM engine PartsCheck has used since
August: VIN into Microcat in the API HELPER browser, right catalogue, number read
off the drawing, CONFIRMED / PROPOSED / NOT_FOUND on every row, confirmed answers
learned for next time. Building a second finder would mean two sets of fixes.

WHAT THE DESK DOES WITH THE ANSWER
    learned before    -> number filled in at once (no browser at all)
    CONFIRMED         -> number filled in, line re-priced
    PROPOSED          -> NOT filled in. Shown on the line as a suggestion; a human
                         types it if it is right. A wrong number is a wrong part
                         on the repairer's bench.
    NOT_FOUND         -> said so on the line.
"""
import datetime
import os
import sys

import desk_core as core

ROOT = core.ROOT

MICROCAT_MAKES = {"TOYOTA", "LEXUS"}


def _engine():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import partfinder
    import microcat_runner
    return partfinder, microcat_runner


def find_numbers(job, human=True, force_microcat=False):
    """human=False is a background caller (a2_rescue.py): it does NOT plant the
    human flag, so a person pressing Find numbers still jumps the queue."""
    # SWITCHED OFF 9 Oct 2026 (Brendon): this searches the WORDING and takes the closest
    # match - never his body-group method. See MICROCAT_NAME_SEARCH_OFF.txt.
    # 13 Oct 2026 (Brendon): both buttons - "Find numbers (frame)" and "Find numbers (Microcat)" - the
    # Microcat button passes force_microcat=True and runs exactly the old Microcat path below.
    if not force_microcat and os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "MICROCAT_NAME_SEARCH_OFF.txt")):
        # 10 Oct 2026 (Brendon): "use the FRAME, not the model - build Partly so it finds numbers and fills them."
        # The name search stays off. The button now runs the FRAME lookup (desk_frame.py): the car's own frame/VIN
        # in the factory catalogue, the PNC from our identification dictionary, noun + side gates, one exact number
        # filled in, anything uncertain listed on the line and NOT filled.
        try:
            import desk_frame
            res = desk_frame.autofill(job) or {}
        except Exception as e:
            return {"asked": 0, "error": "Frame lookup failed: " + str(e)[:160]}
        if res.get("error") or not res.get("asked"):
            return res
        return {"asked": res["asked"], "learned": 0, "confirmed": res.get("filled", 0), "proposed": res.get("several", 0),
                "not_found": res.get("not_found", 0) + res.get("refused", 0), "frame": res.get("frame"),
                "model": res.get("model"), "prod": res.get("prod")}
    j = core.load_job(job)
    if not j.get("vin"):
        return {"error": "No VIN on this job - Microcat is never searched without one."}
    # MICROCAT IS A TOYOTA / LEXUS CATALOGUE.  23 Sep 2026.
    # Job 41604 (Land Rover Range Rover 2019, 40 blank lines) was sent to Microcat
    # and came back "40 not found" in 27 seconds - it had never heard of the car.
    # Forty lines were then reported to Brendon as genuinely not findable, which
    # is a different and much worse statement than "we asked the wrong catalogue".
    # European makes need PartsLink24; until that adapter exists, say so plainly
    # rather than asking a catalogue that cannot answer.
    make = (core.vehicle_make(j) or "").upper()
    if make and make not in MICROCAT_MAKES:
        return {"asked": 0, "error":
                f"Microcat only holds Toyota and Lexus - it cannot identify a {make}. "
                f"{make} needs PartsLink24, which is not wired into the desk yet. "
                f"Nothing was asked and no line has been marked NOT FOUND."}
    need = [l for l in j["lines"] if not core.pn_of(l) and not l.get("kit")]
    if not need:
        return {"asked": 0, "note": "every line already has a number"}
    pf, mr = _engine()
    out = {"asked": len(need), "learned": 0, "confirmed": 0, "proposed": 0, "not_found": 0}
    todo = []
    for l in need:
        num, how = pf.lookup_learned(j["vin"], l["description"], j.get("car", ""))
        if num:
            core.set_pn_text(l, num)
            l.setdefault("notes", {})["finder"] = "Number from " + how
            out["learned"] += 1
        else:
            todo.append(l)
    if todo:
        pfjob = f"PD{job}_{datetime.datetime.now():%H%M%S}"
        pf.submit_request(pfjob, j["vin"],
                          [{"line": str(l["n"]), "description": l["description"], "qty": l["qty"]}
                           for l in todo],
                          # THE REAL MAKE, NOT ALWAYS "TOYOTA".  29 Sep 2026.
                          # This said make="TOYOTA" for every job. The code only
                          # uses make as a Toyota/Lexus gate, so nothing crashed -
                          # but the make is pasted into the prompt the browser
                          # agent reads, so a Lexus UX was handed over labelled
                          # "TOYOTA" and could be looked up in the wrong
                          # catalogue. Brendon, job 32764: "and is for Lexus".
                          # 31 Oct 2026 (Morgan): the `or "TOYOTA"` fallback was
                          # the same bug for a job with NO make - an unknown car
                          # handed over labelled TOYOTA. Blank stays blank; the
                          # VIN is what identifies the car in Microcat.
                          make=make, model=j.get("car", ""),
                          source="partly_desk")
        core.log(job, f"FINDER asked Microcat for {len(todo)} line(s) as {pfjob}")
        # A PERSON PRESSED A BUTTON.  29 Sep 2026.
        # Brendon pressed Find numbers on a Prius and was told the browser was
        # taken - by a background test of mine. A click from the dashboard now
        # plants a flag that every background browser user checks, and the
        # runner waits 2.5 minutes for the browser instead of 30 seconds.
        # Brendon: "make it so it does one at a time - if it busy send message
        # back say looking up another job so be patient."
        if human:
            try:
                with open(mr.HUMAN_FLAG, "w", encoding="utf-8") as _f:
                    _f.write(pfjob)
            except Exception:
                pass
        try:
            mr.run(jobs=[pfjob])                   # drives API HELPER; takes minutes
        finally:
            if human:
                try:
                    import os as _os
                    if _os.path.exists(mr.HUMAN_FLAG):
                        _os.remove(mr.HUMAN_FLAG)
                except Exception:
                    pass
        rows, _misses, problems = pf.validate(pfjob)
        if problems:
            # A MALFUNCTION IS NOT AN ANSWER. 23 Sep 2026: two Find-numbers clicks
            # 2 seconds apart (07:40:17, 07:40:19). The first took the browser lock;
            # the second stood down without running - correct behaviour - and left no
            # result. validate() said "no result yet", and this function then counted
            # all 3 lines NOT_FOUND, exactly as if Microcat had looked and found
            # nothing. It had not looked at all. A line that was never searched must
            # not be reported as a line with no answer.
            #
            # Returning here also means the loop below can no longer run with
            # problems set - which is what used to throw away genuinely CONFIRMED
            # rows because of an unrelated problem on some other line.
            #
            # 31 Oct 2026 (Morgan): "no result yet" also covers a pass that
            # STOPPED - signed out, or the API HELPER window not there - and
            # telling that person "another pass had the browser, press again"
            # sends them round in a loop only signing in can break. run()
            # leaves the real reason in LAST_STOP; it wins over the busy guess.
            stopped = getattr(mr, "LAST_STOP", "")
            busy = not stopped and any("no result yet" in p for p in problems)
            for l in todo:
                l.setdefault("notes", {})["finder"] = (
                    "Microcat has NOT looked at this line yet - "
                    + ("Microcat stopped: " + stopped[:120] if stopped else
                       "another Microcat pass had the browser. Press Find numbers "
                       "again in a minute." if busy else "; ".join(problems[:2])))
            out["unanswered"] = len(todo)
            out["error"] = ("Microcat did NOT answer - nothing was searched. "
                            + ("Microcat stopped: " + stopped if stopped else
                               mr.busy_message() if busy else "; ".join(problems[:3])))
            core.save_job(j)
            core.log(job, f"FINDER NOT ANSWERED {pfjob}: {out['error']}")
            core.run_system(j)
            return out
        for l in todo:
            r = rows.get(str(l["n"])) or {}
            conf, num = str(r.get("confidence", "")).upper(), str(r.get("oem_no") or "").strip()
            note = str(r.get("note") or "")[:120]
            if conf == "CONFIRMED" and num and not problems:
                core.set_pn_text(l, num)
                l.setdefault("notes", {})["finder"] = f"Microcat CONFIRMED {num}. {note}".strip()
                out["confirmed"] += 1
            elif conf == "PROPOSED" and num:
                # Brendon 14 Oct 2026: "found some of part but not added to dashboard".
                # Show it in the yellow Confirm box (priced for supplier asks, but the
                # job cannot be sent until a person confirms it).
                if not core.pn_of(l):
                    core.apply_proposal(l, num, f"Microcat offered {num}. {note}")
                l.setdefault("notes", {})["finder"] = (f"Microcat PROPOSES {num} - press Confirm if right. "
                                                       f"{note}").strip()
                out["proposed"] += 1
            else:
                l.setdefault("notes", {})["finder"] = ("Microcat: NOT FOUND. " + note).strip() if r else \
                    "Microcat gave no answer for this line (is API HELPER signed in to Microcat?)"
                out["not_found"] += 1
    core.save_job(j)
    core.log(job, f"FINDER {out}")
    core.run_system(j)
    return out


# 31 Oct 2026 (Morgan): BODY-TYPE LOOKUP SWITCHED OFF FOR NOW - VIN search only.
# Commented out, not deleted, so it can come back with its button.
# def _body_details(j):
#     """make / model / body / year for a body-type lookup, or None if short.

#     28 Oct 2026: WHICH JOB FIELDS HOLD BODY TYPE AND YEAR IS NOT CONFIRMED YET.
#     "body" and "year" below are placeholders until desk_core's job fields are
#     checked - this is the one place to change when they are. Missing any of
#     the four means no lookup, never a guess."""
#     v = {"make": (core.vehicle_make(j) or "").upper(),
#          "model": str(j.get("car") or "").strip(),
#          "body": str(j.get("body") or "").strip(),
#          "year": str(j.get("year") or "").strip()}
#     return v if all(v.values()) else None


# def find_numbers_by_body(job):
#     """THE NO-VIN BUTTON: "Find numbers (body type)".  28 Oct 2026.

#     Morgan, 28 Oct 2026: a body-type lookup for quotes with no VIN, on its OWN
#     button. It never fills in a number. Without a VIN Microcat cannot apply
#     build date or model code, so everything it finds goes to the yellow Confirm
#     box for a person - the same rule as PROPOSED everywhere else. A job WITH a
#     VIN is sent back to the Microcat button, which is the better answer.
#     """
#     j = core.load_job(job)
#     if j.get("vin"):
#         return {"asked": 0, "error": "This job has a VIN - use Find numbers (Microcat). "
#                                      "The body-type lookup is only for quotes with no VIN."}
#     make = (core.vehicle_make(j) or "").upper()
#     if make and make not in MICROCAT_MAKES:
#         return {"asked": 0, "error":
#                 f"Microcat only holds Toyota and Lexus - it cannot identify a {make}. "
#                 f"Nothing was asked and no line has been marked NOT FOUND."}
#     vehicle = _body_details(j)
#     if not vehicle:
#         return {"asked": 0, "error": "Not enough vehicle detail for a body-type lookup - "
#                                      "it needs make, model, body type and year. "
#                                      "Nothing was asked."}
#     need = [l for l in j["lines"] if not core.pn_of(l) and not l.get("kit")]
#     if not need:
#         return {"asked": 0, "note": "every line already has a number"}
#     _pf, mr = _engine()
#     pdjob = f"PB{job}_{datetime.datetime.now():%H%M%S}"
#     core.log(job, f"FINDER (body type) asked Microcat for {len(need)} line(s) as {pdjob}")
#     res = mr.run_by_body(pdjob, vehicle,
#                          [{"line": str(l["n"]), "description": l["description"], "qty": l["qty"]}
#                           for l in need])
#     out = {"asked": len(need), "confirmed": 0, "proposed": 0, "not_found": 0}
#     if res.get("error"):
#         # NOT SEARCHED IS NOT NOT FOUND - the same rule as find_numbers().
#         for l in need:
#             l.setdefault("notes", {})["finder"] = ("Body-type lookup has NOT looked at this "
#                                                    "line yet - " + res["error"][:160])
#         out["unanswered"] = len(need)
#         out["error"] = "Body-type lookup did NOT run - nothing was searched. " + res["error"]
#         core.save_job(j)
#         core.log(job, f"FINDER (body type) NOT ANSWERED {pdjob}: {res['error'][:160]}")
#         return out
#     rows = {str(r.get("line")): r for r in res.get("rows") or []}
#     for l in need:
#         r = rows.get(str(l["n"])) or {}
#         conf, num = str(r.get("confidence", "")).upper(), str(r.get("oem_no") or "").strip()
#         note = str(r.get("note") or "")[:160]
#         # Only PROPOSED can come back from run_by_body(); anything else with a
#         # number is treated as PROPOSED too, so this button can never fill one in.
#         if num and conf != "NOT_FOUND":
#             if not core.pn_of(l):
#                 core.apply_proposal(l, num, f"Body-type lookup offered {num}. {note}")
#             l.setdefault("notes", {})["finder"] = (f"Body type (no VIN) PROPOSES {num} - "
#                                                    f"press Confirm if right. {note}").strip()
#             out["proposed"] += 1
#         else:
#             l.setdefault("notes", {})["finder"] = ("Body type (no VIN): NOT FOUND. "
#                                                    + note).strip()
#             out["not_found"] += 1
#     core.save_job(j)
#     core.log(job, f"FINDER (body type) {out}")
#     core.run_system(j)
#     return out
