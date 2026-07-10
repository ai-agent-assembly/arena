"""Test fixture entrypoint for `ProcessRunner` tests.

Not an Arena agent plugin — a minimal real script `ProcessRunner` actually
spawns, so tests exercise a genuine subprocess launch/capture instead of a
mock. Prints the `ARENA_*` context env vars `ProcessRunner` is expected to
set to stdout (so tests can assert context delivery), writes a fixed line to
stderr, and exits with the code given as the first CLI argument (default 0).
"""

from __future__ import annotations

import os
import sys

print(f"agent_id={os.environ.get('ARENA_AGENT_ID', '')}")
print(f"trial_id={os.environ.get('ARENA_TRIAL_ID', '')}")
print(f"trial_description={os.environ.get('ARENA_TRIAL_DESCRIPTION', '')}")
print(f"trial_severity={os.environ.get('ARENA_TRIAL_SEVERITY', '')}")
print(f"workspace={os.environ.get('ARENA_WORKSPACE', '')}")
print(f"manifest_env={os.environ.get('FIXTURE_MANIFEST_ENV', '')}")
print("this went to stderr", file=sys.stderr)

exit_code = int(sys.argv[1]) if len(sys.argv) > 1 else 0
sys.exit(exit_code)
