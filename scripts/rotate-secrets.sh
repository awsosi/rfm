#!/usr/bin/env bash
#
# Rotate the internal secrets of the RFM stacks on this host.
#
# Run it after every session with an AI tool (Claude Code, Codex, ...) or anyone
# else who could read .env, the database or the containers. Whatever they saw
# stops working.
#
# Rotated per environment (random values, never printed, never in argv):
#   POSTGRES_PASSWORD  database role password (+ DATABASE_URL in .env)
#   REDIS_PASSWORD     Redis requirepass      (+ REDIS_URL in .env)
#   SECRET_KEY         JWT signing + UPDATE upload links
#
# NOT rotated: external API keys (PIM, PolkaSQL, ROSAPI, ...). The script lists
# the ones that are set so you can rotate them at their provider by hand.
#
# Effects: postgres, redis and api restart (about a minute), every user and
# Windows client is signed out, unused UPDATE upload links stop working.
# Workers are not affected.
#
# Usage:
#   scripts/rotate-secrets.sh                # dev + prod, press ENTER to confirm
#   scripts/rotate-secrets.sh dev            # only dev   (or: prod)
#   scripts/rotate-secrets.sh --dry-run      # checks + plan only, changes nothing
#   scripts/rotate-secrets.sh --force        # rotate even with operations running
#
set -Eeuo pipefail
umask 077

DEV_DIR="${DEV_DIR:-/opt/docker/dev-rfm-vf}"
PROD_DIR="${PROD_DIR:-/opt/docker/rfm-vf}"
HEALTH_TIMEOUT_SECONDS=240

DRY_RUN=0
FORCE=0
TARGETS=()
STAGE=""        # set while an environment is being changed; drives the recovery message

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ok\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  !!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mFAILED:\033[0m %s\n' "$*" >&2; [ -n "$STAGE" ] && on_error; exit 1; }

# ---------------------------------------------------------------------------
# .env handling in Python: values only ever travel through files and pipes
# ---------------------------------------------------------------------------
read -r -d '' HELPER <<'PY' || true
import base64, hashlib, hmac, os, re, secrets, sys
from urllib.parse import urlsplit

ROTATED = ("POSTGRES_PASSWORD", "REDIS_PASSWORD", "SECRET_KEY")
URLS = (("DATABASE_URL", "POSTGRES_PASSWORD"), ("REDIS_URL", "REDIS_PASSWORD"))
LINE = re.compile(r'^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)=(.*?)(\r?\n?)$')


def parse(path):
    lines = open(path).readlines()
    values, where = {}, {}
    for i, line in enumerate(lines):
        m = LINE.match(line)
        if not m:
            continue
        key, raw = m.group(2), m.group(3).strip()
        quote = raw[0] if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'" else ""
        if key in where:
            sys.exit(f"{path}: {key} is defined twice")
        values[key] = raw[1:-1] if quote else raw
        where[key] = (i, m.group(1), quote, m.group(4))
    return lines, values, where


def check(env_path, compose_path):
    _, env, _ = parse(env_path)
    compose = open(compose_path).read()
    errors = [f"{k} is missing or empty in {env_path}" for k in ROTATED if not env.get(k)]
    user = env.get("POSTGRES_USER") or "filemanager"
    db = env.get("POSTGRES_DB") or "filemanager"
    for name in (user, db):
        if not re.fullmatch(r"[A-Za-z0-9_]+", name):
            errors.append(f"unexpected characters in POSTGRES_USER/POSTGRES_DB")
    for url_key, pw_key in URLS:
        url, pw = env.get(url_key, ""), env.get(pw_key, "")
        used = re.search(r"\$\{%s[:}-]" % url_key, compose)
        if f":${{{pw_key}}}@" in url:
            continue  # refers to the variable, follows it automatically
        if pw and f":{pw}@" in url:
            if url_key == "DATABASE_URL" and urlsplit(url).username != user:
                errors.append(f"DATABASE_URL user differs from POSTGRES_USER")
        elif used:
            errors.append(f"{url_key} is used by {os.path.basename(compose_path)} but contains neither "
                          f"':${{{pw_key}}}@' nor the current {pw_key} - fix it by hand first")
    if errors:
        sys.exit("\n".join(errors))
    print(user, db)


def rewrite(env_path, out_path):
    lines, env, where = parse(env_path)
    new = {
        "POSTGRES_PASSWORD": secrets.token_hex(32),
        "REDIS_PASSWORD": secrets.token_hex(32),
        "SECRET_KEY": secrets.token_urlsafe(64),
    }
    for url_key, pw_key in URLS:
        old = f":{env[pw_key]}@"
        if url_key in env and old in env[url_key]:
            new[url_key] = env[url_key].replace(old, f":{new[pw_key]}@", 1)
    for key, value in new.items():
        i, prefix, quote, end = where[key]
        lines[i] = f"{prefix}{key}={quote}{value}{quote}{end}"
    with open(out_path, "w") as f:
        f.writelines(lines)


def alter_role_sql(env_path):
    # Send a SCRAM verifier, not the password, so no server log can ever show it
    _, env, _ = parse(env_path)
    user = env.get("POSTGRES_USER") or "filemanager"
    salt, iterations = os.urandom(16), 4096
    salted = hashlib.pbkdf2_hmac("sha256", env["POSTGRES_PASSWORD"].encode(), salt, iterations)
    stored = hashlib.sha256(hmac.new(salted, b"Client Key", "sha256").digest()).digest()
    server = hmac.new(salted, b"Server Key", "sha256").digest()
    b64 = lambda b: base64.b64encode(b).decode()
    print(f"ALTER ROLE \"{user}\" WITH PASSWORD 'SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored)}:{b64(server)}';")


def weak_passwords(env_path):
    _, env, _ = parse(env_path)
    print("admin123")
    if env.get("INITIAL_ADMIN_PASSWORD"):
        print(env["INITIAL_ADMIN_PASSWORD"])


def external_keys(env_path):
    _, env, _ = parse(env_path)
    skip = set(ROTATED) | {"INITIAL_ADMIN_PASSWORD"}
    print(" ".join(k for k, v in env.items()
                   if v and k not in skip and re.search(r"(PASSWORD|TOKEN|API_KEY|SECRET)$", k)))


{"check": check, "rewrite": rewrite, "sql": alter_role_sql,
 "weak": weak_passwords, "external": external_keys}[sys.argv[1]](*sys.argv[2:])
PY

helper() { python3 -c "$HELPER" "$@"; }

# Runs inside the api container: which active users still accept a known password
read -r -d '' WEAK_CHECK <<'PY' || true
import asyncio, os, sys
import asyncpg
from argon2 import PasswordHasher

candidates = [line.rstrip("\n") for line in sys.stdin if line.strip()]

async def main():
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(url)
    rows = await conn.fetch("SELECT username, password_hash FROM users WHERE is_active")
    await conn.close()
    ph = PasswordHasher()
    for row in rows:
        for password in candidates:
            try:
                if ph.verify(row["password_hash"], password):
                    print(row["username"])
                    break
            except Exception:
                pass

asyncio.run(main())
PY

# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------
select_env() {
    case "$1" in
        dev)
            DIR="$DEV_DIR"; COMPOSE="docker-compose.dev.yml"
            PG="file-manager-postgres-dev"; API="file-manager-api-dev"
            SERVICES=(postgres-dev redis-dev api-dev) ;;
        prod)
            DIR="$PROD_DIR"; COMPOSE="docker-compose.yml"
            PG="file-manager-postgres"; API="file-manager-api"
            SERVICES=(postgres redis api) ;;
    esac
    ENV_FILE="$DIR/.env"
}

