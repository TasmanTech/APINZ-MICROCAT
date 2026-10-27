MICROCAT LOOKUP - VIN + DESCRIPTION -> PART NUMBER
Packaged 21 Oct 2026 for Brendon.

HOW IT RUNS, END TO END

 1. You press "Find numbers (Microcat)" on the desk.
    desk_page.html -> findMicrocat()
    tooltip: "Microcat lookup with the VIN, as before: numbers it CONFIRMS are
    filled in and saved on the line. Toyota / Lexus only. A minute or two."

 2. partly_desk.py receives it and calls:
       desk_finder.find_numbers(job, force_microcat=True)
    force_microcat=True means "run exactly the old Microcat path", not the
    newer frame finder.

 3. desk_finder.py collects the lines with NO part number, and for each one
    hands microcat_runner the VIN and the description.

 4. microcat_runner.py does the real work: signs in, opens the car BY VIN,
    walks to the body group, reads the illustrated parts grid, and matches the
    description against the rows.

 5. Only a number Microcat CONFIRMS is written back onto the line. Anything
    uncertain is listed beside the line and left for a person - the same rule
    as PartsLink24, because a catalogue cannot reliably tell R/H from L/H.

WHAT IS IN THE ZIP

  desk_finder.py                        9987 bytes
      THE ORCHESTRATOR. The dashboard button lands here. Decides whether to run the frame finder or Microcat, loops the lines with no number, and writes back only what Microcat CONFIRMS.

  microcat_runner.py                  109536 bytes
      THE ENGINE. Drives Microcat itself: signs in, opens the car by VIN, walks to the body group, reads the illustrated parts grid, matches the description to a row. This is the big one and the oldest - PartsCheck has used it since before the desk existed.

  microcat_diagram.py                   6232 bytes
      THE DRAWING. Fetches the illustration behind a part so the desk can show it - the bracket on the drawing says what comes with the part and how many the car takes.

  microcat_cart.py                      6580 bytes
      THE BASKET. Adds confirmed parts to the Microcat cart.

  microcat_robustness.py                6274 bytes
      THE GUARDS. What to do when Microcat is slow, signed out, or the grid is not where it should be.

  WIRING_partly_desk_endpoint.txt       1399 bytes
      The Flask endpoint behind the button.

TWO THINGS WORTH KNOWING BEFORE READING THE CODE

  * Toyota and Lexus only. Microcat is not licensed for other makes here, which
    is why the desk shows "No catalogue for <make>" on everything else.

  * THE PNC IS NOT THE PART NUMBER PREFIX. Microcat's PNC is the callout on the
    drawing. For the Hilux rear bumper end, PNC 52152 is the RH bar and its part
    number starts 52151; PNC 52153 is the LH bar and its number starts 52152.
    Measured across our own stock, the PNC differs from the part-number prefix
    on 31.2% of genuine parts. Assuming they are the same puts you on the wrong
    side of the car.
