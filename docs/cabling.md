# Structured Cabling Standard (ANSI/TIA-568-B)

## T568B pinout (RJ-45 8P8C)

| Pin | Wire Color |
| --- | --- |
| 1 | White/Orange |
| 2 | Orange |
| 3 | White/Green |
| 4 | Blue |
| 5 | White/Blue |
| 6 | Green |
| 7 | White/Brown |
| 8 | Brown |

Terminate every run at **both ends** to the same standard (T568B end-to-end)
— mixing T568A and T568B on one cable makes a crossover, not a straight-through.

## Certification

Every terminated cable must pass a digital continuity/pinout tester before
being trusted in the rack:

- All 8 pins map straight through, pin-for-pin.
- No split pairs (pairs must be 1-2, 3-6, 4-5, 7-8 — a "correct-looking"
  pinout can still have wires from the wrong physical pair, which passes a
  simple continuity check but destroys 1000BASE-T/10GBASE-T signal
  integrity through crosstalk).
- No opens, shorts, or miswires reported.

Label both ends with source/destination before dressing into the rack.

## Physical isolation (EMI)

- Route 120V/240V AC power cabling and low-voltage Ethernet on **opposite**
  sides of the rack rails, minimum 5 cm separation at all times.
- Where AC and data must cross, cross them at 90° — never run them
  parallel for any distance, even briefly.
- Keep Cat6 runs away from fluorescent ballasts, motors, and switching
  power supplies.

## Cable management

- Secure exclusively with **Velcro straps**. Never use plastic zip ties —
  over-tightening crushes the twisted-pair geometry inside the jacket and
  measurably degrades return loss / crosstalk margin at 10G rates.
- Leave a service loop at both ends (patch panel and NIC) so a drive
  hot-swap or NIC replacement doesn't require re-terminating the run.
- Front-to-back airflow: cable dressing must never block intake or exhaust
  vents on the chassis face or rear.

## Link validation after termination

```
ethtool eth0 | grep -E 'Speed|Duplex|Link detected'
```

Confirm the negotiated speed/duplex matches the intended link rate (1000
or 10000 Mbps, full-duplex) before relying on the run for production or
`iperf3` saturation testing (`phase2-networking/scripts/network-diagnostics.sh`).