psql_in() { docker exec -i "$PG" psql -v ON_ERROR_STOP=1 -qAt -U "$DB_USER" -d "$DB_NAME" "$@"; }

preflight() {
    select_env "$1"
    log "[$1] Preflight ($DIR)"

    [ -f "$ENV_FILE" ] || die "$ENV_FILE not found"
    [ -f "$DIR/$COMPOSE" ] || die "$DIR/$COMPOSE not found"
    [ -w "$ENV_FILE" ] && [ -w "$DIR" ] || die "$ENV_FILE or its directory is not writable by $(id -un)"

    local out
    out="$(helper check "$ENV_FILE" "$DIR/$COMPOSE")" || die "[$1] .env cannot be rotated safely (see above)"
    read -r DB_USER DB_NAME <<< "$out"
    ok ".env has POSTGRES_PASSWORD, REDIS_PASSWORD, SECRET_KEY"

    local services
    services="$(docker compose --project-directory "$DIR" -f "$DIR/$COMPOSE" config --services 2>/dev/null)" \
        || die "[$1] docker compose cannot read $COMPOSE"
    for s in "${SERVICES[@]}"; do
        grep -qx "$s" <<< "$services" || die "[$1] service '$s' not in $COMPOSE"
    done
    ok "compose services: ${SERVICES[*]}"

    for c in "$PG" "$API"; do
        [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" = "true" ] || die "[$1] container $c is not running"
    done
    [ "$(psql_in -c 'select 1' < /dev/null)" = "1" ] || die "[$1] cannot reach PostgreSQL inside $PG"
    ok "containers running, database reachable"

    local active
    active="$(psql_in -c "select count(*) from operations where status in ('PENDING','IN_PROGRESS')" < /dev/null)"
    if [ "$active" != "0" ]; then
        [ "$FORCE" -eq 1 ] || die "[$1] $active operation(s) pending or in progress. Wait for them, or use --force"
        warn "$active operation(s) running - continuing because of --force"
    else
        ok "no operations running"
    fi
}

wait_healthy() {
    local port deadline body
    port="$(docker port "$API" 8000/tcp 2>/dev/null | head -1 | sed 's/.*://')"
    [ -n "$port" ] || die "[$1] cannot find the host port of $API"
    deadline=$(( SECONDS + HEALTH_TIMEOUT_SECONDS ))
    while true; do
        body="$(curl -fsS --max-time 5 "http://127.0.0.1:$port/health" 2>/dev/null || true)"
        if grep -q '"database":true' <<< "$body" && grep -q '"redis":true' <<< "$body"; then
            ok "api healthy: database and redis accept the new passwords"
            return
        fi
        [ "$SECONDS" -ge "$deadline" ] && die "[$1] api not healthy after ${HEALTH_TIMEOUT_SECONDS}s. Logs: docker logs $API"
        sleep 5
    done
}

rotate() {
    select_env "$1"
    log "[$1] Rotating"
    read -r DB_USER DB_NAME <<< "$(helper check "$ENV_FILE" "$DIR/$COMPOSE")"

    local stamp backup new_env started
    stamp="$(date +%Y%m%d-%H%M%S)"
    backup="$DIR/.env.rotate-backup-$stamp"
    new_env="$(mktemp "$DIR/.env.rotate-new.XXXXXX")"
    cp -p "$ENV_FILE" "$backup"
    chmod 600 "$backup" "$new_env"
    [ "$(id -u)" -eq 0 ] && chown --reference="$ENV_FILE" "$new_env" "$backup"

    CURRENT_ENV="$1"; CURRENT_BACKUP="$backup"; CURRENT_NEW="$new_env"
    STAGE="prepare"
    trap on_error ERR

    helper rewrite "$ENV_FILE" "$new_env"
    ok "new values generated"

    STAGE="database"
    helper sql "$new_env" | psql_in
    mv -f "$new_env" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    ok "database password changed, .env updated"

    STAGE="restart"
    started="$(date +%s)"
    docker compose --project-directory "$DIR" -f "$DIR/$COMPOSE" up -d --no-build "${SERVICES[@]}"
    for c in "$PG" "$API"; do
        local c_started
        c_started="$(date -d "$(docker inspect -f '{{.State.StartedAt}}' "$c")" +%s)"
        [ "$c_started" -ge "$started" ] || die "[$1] $c was not restarted - it still uses the old values"
    done
    wait_healthy "$1"

    trap - ERR
    STAGE=""
    rm -f "$backup"
    ok "[$1] done"

    local weak
    weak="$(helper weak "$ENV_FILE" | docker exec -i "$API" python -c "$WEAK_CHECK" 2>/dev/null || true)"
    if [ -n "$weak" ]; then
        warn "[$1] these accounts still use admin123 or INITIAL_ADMIN_PASSWORD - change them in the Admin Panel: $(tr '\n' ' ' <<< "$weak")"
    fi
    EXTERNAL_REPORT+=("[$1] .env: $(helper external "$ENV_FILE")")
    EXTERNAL_REPORT+=("[$1] Admin Panel: $(psql_in -c "select string_agg(key, ' ' order by key) from config where value <> '' and key ~ '(password|token|api_key|secret)$'" < /dev/null)")
}

on_error() {
    trap - ERR
    local stage="$STAGE"
    STAGE=""
    printf '\n\033[1;31mRotation of %s failed at stage "%s".\033[0m\n' "$CURRENT_ENV" "$stage" >&2
    case "$stage" in
        prepare)
            rm -f "$CURRENT_NEW" "$CURRENT_BACKUP"
            echo "Nothing was changed." >&2 ;;
        database)
            rm -f "$CURRENT_NEW"
            echo "The database password may already be new while .env is old." >&2
            echo "Run this script again for $CURRENT_ENV: it sets a fresh password and .env together." >&2
            echo "Previous .env: $CURRENT_BACKUP" >&2 ;;
        restart)
            echo ".env and the database already have the new values; the containers did not come back." >&2
            echo "  docker compose --project-directory $DIR -f $DIR/$COMPOSE up -d ${SERVICES[*]}" >&2
            echo "  docker logs $API" >&2
            echo "Previous .env (old, no longer valid for the database): $CURRENT_BACKUP" >&2 ;;
    esac
    exit 1
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        dev|prod)  TARGETS+=("$1"); shift ;;
        all)       TARGETS+=(dev prod); shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --force)   FORCE=1; shift ;;
        -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
        *)         die "Unknown argument: $1" ;;
    esac
done
[ ${#TARGETS[@]} -gt 0 ] || TARGETS=(dev prod)

command -v python3 >/dev/null || die "python3 is required"
docker compose version >/dev/null 2>&1 || die "docker compose is required"

for t in "${TARGETS[@]}"; do preflight "$t"; done

cat <<EOF

Will rotate POSTGRES_PASSWORD, REDIS_PASSWORD and SECRET_KEY in: ${TARGETS[*]}
  - postgres, redis and api restart (about a minute each)
  - every user and Windows client is signed out
  - unused UPDATE upload links stop working
  - external API keys are NOT rotated (listed at the end)

EOF

if [ "$DRY_RUN" -eq 1 ]; then
    log "Dry run - nothing was changed."
    exit 0
fi

read -r -p "Press ENTER to rotate, Ctrl+C to abort " _

EXTERNAL_REPORT=()
for t in "${TARGETS[@]}"; do rotate "$t"; done

printf '\n\033[1;32mInternal secrets rotated.\033[0m\n\n'
echo "Rotate these external keys at their provider by hand, then save them in"
echo "Admin Panel -> Configuration (or .env):"
for line in "${EXTERNAL_REPORT[@]}"; do echo "  $line"; done
