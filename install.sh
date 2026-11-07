#!/usr/bin/env bash
# Polka installer for Ubuntu Server.
# Quick start: curl -fsSL https://raw.githubusercontent.com/dangerman2077/polka/main/install.sh | sudo bash
# The only interactive input is a DNS domain.
set -Eeuo pipefail
IFS=$'\n\t'
umask 027

REPO="https://github.com/${POLKA_REPOSITORY:-dangerman2077/polka}"
REF="${POLKA_GIT_REF:-main}"
PORT=443
APP_DIR=/opt/polka
DATA_DIR=/var/lib/polka
ACME_DIR=/var/lib/polka-acme
TMP=""
ACME_CREATED=0

log() { printf '\n\033[1;36m[Polka]\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m[Polka] Внимание:\033[0m %s\n' "$*" >&2; }
die() { printf '\n\033[1;31m[Polka] Ошибка:\033[0m %s\n' "$*" >&2; exit 1; }
on_error() {
    printf '\n[Polka] Установка прервана на строке %s. Данные пользователей не удаляются.\n' "$1" >&2
    # Allow a clean retry after DNS/certificate failure without touching other Nginx sites.
    if (( ACME_CREATED )) && [[ ! -f /etc/polka.env ]]; then
        rm -f -- /etc/nginx/conf.d/polka-acme.conf
        if command -v nginx >/dev/null && nginx -t >/dev/null 2>&1 && systemctl is-active --quiet nginx; then
            systemctl reload nginx || true
        fi
    fi
}
cleanup() { if [[ -n "$TMP" && -d "$TMP" ]]; then rm -rf -- "$TMP"; fi; }
trap 'status=$?; if (( status != 0 )); then on_error "$LINENO"; fi; cleanup' EXIT

[[ $EUID -eq 0 ]] || die 'Для установки нужны права root. Используйте: curl -fsSL URL | sudo bash'
[[ -f /etc/os-release ]] || die 'Не удалось определить операционную систему.'
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == ubuntu ]] || die 'Автоустановка поддерживает Ubuntu Server 22.04, 24.04 и 26.04.'
case "${VERSION_ID:-}" in
    22.04|24.04|26.04) ;;
    *) die "Ubuntu ${VERSION_ID:-unknown} не проверена для этого установщика." ;;
esac

[[ "$REF" =~ ^[A-Za-z0-9._/-]+$ ]] && [[ "$REF" != *..* ]] || die 'Недопустимая ветка POLKA_GIT_REF.'

printf '\n\033[1;34m'
printf '  ┌──────────────────────────────────────────┐\n'
printf '  │           Polka Cloud Installer          │\n'
printf '  │         Django + WebDAV + HTTPS         │\n'
printf '  └──────────────────────────────────────────┘\n'
printf '\033[0m\n'
printf ' Сайт будет работать на HTTPS-порту %s.\n' "$PORT"

DOMAIN="${1:-${POLKA_DOMAIN:-}}"
if [[ -z "$DOMAIN" ]]; then
    if [[ ! -r /dev/tty ]]; then
        die 'Нужен домен. Пример: curl -fsSL URL | sudo bash -s -- cloud.example.com'
    fi
    read -r -p 'Введите домен Polka (например, cloud.example.com): ' DOMAIN </dev/tty \
        || die 'Не удалось прочитать домен.'
