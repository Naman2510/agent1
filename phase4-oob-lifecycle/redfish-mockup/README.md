# Redfish / BMC Emulation

Three options, in order of fidelity (and setup cost):

## 1. This repo's mock server (fastest — used for this repo's own testing)

A ~150-line stdlib-only Python server that keeps real mutable state, so
`oob_control.py power-cycle` actually flips `PowerState`, a `boot-override`
PATCH actually sticks, and `set-led` actually sticks — enough to exercise
every `oob_control.py` command and `fault_drill.sh` end-to-end without any
external dependency.

```
python3 redfish_mock_server.py --port 8443
python3 ../oob_control.py --insecure --base-url http://127.0.0.1:8443 power-status
```

Not a general-purpose Redfish implementation — it only knows the four
endpoints `oob_control.py` calls. Use option 2 or 3 below to test against
a broader/more realistic Redfish surface.

## 2. Docker Compose (redfish_mock_server, containerized)

```
docker compose up -d
# or: podman-compose up -d
```

See `docker-compose.yml` — binds the same mock server to `8443` inside an
isolated bridge network, closer to how the real service processor sits on
its own management network segment in production.

## 3. DMTF Redfish-Mockup-Server (broader API surface, read-mostly)

For validating a client against the wider Redfish schema (more endpoints,
realistic `$metadata`, `Chassis`, `Managers`, etc.) rather than just the
handful of actions this repo automates:

```
pip install redfish-mockup-server
git clone https://github.com/DMTF/Redfish-Mockup-Files
redfishMockupServer -H 0.0.0.0 -p 8443 -D Redfish-Mockup-Files/public-mockups/<some-mockup>
```

Note: the DMTF mockup server replays static JSON and does not durably
execute `POST`/`PATCH` actions — use it for read-path/API-surface testing,
not for driving `fault_drill.sh`'s stateful power-cycle/LED sequence.

## 4. OpenBMC in QEMU (highest fidelity — full BMC firmware stack)

For testing against real OpenBMC firmware (IPMI on 623 + Redfish on 8443):

```
docker run -it --rm -p 8443:443 -p 623:623/udp \
    openbmc/qemu-system-arm openbmc-qemu-image
```

See https://github.com/openbmc/openbmc for build instructions and
`docs/development/qemu.md` for the QEMU boot flags. This is the closest
emulation to physical hardware, at the cost of a much heavier setup than
options 1–3 — reserve it for final validation before touching a real BMC.
