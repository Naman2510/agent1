# Static Network Topology Reference

Fill in the real values for your site before treating this as authoritative
— the table below is the shape of the reference, with the example values
this repo's configs (`phase2-networking/netplan/01-netcfg.yaml`,
`phase2-networking/nftables/nftables.conf`) are written against.

## Subnet allocation

| Segment | CIDR | Purpose |
| --- | --- | --- |
| Production LAN | `10.10.0.0/24` | Primary host traffic |
| Management VLAN (id 100) | `10.10.100.0/24` | SSH, Prometheus scrape, Redfish |
| Diagnostic namespace | `169.254.100.0/30` | `diag-ns` veth link-local, NATed egress only |

## MAC-to-IP bindings

| Hostname | Interface | MAC | IP | VLAN |
| --- | --- | --- | --- | --- |
| edge-server-01 | eth0 | `<replace: aa:bb:cc:dd:ee:ff>` | 10.10.0.10/24 | untagged (native) |
| edge-server-01 | eth0.100 | `<replace>` | 10.10.100.10/24 | 100 |
| bmc-01 (mgmt) | bmc0 | `<replace>` | 10.10.100.20/24 | 100 |

## Gateway & DNS

- Gateway: `10.10.0.1`
- DNS: `1.1.1.1` (Cloudflare), `9.9.9.9` (Quad9)
- NTP: site NTP server or `pool.ntp.org`, UDP/123 egress only (see nftables)

## VLAN tags in use

| VLAN ID | Name | Notes |
| --- | --- | --- |
| (untagged) | Production | Default native VLAN on the switch port |
| 100 | Management/Diagnostic | SSH, metrics scrape, Redfish — see `nftables.conf` for the source-restricted accept rules |

## Firewall summary

See `phase2-networking/nftables/nftables.conf` for the authoritative,
version-controlled ruleset. Summary:

- Default-deny inbound and outbound.
- Inbound SSH/9100(Prometheus)/8443(Redfish) accepted **only** from
  `10.10.100.0/24` (management VLAN), SSH additionally SYN-rate-limited.
- Outbound limited to DNS (53), NTP (123), HTTP/HTTPS (80/443), SSH (22).
- `diag-ns` reaches the internet only via a dedicated NAT rule — never via
  the production routing table.
