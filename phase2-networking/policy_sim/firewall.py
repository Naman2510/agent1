"""A Python model of the DECISION LOGIC in nftables/nftables.conf.

Classification (see PROJECT_SPEC.md's ledger): SIMULATION TESTED. This
is NOT the real nftables ruleset, NOT parsed from it, and NOT verified
against real kernel netfilter — real rule *loading* (not just `nft -c`
syntax checking, which the repo does do — see phase2-networking/README.md)
was attempted in this sandbox and denied by the environment's own
security classifier as a "security weaken" action, a reasonable refusal
since loading live firewall rules would change this container's own
network posture, not a real VM's. This module exists so the *intended*
behavior of the ruleset — who gets in, who gets rate-limited, who gets
out — can still be exercised by real, repeatable tests, with the
honestly-stated limitation that it's a hand-maintained duplicate of the
real file's logic and can drift out of sync with it if one changes
without the other. `tests/test_firewall.py` includes a literal-text
consistency guard against the real file specifically to catch that.

Every rule below cites the exact line(s) in nftables.conf it models.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Dict, Optional

MGMT_VLAN = ipaddress.ip_network("10.10.100.0/24")   # nftables.conf: management-VLAN source checks
DIAG_NS_SUBNET = ipaddress.ip_network("169.254.100.0/30")  # nftables.conf: diag-ns NAT source

ALLOWED_ICMP_TYPES = {"echo-request", "destination-unreachable", "time-exceeded"}  # line 32

Verdict = str  # "accept" or "drop"


@dataclass
class Packet:
    """A minimal packet description — only the fields the real ruleset's
    rules actually match on."""

    src_ip: str
    dst_ip: str = "0.0.0.0"
    protocol: str = "tcp"          # "tcp" | "udp" | "icmp"
    src_port: Optional[int] = None
    dst_port: Optional[int] = None
    iif: Optional[str] = None      # incoming interface name
    oif: Optional[str] = None      # outgoing interface name
    conn_state: str = "new"        # "new" | "established" | "related" | "invalid"
    icmp_type: Optional[str] = None


class TokenBucketRateLimiter:
    """Models nftables' `meter ... { ip saddr limit rate N/second burst B
    packets }` (nftables.conf line 37) as a standard token-bucket keyed
    per source IP — the same algorithm nftables' own meter implements
    internally, re-derived here rather than imported from anywhere,
    since nothing in the stdlib provides it."""

    def __init__(self, rate_per_second: float, burst: int):
        self.rate = rate_per_second
        self.burst = burst
        self._tokens: Dict[str, float] = {}
        self._last_seen: Dict[str, float] = {}

    def allow(self, key: str, now: float) -> bool:
        tokens = self._tokens.get(key, float(self.burst))
        last = self._last_seen.get(key, now)
        elapsed = max(0.0, now - last)
        tokens = min(self.burst, tokens + elapsed * self.rate)
        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0
        self._tokens[key] = tokens
        self._last_seen[key] = now
        return allowed

    def reset(self) -> None:
        self._tokens.clear()
        self._last_seen.clear()


class FirewallPolicy:
    """Evaluates the three chains (input/forward/output) in the same
    top-to-bottom, first-match order nftables itself uses within a
    chain, ending in that chain's default policy if nothing matched —
    exactly mirroring nftables.conf's structure."""

    def __init__(self) -> None:
        # One rate limiter instance per policy object, matching how the
        # real named meter's state persists for the life of the loaded
        # ruleset, not per-packet.
        self.ssh_rate_limiter = TokenBucketRateLimiter(rate_per_second=20, burst=40)

    # -- chain input : nftables.conf lines 21-47 -----------------------------

    def evaluate_input(self, pkt: Packet, now: float = 0.0) -> Verdict:
        if pkt.iif == "lo":  # line 25
            return "accept"
        if pkt.conn_state in ("established", "related"):  # line 28
            return "accept"
        if pkt.conn_state == "invalid":  # line 29
            return "drop"
        if pkt.protocol == "icmp" and pkt.icmp_type in ALLOWED_ICMP_TYPES:  # line 32
            return "accept"
        if (
            pkt.protocol == "tcp"
            and pkt.dst_port == 22
            and pkt.conn_state == "new"
            and self._in_mgmt_vlan(pkt.src_ip)
        ):  # lines 36-37
            if self.ssh_rate_limiter.allow(pkt.src_ip, now):
                return "accept"
            # Rate-limited: the meter simply doesn't match, so — exactly
            # like nftables — we fall through to any later rules (none
            # apply here) and the chain's default policy below.
        if (
            pkt.protocol == "tcp" and pkt.dst_port == 9100
            and pkt.conn_state == "new" and self._in_mgmt_vlan(pkt.src_ip)
        ):  # line 40
            return "accept"
        if (
            pkt.protocol == "tcp" and pkt.dst_port == 8443
            and pkt.conn_state == "new" and self._in_mgmt_vlan(pkt.src_ip)
        ):  # line 43
            return "accept"
        return "drop"  # line 22: policy drop

    # -- chain forward : nftables.conf lines 49-58 --------------------------

    def evaluate_forward(self, pkt: Packet) -> Verdict:
        if pkt.conn_state in ("established", "related"):  # line 52
            return "accept"
        if pkt.conn_state == "invalid":  # line 53
            return "drop"
        if (
            pkt.iif is not None and pkt.iif.startswith("veth-diag")
            and pkt.oif == "eth0" and pkt.conn_state == "new"
        ):  # line 57
            return "accept"
        return "drop"  # line 50: policy drop

    # -- chain output : nftables.conf lines 60-77 ----------------------------

    def evaluate_output(self, pkt: Packet) -> Verdict:
        if pkt.oif == "lo":  # line 63
            return "accept"
        if pkt.conn_state in ("established", "related"):  # line 64
            return "accept"
        if pkt.dst_port == 53 and pkt.protocol in ("udp", "tcp"):  # lines 67-68
            return "accept"
        if pkt.dst_port == 123 and pkt.protocol == "udp":  # line 69
            return "accept"
        if pkt.dst_port in (80, 443) and pkt.protocol == "tcp":  # line 70
            return "accept"
        if pkt.dst_port == 22 and pkt.protocol == "tcp":  # line 74
            return "accept"
        return "drop"  # line 61: policy drop

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _in_mgmt_vlan(ip: str) -> bool:
        try:
            return ipaddress.ip_address(ip) in MGMT_VLAN
        except ValueError:
            return False
