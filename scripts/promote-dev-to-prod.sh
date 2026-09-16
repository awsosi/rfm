#!/usr/bin/env bash
#
# Promote dev-vf -> vf and redeploy the production RFM stack.
#
# Safe by construction:
#   - refuses to run unless both working trees are clean and on the right branch
#   - takes a full backup (source tree, database, current image IDs) BEFORE
#     touching anything, and prints the exact rollback command
#   - never touches .env; production keeps its own secrets and hostnames
#   - verifies health and the migration afterwards, and aborts loudly if either
#     fails rather than leaving a half-deployed stack unreported
#
# Usage:
#   scripts/promote-dev-to-prod.sh              # full promotion (asks to confirm)
#   scripts/promote-dev-to-prod.sh --dry-run    # checks + plan only, changes nothing
#   scripts/promote-dev-to-prod.sh --yes        # skip the confirmation prompt
#   scripts/promote-dev-to-prod.sh --rollback <backup-dir>
#
set -Eeuo pipefail

PROD_DIR="${PROD_DIR:-/opt/docker/rfm-vf}"
DEV_DIR="${DEV_DIR:-/opt/docker/dev-rfm-vf}"
BACKUP_ROOT="${BACKUP_ROOT:-/opt/docker/rfm-vf-backups}"
PROD_COMPOSE="docker-compose.yml"
PROD_DB_CONTAINER="file-manager-postgres"
PROD_API_CONTAINER="file-manager-api"
PROD_WEBUI_CONTAINER="file-manager-webui"
PROD_API_URL="http://127.0.0.1:48080"
HEALTH_TIMEOUT_SECONDS=180

DRY_RUN=0
ASSUME_YES=0

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ok\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  !!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mFAILED:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------
do_rollback() {
    local backup_dir="$1"
    [ -d "$backup_dir" ] || die "Backup directory not found: $backup_dir"

    log "Rolling back from $backup_dir"
    [ -f "$backup_dir/MANIFEST" ] || die "No MANIFEST in $backup_dir - not a promotion backup"
    cat "$backup_dir/MANIFEST"

    read -r -p "Roll back production to this state? [type ROLLBACK to confirm] " reply
    [ "$reply" = "ROLLBACK" ] || die "Aborted by user"

    local prev_commit
    prev_commit="$(grep '^vf_commit=' "$backup_dir/MANIFEST" | cut -d= -f2)"

    log "Restoring source tree to $prev_commit"
    git -C "$PROD_DIR" reset --hard "$prev_commit"

    log "Restoring images"
    while IFS='=' read -r tag image_id; do
        case "$tag" in image_*)
            local name="${tag#image_}"
            docker tag "$image_id" "$name" && ok "retagged $name -> $image_id"
            ;;
        esac
    done < "$backup_dir/MANIFEST"

    log "Recreating containers"
    ( cd "$PROD_DIR" && docker compose -f "$PROD_COMPOSE" up -d --force-recreate api webui )

    warn "Database was NOT restored automatically."
    warn "Migrations 012 and 013 only ADD enum values and config rows, so the"
    warn "previous code runs against the newer schema and a DB rollback is usually"
    warn "unnecessary. One exception: code older than 013 cannot load workers in"
    warn "the OFFLINE status. Move them to SUSPENDED (an administrator reactivates"
    warn "them) before using the rolled-back admin panel:"
    warn "  docker exec $PROD_DB_CONTAINER psql -U filemanager -d filemanager -c \"UPDATE workers SET status='SUSPENDED' WHERE status='OFFLINE';\""
    warn "If you do need a full DB restore:"
    warn "  gunzip -c $backup_dir/prod-db.sql.gz | docker exec -i $PROD_DB_CONTAINER psql -U filemanager -d filemanager"
    ok "Rollback complete"
    exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)  DRY_RUN=1; shift ;;
        --yes|-y)   ASSUME_YES=1; shift ;;
        --rollback) shift; [ $# -ge 1 ] || die "--rollback needs a backup directory"; do_rollback "$1" ;;
        -h|--help)  sed -n '2,20p' "$0"; exit 0 ;;
        *)          die "Unknown argument: $1" ;;
    esac
done

# ---------------------------------------------------------------------------
# 1. Preflight
# ---------------------------------------------------------------------------
log "Preflight checks"

[ -d "$PROD_DIR/.git" ] || die "$PROD_DIR is not a git repository"
[ -d "$DEV_DIR/.git" ]  || die "$DEV_DIR is not a git repository"

prod_branch="$(git -C "$PROD_DIR" rev-parse --abbrev-ref HEAD)"
dev_branch="$(git -C "$DEV_DIR" rev-parse --abbrev-ref HEAD)"
[ "$prod_branch" = "vf" ]     || die "Production is on '$prod_branch', expected 'vf'"
[ "$dev_branch" = "dev-vf" ]  || die "Dev is on '$dev_branch', expected 'dev-vf'"
ok "branches: prod=vf dev=dev-vf"

