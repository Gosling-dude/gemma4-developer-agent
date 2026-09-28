#!/usr/bin/env bash
# Anonymous calls to Kaggle's web API (the same endpoints kaggle.com uses). Public data only; no credentials.
# Usage: kapi.sh Service/Method '{"json":"body"}'
set -euo pipefail
J=${TMPDIR:-/tmp}/kaggle_cookies.txt
[[ -s $J ]] || curl -s -c "$J" -o /dev/null https://www.kaggle.com/
X=$(awk '$6=="XSRF-TOKEN"{print $7}' "$J")
curl -s -b "$J" -H "x-xsrf-token: $X" -H "content-type: application/json" -X POST "https://www.kaggle.com/api/i/$1" -d "$2"
