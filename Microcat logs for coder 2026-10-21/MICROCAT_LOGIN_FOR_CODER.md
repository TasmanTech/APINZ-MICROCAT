# Microcat sign-in — conflicts to look at

**For a developer. Written 21 Oct 2026.**
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
there is no login to do. Right now it is signed in and reports
`signed in: True`, under the account **Sam Forsyth / Auto Parts I…**.

---

## CONFLICT 1 — two opposite rules in the same file

`signed_in()` around line 371:

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

There is also a known rejection on record:

> *"it returned errorCode=1 on 29 Sep, which means the credentials were
> refused."*

Worth confirming the account is still valid before assuming the code is at
fault.

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

---

## What is NOT a problem

* Attaching to a running Chrome rather than launching a clean automated one is
  deliberate and good — the session persists, and it keeps the work off
  Brendon's personal browser.
* Failing closed when the API HELPER profile is missing is correct.
* The credential file being git-ignored is correct.
* Refusing to guess when there are no credentials is correct; it is only the
  silence about it that is poor.

---

## Suggested order

1. **Create `microcat_credentials.json`** (copy the EXAMPLE, fill it in) and
   confirm the account still authenticates — this is the one that actually
   stops auto sign-in working.
2. **Make a failed or skipped auto sign-in loud**, so it cannot be inert
   without anyone noticing.
3. **Switch the login to typed keystrokes**, matching the rest of the file.
4. **Fix the stale `signed_in()` docstring.**

Items 1 and 2 are the useful ones. 3 is a hypothesis about the 29 Sep
rejection, not a diagnosis. 4 is tidiness, but it is the kind of stale comment
that sends the next reader down the wrong path.
