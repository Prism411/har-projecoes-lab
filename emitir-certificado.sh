#!/usr/bin/env bash
# Emite o certificado HTTPS usado na sala de aula.
#
# O iPhone só libera acelerômetro e giroscópio em contexto seguro, e não existe
# certificado para IP privado. A saída é ter um NOME com certificado válido e
# fazer a rede local resolver esse nome para o IP do notebook.
#
# Dois caminhos, nesta ordem:
#   1. seu domínio, por desafio DNS (funciona sem expor o notebook à internet);
#   2. o nome .ts.net do Tailscale, que também rende um Let's Encrypt de verdade.
#
# Os dois produzem certificado publicamente confiável: nada para instalar no
# aparelho dos alunos.
set -euo pipefail

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="$BASE/cert"
DOMINIO="${HAR_DOMINIO:-}"
EMAIL="${HAR_EMAIL:-}"

log(){ printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31merro:\033[0m %s\n' "$*" >&2; exit 1; }

mkdir -p "$CERT_DIR"
chmod 700 "$CERT_DIR"

instalar_acme() {
  [ -x "$HOME/.acme.sh/acme.sh" ] && return 0
  log "instalando o acme.sh (cliente Let's Encrypt, sem root)"
  command -v curl >/dev/null || die "curl é necessário."
  curl -fsS https://get.acme.sh | sh -s email="${EMAIL:-nobody@example.com}" >/dev/null
  [ -x "$HOME/.acme.sh/acme.sh" ] || die "não consegui instalar o acme.sh."
}

emitir_pelo_dominio() {
  [ -n "$DOMINIO" ] || return 1
  [ -n "${CF_Token:-}" ] || {
    log "sem CF_Token no ambiente: pulando o caminho do domínio"
    return 1
  }
  instalar_acme
  log "emitindo certificado para $DOMINIO por desafio DNS"
  # O desafio DNS não exige que o notebook esteja acessível pela internet:
  # a prova é um registro TXT na zona, criado e removido pela API.
  CF_Token="$CF_Token" "$HOME/.acme.sh/acme.sh" --issue \
    --dns dns_cf -d "$DOMINIO" \
    --server letsencrypt --keylength ec-256 >/dev/null 2>&1 \
    || { log "a emissão falhou (token sem permissão de zona? domínio ainda propagando?)"; return 1; }

  "$HOME/.acme.sh/acme.sh" --install-cert -d "$DOMINIO" --ecc \
    --key-file "$CERT_DIR/servidor.key" \
    --fullchain-file "$CERT_DIR/servidor.crt" >/dev/null
  printf '%s' "$DOMINIO" > "$CERT_DIR/nome.txt"
  return 0
}

emitir_pelo_tailscale() {
  command -v tailscale >/dev/null || return 1
  local nome
  nome="$(tailscale status --json 2>/dev/null \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')" || return 1
  [ -n "$nome" ] || return 1
  log "emitindo certificado para $nome (Tailscale)"
  tailscale cert --cert-file "$CERT_DIR/servidor.crt" --key-file "$CERT_DIR/servidor.key" "$nome" >/dev/null 2>&1 \
    || { log "o Tailscale recusou emitir (HTTPS habilitado na tailnet?)"; return 1; }
  printf '%s' "$nome" > "$CERT_DIR/nome.txt"
  return 0
}

if ! emitir_pelo_dominio; then
  emitir_pelo_tailscale || die "nenhum caminho de certificado funcionou."
fi

chmod 600 "$CERT_DIR/servidor.key"
chmod 644 "$CERT_DIR/servidor.crt"

NOME="$(cat "$CERT_DIR/nome.txt")"
VALIDADE="$(openssl x509 -in "$CERT_DIR/servidor.crt" -noout -enddate | cut -d= -f2)"
EMISSOR="$(openssl x509 -in "$CERT_DIR/servidor.crt" -noout -issuer | sed 's/.*CN *= *//')"

printf '\n\033[1;32mCertificado pronto.\033[0m\n\n'
printf '  nome      : %s\n' "$NOME"
printf '  emissor   : %s\n' "$EMISSOR"
printf '  válido até: %s\n' "$VALIDADE"
printf '  arquivos  : %s\n\n' "$CERT_DIR"
printf '  Nada para instalar no iPhone: este certificado é confiável de fábrica.\n'
printf '  Renove antes da validade acabar — a emissão precisa de internet.\n'
