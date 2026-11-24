#!/bin/bash
# Cài TravelMate lên một máy EC2 Ubuntu 24.04 mới (t3.micro). Chạy một lần sau khi SSH vào máy:
#
#   curl -fsSL https://raw.githubusercontent.com/hoangluan1122/travel-planning-multi-agent/main/deploy/aws/setup.sh -o setup.sh
#   sudo bash setup.sh                      # địa chỉ tự đặt: <IP-có-gạch-ngang>.sslip.io
#   sudo bash setup.sh travel.example.com   # hoặc tên miền riêng đã trỏ về IP của máy
#
# Lần đầu: tạo /opt/travelmate/.env rồi dừng để bạn điền khoá (nano). Chạy lại lệnh trên để khởi động.
# Chạy lại bao nhiêu lần cũng được: chỉ cập nhật file cấu hình, không ghi đè .env.
# Hướng dẫn đầy đủ: docs/deploy-aws.md.
set -euo pipefail

RAW="${TRAVELMATE_RAW:-https://raw.githubusercontent.com/hoangluan1122/travel-planning-multi-agent/main/deploy/aws}"
DIR=/opt/travelmate

[ "$(id -u)" = 0 ] || { echo "Cần chạy bằng sudo: sudo bash setup.sh"; exit 1; }

echo "== 1. Bộ nhớ phụ (swap) 2 GB: t3.micro chỉ có 1 GB RAM"
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== 2. Docker"
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io docker-compose-v2 curl openssl >/dev/null
fi
systemctl enable --now docker >/dev/null

echo "== 3. File cấu hình vào $DIR"
mkdir -p "$DIR"
for f in compose.yml Caddyfile update.sh; do curl -fsSL "$RAW/$f" -o "$DIR/$f"; done
chmod +x "$DIR/update.sh"

echo "== 4. Địa chỉ trang"
SITE="${1:-}"
if [ -z "$SITE" ]; then
  TOKEN=$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
  IP=$(curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
  SITE="${IP//./-}.sslip.io"
fi
echo "SITE_ADDRESS=$SITE" > "$DIR/site.env"
echo "   https://$SITE"

if [ ! -f "$DIR/.env" ]; then
  umask 077
  cat > "$DIR/.env" <<ENV
# Bí mật của TravelMate trên máy này. Chỉ root đọc được; không đưa vào git, không gửi cho ai.
# Điền 2 dòng trống bên dưới (GOOGLE_API_KEY, TRAVELMATE_DATABASE_URL) rồi chạy lại: sudo bash setup.sh
GOOGLE_API_KEY=
TRAVELMATE_DATABASE_URL=
TRAVELMATE_ADMIN_EMAIL=
TRAVELMATE_OPERATOR_NAME=
TRAVELMATE_CONTACT_EMAIL=

# Đã điền sẵn
TRAVELMATE_PUBLIC_URL=https://$SITE
TRAVELMATE_API_TOKEN=$(openssl rand -hex 32)
GEMINI_MODEL=gemini-3.5-flash-lite
TRAVELMATE_DAILY_PLANS=10
TRAVELMATE_DAILY_CHATS=60
TRAVELMATE_SIGNUP_OPEN=true
ENV
  echo
  echo "Đã tạo $DIR/.env. Mở để điền khoá Gemini và chuỗi kết nối Neon:"
  echo "   sudo nano $DIR/.env"
  echo "rồi chạy lại: sudo bash setup.sh ${1:-}"
  exit 0
fi
if grep -Eq '^(GOOGLE_API_KEY|TRAVELMATE_DATABASE_URL)=$' "$DIR/.env"; then
  echo "Còn thiếu GOOGLE_API_KEY hoặc TRAVELMATE_DATABASE_URL trong $DIR/.env: sudo nano $DIR/.env"
  exit 1
fi
# Đổi địa chỉ (ví dụ sang tên miền riêng) thì đổi luôn TRAVELMATE_PUBLIC_URL.
sed -i "s#^TRAVELMATE_PUBLIC_URL=.*#TRAVELMATE_PUBLIC_URL=https://$SITE#" "$DIR/.env"

echo "== 5. Tự cập nhật 5 phút một lần khi main có image mới"
cat > /etc/systemd/system/travelmate-update.service <<UNIT
[Unit]
Description=Pull the latest TravelMate image and restart if it changed
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
ExecStart=$DIR/update.sh
UNIT
cat > /etc/systemd/system/travelmate-update.timer <<UNIT
[Unit]
Description=Check for a new TravelMate image every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now travelmate-update.timer >/dev/null

echo "== 6. Khởi động"
"$DIR/update.sh"
echo "   chờ app sẵn sàng..."
for _ in $(seq 1 40); do
  if curl -fsS "https://$SITE/health" >/dev/null 2>&1; then
    echo "Xong: https://$SITE  (kiểm tra: https://$SITE/health)"
    exit 0
  fi
  sleep 5
done
echo "Chưa mở được https://$SITE/health sau 200 giây. Xem log: cd $DIR && sudo docker compose --env-file site.env logs --tail 50"
exit 1
