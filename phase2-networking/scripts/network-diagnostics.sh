#!/usr/bin/env bash
# Phase 2 — network validation suite: throughput, cross-VLAN leak check,
# and socket exposure audit. Run from inside diag-ns for isolation:
#   ip netns exec diag-ns ./network-diagnostics.sh
#
# Usage:
#   IPERF_TARGET=10.10.100.1 ./network-diagnostics.sh
#   OUT_DIR=/tmp/netcheck ./network-diagnostics.sh

source "$(dirname "${BASH_SOURCE[0]}")/../../lib/common.sh"

IPERF_TARGET="${IPERF_TARGET:-}"
CAPTURE_IFACE="${CAPTURE_IFACE:-eth0}"
VLAN_ID="${VLAN_ID:-100}"
OUT_DIR="${OUT_DIR:-./netcheck-$(date -u +%Y%m%dT%H%M%SZ)}"
CAPTURE_SECONDS="${CAPTURE_SECONDS:-15}"

require_cmd ss ip
mkdir -p "${OUT_DIR}"

log "Socket exposure audit -> ${OUT_DIR}/sockets.txt"
if [[ "${SIMULATE}" == "1" ]]; then
    echo "(simulated) ss -tulpn" > "${OUT_DIR}/sockets.txt"
else
    ss -tulpn > "${OUT_DIR}/sockets.txt"
fi
UNEXPECTED="$(grep -vE ':(22|53|123|443|80|9100|8443)\b' "${OUT_DIR}/sockets.txt" | grep LISTEN || true)"
if [[ -n "${UNEXPECTED}" ]]; then
    warn "Listening sockets outside the expected allow-list:"
    echo "${UNEXPECTED}" | tee -a "${OUT_DIR}/sockets.txt"
fi

if [[ -n "${IPERF_TARGET}" ]]; then
    require_cmd iperf3
    log "Throughput test against ${IPERF_TARGET} -> ${OUT_DIR}/iperf3.json"
    if [[ "${SIMULATE}" == "1" ]]; then
        echo '{"note":"simulated iperf3 run"}' > "${OUT_DIR}/iperf3.json"
    else
        iperf3 -c "${IPERF_TARGET}" -J > "${OUT_DIR}/iperf3.json"
    fi
else
    warn "IPERF_TARGET not set — skipping throughput saturation test"
fi

log "Capturing ${CAPTURE_SECONDS}s on ${CAPTURE_IFACE} to verify zero cross-VLAN leakage -> ${OUT_DIR}/leak-check.pcap"
if [[ "${SIMULATE}" == "1" ]]; then
    require_cmd tcpdump || true
    echo "(simulated) tcpdump -i ${CAPTURE_IFACE} vlan and not vlan ${VLAN_ID} -w ${OUT_DIR}/leak-check.pcap"
else
    require_cmd tcpdump timeout
    timeout "${CAPTURE_SECONDS}" tcpdump -i "${CAPTURE_IFACE}" -w "${OUT_DIR}/leak-check.pcap" "vlan and not vlan ${VLAN_ID}" || true
    SIZE="$(stat -c%s "${OUT_DIR}/leak-check.pcap" 2>/dev/null || echo 0)"
    if [[ "${SIZE}" -gt 24 ]]; then
        warn "Non-empty capture: traffic outside VLAN ${VLAN_ID} was seen on ${CAPTURE_IFACE} — investigate leakage"
    else
        log "Clean: no cross-VLAN packets captured"
    fi
fi

log "Report written to ${OUT_DIR}/"
