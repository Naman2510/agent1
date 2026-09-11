#!/usr/bin/env bash
# Phase 1 / Step 5 — deploy the SSH hardening drop-in and reload sshd.
#
# Usage: ./05-harden-ssh.sh

source "$(dirname "${BASH_SOURCE[0]}")/../../lib/common.sh"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${REPO_DIR}/config/sshd_config.d/99-hardening.conf"
DST="/etc/ssh/sshd_config.d/99-hardening.conf"

require_root
require_cmd sshd systemctl

[[ -f "${SRC}" ]] || die "missing ${SRC}"

log "Installing ${DST}"
run install -m 0644 -o root -g root "${SRC}" "${DST}"

log "Validating sshd configuration syntax"
run sshd -t

log "Reloading sshd"
run systemctl reload ssh || run systemctl reload sshd

warn "Before disconnecting: confirm you have an ed25519 key already authorized"
warn "in ~/.ssh/authorized_keys — PasswordAuthentication is now disabled."
log "Done. Next: 06-sudoers-audit.sh"
