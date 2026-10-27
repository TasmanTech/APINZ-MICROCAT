# -*- coding: utf-8 -*-
r"""
====  GET THE DRAWING, BECAUSE THE DRAWING IS WHERE THE ANSWER IS  ====
Brendon, 29 Sep 2026:
    "that is how the EPC works - if all in box come with all those parts, or if
     line connect to PNC come with it. So why the diagram is important, not
     search part number and guess."
    "it is only a win if you code it and use it and listen to learn, not shortcuts."

WHAT THE DRAWING HAS THAT NOTHING ELSE HAS
    A horizontal line under a PNC with verticals rising off it means every part
    on those verticals is INCLUDED in that PNC. A dashed leader line means the
    part is shown for fitment but is not included. A black dot means
    non-reusable. And the quantity the car actually takes is printed on the
    drawing in brackets - (11), (7), (4).

    None of that is in any text field. The parts grid gives "Quantity 1" for
    everything, which means one per part number and NOT how many the car needs.
    Reading the grid is how a flare that takes ELEVEN clips got quoted as four.

WHY THIS FETCHES A PICTURE INSTEAD OF SCRAPING
    I spent an hour trying to read the illustration's own parts grid - clicking
    the "Illustrated Parts (35)" tab, clearing both filter inputs - and it kept
    returning the one row the search had filtered to. The image never failed
    once. So: take the picture, keep it with the job, and put it in front of a
    human. When the drawing is on screen the answer takes Brendon three seconds.

    The illustration is a plain GIF on a CDN and needs no session at all.

    python microcat_diagram.py <VIN> <search term>
    python microcat_diagram.py JTHYBBAH002003206 75072
"""
import io
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "diagrams")
INDEX = os.path.join(STORE, "index.json")
CDN = re.compile(r"https://[^\"' ]*superservice\.com/content/live/images/[^\"' ]+\.(?:gif|png|jpg)",
                 re.I)


def _index():
    try:
        return json.load(io.open(INDEX, encoding="utf-8"))
    except Exception:
        return {}


def _save_index(ix):
    os.makedirs(STORE, exist_ok=True)
    with io.open(INDEX, "w", encoding="utf-8") as f:
        json.dump(ix, f, indent=1, ensure_ascii=False)


def fetch_image(url, name):
    """Download the illustration. No credentials - it is a public CDN object,
    which is also why this keeps working when the Microcat session does not."""
    os.makedirs(STORE, exist_ok=True)
    gif = os.path.join(STORE, name + os.path.splitext(url)[1].lower())
    if not os.path.exists(gif):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=60).read()
        with open(gif, "wb") as f:
            f.write(data)
    png = os.path.splitext(gif)[0] + ".png"
    if not os.path.exists(png):
        try:
            from PIL import Image
            Image.open(gif).convert("RGB").save(png)
        except Exception:
            png = gif                      # no PIL: the gif is still readable
    return gif, png


def drawing_for(vin, term, mc=None):
    """{'url','gif','png','section','illustration','part'} for a search term.

    term is best as a PNC or a part number - Brendon's own first move. A
    description here is a coin toss, because the one search box is
    PNC/Part Number/Description/Section all at once.
    """
    close_after = mc is None
    if mc is None:
        sys.path.insert(0, HERE)
        import microcat_runner as mr
        mc = mr.Microcat().open()
    try:
        mc.vin(vin)
        mc.find(str(term))
        mc.page.wait_for_timeout(2500)
        info = mc.page.evaluate("""
        () => {
          let best = '', w = 0;
          document.querySelectorAll('img').forEach(e => {
            if (e.naturalWidth > w && e.naturalWidth > 600) { w = e.naturalWidth; best = e.src; }
          });
          const txt = document.body.innerText;
          return {img: best, width: w, text: txt.slice(0, 4000)};
        }""")
        url = info.get("img") or ""
        if not url or not CDN.match(url):
            m = CDN.search(info.get("text") or "")
            url = m.group(0) if m else url
        if not url:
            return {"error": "no illustration image on this page - the search may "
                             "not have landed on a drawing", "part": str(term)}
        L = [re.sub(r"\s+", " ", x).strip() for x in (info.get("text") or "").splitlines()]
        L = [x for x in L if x]
        section = next((x for x in L if re.match(r"^\d\s+[A-Z]", x)), "")
        illus = next((x for x in L if re.match(r"^\d\d\.\d\d", x)), "")
        d = {}
        for i, x in enumerate(L):
            if x in ("PNC", "Number", "Description", "Quantity") and i + 1 < len(L):
                d.setdefault(x, L[i + 1])
        name = re.sub(r"[^A-Za-z0-9]+", "_", f"{vin}_{illus or term}")[:70]
        gif, png = fetch_image(url, name)
        rec = {"vin": vin, "term": str(term), "url": url,
               "gif": gif, "png": png, "width": info.get("width"),
               "section": section, "illustration": illus,
               "pnc": d.get("PNC", ""), "number": d.get("Number", ""),
               "description": d.get("Description", "")}
        ix = _index()
        ix[f"{vin}|{term}"] = rec
        _save_index(ix)
        return rec
    finally:
        if close_after:
            try:
                mc.close()
            except Exception:
                pass


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip().splitlines()[-2].strip())
        return 2
    r = drawing_for(sys.argv[1], sys.argv[2])
    if r.get("error"):
        print(r["error"]); return 1
    print(f"  section     : {r['section']}")
    print(f"  illustration: {r['illustration']}")
    print(f"  part        : {r['pnc']}  {r['number']}  {r['description']}")
    print(f"  drawing     : {r['png']}  ({r['width']}px wide)")
    print(f"  from        : {r['url']}")
    print("\nOpen that PNG and read the brackets - the quantity the car takes is")
    print("printed on the drawing in ( ), not in the parts grid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
