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
