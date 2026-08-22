#!/usr/bin/env bash
# Best-effort setup of Endless Worlds' OPTIONAL art dependencies, run at app
# install time via `setup.onInstall` in app.json.
#
# NOTHING here is required. If every step fails, the app still runs — backdrop
# publication just falls back to the narrator's hand-drawn path, and SCENE
# photo-tracing degrades to a quiet procedural tonal base. The story is
# unaffected. So this script NEVER fails the install: it overrides the caller's
# `set -e`, guards every step, and always exits 0.
#
# What it tries to provide:
#   - an SVG rasterizer, so the illustrator can preview/review draft backdrops
#     (CairoSVG, and/or the system librsvg the backend also reaches via ctypes);
#   - vtracer + pillow, so the SCENE lane can trace reference photos into underlays.
#
# The runner sets NONINTERACTIVE=1 and gives us a sandboxed, usually non-root
# environment, so system-package installs are attempted only when a privilege
# path exists and are skipped quietly otherwise — the pip path is the reliable one.
set +e

log() { printf '  [endless-worlds setup] %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
run_priv() {
  if [ "$(id -u 2>/dev/null)" = "0" ]; then "$@"; return $?; fi
  if have sudo; then sudo -n "$@"; return $?; fi
  return 1
}

log "installing optional art dependencies (best-effort; failures are ignored)"

# 1. Python packages — the cross-platform path. CairoSVG rasterizes draft
#    previews; vtracer + pillow trace SCENE reference photos. Install into the
#    active environment (the app's own python), falling back to a --user install
#    if that environment is not writable.
PY="$(command -v python3 || command -v python || true)"
if [ -n "$PY" ]; then
  log "python: $PY"
  if "$PY" -m pip install --disable-pip-version-check --quiet cairosvg vtracer pillow >/dev/null 2>&1 \
     || "$PY" -m pip install --user --disable-pip-version-check --quiet cairosvg vtracer pillow >/dev/null 2>&1; then
    log "pip: cairosvg + vtracer + pillow ready (installed or already present)"
  else
    log "pip step skipped/failed — the app still runs, art just degrades gracefully"
  fi
else
  log "no python found; skipping pip dependencies"
fi

# 2. System librsvg — the backend can reach it directly through ctypes with no
#    Python package. Attempted only if a package manager AND a privilege path are
#    available; a sandboxed install usually has neither, which is fine.
if have apt-get; then
  run_priv apt-get install -y --no-install-recommends librsvg2-2 >/dev/null 2>&1 \
    && log "apt: librsvg2-2 present" || log "apt librsvg skipped (no privilege / unavailable)"
elif have dnf; then
  run_priv dnf install -y librsvg2 >/dev/null 2>&1 \
    && log "dnf: librsvg2 present" || log "dnf librsvg skipped (no privilege / unavailable)"
elif have brew; then
  { brew list librsvg >/dev/null 2>&1 || brew install librsvg >/dev/null 2>&1; } \
    && log "brew: librsvg present" || log "brew librsvg skipped"
fi

log "done — any failures above are non-fatal by design"
exit 0
