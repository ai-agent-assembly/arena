"""Match runner: orchestrates matches and executes agents against trials.

`arena.runner.match` implements match/trial orchestration (AAASM-4373):
loading a scenario, selecting compatible agents, and running every trial for
every selected agent through a `Runner` (`arena.runner.base`), emitting
lifecycle events (`arena.runner.events`) along the way. `arena.runner.noop`
is a temporary placeholder `Runner` implementation; the real execution
backends (process, Docker) land in AAASM-4374/4375.
"""
