#!/usr/bin/env bash
# Encerra o modo sala: derruba o servidor, o hotspot e o DNS local.
set -uo pipefail
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN="$BASE/.run"
WIFI_NOME="${HAR_WIFI:-laboratorio-har}"

[ -f "$RUN/live.pid" ] && { sudo kill "$(cat "$RUN/live.pid")" 2>/dev/null; rm -f "$RUN/live.pid"; echo "==> servidor encerrado"; }
sudo rm -f /etc/NetworkManager/dnsmasq-shared.d/har-live.conf 2>/dev/null && echo "==> DNS local removido"
sudo nmcli connection down "$WIFI_NOME" 2>/dev/null && echo "==> hotspot desligado"
sudo systemctl reload NetworkManager 2>/dev/null || true
rm -f "$RUN/token" "$RUN/sala.txt"
echo "==> token invalidado"