[ -z "$(git -C "$PROD_DIR" status --porcelain)" ] \
    || die "Production working tree has uncommitted changes. Commit or discard them first."
ok "production working tree clean"

[ -z "$(git -C "$DEV_DIR" status --porcelain)" ] \
    || die "Dev working tree has uncommitted changes. Commit them first so prod gets what you tested."
ok "dev working tree clean"

log "Fetching from origin"
git -C "$PROD_DIR" fetch --quiet origin || die "Could not fetch origin"

git -C "$PROD_DIR" rev-parse --verify --quiet origin/dev-vf >/dev/null \
    || die "origin/dev-vf does not exist - push dev-vf before promoting"

dev_local="$(git -C "$DEV_DIR" rev-parse dev-vf)"
dev_remote="$(git -C "$PROD_DIR" rev-parse origin/dev-vf)"
[ "$dev_local" = "$dev_remote" ] \
    || die "Local dev-vf ($dev_local) differs from origin/dev-vf ($dev_remote). Push dev first."
ok "dev-vf is pushed and matches origin"

if git -C "$PROD_DIR" merge-base --is-ancestor origin/dev-vf vf; then
    ok "vf already contains dev-vf - nothing to promote"
    exit 0
fi

log "Commits that will be promoted"
git -C "$PROD_DIR" --no-pager log --oneline vf..origin/dev-vf | sed 's/^/    /'

log "Files that will change"
git -C "$PROD_DIR" --no-pager diff --stat vf..origin/dev-vf | sed 's/^/    /'

for c in "$PROD_DB_CONTAINER" "$PROD_API_CONTAINER"; do
    docker inspect "$c" >/dev/null 2>&1 || die "Container $c is not present"
done
ok "production containers present"

if [ "$DRY_RUN" -eq 1 ]; then
    log "Dry run - stopping here. Nothing was changed."
    exit 0
fi

if [ "$ASSUME_YES" -eq 0 ]; then
    printf '\n'
    read -r -p "Promote these commits to PRODUCTION and redeploy? [type PROMOTE to confirm] " reply
    [ "$reply" = "PROMOTE" ] || die "Aborted by user"
fi

# ---------------------------------------------------------------------------
# 2. Backup
# ---------------------------------------------------------------------------
STAMP="$(date +%Y-%m-%d_%H%M%S)"
BACKUP_DIR="$BACKUP_ROOT/$STAMP"
log "Backing up to $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

vf_commit="$(git -C "$PROD_DIR" rev-parse vf)"

tar czf "$BACKUP_DIR/prod-tree.tgz" -C "$(dirname "$PROD_DIR")" \
    --exclude='.git' "$(basename "$PROD_DIR")"
ok "source tree -> prod-tree.tgz"

docker exec "$PROD_DB_CONTAINER" pg_dump -U filemanager -d filemanager \
    | gzip > "$BACKUP_DIR/prod-db.sql.gz"
ok "database -> prod-db.sql.gz ($(du -h "$BACKUP_DIR/prod-db.sql.gz" | cut -f1))"

cp -a "$PROD_DIR/.env" "$BACKUP_DIR/env.backup"
chmod 600 "$BACKUP_DIR/env.backup"
ok ".env -> env.backup (not modified by this script, kept for completeness)"

{
    echo "timestamp=$STAMP"
    echo "vf_commit=$vf_commit"
    echo "promoting_to=$(git -C "$PROD_DIR" rev-parse origin/dev-vf)"
    echo "alembic_version=$(docker exec "$PROD_DB_CONTAINER" psql -U filemanager -d filemanager -tAc 'select version_num from alembic_version;' | tr -d '[:space:]')"
    echo "image_rfm-vf-api:latest=$(docker inspect -f '{{.Id}}' rfm-vf-api:latest)"
    echo "image_rfm-vf-webui:latest=$(docker inspect -f '{{.Id}}' rfm-vf-webui:latest)"
} > "$BACKUP_DIR/MANIFEST"
ok "manifest written"

ROLLBACK_CMD="$PROD_DIR/scripts/promote-dev-to-prod.sh --rollback $BACKUP_DIR"

# From here on, any failure prints the rollback command.
trap 'printf "\n\033[1;31mPromotion failed.\033[0m Roll back with:\n  %s\n" "$ROLLBACK_CMD"' ERR

# ---------------------------------------------------------------------------
# 3. Merge
# ---------------------------------------------------------------------------
log "Merging origin/dev-vf into vf"
git -C "$PROD_DIR" merge --no-edit origin/dev-vf
ok "merged -> $(git -C "$PROD_DIR" rev-parse --short HEAD)"

