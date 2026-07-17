"""Optional CLI wrapper around the same full refresh the in-app
"Update all data" button runs. Handy for scheduled/headless refreshes:

    .venv\\Scripts\\python.exe scripts\\update_data.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Allow running as `python scripts/update_data.py` from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import refresh  # noqa: E402


def main() -> int:
    started = time.time()
    failures = 0
    for job in refresh.jobs():
        outcome = refresh.run_job(job)
        if outcome.ok and not outcome.stale:
            print(f"  [ok]     {outcome.name}")
        elif outcome.ok:
            print(f"  [cache]  {outcome.name} (source failed, kept previous: "
                  f"{outcome.error})")
        else:
            print(f"  [FAIL]   {outcome.name}: {outcome.error}")
            failures += 1
    print(f"\nDone in {time.time() - started:.0f}s, {failures} hard failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
