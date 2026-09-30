#!/usr/bin/env bash
# Exercise the external-database path of the chart (migration hook Job + hook Secret) on
# the local k3s cluster: installs a second release whose "external" database is a fresh
# database on the first release's bundled Postgres, upgrades it, runs `helm test`, then
# uninstalls it. Needs a running `soundings` release (scripts/k3s-install.sh).
#
#   RELEASE / NAMESPACE   the existing release (default soundings / soundings)
#   IMAGE_TAG             image tag to deploy (default dev)
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=lib/k3s-env.sh
source "$(dirname "$0")/lib/k3s-env.sh"

RELEASE="${RELEASE:-soundings}"
NAMESPACE="${NAMESPACE:-soundings}"
IMAGE_TAG="${IMAGE_TAG:-dev}"
EXT_RELEASE="${RELEASE}-ext"
EXT_NAMESPACE="${NAMESPACE}-ext"
EXT_DB="soundings_ext"
require_k3s

# The chart's fullname: the release name if it contains "soundings", else <release>-soundings.
fullname="$RELEASE"
[[ "$RELEASE" == *soundings* ]] || fullname="$RELEASE-soundings"
pg_service="$fullname-postgresql"
pg_pod="$pg_service-0"
db_host="$pg_service.$NAMESPACE.svc"
password="$(kubectl -n "$NAMESPACE" get secret "$pg_service" -o jsonpath='{.data.password}' | base64 -d)"

log "creating database $EXT_DB on $pg_pod"
kubectl -n "$NAMESPACE" exec "$pg_pod" -- sh -c \
  "psql -U soundings -d soundings -tAc \"select 1 from pg_database where datname = '$EXT_DB'\" | grep -q 1 ||
   psql -U soundings -d soundings -c 'create database $EXT_DB'" >/dev/null

install() {
  RELEASE="$EXT_RELEASE" NAMESPACE="$EXT_NAMESPACE" "$(dirname "$0")/k3s-install.sh" \
    --set "image.tag=$IMAGE_TAG" \
    --set postgresql.enabled=false \
    --set "externalDatabase.host=$db_host" \
    --set "externalDatabase.database=$EXT_DB" \
    --set externalDatabase.sslmode=disable \
    --set "externalDatabase.password=$password" \
    --set ingress.enabled=false "$@" >/dev/null
}

log "install $EXT_RELEASE (external database, pre-install migration hook)"
install
log "upgrade $EXT_RELEASE (pre-upgrade migration hook)"
install --set logLevel=WARNING

version="$(kubectl -n "$NAMESPACE" exec "$pg_pod" -- psql -U soundings -d "$EXT_DB" -tAc 'select version_num from alembic_version')"
[ -n "$version" ] || die "no alembic version in $EXT_DB"
log "schema of $EXT_DB is at revision $version"
jobs="$(kubectl -n "$EXT_NAMESPACE" get jobs -o name)"
[ -z "$jobs" ] || die "hook Job not cleaned up after success: $jobs"

helm test "$EXT_RELEASE" --namespace "$EXT_NAMESPACE" --logs --hide-notes >/dev/null
log "helm test $EXT_RELEASE passed"

helm uninstall "$EXT_RELEASE" --namespace "$EXT_NAMESPACE" --wait >/dev/null
kubectl delete namespace "$EXT_NAMESPACE" --wait=false >/dev/null
log "external-database path OK"
