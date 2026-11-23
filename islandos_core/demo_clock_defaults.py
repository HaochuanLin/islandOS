"""The default position of the demo clock, frozen so a default page is reproducible.

Pages 05 and 06 used to pass ``now.date()`` and ``now.hour`` into the synthetic
window, so the same code reported a different annual figure depending on when it
was opened: moving the anchor by one hour moves the 24-hour target window across
the PV/wind ripple (documented range 4,548.68–8,631.34 for the same 186,150 kWh).
The clock is now frozen at 2026-11-22 14:00 UTC — the hour the recorded 7,709.55
figure was measured at — and both sliders stay editable.

Kept in its own module rather than added to ``demo_site_history`` on purpose: a
running Streamlit process keeps imported modules in ``sys.modules``, so editing an
already-imported module does not take effect until the process restarts. A new
module is imported fresh on the next script run.
"""

from __future__ import annotations

from datetime import date

DEMO_CLOCK_DEFAULT_DATE = date(2026, 11, 22)
"""The UTC date the synthetic default window ends on; frozen 2026-11-23."""

DEMO_CLOCK_DEFAULT_HOUR = 14
"""The UTC hour the synthetic default window ends on; the recorded 7,709.55 run."""
