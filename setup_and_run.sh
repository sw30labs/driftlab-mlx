#!/usr/bin/env bash
# Set up DriftLab from a source checkout, run the test suite, and start the
# local web command deck.
#
# Usage:
#   ./setup_and_run.sh                     # use a local OMLX server if one is up
#   ./setup_and_run.sh --provider omlx     # require OMLX; fail if unreachable
#   ./setup_and_run.sh --provider none     # deterministic path only, no narratives
#   ./setup_and_run.sh --no-cycle          # skip the opening estate cycle
#   ./setup_and_run.sh --no-tests          # skip pytest
#
# The advisory LLM is genuinely optional here, which is why the default is
# `auto` rather than a hard requirement: DriftLab's diff, severity, score and
# experiment verdicts are deterministic pure Python, and the test suite proves
# a full compliance run succeeds with no model reachable. OMLX only ever writes
# narrative prose on top of a finished cycle. A missing inference server is
# therefore a downgrade, not a failure — the deck says the backend is off and
# everything else works.
#
# Environment overrides:
#   DRIFTLAB_PORT             deck port (default 8321)
#   DRIFTLAB_DATA_DIR         store + artifacts root (default ./.driftlab)
#   DRIFTLAB_OMLX_BASE_URL    OpenAI-compatible endpoint (default 127.0.0.1:8000/v1)
#   DRIFTLAB_OMLX_MODEL       pin a model instead of taking the served one
#   OMLX_API_KEY              shared workstation key (DriftLab's own var wins)
#   DRIFTLAB_NO_BROWSER=1     do not open a browser tab
#
# A DGX/vLLM backend works the same way without a flag: export
# DRIFTLAB_LLM_PROVIDER=dgx and DRIFTLAB_DGX_BASE_URL, then pass --provider none
# here so this script leaves the LLM configuration alone.
set -euo pipefail

cd "$(dirname "$0")"

PROVIDER="auto"
RUN_TESTS=1
RUN_CYCLE=1

while [ $# -gt 0 ]; do
    case "$1" in
        --provider)
            PROVIDER="${2:?--provider needs a value (auto|omlx|none)}"
            shift 2
            ;;
        --no-tests) RUN_TESTS=0; shift ;;
        --no-cycle) RUN_CYCLE=0; shift ;;
        -h|--help)
            # The header comment IS the help text; print it up to the first
            # line of code so the two can never drift apart.
            awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' "$0"
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument '$1' (see --help)" >&2
            exit 1
            ;;
    esac
done

case "$PROVIDER" in
    auto)      ;;
    omlx|mlx)  PROVIDER=omlx ;;
    none|off)  PROVIDER=none ;;
    *) echo "ERROR: unknown provider '$PROVIDER' (expected auto, omlx or none)" >&2
       exit 1 ;;
esac

VENV=.venv
PORT="${DRIFTLAB_PORT:-8321}"
OMLX_BASE="${DRIFTLAB_OMLX_BASE_URL:-http://127.0.0.1:8000/v1}"
OMLX_KEY="${DRIFTLAB_OMLX_API_KEY:-${OMLX_API_KEY:-test}}"

# ── stale decks ─────────────────────────────────────────────────────────────
# A deck from an earlier run outlives the terminal that started it, and it
# holds the port — which makes a fresh start look like a hang. Only processes
# whose executable is actually python count: an editor or a grep whose command
# line merely mentions the module must never become a kill target.
deck_pids() {
    local pid comm
    for pid in $(pgrep -f ' -m driftlab\.web| driftlab serve' 2>/dev/null || true); do
        [ "$pid" = "$$" ] && continue
        comm="$(ps -o comm= -p "$pid" 2>/dev/null || true)"
        case "${comm##*/}" in
            python | python[0-9]* | driftlab) printf '%s\n' "$pid" ;;
        esac
    done
}

stop_stale_decks() {
    local pids
    pids="$(deck_pids)"
    if [ -n "$pids" ]; then
        echo "==> Stopping stale deck process(es): $(echo "$pids" | tr '\n' ' ')"
        # shellcheck disable=SC2086
        kill $pids 2>/dev/null || true
        sleep 2
        pids="$(deck_pids)"
        if [ -n "$pids" ]; then
            # shellcheck disable=SC2086
            kill -9 $pids 2>/dev/null || true
            sleep 1
        fi
    fi
    if command -v lsof >/dev/null 2>&1 &&
       lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "ERROR: port $PORT is held by a process that is not a DriftLab deck:" >&2
        lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2
        echo "Stop it, or set DRIFTLAB_PORT to a free port." >&2
        exit 1
    fi
}

