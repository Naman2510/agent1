#!/usr/bin/env bash
# Phase 1 / Step 6 — install the isolated sudoers policy with syntax
# validation (a syntax error here can lock every admin out of sudo).
#
# Usage: ./06-sudoers-audit.sh

source "$(dirname "${BASH_SOURCE[0]}")/../../lib/common.sh"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${REPO_DIR}/config/sudoers.d/99-sysadmin"
DST="/etc/sudoers.d/99-sysadmin"

require_root
require_cmd visudo touch chmod

[[ -f "${SRC}" ]] || die "missing ${SRC}"

log "Validating sudoers syntax before install"
run visudo -c -f "${SRC}"

log "Installing ${DST} (0440 root:root)"
run install -m 0440 -o root -g root "${SRC}" "${DST}"

log "Ensuring audit log exists with correct permissions"
run touch /var/log/sudo_audit.log
run chmod 0600 /var/log/sudo_audit.log

log "Re-validating the full sudoers tree"
run visudo -c

log "Phase 1 complete: hardened storage, boot redundancy, SSH, and sudo audit are in place."
