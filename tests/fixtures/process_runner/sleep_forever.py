"""Test fixture entrypoint for `ProcessRunner` timeout tests.

Not an Arena agent plugin — sleeps far longer than any test's configured
`ProcessRunner(timeout_seconds=...)`, so `subprocess.run`'s timeout is
guaranteed to fire against a genuinely still-running process rather than a
race against a script that might finish first.
"""

from __future__ import annotations

import time

time.sleep(60)
