# Phase 2 — Deterministic Networking & Traffic Control

Replaces dynamic/unpredictable network configuration with static routing,
segmented traffic paths, and a stateful default-deny firewall.

## Layout

| Path | Purpose |
| --- | --- |
| `netplan/01-netcfg.yaml` | Declarative static IP + VLAN config via `systemd-networkd` |
| `nftables/nftables.conf` | Atomic default-deny firewall: stateful input/forward/output, SYN rate-limiting, egress allow-list, NAT for the diagnostic namespace |
| `scripts/setup-vlan.sh` | Imperative 802.1Q VLAN sub-interface creation (ad-hoc/testing) |
| `scripts/setup-diag-netns.sh` | Creates/tears down the isolated `diag-ns` network namespace + veth pair |
| `scripts/network-diagnostics.sh` | Runs `iperf3`, a cross-VLAN leak-check capture with `tcpdump`, and an `ss -tulpn` socket audit |
| `policy_sim/` | A Python model of the firewall's decision logic — see "Testing the firewall logic" below |

## Apply

```
sudo cp netplan/01-netcfg.yaml /etc/netplan/01-netcfg.yaml
sudo netplan generate
sudo netplan apply

sudo nft -c -f nftables/nftables.conf   # syntax-check first
sudo cp nftables/nftables.conf /etc/nftables.conf
sudo systemctl enable --now nftables

sudo ./scripts/setup-diag-netns.sh
```

## Validate

```
sudo ip netns exec diag-ns \
    IPERF_TARGET=10.10.100.1 ./scripts/network-diagnostics.sh
```

Everything here supports `SIMULATE=1` for dry runs on hardware that doesn't
match the target NIC/VLAN layout yet.

## Testing the firewall logic without loading it into a live kernel

`nftables.conf` is syntax-checked with the real `nft -c` binary (see
`make lint`) — but actually *loading* the ruleset (even into this
sandbox's own, isolated network namespace, not a real VM) was attempted
while building this and denied by the environment's own security policy,
correctly, since it would weaken this container's own network posture to
test a firewall on it. There is no live-kernel verification of rule
*behavior* anywhere in this repo.

`policy_sim/` is the mitigation: a hand-maintained Python model of the
ruleset's intended decision logic (34 tests — every accept/drop path in
all three chains, the SYN rate limiter as an actual token bucket, and a
literal-text consistency guard against `nftables.conf` itself so a port
or CIDR changed in one place without the other fails loudly). Read
`policy_sim/firewall.py`'s module docstring before treating this as
proof the real firewall behaves this way — classified as **SIMULATION
TESTED**, not real-netfilter-tested, in `PROJECT_SPEC.md`'s ledger.

```
cd policy_sim && python3 -m unittest discover -s tests -v
```

## Design notes

- **Default deny everywhere.** `input`, `forward`, and `output` chains all
  end in `policy drop`; every accepted flow is explicit.
- **diag-ns never touches production routes.** Diagnostic traffic is
  confined to its own namespace and reaches the internet only through a
  dedicated NAT rule (`table ip nat`), never through the host's main routing
  table — so a `tcpdump` or `iperf3` run can never leak into or be confused
  with production traffic.
- **SYN flood mitigation** uses an nftables `meter`, not a separate
  userspace daemon — one less moving part to keep alive.
