#!/bin/sh
# Start-time edge setup, run by the nginx-unprivileged entrypoint from /docker-entrypoint.d/
# (alphabetically before 20-envsubst-on-templates.sh). POSIX sh: the image has no node.
#
# 1. NS_UI_API_UPSTREAM is always required: the nginx template proxies /api/ to it.
# 2. config.json precedence ("a mounted file wins"): the image ships NO config.json under the
#    web root. If a deploy-time mount put one at $NS_UI_HTML_DIR/config.json, nothing is
#    rendered and the NS_UI_CLOUD/TENANT_ID/CLIENT_ID/API_SCOPE variables are not required;
#    nginx serves the mounted file (try_files in the template). Otherwise config.json is
#    rendered from those four variables into $NS_UI_CONFIG_OUT_DIR (default /tmp/ns-config,
#    writable under uid 10001 and readOnlyRootFilesystem) and nginx falls back to it.
# Only variable NAMES are ever printed, never values.
set -eu

HTML_DIR="${NS_UI_HTML_DIR:-/usr/share/nginx/html}"
OUT_DIR="${NS_UI_CONFIG_OUT_DIR:-/tmp/ns-config}"
CONF_OUT_DIR="${NGINX_ENVSUBST_OUTPUT_DIR:-}"

fail() {
  echo "ns-edge: ERROR: $1" >&2
  exit 1
}

# Value of the variable whose name is $1 (empty when unset).
value_of() {
  eval "printf '%s' \"\${$1:-}\""
}

require() {
  [ -n "$(value_of "$1")" ] || fail "required environment variable $1 is not set or empty"
}

# Reject (rather than escape) anything that cannot be embedded safely in JSON or nginx config.
safe() {
  v="$(value_of "$1")"
  case "$v" in
    *'"'* | *'\'* | *';'* | *'{'* | *'}'* | *'$'* | *'`'* | *"'"* | *' '* | *'#'*)
      fail "environment variable $1 contains a character that is not allowed (quote, backslash, space, semicolon, brace, dollar, hash or backtick)"
      ;;
  esac
  case "$v" in
    *[![:print:]]*) fail "environment variable $1 contains a control or non-ASCII character" ;;
  esac
}

require NS_UI_API_UPSTREAM
safe NS_UI_API_UPSTREAM
case "$NS_UI_API_UPSTREAM" in
  http://* | https://*) ;;
  *) fail "NS_UI_API_UPSTREAM must start with http:// or https://" ;;
esac

[ -z "$CONF_OUT_DIR" ] || mkdir -p "$CONF_OUT_DIR"

if [ -f "$HTML_DIR/config.json" ]; then
  echo "ns-edge: using the mounted $HTML_DIR/config.json; NS_UI_* identity variables ignored"
  exit 0
fi

for name in NS_UI_CLOUD NS_UI_TENANT_ID NS_UI_CLIENT_ID NS_UI_API_SCOPE; do
  require "$name"
  safe "$name"
done
case "$NS_UI_CLOUD" in
  commercial | government) ;;
  *) fail 'NS_UI_CLOUD must be "commercial" or "government"' ;;
esac

mkdir -p "$OUT_DIR"
tmp="$OUT_DIR/config.json.tmp"
printf '{\n  "cloud": "%s",\n  "tenantId": "%s",\n  "clientId": "%s",\n  "apiBaseUrl": "/",\n  "apiScope": "%s"\n}\n' \
  "$NS_UI_CLOUD" "$NS_UI_TENANT_ID" "$NS_UI_CLIENT_ID" "$NS_UI_API_SCOPE" >"$tmp"
mv "$tmp" "$OUT_DIR/config.json"
echo "ns-edge: rendered config.json from NS_UI_* environment"
