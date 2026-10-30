MICROCAT TESTS
Written 31 Oct 2026 (Morgan).

Copy this tests folder next to microcat_runner.py on the live machine
(D:\PowerBI\Automation_System\tests) and run from D:\PowerBI\Automation_System.
Needs pytest:   python -m pip install pytest


1. OFFLINE - run any time, on any machine, including the live one

       python -m pytest tests

   The real microcat_runner.py and desk_finder.py, on stand-ins (tests\fakes.py)
   for the queue, the lock, the browser and the desk. NOTHING on the live system
   is read or written: not the queue, not results\, not the runner log, not the
   human flag, not the busy file, not the sign-in refusal file, not the browser.
   Safe while the desk is in use.

   test_matching.py        side, front/rear, spring "bumper", stabilizer "bar",
                           ties go to a person - each one a mistake that reached
                           a quote
   test_session_loss.py    a lapsed session stops the pass, alerts, writes
                           nothing, and is never recorded as "no vehicle"
   test_sign_in.py         loud when there are no credentials, one refusal not
                           one per pass, success only on the Start tile
   test_desk_and_queue.py  what the desk button fills in, proposes, or says;
                           plus every bug fixed on 31 Oct 2026
   test_cart_diagram_robustness.py
                           the cart reads and never orders; the robustness
                           harness names its failures correctly

   Run these after ANY change to microcat_runner.py or desk_finder.py.


2. LIVE - the real Microcat, read-only, on the live machine only

       set MICROCAT_LIVE=1
       python -m pytest tests\live -v

   Skipped unless MICROCAT_LIVE=1. Needs API HELPER open and signed in to
   Microcat. Takes about two minutes and holds the browser while it runs, so
   pick a quiet moment - a scheduled pass that fires meanwhile simply waits its
   turn and stands down as busy.

   What it checks: API HELPER is the profile (never Default); one EPC tab; the
   test VIN opens THAT car; the four parts Brendon confirmed on 29 Sep 2026
   are in the grid; the matcher confirms the LH moulding and will not give it
   to an RH line; the grid scrolls past the first screen; the drawing fetches;
   a made-up VIN is a clean VinNotFound.

   What it will NOT do:
     * write results\ or teach partfinder a number (it never calls run())
     * sign in. A signed-out window SKIPS the tests. To let them use the stored
       login:  set MICROCAT_LIVE_ALLOW_SIGNIN=1
     * ask CarJam about a made-up VIN
     * place an order (the cart test only reads, and skips unless the browser
       is already on the Orders page)
     * write to partfinder\microcat_runner.log - its lines go to
       tests\live\last_live_run.log
     * carry on if someone presses a desk button - it stands down

   It DOES save the test drawing into diagrams\, as microcat_diagram.py always
   does.

   Skip the one-minute unknown-VIN test:   python -m pytest tests\live -m "not slow"

   Run the live tests ON THEIR OWN, not in the same command as the offline
   ones. The suite guards against it, but there is no reason to mix them.

   FIRST LIVE RUN: three expectations were written without a live Microcat to
   check them against - test_grid_is_harvested_past_the_first_screen ("FRONT
   DOOR" gives more than 8 rows), test_matcher_confirms_the_known_lh_moulding
   and test_matcher_will_not_give_the_lh_part_to_an_rh_line. If one fails,
   look at what Microcat actually returned before deciding whether the test
   or the code is wrong.
