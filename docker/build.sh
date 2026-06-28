#!/usr/bin/env bash
# Build the agentic-tamp-sandbox image (robocode-sandbox + TAMPEST + check_move).
# Requires robocode-sandbox to be built first: bash ~/robocode/docker/build.sh
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Building agentic-tamp-sandbox from ${DIR} ..."
docker build --tag agentic-tamp-sandbox --file "${DIR}/Dockerfile" "${DIR}"
echo "Done. Image tagged: agentic-tamp-sandbox"
