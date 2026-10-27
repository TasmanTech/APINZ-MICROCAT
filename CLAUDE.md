# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this folder is

A **review snapshot** (packaged 21 Oct 2026), not a runnable project and not a git repo. It holds part of Brendon's parts-desk automation so a developer can review the Microcat VIN + description -> Toyota/Lexus part-number lookup.

- `Microcat lookup code 2026-10-21/`: the five Python modules plus `READ_ME_FIRST.txt` (end-to-end flow) and `WIRING_partly_desk_endpoint.txt` (an excerpt of the Flask app behind the desk button).
- `Microcat logs for coder 2026-10-21/`: `microcat_runner.log` (2.1 MB, 19 Aug to 21 Oct 2026), `microcat_robustness.log`, `READ_ME_the_evidence.txt` (summary of the log), and `MICROCAT_LOGIN_FOR_CODER.md` (the open sign-in issues and the order to fix them in).

The live system is at `D:\PowerBI\Automation_System` on Brendon's machine. Many imports are **not in this snapshot**: `partfinder`, `desk_core`, `desk_frame`, `partly_desk`, `runlock`, `browser_guard`, `chrome_session`, `attempt_log`, `partsouq_client`. They can't be run or imported here, so don't try. To understand their behaviour, read how these files call them.

## Commands (they only work on the live machine)

There are no build, lint or test commands. Each script has its own CLI, documented in its module docstring:

```
python microcat_runner.py --check              # is API HELPER signed in?
python microcat_runner.py --status             # queue at a glance
python microcat_runner.py --explore <VIN>      # dump the page, pin selectors
python microcat_runner.py --run [--all] [--job <ID>] [--limit N]
python microcat_robustness.py [rounds]         # repeated real lookups, failures classified
python microcat_diagram.py <VIN> <search term> # fetch the illustration GIF
python microcat_cart.py [--job <n>]            # read the Microcat order page
```

The desk itself is a Flask app at `http://localhost:5077`, started with `START PARTLY DESK.bat`.

## Architecture

Flow: desk button `findMicrocat()` -> `partly_desk.py` -> `desk_finder.find_numbers(job, force_microcat=True)` -> `partfinder.submit_request()` writes a request -> `microcat_runner.run(jobs=[...])` drives the browser and writes `partfinder\results\<job>.json` -> `partfinder.validate()` -> desk_finder writes the answers back onto the job lines.

- **The contract between runner and desk is the results file.** Every row is stamped `CONFIRMED`, `PROPOSED` or `NOT_FOUND`. Only `CONFIRMED` fills in a part number. `PROPOSED` goes to the yellow Confirm box for a person to accept. Learned mappings (`partfinder.lookup_learned`) are checked first and need no browser.
- **"Not searched" must never be reported as `NOT_FOUND`.** If `validate()` returns problems (for example the browser was busy), `find_numbers` returns early and marks the lines unanswered.
- **The browser is attached, never launched.** Playwright connects over CDP (port 9222) to the dedicated **API HELPER** Chrome profile. That profile is found by its *display name* in Chrome's Local State, and the runner fails closed if it's missing. It must never land on `Default`, which is Brendon's personal profile with his banking open. The old flags `--headless` and `--profile-copy` were removed on purpose, so don't add them back.
- **Only one browser user at a time.** `runlock` serialises passes. A dashboard click writes `HUMAN_FLAG` (`human_wants_browser.flag`), which background users give way to, and `microcat_busy.json` feeds `busy_message()`.
- **Matching** (`best_match`, `group_phrase`, `translate`, `GLOSSARY`, `SIDE_WORDS` in `microcat_runner.py`): the runner walks to the body group and scores grid rows. A row has to earn `CONFIRMED`, and side (RH/LH) and front/rear gates apply.
- `microcat_cart.py` only reads the Orders page. It must **never** click Place Order.
- `microcat_diagram.py` fetches the illustration GIF, because quantities and what's included are only printed on the drawing. The grid's "Quantity 1" is per part number, not per car.

## Domain rules that are easy to get wrong

- **Toyota and Lexus only.** Other makes return a "needs PartsLink24" error before anything is searched. Pass the real make through. Don't default it to `TOYOTA`.
- **The PNC is not the part-number prefix.** The two differ on 31.2% of genuine parts. For example, Hilux PNC 52152 is the RH bar, and its part number starts with 52151.
- No VIN means no Microcat search.
- The code records history in comments that are dated and quote Brendon (e.g. `# 29 Sep 2026 (Brendon): ...`), each explaining why a rule exists. Keep that style when changing behaviour, and don't delete those comments as clutter.

## Known open issues (see `MICROCAT_LOGIN_FOR_CODER.md`)

1. No credentials are configured, so `sign_in()` silently does nothing. Auto sign-in has succeeded 0 times in the log. The 29 Sep `errorCode=1` means the credentials were refused. Credentials now come from `MICROCAT_USERNAME` / `MICROCAT_PASSWORD`: a real environment variable is used first, then the git-ignored `.env` beside `microcat_runner.py` (template: `.env.example`). This replaced `microcat_credentials.json`; the log and the older `.md` notes still use the old name.
2. A skipped auto sign-in should be logged loudly.
3. `sign_in()` uses `fill()`, while the rest of the file types real keystrokes with `keyboard.type(..., delay=35)`.
4. The `signed_in()` docstring and the log message near line 2204 still say "the runner never types credentials". That rule was reversed on 1 Oct 2026.
