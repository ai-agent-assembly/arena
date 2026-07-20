"""Test fixture entrypoint for `ProcessRunner`'s env-allowlist test.

Not an Arena agent plugin — a minimal real script `ProcessRunner` spawns so a
test can inspect which environment variables actually reach the subprocess.
Prints whether a deliberately-planted host secret (`AASM_TEST_HOST_SECRET`)
leaked through, and whether `PATH` (an allowlisted base var) survived.

Reports the secret's *presence* only, never its value — echoing the value would
both trip clear-text-logging scanners and, if the allowlist ever regressed,
print a real secret to captured stdout.
"""

from __future__ import annotations

import os

print(f"host_secret={'LEAKED' if 'AASM_TEST_HOST_SECRET' in os.environ else 'ABSENT'}")
print(f"path={'set' if os.environ.get('PATH') else 'unset'}")
