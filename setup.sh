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
#    previews; vtracer + pillow trace SCENE reference photos.
#
#    Every candidate interpreter is attempted, not just the first one found, and
#    each is VERIFIED by importing the tracer afterwards. One `command -v python3`
#    is not enough: the interpreter that runs the MCP server is the one the HOST
#    spawns it with (a gateway virtualenv, say), while PATH here resolves to
#    whatever the installer happened to have — routinely a different interpreter.
#    Installing into only that one leaves a host that searches and fetches
#    references perfectly and cannot trace a single pixel of them, which reads as a
#    network fault and is not one. The runtime probes the same candidate set, so any
#    one of them landing is enough.
#
#    The check is the backend's OWN probe entry point rather than a second copy of
#    the import list here, so install-time and run-time can never disagree about
#    what "can trace" means.
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
verify_tracer() {
  [ -f "$SELF_DIR/backend/phototrace.py" ] || return 1
  "$1" "$SELF_DIR/backend/phototrace.py" --probe-tracer >/dev/null 2>&1
}

ART_PKGS="cairosvg vtracer pillow"
TRACER_OK=0
for PY in "${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python}" "$(command -v python3)" "$(command -v python)"; do
  [ -n "$PY" ] || continue
  [ -x "$PY" ] || continue
  case " $SEEN_PY " in *" $PY "*) continue ;; esac
  SEEN_PY="$SEEN_PY $PY"
  log "python: $PY"
  if verify_tracer "$PY"; then
    log "  tracer already present"
    TRACER_OK=1
    continue
  fi
  # A --user install is refused inside a virtualenv, so it is only a fallback for
  # a non-writable system interpreter.
  "$PY" -m pip install --disable-pip-version-check --quiet $ART_PKGS >/dev/null 2>&1 \
    || "$PY" -m pip install --user --disable-pip-version-check --quiet $ART_PKGS >/dev/null 2>&1
  if verify_tracer "$PY"; then
    log "  cairosvg + vtracer + pillow ready"
    TRACER_OK=1
  else
    log "  pip step skipped/failed for this interpreter"
  fi
done
if [ -z "$SEEN_PY" ]; then
  log "no python found; skipping pip dependencies"
elif [ "$TRACER_OK" = "0" ]; then
  log "no interpreter can import the tracer — SCENE pages will be hand-drawn instead"
  log "  to enable photo tracing later: <that python> -m pip install vtracer pillow"
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
