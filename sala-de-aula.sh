#!/usr/bin/env bash
# Modo sala de aula: vários iPhones capturando ao mesmo tempo, sem internet.
#
# A peça central é o DNS. O certificado vale para um NOME, e o aparelho do aluno
# precisa resolver esse nome para o IP do notebook na rede local. Quem faz isso
# é o dnsmasq que o NetworkManager já sobe junto com o hotspot.
#
#   iPhone → hotspot do notebook → "qual o IP de <nome>?" → IP local
#          → HTTPS com certificado válido → sensores liberados
#
# Sem o passo do DNS, o Safari recusaria o certificado; sem o certificado, o
# Safari recusaria os sensores. Os dois precisam estar de pé.
set -euo pipefail

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="$BASE/cert"
RUN="$BASE/.run"
VENV="$BASE/.venv"
PORTA="${HAR_PORTA:-443}"
SALA="${HAR_SALA:-AULA}"
WIFI_NOME="${HAR_WIFI:-laboratorio-har}"
WIFI_SENHA="${HAR_WIFI_SENHA:-}"
mkdir -p "$RUN"

log(){ printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31merro:\033[0m %s\n' "$*" >&2; exit 1; }

[ -s "$CERT_DIR/servidor.crt" ] || die "sem certificado. Rode antes: ./emitir-certificado.sh"
NOME="$(cat "$CERT_DIR/nome.txt")"

# ------------------------------------------------------------------- o hotspot
criar_hotspot() {
  command -v nmcli >/dev/null || die "nmcli não encontrado (NetworkManager)."
  if nmcli -t -f NAME connection show --active 2>/dev/null | grep -qx "$WIFI_NOME"; then
    log "hotspot '$WIFI_NOME' já está ativo"
    return 0
  fi
  local dispositivo
  dispositivo="$(nmcli -t -f DEVICE,TYPE device | awk -F: '$2=="wifi"{print $1; exit}')"
  [ -n "$dispositivo" ] || die "nenhuma interface wifi encontrada."

  log "criando o hotspot '$WIFI_NOME' em $dispositivo"
  if [ -n "$WIFI_SENHA" ]; then
    sudo nmcli device wifi hotspot ifname "$dispositivo" con-name "$WIFI_NOME" \
      ssid "$WIFI_NOME" password "$WIFI_SENHA" >/dev/null
  else
    sudo nmcli device wifi hotspot ifname "$dispositivo" con-name "$WIFI_NOME" \
      ssid "$WIFI_NOME" >/dev/null
    log "hotspot aberto, sem senha — use apenas durante a aula"
  fi
}

# --------------------------------------------------- o nome resolvendo para cá
configurar_dns_local() {
  local ip="$1"
  local destino=/etc/NetworkManager/dnsmasq-shared.d/har-live.conf
  log "fazendo $NOME apontar para $ip na rede do hotspot"
  sudo mkdir -p "$(dirname "$destino")"
  # address=/nome/IP responde esse nome com esse IP para quem usa este dnsmasq
  printf 'address=/%s/%s\n' "$NOME" "$ip" | sudo tee "$destino" >/dev/null
  sudo systemctl reload NetworkManager 2>/dev/null || sudo systemctl restart NetworkManager
}

ip_do_hotspot() {
  local dispositivo
  dispositivo="$(nmcli -t -f DEVICE,TYPE device | awk -F: '$2=="wifi"{print $1; exit}')"
  ip -4 addr show "$dispositivo" 2>/dev/null | grep -oP 'inet \K[\d.]+' | head -1
}

criar_hotspot
sleep 3
IP="$(ip_do_hotspot)"
[ -n "$IP" ] || die "o hotspot subiu sem endereço IPv4."
configurar_dns_local "$IP"

# ------------------------------------------------------------------- servidor
TOKEN="${HAR_LIVE_TOKEN:-$(python3 -c 'import secrets;print(secrets.token_urlsafe(18))')}"
printf '%s' "$TOKEN" > "$RUN/token"; chmod 600 "$RUN/token"

for nome_servico in live lab; do
  [ -f "$RUN/$nome_servico.pid" ] && { kill "$(cat "$RUN/$nome_servico.pid")" 2>/dev/null || true; rm -f "$RUN/$nome_servico.pid"; }
done

log "servindo HTTPS direto na porta $PORTA"
sudo -E "$VENV/bin/python" "$BASE/src/live_server.py" \
  --host 0.0.0.0 --port "$PORTA" --token "$TOKEN" \
  --ssl-certfile "$CERT_DIR/servidor.crt" --ssl-keyfile "$CERT_DIR/servidor.key" \
  > "$RUN/live.log" 2>&1 &
echo $! > "$RUN/live.pid"

curl -sfk --retry 40 --retry-delay 1 --retry-connrefused \
  "https://127.0.0.1:$PORTA/api/health" >/dev/null \
  || { sed 's/^/    /' "$RUN/live.log"; die "o servidor não subiu."; }

BASE_URL="https://$NOME$([ "$PORTA" = 443 ] || echo ":$PORTA")"
cat > "$RUN/sala.txt" <<URLS
Wi-Fi da sala : $WIFI_NOME${WIFI_SENHA:+  (senha: $WIFI_SENHA)}
Captura       : $BASE_URL/mobile?session=$SALA&token=$TOKEN&participante=NUMERO
Painel        : $BASE_URL/dashboard?session=$SALA&token=$TOKEN
Laboratório   : $BASE_URL/laboratorio/?token=$TOKEN
URLS
chmod 600 "$RUN/sala.txt"

printf '\n\033[1;32mSala pronta.\033[0m Sem internet e sem instalar nada no iPhone.\n\n'
sed 's/^/  /' "$RUN/sala.txt"
cat <<FIM

  Cada aluno troca NUMERO pelo próprio (31 em diante; 1 a 30 são da UCI).
  Um QR por número evita digitação.

  Para encerrar: $BASE/encerrar-sala.sh
FIM
