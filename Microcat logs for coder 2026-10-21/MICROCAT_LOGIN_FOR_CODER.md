# Microcat sign-in — conflicts to look at

**For a developer. Written 21 Oct 2026. Updated 30 Oct 2026** to match the code and the logs (see the status line under each conflict).
File: `D:\PowerBI\Automation_System\microcat_runner.py` (109 KB)

This is the script behind the **Find numbers (Microcat)** button on the parts
desk. It takes a VIN and a part description and returns the Toyota part number.
It does not open its own browser — it attaches to an existing Chrome.

---

## How it works today

**The browser.** A dedicated Chrome called **API HELPER**, its own install at
`D:\PowerBI\Automation_System\api_helper_chrome`, driven over the DevTools
protocol on port 9222. It is deliberately *not* Brendon's personal Chrome:

> Brendon, 11 Aug 2026: *"make sure you check api helper as other days you were
> on my web…"*

`PROFILE_NAME = "API HELPER"`, and the code reads Chrome's own Local State to
find the profile whose **display name** is API HELPER. It fails closed if that
profile is missing, rather than falling back to a personal window.

**The session.** Signing in once leaves a cookie in that profile, so normally
there is no login to do. On 21 Oct it was signed in and reported
`signed in: True`, under the account **Sam Forsyth / Auto Parts I…**.

**Sign-in policy (since 1 Oct 2026).** The runner is meant to sign itself in. If the API HELPER
window is signed out, `sign_in()` reads the login from `microcat_credentials.json` and types it in.
If that file is missing, no attempt is made and a person has to sign in by hand in the API HELPER
window. The older rule, "the runner never types credentials", was reversed on Brendon's
instruction of 1 October and no longer applies.

---

## CONFLICT 1 — two opposite rules in the same file

> **Status: FIXED 30 Oct 2026.** The `signed_in()` docstring now describes the current behaviour,
> and the log line printed after a failed EPC entry no longer says "The runner never types
> credentials."; it now points to `microcat_credentials.json`. Two comments in `_run_locked()` that
> said only a person (or only Brendon) can sign in were also corrected. Comments and log text only;
> no logic changed. The text below shows the file as it was before the fix.

`signed_in()` around line 371 (before the fix):

```python
def signed_in(self):
    """A login screen means a PERSON has to sign in - the runner never types
    credentials (house rule). Report it and stop; do not half-run the queue."""
```

`sign_in()` around line 392, which types credentials:

```python
def sign_in(self):
    """Sign the API HELPER browser in to Infomedia. True if it worked.

    1 Oct 2026. Brendon: "on Microcat just log in, do not ask me, ok, in API
    helper page - or slows down process."

    The old house rule was that a person signs in and the runner never types
    credentials. He has now asked for the opposite..."""
```

**The docstring on `signed_in()` is stale.** It states the rule that was
reversed on 1 October. Anyone reading the file top to bottom will believe the
script never signs itself in, which is wrong. It is a comment, not behaviour, so
nothing is broken — but it is actively misleading.

**Suggested:** rewrite that docstring to say only what the function does (detect
a login screen), and leave the policy statement in `sign_in()` where it belongs.

---

## CONFLICT 2 — the credentials file does not exist, so auto sign-in cannot run

`_credentials()` reads `microcat_credentials.json`:

```python
f = os.path.join(HERE, "microcat_credentials.json")
...
return ()          # when absent or still holding the example text
```

On this machine only **`microcat_credentials.EXAMPLE.json`** is present. The
real file has never been created. So:

* `_credentials()` returns `()`
* `sign_in()` returns `False` immediately
* Microcat only works while a **person** has signed the API HELPER browser in

That is exactly the behaviour Brendon asked to be rid of on 1 October, and it is
silent — the feature looks implemented and is inert. It is correctly
git-ignored (`.gitignore` line 104), so creating it is safe.

**Suggested:** either create the file, or have `sign_in()` log once, loudly,
that auto sign-in is configured but has no credentials — so it is obvious
rather than quiet.

> **Update 30 Oct 2026: the skip is now loud.** `sign_in()` logs "sign-in SKIPPED: no
> microcat_credentials.json…" and `--check` prints "auto sign-in: OFF" when the file is missing.
>
> **Watch out: `.env.example` points to the wrong place.** The code folder has a `.env.example`
> saying to put `MICROCAT_USERNAME` and `MICROCAT_PASSWORD` in a `.env` file. The code never reads
> `.env`; it only reads `microcat_credentials.json` (keys `username` and `password`). Following
> `.env.example` leaves auto sign-in off.

