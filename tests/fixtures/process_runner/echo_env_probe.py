"""Test fixture entrypoint for `ProcessRunner`'s env-allowlist test.

Not an Arena agent plugin — a minimal real script `ProcessRunner` spawns so a
test can inspect which environment variables actually reach the subprocess.
Prints whether a deliberately-planted host secret (`AASM_TEST_HOST_SECRET`)
leaked through, and whether `PATH` (an allowlisted base var) survived.
"""

from __future__ import annotations

import os

print(f"host_secret={os.environ.get('AASM_TEST_HOST_SECRET', 'ABSENT')}")
print(f"path={'set' if os.environ.get('PATH') else 'unset'}")