fi
DOMAIN="${DOMAIN,,}"
[[ ${#DOMAIN} -le 253 && "$DOMAIN" == *.* && "$DOMAIN" =~ ^[a-z0-9.-]+$ ]] \
    || die 'Введите DNS-имя без https://, порта, пробелов и пути.'
IFS='.' read -r -a LABELS <<< "$DOMAIN"
for label in "${LABELS[@]}"; do
    [[ ${#label} -ge 1 && ${#label} -le 63 ]] \
        && [[ "$label" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] \
        || die 'Домен содержит некорректную DNS-метку.'
done
[[ "${LABELS[-1]}" =~ [a-z] ]] || die 'Для автоматического TLS нужен публичный домен, не IP.'

command -v ss >/dev/null 2>&1 || die 'Команда ss не найдена (пакет iproute2).'
command -v curl >/dev/null 2>&1 || die 'Для установки нужен curl: sudo apt install curl.'
command -v tar >/dev/null 2>&1 || die 'Для установки нужен tar.'

# Do not overwrite an existing installation or unrelated configuration.
[[ ! -e /etc/polka.env && ! -e "$APP_DIR/manage.py" && ! -e "$DATA_DIR/db.sqlite3" ]] \
    || die 'Обнаружена существующая установка Polka. Данные не изменены; установка поверх неё запрещена.'
for dir in "$APP_DIR" "$DATA_DIR"; do
    if [[ -d "$dir" ]] && [[ -n "$(find "$dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
        die "Каталог $dir уже содержит данные. Остановились, чтобы не повредить чужие файлы."
    fi
done
[[ ! -e /etc/nginx/conf.d/polka.conf && ! -e /etc/nginx/conf.d/polka-acme.conf ]] \
    || die 'Уже существуют nginx-конфигурации Polka. Проверьте /etc/nginx/conf.d/.'

port_in_use() { ss -H -lnt "( sport = :$1 )" | grep -q .; }
for p in "$PORT" 18081 18082; do
    if port_in_use "$p"; then
        die "Порт $p уже занят. Установщик не будет отключать или перенастраивать чужие службы."
    fi
done

if port_in_use 80; then
    listeners="$(ss -H -lntp '( sport = :80 )')"
    while IFS= read -r listener; do
        [[ "$listener" == *nginx* ]] \
            || die 'Порт 80 занят не Nginx. Для автоматического HTTP-01 освободите 80/tcp или используйте отдельную ручную настройку SSL.'
    done <<< "$listeners"
    log 'Порт 80 уже обслуживает Nginx. Добавим отдельный vhost только для домена Polka.'
else
    log 'Порт 80 свободен; Nginx будет обслуживать проверку сертификата.'
fi

if ! getent ahosts "$DOMAIN" >/dev/null; then
    die "DNS-записи для $DOMAIN пока не видны серверу. Создайте A-запись на публичный IP VPS и повторите."
fi

log "Проверен домен $DOMAIN. Скачиваем исходники из GitHub..."
TMP="$(mktemp -d -t polka-install.XXXXXXXX)"
curl --fail --silent --show-error --location --retry 3 --proto '=https' --tlsv1.2 \
    "$REPO/archive/refs/heads/$REF.tar.gz" -o "$TMP/source.tar.gz"
mkdir -p "$TMP/source"
tar -xzf "$TMP/source.tar.gz" -C "$TMP/source" --strip-components=1
for required in manage.py dav_app.py requirements.txt deploy/nginx-polka.conf \
    deploy/nginx-polka-acme.conf deploy/polka-web.service deploy/polka-dav.service scripts/polka; do
    [[ -f "$TMP/source/$required" ]] \
        || die "В ветке $REF нет $required. Опубликуйте полный проект в корне репозитория GitHub."
done

log 'Устанавливаем системные пакеты...'
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip nginx certbot ca-certificates openssl

command -v nginx >/dev/null || die 'Не удалось установить Nginx.'
nginx -t || die 'Существующая конфигурация Nginx некорректна. Не изменяя её, остановили установку.'

render_nginx() {
    local src="$1" dest="$2"
    sed -e "s/__DOMAIN__/$DOMAIN/g" -e "s/__PORT__/$PORT/g" "$src" > "$dest"
    if [[ "$(cat /proc/sys/net/ipv6/conf/all/disable_ipv6 2>/dev/null || true)" == 1 ]]; then
        sed -i '/listen \[::\]:/d' "$dest"
    fi
    chmod 0644 "$dest"
}

log 'Настраиваем HTTP-01 для домена...'
install -d -m 0755 "$ACME_DIR" "$ACME_DIR/.well-known" "$ACME_DIR/.well-known/acme-challenge"
render_nginx "$TMP/source/deploy/nginx-polka-acme.conf" /etc/nginx/conf.d/polka-acme.conf
ACME_CREATED=1
nginx -t || die 'Невозможно добавить HTTP-01 vhost к Nginx. Исправьте конфигурацию и повторите.'
if systemctl is-active --quiet nginx; then
    systemctl reload nginx
else
    systemctl enable --now nginx || die 'Nginx не запустился. Проверьте journalctl -u nginx.'
fi

# Verify that this Nginx actually serves the required webroot for this hostname.
# A custom nginx.conf might not include /etc/nginx/conf.d/*.conf.
printf 'polka-acme-ready\n' > "$ACME_DIR/.well-known/acme-challenge/polka-health-check"
chmod 0644 "$ACME_DIR/.well-known/acme-challenge/polka-health-check"
challenge_response="$(curl --noproxy '*' --silent --show-error --max-time 5 \
    -H "Host: $DOMAIN" http://127.0.0.1/.well-known/acme-challenge/polka-health-check || true)"
rm -f -- "$ACME_DIR/.well-known/acme-challenge/polka-health-check"
[[ "$challenge_response" == polka-acme-ready ]] \
    || die 'Nginx не отдаёт ACME-файлы для указанного домена на порту 80. Проверьте виртуальные хосты и include conf.d.'

# Open only the ports required by Polka if UFW was already active.
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
    ufw allow 80/tcp
    ufw allow "$PORT/tcp"
fi

log "Получаем TLS-сертификат Let's Encrypt для $DOMAIN..."
if [[ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]]; then
    openssl x509 -in "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" -noout -checkend 604800 \
        && openssl x509 -in "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" -noout -checkhost "$DOMAIN" \
        || die 'Найден существующий, но неверный или истекающий сертификат. Не перезаписываем сертификаты других сервисов.'
    log 'Найден подходящий существующий сертификат, повторный выпуск не требуется.'
else
    certbot certonly --webroot --webroot-path "$ACME_DIR" \
        --non-interactive --agree-tos --register-unsafely-without-email \
        --preferred-challenges http -d "$DOMAIN" \
        || die 'Не удалось выпустить сертификат. Убедитесь, что DNS A/AAAA указывают на VPS, а 80/tcp доступен извне (UFW и firewall провайдера).'
fi

log 'Устанавливаем Polka и зависимости Python...'
if ! id polka >/dev/null 2>&1; then
    useradd --system --user-group --home-dir "$APP_DIR" --shell /usr/sbin/nologin polka
else
    warn 'Системный пользователь polka уже существует. Используем его для приложения.'
fi
install -d -o polka -g polka -m 0755 "$APP_DIR"
install -d -o polka -g polka -m 0700 "$DATA_DIR"
tar -xzf "$TMP/source.tar.gz" -C "$APP_DIR" --strip-components=1
chown -R polka:polka "$APP_DIR"
chmod 0700 "$DATA_DIR"

SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
cat >/etc/polka.env <<ENV
POLKA_SECRET_KEY=$SECRET_KEY
POLKA_ALLOWED_HOSTS=$DOMAIN
POLKA_CSRF_ORIGINS=https://$DOMAIN
POLKA_DATA_ROOT=$DATA_DIR
POLKA_DB_PATH=$DATA_DIR/db.sqlite3
POLKA_FORCE_SSL=1
POLKA_DEBUG=0
ENV
chown root:polka /etc/polka.env
chmod 0640 /etc/polka.env

runuser -u polka -- python3 -m venv "$APP_DIR/.venv"
runuser -u polka -- "$APP_DIR/.venv/bin/python" -m pip install \
    --no-input --disable-pip-version-check -r "$APP_DIR/requirements.txt"
install -m 0755 "$APP_DIR/scripts/polka" /usr/local/bin/polka
/usr/local/bin/polka check
# Django migration and static collection are performed without root privileges.
runuser -u polka -- /bin/bash -c '
    set -e
    set -a
    source /etc/polka.env
    set +a
    cd /opt/polka
    /opt/polka/.venv/bin/python manage.py migrate --noinput
    /opt/polka/.venv/bin/python manage.py collectstatic --noinput
'

chmod -R a+rX "$APP_DIR/staticfiles"

log 'Настраиваем HTTPS и сервисы systemd...'
render_nginx "$APP_DIR/deploy/nginx-polka.conf" /etc/nginx/conf.d/polka.conf
nginx -t || die 'HTTPS-конфигурация Nginx не прошла проверку. Конфигурации других сайтов не менялись.'
systemctl reload nginx
install -m 0644 "$APP_DIR/deploy/polka-web.service" /etc/systemd/system/polka-web.service
install -m 0644 "$APP_DIR/deploy/polka-dav.service" /etc/systemd/system/polka-dav.service
systemctl daemon-reload
systemctl enable --now polka-web.service polka-dav.service
# Type=simple can report started before a worker has finished importing Django.
sleep 2
if ! systemctl is-active --quiet polka-web.service || ! systemctl is-active --quiet polka-dav.service; then
    journalctl -u polka-web.service -u polka-dav.service -n 50 --no-pager >&2 || true
    die 'Одна из служб Polka не запустилась. Выше приведён журнал ошибок.'
fi
if ! curl --noproxy '*' --fail --silent --show-error --max-time 15 \
    --resolve "$DOMAIN:$PORT:127.0.0.1" \
    "https://$DOMAIN/accounts/login/" --output /dev/null; then
    die 'HTTPS Django не отвечает корректно. Проверьте журналы: sudo polka logs.'
fi
dav_status="$(curl --noproxy '*' --silent --show-error --max-time 15 \
    --resolve "$DOMAIN:$PORT:127.0.0.1" \
    --request PROPFIND --header 'Depth: 0' \
    --output /dev/null --write-out '%{http_code}' \
    "https://$DOMAIN/dav/" || true)"
[[ "$dav_status" == 401 ]] || die "WebDAV должен требовать авторизацию (HTTP 401), получен HTTP $dav_status."

# The hook runs ONLY after renewal of this particular certificate.
install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
cat >/etc/letsencrypt/renewal-hooks/deploy/polka-nginx-reload.sh <<HOOK
#!/usr/bin/env bash
set -e
if [[ "\${RENEWED_LINEAGE:-}" == "/etc/letsencrypt/live/$DOMAIN" ]]; then
    nginx -t && systemctl reload nginx
fi
HOOK
chmod 0755 /etc/letsencrypt/renewal-hooks/deploy/polka-nginx-reload.sh
if systemctl list-unit-files certbot.timer --no-legend 2>/dev/null | grep -q 'certbot.timer'; then
    systemctl enable --now certbot.timer
else
    warn 'Не обнаружен certbot.timer; проверьте автоматическое продление сертификата вручную.'
fi

log 'Создаём первую учётную запись администратора...'
ADMIN_CREDENTIALS="$(/usr/local/bin/polka account create admin --admin)"

printf '\n\033[1;32m'
printf '  ┌──────────────────────────────────────────┐\n'
printf '  │             Polka установлена!           │\n'
printf '  └──────────────────────────────────────────┘\n'
printf '\033[0m\n'
printf '  Веб-интерфейс: https://%s/\n' "$DOMAIN"
printf '  Админ-панель:   https://%s/admin/\n' "$DOMAIN"
printf '  WebDAV:         https://%s/dav/\n\n' "$DOMAIN"
printf '%s\n\n' "$ADMIN_CREDENTIALS"
printf '  Сохраните пароль. Он отображается один раз.\n'
printf '  Новый пароль: sudo polka account password admin\n'
printf '  Добавить пользователя: sudo polka account create ivan\n'
printf '  Журнал: sudo polka logs\n'
printf '  Если сайт недоступен, проверьте firewall провайдера: %s/tcp.\n\n' "$PORT"