> **Status: still open (the file itself).** Confirmed by the logs: `microcat_runner.log` contains no line from inside
> `sign_in()` at all (no "signed in to Microcat automatically", "sign-in did not take",
> "no username box" or "no password box"). So in every failure since 1 Oct, `sign_in()` stopped at
> the missing-file check and never reached the login form.

**About the "errorCode=1 on 29 Sep" rejection.** This was previously stated as fact, but nothing in
the logs supports it:

* `errorCode` appears **0 times** in `microcat_runner.log` and `microcat_robustness.log`. The only
  place it appears is the code's own failure message in `sign_in()` (around line 462), which still
  states it as fact.
* On 29 Sep the runner **could not** have typed credentials: auto sign-in was only added on 1 Oct.
* The runner log shows the window signed out from 11:05 to 11:11 on 29 Sep, then the EPC opening at
  11:15, so someone signed in by hand in that gap. The robustness test then passed 100% at 12:50 and
  22:39 the same day.

So the account was working on 29 Sep. Where errorCode=1 came from (a mistyped manual sign-in in that
11:11–11:15 gap, another tool sharing the window, or something else) is unknown. It should be
confirmed with whoever saw it before it is used to explain anything.

---

## CONFLICT 3 — the login does not type like a person, the rest of the script does

Everywhere else the script imitates a human. Searching, for example:

```python
p.keyboard.press("Control+a")
p.keyboard.press("Delete")
p.keyboard.type(value, delay=35)        # real keystrokes, 35 ms apart
```

There is even a comment explaining that `keyboard.type()` is used *because* it
produces genuine keystrokes.

But the sign-in sets the fields directly:

```python
u.fill(user)
...
w.fill(pwd)
```

`fill()` writes the value into the DOM in one go. No keydown/keyup, no timing —
which is one of the simplest things a bot check looks at. Given this is a login
form on a vendor portal, and given the 29 Sep `errorCode=1`, this is worth a
look: it may be the credentials, or it may be *how* they are entered.

**Suggested:** use the same `keyboard.type(..., delay=…)` approach for the
username and password as the rest of the file already uses for search boxes, so
the whole script behaves consistently.

> **Update 30 Oct 2026: changed.** `sign_in()` now enters the username and password with
> `_type_like_a_person()` (real keystrokes, 35 ms apart) instead of `fill()`.
>
> **Status: untested, and not the cause of any failure so far.** Because the credentials file has
> never existed, `sign_in()` has never reached the form, so neither method has been tried against
> Infomedia. Note also that the search box uses `keyboard.type()` for a functional reason (its comment
> says the Angular input does not always register `fill()`), not to look human. The first real test
> is simply whether the login form accepts the typed values. If Infomedia turns out to be
> blocking automated sign-ins deliberately, raise it with Infomedia rather than working around it.

---

## What is NOT a problem

* Attaching to a running Chrome rather than launching a clean automated one is
  deliberate and good — the session persists, and it keeps the work off
  Brendon's personal browser.
* Failing closed when the API HELPER profile is missing is correct.
* The credential file being git-ignored is correct.
* Refusing to guess when there are no credentials is correct, and since 30 Oct
  it is logged rather than silent.

---

## Suggested order

1. **Create `microcat_credentials.json`** (copy the EXAMPLE, fill it in) and
   confirm the account still authenticates — this is the one that actually
   stops auto sign-in working. Use the JSON file, not `.env` (see Conflict 2).
2. ~~**Make a failed or skipped auto sign-in loud**~~ Done 30 Oct 2026 (see Conflict 2).
3. ~~**Switch the login to typed keystrokes**~~ Done 30 Oct 2026 (see Conflict 3).
4. ~~**Fix the stale `signed_in()` docstring.**~~ Done 30 Oct 2026 (see Conflict 1).

Item 1 is the one still open. 3 was a hypothesis, not a diagnosis, and the logs show
it cannot explain any failure to date (see Conflict 3). 4 is tidiness, but it is the kind of stale comment
that sends the next reader down the wrong path.
