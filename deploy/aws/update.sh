#!/bin/sh
# Kéo image mới nhất và khởi động lại nếu có thay đổi. systemd chạy file này 5 phút một lần
# (travelmate-update.timer); chạy tay: sudo /opt/travelmate/update.sh
set -eu
cd /opt/travelmate
docker compose --env-file site.env pull --quiet
docker compose --env-file site.env up -d --remove-orphans
docker image prune -f >/dev/null
