#!/usr/bin/env bash
# Phase 2 — create an 802.1Q tagged VLAN sub-interface imperatively.
# (netplan/01-netcfg.yaml is the declarative, persistent equivalent — use
# this script for ad-hoc testing or on hosts not managed by netplan.)
#
# Usage:
#   PARENT=eth0 VLAN_ID=100 VLAN_IP=10.10.100.10/24 ./setup-vlan.sh

source "$(dirname "${BASH_SOURCE[0]}")/../../lib/common.sh"

PARENT="${PARENT:-eth0}"
VLAN_ID="${VLAN_ID:?set VLAN_ID, e.g. 100}"
VLAN_IP="${VLAN_IP:?set VLAN_IP, e.g. 10.10.100.10/24}"
IFACE="${PARENT}.${VLAN_ID}"

require_root
require_cmd ip ethtool

log "Validating link speed/duplex on ${PARENT}"
if [[ "${SIMULATE}" != "1" ]]; then
    ethtool "${PARENT}" | grep -E 'Speed|Duplex' || warn "ethtool could not read link state for ${PARENT}"
fi

log "Creating 802.1Q VLAN interface ${IFACE} (id ${VLAN_ID}) on ${PARENT}"
run ip link add link "${PARENT}" name "${IFACE}" type vlan id "${VLAN_ID}"
run ip addr add "${VLAN_IP}" dev "${IFACE}"
run ip link set "${IFACE}" up

log "VLAN interface ${IFACE} is up with ${VLAN_IP}"
