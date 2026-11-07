#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
fail() { echo "Polka: $*" >&2; exit 1; }
[[ $EUID == 0 ]] || fail "Запустите установщик через sudo bash."
source /etc/os-release
[[ $ID == ubuntu ]] || fail "Нужен Ubuntu Server."
domain=${POLKA_DOMAIN:-}
if [[ -z $domain ]]; then
    read -rp 'Домен хранилища (например, files.example.org): ' domain </dev/tty
fi
domain=${domain,,}
[[ ${#domain} -le 253 && $domain =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]([a-z0-9-]{0,61}[a-z0-9])?$ ]] || fail "Введите домен без https:// и пути."
repo=${POLKA_REPOSITORY:-dangerman2077/polka-cloud}
[[ $repo =~ ^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$ ]] || fail "Некорректное имя репозитория."
base=/opt/polka-cloud
exec 9>/run/polka-cloud-install.lock
flock -n 9 || fail "Другая установка ещё выполняется."
if [[ -e $base && ! -f $base/.polka-install ]]; then
    fail "Каталог $base уже существует. Укажите чистый VPS или перенесите каталог вручную."
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y git curl openssl ca-certificates
if ! command -v docker >/dev/null; then
    apt-get install -y docker.io
fi
if ! docker compose version >/dev/null 2>&1; then
    apt-get install -y docker-compose-v2
fi
systemctl enable --now docker
if [[ ! -e $base ]]; then
    work=$(mktemp -d /opt/.polka-cloud.XXXXXX)
    trap 'rm -rf -- "$work"' EXIT
    git clone --depth 1 --branch main "https://github.com/$repo.git" "$work/source"
    for file in compose.yaml deploy/Caddyfile manage.py locker/dav.py; do
        [[ -s $work/source/$file ]] || fail "В ветке main отсутствует $file. Сначала опубликуйте новый проект."
    done
    printf '%s\n' "$repo" >"$work/source/.polka-install"
    mv "$work/source" "$base"
fi
cd "$base"
[[ $(cat .polka-install) == "$repo" ]] || fail "Эта установка принадлежит другому репозиторию."
if [[ -e .env ]]; then
    grep -Fxq "POLKA_DOMAIN=$domain" .env || fail "Установка уже настроена на другой домен."
else
    secret=$(openssl rand -hex 48)
    printf 'POLKA_DOMAIN=%s\nPOLKA_SECRET=%s\n' "$domain" "$secret" >.env.tmp
    mv .env.tmp .env
fi
docker compose config --quiet
docker compose up --build -d
ready=0
for ((i=0; i<60; i++)); do
    if curl --fail --silent --max-time 4 --resolve "$domain:443:127.0.0.1" "https://$domain/login/" -o /dev/null; then
        ready=1; break
    fi
    sleep 2
done
((ready)) || fail "HTTPS ещё не отвечает. Проверьте DNS и порты 80/443, затем выполните cd $base && sudo docker compose logs --tail=60. После исправления повторите установку с тем же доменом."
status=$(curl -sS --max-time 10 --resolve "$domain:443:127.0.0.1" -o /dev/null -w '%{http_code}' -X PROPFIND -H 'Depth: 0' "https://$domain/dav")
[[ $status == 401 ]] || fail "Проверка WebDAV: ожидался 401, получен $status."
docker compose exec -T app python manage.py first_admin
printf 'Сайт: https://%s/\nАдминистратор: https://%s/admin/\nWebDAV: https://%s/dav\n' "$domain" "$domain" "$domain"
