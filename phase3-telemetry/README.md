# Phase 3 — Hardware Telemetry Daemon & Alert Pipeline

An active telemetry agent that polls low-level physical sensors, flags
degradation before catastrophe, and streams metrics to Prometheus/Grafana
plus a webhook alert channel.

## Components

| Path | Purpose |
| --- | --- |
| `telemetryd/telemetryd.py` | The async daemon itself (stdlib + PyYAML only) |
| `telemetryd/tests/` | Automated test suite (19 tests) — see "Testing" below |
| `telemetryd/telemetryd.service` | systemd unit, `CAP_SYS_RAWIO`, no root |
| `telemetryd/config.yaml.example` | Poll intervals, thresholds, webhook URL |
| `prometheus/prometheus.yml.example` | Scrapes node_exporter (with the textfile collector enabled) |
| `prometheus/alert.rules.yml` | Alerting rules over telemetryd's metrics |
| `alertmanager/alertmanager.yml.example` | Routes warning → Slack, critical → PagerDuty |
| `grafana/dashboard.json` | Thermal heatmap, disk endurance, interface drops |

## What it polls

- **S.M.A.R.T.** via `smartctl --json`: attribute 5 (reallocated sectors),
  197 (pending sectors), 198 (uncorrectable sectors).
- **Thermals** from `/sys/class/thermal/thermal_zone*/temp`.
- **Hardware faults** by tailing `/dev/kmsg` for MCE / EDAC(ECC) / AER lines.

## Anomaly detection

A 5-minute sliding window (`SlidingWindow` in `telemetryd.py`) computes a
moving average and its drift from an initial baseline. Alerts fire only on
sustained drift (default: >15°C over baseline for thermals; any increase
in a S.M.A.R.T. raw value), not on single transient spikes.

## Running it

```
pip install -r telemetryd/requirements.txt
useradd --system --no-create-home telemetry
setcap cap_sys_rawio+ep "$(readlink -f "$(command -v smartctl)")"   # or use the sudoers.d fallback in phase1

sudo cp telemetryd/telemetryd.py /opt/telemetryd/telemetryd.py
sudo mkdir -p /etc/telemetryd && sudo cp telemetryd/config.yaml.example /etc/telemetryd/config.yaml
sudo cp telemetryd/telemetryd.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now telemetryd
```

### Testing without real hardware

The daemon has a `--mock` mode that synthesizes S.M.A.R.T./thermal readings
and never touches `smartctl`, sysfs, or `/dev/kmsg`:

```
python3 telemetryd/telemetryd.py --mock --once -v --config telemetryd/config.yaml.example
```

There's also a real automated test suite, not just manual runs:

```
cd telemetryd && python3 -m unittest discover -s tests -v   # 19 tests
```

It covers the sliding-window math, the Prometheus textfile writer, webhook
dispatch (including a genuine unreachable-endpoint failure), a full
TelemetryDaemon integration run, and — via a small, deliberate testability
fix (`ThermalCollector` now takes a configurable `base` path instead of
hardcoding `/`) — the **real** (non-mock) sysfs-thermal-glob code path and
the **real** `/dev/kmsg`-tailing fault-detection path, both against fake
files standing in for hardware this sandbox doesn't have. Those two code
paths were never actually exercised by the original manual verification,
since this sandbox has no real thermal zones or `/dev/kmsg` to fall
through to them. Real `smartctl` on a real disk has still never run.

## Wiring into Prometheus/Grafana

```
sudo cp prometheus/prometheus.yml.example /etc/prometheus/prometheus.yml
sudo cp prometheus/alert.rules.yml /etc/prometheus/alert.rules.yml
sudo cp alertmanager/alertmanager.yml.example /etc/alertmanager/alertmanager.yml
# Import grafana/dashboard.json via Grafana UI -> Dashboards -> Import
```

node_exporter must be started with
`--collector.textfile.directory=/var/lib/node_exporter/textfile_collector`
so it picks up `hardware.prom`.
