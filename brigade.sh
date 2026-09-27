#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export BRIGADE_STATE_DIR="$PWD/.brigade"
export BRIGADE_CONFIG_PATH="$BRIGADE_STATE_DIR/brigade.json"
brigade_bin="$PWD/.brigade-runtime/node_modules/@spinabot/brigade/brigade.mjs"
if [[ "${1:-}" == setup ]]; then
  command -v node >/dev/null 2>&1 || { echo 'Brigade requires Node 22.12 or newer.' >&2; exit 1; }
  npm install --prefix .brigade-runtime @spinabot/brigade@1.39.0
  mkdir -p "$BRIGADE_STATE_DIR/extensions/job-scout" "$BRIGADE_STATE_DIR/workspace/skills/job-scout"
  cp brigade/extension/index.mjs brigade/extension/package.json brigade/extension/package-lock.json "$BRIGADE_STATE_DIR/extensions/job-scout/"
  npm ci --prefix "$BRIGADE_STATE_DIR/extensions/job-scout"
  cp brigade/skills/job-scout/SKILL.md "$BRIGADE_STATE_DIR/workspace/skills/job-scout/"
  chmod 700 "$BRIGADE_STATE_DIR"
  echo 'Installed in this project only. Next: ./brigade.sh onboard'
  exit 0
fi
if [[ ! -f "$brigade_bin" ]]; then
  echo 'Run ./brigade.sh setup first.' >&2
  exit 1
fi
if [[ "${1:-}" == scout ]]; then
  shift
  exec node "$brigade_bin" agent --workspace "$BRIGADE_STATE_DIR/workspace" --autonomous --max-iterations 12 --message 'Use the job-scout skill to discover relevant employers, refresh listings, and write evidence-backed reviews for the best candidates. Do not apply or contact anyone.' "$@"
fi
exec node "$brigade_bin" "$@"