# ---------------------------------------------------------------------------
# 4. Rebuild and redeploy
# ---------------------------------------------------------------------------
log "Rebuilding production images"
( cd "$PROD_DIR" && docker compose -f "$PROD_COMPOSE" build api webui )
ok "images rebuilt"

log "Recreating api and webui (entrypoint runs alembic upgrade head)"
( cd "$PROD_DIR" && docker compose -f "$PROD_COMPOSE" up -d api webui )

# ---------------------------------------------------------------------------
# 5. Verify
# ---------------------------------------------------------------------------
log "Waiting for api to report healthy (timeout ${HEALTH_TIMEOUT_SECONDS}s)"
deadline=$(( SECONDS + HEALTH_TIMEOUT_SECONDS ))
while true; do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$PROD_API_CONTAINER" 2>/dev/null || echo unknown)"
    [ "$status" = "healthy" ] && { ok "api healthy"; break; }
    [ "$SECONDS" -ge "$deadline" ] && die "api did not become healthy (last status: $status). Logs: docker logs $PROD_API_CONTAINER"
    sleep 5
done

log "Verifying migration"
version="$(docker exec "$PROD_DB_CONTAINER" psql -U filemanager -d filemanager -tAc 'select version_num from alembic_version;' | tr -d '[:space:]')"
ok "alembic version: $version"

enum_has_update="$(docker exec "$PROD_DB_CONTAINER" psql -U filemanager -d filemanager -tAc \
    "select count(*) from pg_enum e join pg_type t on t.oid=e.enumtypid where t.typname='operationtype' and e.enumlabel='UPDATE';" | tr -d '[:space:]')"
[ "$enum_has_update" = "1" ] || die "operationtype enum is missing the UPDATE value"
ok "operationtype enum includes UPDATE"

enum_has_offline="$(docker exec "$PROD_DB_CONTAINER" psql -U filemanager -d filemanager -tAc \
    "select count(*) from pg_enum e join pg_type t on t.oid=e.enumtypid where t.typname='workerstatus' and e.enumlabel='OFFLINE';" | tr -d '[:space:]')"
[ "$enum_has_offline" = "1" ] || die "workerstatus enum is missing the OFFLINE value"
ok "workerstatus enum includes OFFLINE"

seeded="$(docker exec "$PROD_DB_CONTAINER" psql -U filemanager -d filemanager -tAc \
    "select count(*) from config where key like 'pim%' or key like 'catalog_validation%' or key like 'push_validation%' or key='enable_update_archive_mirror';" | tr -d '[:space:]')"
[ "$seeded" -ge 25 ] || die "Expected at least 25 seeded config rows, found $seeded"
ok "$seeded integration config rows present"

log "Smoke-testing the API"
curl -fsS --max-time 15 "$PROD_API_URL/health" >/dev/null || die "/health did not respond"
ok "/health responds"

for route in /api/operations/update /api/operations/preflight; do
    curl -fsS --max-time 15 "$PROD_API_URL/openapi.json" \
        | grep -q "\"$route\"" || die "Route $route missing from OpenAPI"
    ok "route present: $route"
done

webui_status="$(docker inspect -f '{{.State.Health.Status}}' "$PROD_WEBUI_CONTAINER" 2>/dev/null || echo unknown)"
[ "$webui_status" = "healthy" ] || warn "webui health is '$webui_status' - check: docker logs $PROD_WEBUI_CONTAINER"

trap - ERR

# ---------------------------------------------------------------------------
# 6. Done
# ---------------------------------------------------------------------------
cat <<EOF

$(printf '\033[1;32mPromotion complete.\033[0m')

  vf is now at : $(git -C "$PROD_DIR" rev-parse --short HEAD)
  backup       : $BACKUP_DIR
  rollback     : $ROLLBACK_CMD

Remaining manual steps:
  1. Push the merged branch:   git -C $PROD_DIR push origin vf
  2. Configure the new integrations in the Admin Panel -> Configuration:
       - PIM: base URL, endpoint, API token, then enable. Delivery is queued and
         retried (Delivery & Retries); the default payload now sends tgId.
       - Catalog Validation: RFM_ValidateProductName URL + API key, then enable.
         The URL + key are also what resolves tgId for PIM, so set them even if
         the gate itself stays off. The procedure must be the current
         docs/polkasql/RFM_ValidateProductName.sql (returns tg_id).
       - Image Host Sync Verification: optional, off by default
     Production .env was not modified. Because the new keys sync from .env only
     when the variable is present, leaving them unset keeps the Admin Panel
     authoritative across restarts.
  3. Deploy the rebuilt worker to the Windows host and re-pair it.
  4. Workers that the old health check left SUSPENDED stay SUSPENDED (they
     cannot be told apart from administrator suspensions). Reactivate each
     one once in Admin Panel -> Workers; from then on a worker that misses
     heartbeats goes OFFLINE and returns to ACTIVE on its own.

EOF
