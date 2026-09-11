#!/usr/bin/env bash
# Phase 2 — spin up an isolated network namespace ("diag-ns") for running
# diagnostic traffic (iperf3, tcpdump, packet generators) with zero access
# to production routing tables or interfaces.
#
# Usage:
#   ./setup-diag-netns.sh          # create
#   TEARDOWN=1 ./setup-diag-netns.sh   # destroy

source "$(dirname "${BASH_SOURCE[0]}")/../../lib/common.sh"

NETNS="${NETNS:-diag-ns}"
VETH_HOST="${VETH_HOST:-veth-diag-h}"
VETH_NS="${VETH_NS:-veth-diag-n}"
HOST_IP="${HOST_IP:-169.254.100.1/30}"
NS_IP="${NS_IP:-169.254.100.2/30}"
UPLINK="${UPLINK:-eth0}"

require_root
require_cmd ip

teardown() {
    log "Tearing down ${NETNS}"
    run ip link del "${VETH_HOST}" 2>/dev/null || true
    run ip netns del "${NETNS}" 2>/dev/null || true
    log "Done"
}

if [[ "${TEARDOWN:-0}" == "1" ]]; then
    teardown
    exit 0
fi

log "Creating network namespace ${NETNS}"
run ip netns add "${NETNS}"

log "Creating veth pair ${VETH_HOST} <-> ${VETH_NS}"
run ip link add "${VETH_HOST}" type veth peer name "${VETH_NS}"
run ip link set "${VETH_NS}" netns "${NETNS}"

log "Configuring host side"
run ip addr add "${HOST_IP}" dev "${VETH_HOST}"
run ip link set "${VETH_HOST}" up

log "Configuring namespace side"
run ip netns exec "${NETNS}" ip addr add "${NS_IP}" dev "${VETH_NS}"
run ip netns exec "${NETNS}" ip link set "${VETH_NS}" up
run ip netns exec "${NETNS}" ip link set lo up
run ip netns exec "${NETNS}" ip route add default via "${HOST_IP%/*}"

warn "Egress from ${NETNS} reaches the internet only via NAT in nftables.conf"
warn "(table ip nat, chain postrouting) — it never touches production routes."

log "diag-ns ready. Run diagnostics inside it with:"
echo "  ip netns exec ${NETNS} iperf3 -c <target>"
echo "  ip netns exec ${NETNS} tcpdump -i ${VETH_NS} -w /tmp/diag.pcap"
log "Tear down with: TEARDOWN=1 $0"
