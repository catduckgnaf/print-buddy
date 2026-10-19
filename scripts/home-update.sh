#!/bin/sh
# Update the home checkout, then prove it works. Roll back if it does not.
#
#   scripts/home-update.sh            fast-forward to origin/main
#   scripts/home-update.sh v2.0.2     fast-forward to a tag or branch
#
# Never touches config/local.toml. If config/after-update.sh exists (gitignored), it runs after a
# good update, for example to restart the Discord listener.
set -eu
cd "$(dirname "$0")/.."
target="${1:-origin/main}"
# Same interpreter choice as install-hermes.sh: an explicit $PYTHON wins, then the Hermes agent
# venv (bare python3 on a Hermes host is a stripped tools interpreter without pytest), then python3.
if [ -n "${PYTHON:-}" ]; then
    python=$PYTHON
elif [ -x "$HOME/.hermes/hermes-agent/venv/bin/python" ]; then
    python="$HOME/.hermes/hermes-agent/venv/bin/python"
else
    python=python3
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Tracked files have local edits. Move machine settings into config/local.toml, or commit, then retry."
    exit 1
fi

previous=$(git rev-parse HEAD)
git fetch --quiet --tags origin
case "$target" in origin/*|v*|*.*) ;; *) git rev-parse --verify --quiet "origin/$target" >/dev/null && target="origin/$target" ;; esac
if ! git merge --ff-only --quiet "$target"; then
    echo "Cannot fast-forward to $target. Nothing changed."
    exit 1
fi
if [ "$(git rev-parse HEAD)" = "$previous" ]; then
    echo "Already at $target."
    exit 0
fi

echo "Updated $(git rev-parse --short "$previous") -> $(git rev-parse --short HEAD). Checking..."
if PRINT_BUDDY_UPDATE_CHECK=1 "$python" -m pytest -q -p no:cacheprovider tests && "$python" -m print_buddy.doctor; then
    if [ -x config/after-update.sh ]; then
        config/after-update.sh
    fi
    echo "Update good."
else
    git reset --quiet --hard "$previous"
    echo "Checks failed. Rolled back to $(git rev-parse --short HEAD)."
    exit 1
fi
