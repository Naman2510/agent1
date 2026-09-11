# Dashboard — Web Front End

A single-page operations dashboard for the platform: live power/RAID/thermal
status, S.M.A.R.T. and thermal detail, network state, a live alert feed fed
by telemetryd's webhook, and Redfish-based OOB control buttons (power-cycle,
boot override, drive LED) — all backed by the same code the CLI/daemon use,
not a reimplementation of it.

## Architecture

- **`server.py`** — a stdlib-only (`http.server` + `requests` via the
  imported `oob_control` module) backend. No Flask/Django/npm build step —
  consistent with the zero-dependency style of the rest of this repo.
- **`static/`** — plain HTML/CSS/JS, no framework or build step. Served
  directly by `server.py`.

It does not reimplement anything: RAID state comes from parsing
`/proc/mdstat` directly, S.M.A.R.T./thermal data comes from parsing
telemetryd's own Prometheus textfile output, and every OOB action calls
into `phase4-oob-lifecycle/oob_control.py`'s `RedfishClient` by importing
the module directly.

## Run it

```
pip install -r requirements.txt
cp config.yaml.example config.yaml   # edit paths/Redfish endpoint for your host
python3 server.py --config config.yaml
```

Then open `http://<host>:8080/`.

### Wiring up live data

- **Telemetry/S.M.A.R.T./thermal**: point `textfile_collector_path` in
  `config.yaml` at the same path telemetryd writes to
  (`phase3-telemetry/telemetryd/config.yaml`'s `textfile_collector_path`).
- **Live alert feed**: set telemetryd's `webhook_url` to
  `http://<dashboard-host>:8080/api/alerts/ingest` — every sliding-window
  breach and kmsg fault telemetryd detects then shows up in the dashboard's
  alert feed in real time, no polling needed on that side.
- **OOB control**: point `redfish_base_url` at a real BMC or one of the
  options in `phase4-oob-lifecycle/redfish-mockup/`.
- **RAID/network**: read live from the host (`/proc/mdstat`, `ip -j`,
  `ss`, `nft -j list ruleset`) when the dashboard runs directly on the
  edge server; falls back to showing the repo's static config with a
  clear "no live data" note when it doesn't (e.g. running the dashboard
  from a laptop against a remote Redfish endpoint only).

## API

All JSON, no auth (put this behind the management VLAN + the nftables
rules in `phase2-networking/`, same as Prometheus/Redfish — it is an
internal admin surface, not internet-facing).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/overview` | Summary card data: power state, RAID health, fault count, 5 most recent alerts |
| GET | `/api/storage` | `/proc/mdstat` parsed + S.M.A.R.T. attributes from the textfile |
| GET | `/api/telemetry` | Full parsed Prometheus textfile (thermal zones, S.M.A.R.T., fault counter) |
| GET | `/api/network` | Live `ip`/`ss`/`nft` state, or the static netplan config as a fallback |
| GET | `/api/alerts` | The in-memory alert feed |
| POST | `/api/alerts/ingest` | Webhook receiver — point telemetryd's `webhook_url` here |
| GET | `/api/oob/power-status` | Proxies to Redfish `GET /Systems/{id}` |
| POST | `/api/oob/power-cycle` | `{"reset_type": "cycle"\|"on"\|"off"\|"graceful-shutdown"\|"force-restart"}` |
| POST | `/api/oob/boot-override` | `{"target": "pxe"\|"hdd"\|"cd"\|"usb"\|"bios-setup"\|"none", "persistent": bool}` |
| POST | `/api/oob/set-led` | `{"drive": "1", "state": "Lit"\|"Blinking"\|"Off"}` |
| POST | `/api/drill/run` | Runs `fault_drill.sh` **forced to `SIMULATE=1`** — see below |

### Why the drill button is simulate-only

The dashboard's "Run Simulated Drill" button always forces `SIMULATE=1`
regardless of what's typed into the form — a real fault drill calls
`mdadm --fail` against a live array, which is deliberately kept a
CLI-only action (`phase4-oob-lifecycle/fault_drill.sh` run directly by an
operator who has confirmed the array/disk identifiers). A web button is
the wrong place for a control that can take a production mirror down to
one member.

## Testing without real hardware

This has been run in this repo's own build/test pass as a full local
stack: `redfish_mock_server.py` (Phase 4) + `telemetryd.py --mock` (Phase
3, with `webhook_url` pointed at this dashboard) + `server.py`, all
talking to each other. Confirmed working: every GET endpoint, all three
OOB POST actions (verified `power-cycle` actually flips the mock BMC's
`PowerState`, `boot-override` and `set-led` both persist), the simulated
drill endpoint, live alerts arriving from telemetryd's webhook in
real time, and static file serving (including a path-traversal check).

```
python3 ../phase4-oob-lifecycle/redfish-mockup/redfish_mock_server.py --port 8443 &
python3 ../phase3-telemetry/telemetryd/telemetryd.py --mock --config ../phase3-telemetry/telemetryd/config.yaml.example &
python3 server.py --config config.yaml.example &
curl -s http://127.0.0.1:8080/api/overview
```
