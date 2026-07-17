"""Render every page server-side via Streamlit's AppTest and report
uncaught exceptions. Run:  .venv\\Scripts\\python.exe scripts\\page_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

PAGES = ["views/cockpit.py", "views/macro.py", "views/market.py",
         "views/sentiment.py", "views/granny_shots.py", "views/seasonality.py"]

failures = 0
for page in PAGES:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.switch_page(page)
    at.run()
    if at.exception:
        failures += 1
        print(f"[FAIL] {page}")
        for exc in at.exception:
            print(f"       {exc.value}")
    else:
        warnings = [w.value for w in at.warning]
        note = f" (page warnings: {warnings})" if warnings else ""
        print(f"[ok]   {page}{note}")

print(f"\n{failures} page failure(s)")
raise SystemExit(1 if failures else 0)
