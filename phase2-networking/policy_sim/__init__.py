"""policy_sim — a Python model of nftables/nftables.conf's DECISION LOGIC.

Read `firewall.py`'s module docstring before treating anything here as
proof the real firewall behaves this way — it is a hand-maintained
model, not something derived by parsing or executing the real ruleset,
built specifically because loading the real ruleset into this sandbox's
own network namespace to test it live was denied by the environment's
own security policy (a reasonable refusal: it would weaken this
container's own posture to test it). See PROJECT_SPEC.md's testing
ledger for exactly what this does and doesn't prove.
"""
