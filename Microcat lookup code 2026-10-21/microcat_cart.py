# -*- coding: utf-8 -*-
r"""
====  READ THE MICROCAT ORDER, NEVER PLACE IT  ====
Brendon, 29 Sep 2026: "you can add to order but do not order, and then return to
get all part numbers." And: "just for seeing part number etc."

This is the best part source we have found. Instead of clicking one callout at a
time and reading a pop-up box - which is how I collected FOUR clips when the car
needed FIVE - Brendon adds every part he wants to the Microcat order and the
Orders page then lists the lot as one table:

    Description        Number         Qty
    CLIP               90467-07215      5

One read, every number, every quantity, already filtered by a human who knows
which of them the job actually needs. A screw sitting next to the clips on the
drawing never makes it in, because he did not add it.

    IT READS. IT NEVER ORDERS.
    The Orders page carries a PLACE ORDER button. Nothing in this file clicks
    anything - it only pulls innerText out of the page. Placing an order spends
    Brendon's money and that stays a human click, permanently.

    python microcat_cart.py                 print what is in the order now
    python microcat_cart.py --job 32764     and say how it maps to that job
"""
import json
import os
import re
import sys
import time
import urllib.request

import websocket

CDP = "http://127.0.0.1:9222/json/list"
# Toyota/Lexus numbers, hyphen optional, optional two-char colour/trim suffix
# FIVE DIGITS, not five characters. The first cut matched the word
# "Description" - DESCR + IPTION fits [0-9A-Z]{5}-?[0-9A-Z]{5,6} exactly -
# and put a column heading in the parts list. A Toyota PNC is five digits.
NUM = re.compile(r"^([0-9]{5})-?([0-9A-Z]{5,6})(-[A-Z0-9]{2})?$")


def _page():
    d = json.load(urllib.request.urlopen(CDP, timeout=10))
    for t in d:
        if t.get("type") == "page" and "microcat" in (t.get("url") or ""):
            return t
    return None


def page_text():
    """The longest innerText across every execution context.

    Microcat EPC draws inside iframes - around 30 contexts - so the top frame's
    body is the shell only. Reading just the top frame is why I twice told
    Brendon "no change" while the answer was on his screen."""
    p = _page()
    if not p:
        raise RuntimeError("Microcat is not open on the API HELPER browser (port 9222)")
    ws = websocket.create_connection(p["webSocketDebuggerUrl"], timeout=25)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        ctxs, t0 = [], time.time()
        while time.time() - t0 < 4:
            try:
                ws.settimeout(0.9)
                m = json.loads(ws.recv())
            except Exception:
                continue
            if m.get("method") == "Runtime.executionContextCreated":
                ctxs.append(m["params"]["context"]["id"])
        best = ""
        for cid in ctxs:
            ws.send(json.dumps({"id": 800 + cid, "method": "Runtime.evaluate",
                                "params": {"expression": "document.body?document.body.innerText:''",
                                           "returnByValue": True, "contextId": cid}}))
            t1 = time.time()
            while time.time() - t1 < 2:
                try:
                    m = json.loads(ws.recv())
                except Exception:
                    break
                if m.get("id") == 800 + cid:
                    v = ((m.get("result", {}).get("result", {}) or {}).get("value") or "")
                    if len(v) > len(best):
                        best = v
                    break
        return best, (p.get("url") or ""), (p.get("title") or "")
    finally:
        ws.close()


def parse(txt):
    """{'vin':..,'vehicle':..,'parts':[{'description','number','qty'}]}

    The order table comes through innerText as three consecutive lines per row:
        CLIP
        90467-07215
        1
    So a line that looks like a part number is the anchor: the description is
    above it and the quantity below. That is far steadier than matching column
    headings, which move about between Microcat layouts."""
    lines = [l.strip() for l in txt.splitlines()]
    lines = [l for l in lines if l not in ("", "\t")]
    vin = ""
    m = re.search(r"[A-HJ-NPR-Z0-9]{17}", txt.upper())
    if m:
        vin = m.group(0)
    veh = ""
    for l in lines:
        if "(" in l and re.search(r"\(\d{4}\s*-", l):
            veh = l
            break
    parts, i = [], 0
    while i < len(lines):
        mm = NUM.match(lines[i].upper())
        # a number, a description before it and something numeric after it
        if mm and i > 0:
            qty = ""
            for j in (i + 1, i + 2):
                if j < len(lines) and re.fullmatch(r"\d{1,3}", lines[j]):
                    qty = lines[j]
                    break
            desc = lines[i - 1]
            if desc.upper() not in ("NUMBER", "DESCRIPTION", "QTY") and not NUM.match(desc.upper()):
                parts.append({"description": desc, "number": lines[i], "qty": int(qty or 1)})
        i += 1
    # the same part added on two pages is ONE line with the counts added up.
    # Brendon's front bumper: 4 clips on illustration 1 and 1 more on the next
    # page, same number - the car needs five, not "4 or 1".
    rolled = {}
    for p in parts:
        k = p["number"].upper()
        if k in rolled:
            rolled[k]["qty"] += p["qty"]
        else:
            rolled[k] = dict(p)
    return {"vin": vin, "vehicle": veh, "parts": list(rolled.values())}


def read():
    txt, url, title = page_text()
    if "/orders" not in url:
        return {"error": "The browser is not on the Orders page. In Microcat click "
                         "Orders, then run this again.", "url": url[:120],
                "vin": "", "vehicle": title[:90], "parts": []}
    out = parse(txt)
    out["url"] = url[:120]
    return out


def kit_text(parts):
    """The desk's own kit wording: PN*QTY + PN*QTY."""
    return " + ".join(f"{p['number']}*{p['qty']}" for p in parts)


def main():
    r = read()
    if r.get("error"):
        print(r["error"])
        return 1
    print(f"{r['vehicle']}   {r['vin']}")
    if not r["parts"]:
        print("nothing in the order")
        return 0
    print(f"\n{'QTY':>4}  {'NUMBER':<16} DESCRIPTION")
    for p in r["parts"]:
        print(f"{p['qty']:>4}  {p['number']:<16} {p['description'][:55]}")
    print("\nas a desk kit:  " + kit_text(r["parts"]))
    print("\n(read only - nothing here places an order)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