# ── interpreter ─────────────────────────────────────────────────────────────
# The project requires >=3.11. Prefer the newest available rather than pinning:
# there is no upper bound and the suite is green on 3.14.
PY=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        PY="$candidate"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "ERROR: no Python >= 3.11 found (DriftLab requires it)." >&2
    exit 1
fi

echo "==> Using $PY ($("$PY" --version 2>&1))"

if [ ! -d "$VENV" ]; then
    echo "==> Creating virtual environment in $VENV"
    "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# Installed as a wheel, not editable: the editable install's .pth is not
# honored by this venv layout (see NOTES.md), so `pip install -e .` would
# produce a driftlab that imports from nowhere. Re-running this script always
# reinstalls current source, which is what a setup script should do.
echo "==> Installing DriftLab (with test extras)"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet '.[test]'

# ── advisory backend ────────────────────────────────────────────────────────
omlx_models() {
    curl -sS --max-time 5 -H "Authorization: Bearer ${OMLX_KEY}" \
        "${OMLX_BASE%/}/models" 2>/dev/null
}

# Pick a chat model, not whatever happens to be first: an OMLX host commonly
# also serves speech and embedding models, and asking one of those to narrate a
# compliance cycle fails in a way that looks like a DriftLab bug.
#
# The JSON arrives as $1, not on stdin — the heredoc already owns stdin here.
pick_chat_model() {
    python - "$1" <<'PY' 2>/dev/null || true
import json, re, sys
try:
    data = json.loads(sys.argv[1]).get("data", [])
except Exception:
    sys.exit(0)
skip = re.compile(r"whisper|\basr\b|embed|rerank|tts|vision|clip", re.I)
ids = [m["id"] for m in data if isinstance(m, dict) and "id" in m]
chat = [i for i in ids if not skip.search(i)]
print((chat or ids or [""])[0])
PY
}

MODEL=""
if [ "$PROVIDER" = "none" ]; then
    echo "==> Advisory LLM off by request"
else
    echo "==> Probing advisory LLM at $OMLX_BASE"
    MODELS_JSON="$(omlx_models || true)"
    if [ -n "$MODELS_JSON" ] && printf '%s' "$MODELS_JSON" | grep -q '"data"'; then
        MODEL="${DRIFTLAB_OMLX_MODEL:-$(pick_chat_model "$MODELS_JSON")}"
        if [ -n "$MODEL" ]; then
            PROVIDER=omlx
            echo "    reachable — narrating with: $MODEL"
        else
            echo "    reachable but serving no usable chat model"
            PROVIDER=none
        fi
    elif [ "$PROVIDER" = "omlx" ]; then
        echo "ERROR: --provider omlx was requested but no OMLX server answers at" >&2
        echo "       $OMLX_BASE. Start it, or run with --provider none." >&2
        exit 1
    else
        echo "    no server answering — advisory narratives stay off"
        PROVIDER=none
    fi
fi

if [ "$PROVIDER" = "none" ]; then
    echo "    compliance is unaffected: verdicts never use a model"
fi

# ── verify ──────────────────────────────────────────────────────────────────
# Before the backend is exported, so the suite proves the LLM-optional
# invariant against a clean environment rather than the ambient one.
if [ "$RUN_TESTS" = "1" ]; then
    echo "==> Running test suite"
    python -m pytest
fi

export DRIFTLAB_LLM_PROVIDER="$PROVIDER"
if [ "$PROVIDER" = "omlx" ]; then
    export DRIFTLAB_OMLX_BASE_URL="$OMLX_BASE"
    export DRIFTLAB_OMLX_API_KEY="$OMLX_KEY"
    export DRIFTLAB_OMLX_MODEL="$MODEL"
fi

# ── first cycle ─────────────────────────────────────────────────────────────
# So the deck opens with evidence rather than an empty estate. Idempotent:
# cycle ids are content-derived, so re-running the same inputs upserts the same
# row instead of accumulating history.
if [ "$RUN_CYCLE" = "1" ]; then
    echo "==> Running an opening estate cycle"
    driftlab monitor run --force --no-email
fi

stop_stale_decks

BROWSER_FLAG=""
[ -n "${DRIFTLAB_NO_BROWSER:-}" ] && BROWSER_FLAG="--no-browser"

echo "==> Starting the command deck at http://127.0.0.1:$PORT (llm=$PROVIDER, Ctrl+C to stop)"
echo "    headless? tunnel with: ssh -L $PORT:127.0.0.1:$PORT <this-host>"
# shellcheck disable=SC2086
exec python -m driftlab.web --port "$PORT" $BROWSER_FLAG
