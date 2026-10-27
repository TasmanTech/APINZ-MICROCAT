MICROCAT RUNNER LOG - what it shows
============================================================
file      : partfinder\microcat_runner.log
size      : 2.1 MB, 21216 lines
covers    : 2026-08-19 21:54:46  ..  2026-10-21 10:01:56

runs started                         : 698
runs finished                        : 289
attached to API HELPER               : 5265

NOT SIGNED IN / could not enter EPC  : 109   <- the failure
automatic sign-in attempted & failed : 8
automatic sign-in SUCCEEDED          : 0   <- note this number
"Put the login in microcat_credentials.json" : 8
lines mentioning errorCode           : 0
lines about a personal/wrong profile : 5265

days with a sign-in failure (most recent 12):
   2026-10-20   1
   2026-10-19   1
   2026-10-13   2
   2026-10-08   1
   2026-10-07   1
   2026-10-05   2
   2026-10-01   2
   2026-09-30   1
   2026-09-29   3
   2026-09-28   4
   2026-09-25   1
   2026-09-24   2

THE MOST RECENT FAILURE, in full:
   2026-10-20 16:34:41 MICROCAT RUNNER START - 1 job(s) to work, limit 8
   2026-10-20 16:35:12   [runlock] 'microcat_runner' already running (pid=26668 started=2026-10-20 16:34:41, 31s) - this pass exits, next one will pick i
   2026-10-20 16:35:12   another Microcat pass is already running - leaving the queue to it
   2026-10-20 16:35:39   ATTACHED to the live API HELPER window (1 tab(s), none personal) - no new browser opened
   2026-10-20 16:35:42 *** CANNOT ENTER THE MICROCAT EPC: the API HELPER window is not signed in to Microcat and the automatic sign-in did not work. Put 
   2026-10-20 16:35:42     If it says not signed in: sign in once by hand in the API HELPER window. The runner never types credentials.
   2026-10-21 10:01:56   ATTACHED to the live API HELPER window (1 tab(s), none personal) - no new browser opened

WHAT TO TAKE FROM IT
------------------------------------------------------------
* The runner never opens its own browser. Every run attaches to the
  dedicated API HELPER Chrome - the log says so each time, and says
  "none personal", i.e. it checked it was not on Brendon's window.
* When the session lapses the run stops cleanly and says why. It does
  not half-finish a queue.
* The automatic sign-in has succeeded 0 time(s). The credentials file
  microcat_credentials.json has never been created on this machine -
  only the EXAMPLE - so there is nothing for it to sign in WITH.
* The log line after the failure still prints the OLD house rule,
  "The runner never types credentials", which contradicts sign_in().
  Same stale rule as the docstring. See MICROCAT_LOGIN_FOR_CODER.md.