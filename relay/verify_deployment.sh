#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || ( "$2" != "netlify" && "$2" != "vercel" ) ]]; then
  echo "Usage: bash verify_deployment.sh https://deployed-host netlify|vercel"
  exit 2
fi

origin="${1%/}"
provider="$2"
case "$origin" in
  https://*.netlify.app|https://*.vercel.app|https://*.*) ;;
  *)
    echo "Expected an HTTPS origin with a real hostname, got: $origin"
    exit 2
    ;;
esac

for route_path in / /connect/ /reconnect/ /disconnect/; do
  status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$origin$route_path")"
  if [[ "$status" != "200" ]]; then
    echo "FAIL $origin$route_path returned HTTP $status"
    exit 1
  fi
  echo "PASS $origin$route_path returned HTTP 200"
done

if [[ "$provider" == "netlify" ]]; then
  callback_path="/.netlify/functions/qb-callback"
else
  callback_path="/api/qb-callback"
fi

headers="$(curl --silent --show-error --head "$origin$callback_path")"
status="$(printf '%s\n' "$headers" | awk 'NR == 1 { print $2 }')"
location="$(printf '%s\n' "$headers" | awk 'BEGIN { IGNORECASE=1 } /^location:/ { sub(/^[^:]*:[[:space:]]*/, ""); sub(/\r$/, ""); print; exit }')"
cache_control="$(printf '%s\n' "$headers" | awk 'BEGIN { IGNORECASE=1 } /^cache-control:/ { sub(/^[^:]*:[[:space:]]*/, ""); sub(/\r$/, ""); print; exit }')"

if [[ "$status" != "302" ]]; then
  echo "FAIL $origin$callback_path returned HTTP $status (expected 302)"
  exit 1
fi
if [[ "$location" != "http://localhost:7655/api/quickbooks/callback" ]]; then
  echo "FAIL callback Location header was not the local DTM callback"
  exit 1
fi
cache_control_lower="$(printf '%s' "$cache_control" | tr '[:upper:]' '[:lower:]')"
if [[ "$cache_control_lower" != *"no-store"* ]]; then
  echo "FAIL callback did not return Cache-Control: no-store"
  exit 1
fi

echo "PASS $origin$callback_path returned a no-store 302 to the local DTM callback"
