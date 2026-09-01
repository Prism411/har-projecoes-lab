# Participante 31 — especificação iPhone e tempo real

## Decisão de viabilidade

É possível usar um iPhone sem aplicativo nativo. O Safari expõe movimento por
`DeviceMotionEvent`, incluindo aceleração, aceleração com gravidade, taxa de
rotação e intervalo. A captura precisa ocorrer em um contexto seguro visível e
a permissão deve ser solicitada após um toque do usuário. `http://127.0.0.1`
serve para testes no próprio notebook, mas o iPhone acessando outro aparelho
pela rede precisa de HTTPS; o `localhost` do telefone não representa o notebook.

O `file://` atual continua válido como entrega offline do laboratório, mas não é
a superfície de captura. O modo ao vivo adiciona um pequeno servidor e duas
rotas web:

- `/mobile`: controle de captura aberto diretamente no Safari do iPhone;
- `/dashboard`: monitor técnico aberto no notebook;
- `/ws/mobile`: entrada dos lotes de sensores;
- `/ws/dashboard`: retransmissão para uma ou mais telas.

## Experiência móvel

### Estado 1 — conexão

- Marca curta: `HAR / PARTICIPANTE 31`.
- Indicadores: servidor, HTTPS, Safari, conexão com a sessão.
- Uma única ação principal: `Conectar ao experimento`.
- Se o QR já incluir a sessão, nenhum código precisa ser digitado.

### Estado 2 — autorização

- Explicação em duas linhas sobre acelerômetro e giroscópio.
- Ação `Permitir sensores`, que chama `requestPermission()` no gesto de toque.
- Erros específicos para permissão negada, contexto inseguro, iframe e campos
  nulos.

### Estado 3 — preparação

- Ilustração funcional da orientação: iPhone em retrato, tela para fora, preso
  firmemente à cintura.
- Escolha da atividade instruída.
- Ação `Calibrar parado por 3 segundos`.
- Verificações: taxa observada, campos disponíveis, ruído parado e conexão.

### Estado 4 — gravação

- Contagem regressiva 3–2–1.
- Cronômetro grande, atividade e estado da conexão.
- Botão de parada sempre visível.
- Sem gráficos densos: o participante precisa executar a atividade com segurança.
- Feedback háptico/sonoro é opcional e nunca o único feedback.

### Estado 5 — envio e resultado

- Quantidade de amostras, frequência observada, lacunas e janelas válidas.
- Confirmação de que a gravação chegou ao notebook.
- Ações `Gravar novamente` e `Encerrar`.

## Experiência no notebook

- Cabeçalho `Participante 31` com conexão, bateria de dados e atividade instruída.
- Cena do aparelho mostrando eixos do dispositivo e orientação medida.
- Sinais X/Y/Z em tempo real, usados como diagnóstico e não como palco principal.
- Buffer temporal bruto e marcador de 2,56 segundos antes da reamostragem.
- Ao fechar uma janela: novo ponto `VOCÊ` e trilha temporal no PCA/UMAP.
- Painel de vizinhos: composição das atividades mais próximas e distância.
- Indicador `dentro / limítrofe / fora da distribuição`.
- t-SNE ao vivo marcado como indisponível ou aproximado; nunca apresentado como
  `transform()` nativo.

## Contrato de streaming

O iPhone transmite lotes para reduzir overhead e preservar timestamps reais:

```json
{
  "type": "samples",
  "session": "P31",
  "sequence": 18,
  "sent_at": 1787500000000,
  "samples": [
    {
      "t": 1787499999900,
      "interval_ms": 20,
      "acceleration": [0.1, -0.2, 0.3],
      "acceleration_gravity": [0.2, 9.5, 1.3],
      "rotation_deg_s": [1.2, -3.4, 0.5],
      "orientation_deg": [110.0, 3.0, -1.0]
    }
  ]
}
```

Mensagens de estado usam `hello`, `status`, `recording`, `samples`, `summary`
e `error`. Cada lote recebe no servidor `server_received_at` antes de ser
retransmitido. O token de pareamento via query string é obrigatório nos dois
WebSockets, cada lote aceita no máximo 25 amostras e o frame é limitado a 256
KiB. O servidor descarta campos desconhecidos, números não finitos, atividades
inválidas e estados fora do protocolo.

`acceleration` pode ser nulo em implementações que não separam gravidade. Nesse
caso, a captura aceita `acceleration_gravity` como fallback operacional e
registra separadamente a proporção de amostras com aceleração linear nativa. O
pipeline científico precisa remover ou estimar gravidade antes de comparar
esses dados ao HAR.

## Compatibilidade científica com o HAR

Não é seguro aplicar diretamente o scaler atual: o projeto carrega as 561
features prontas da UCI, mas ainda não reproduz sua extração integral a partir de
um sinal novo. A rota recomendada é criar um **pipeline live compatível**:

1. Usar as mesmas seis séries disponíveis no HAR e no navegador: aceleração
   linear X/Y/Z e giroscópio X/Y/Z.
2. Converter aceleração de m/s² para g e rotação de deg/s para rad/s.
3. Preservar timestamps e reamostrar por interpolação para 50 Hz.
4. Formar janelas de 128 amostras com passo 64.
5. Extrair um conjunto documentado de características temporais e espectrais
   implementado igualmente para todas as 10.299 janelas HAR e para o iPhone.
6. Reajustar scaler, PCA e UMAP nesse espaço comum e salvar os modelos completos.
7. Usar `PCA.transform()` e `UMAP.transform()` nas novas janelas.

Essa projeção deve aparecer como `HAR live — features comuns`, separada da vista
oficial de 561 features. Uma alternativa aproximada por vizinhos pode existir
como contingência, mas precisa ser rotulada como interpolação, não como UMAP.

## Montagem e domínio

- Posição obrigatória: cintura, iPhone em retrato e tela para fora.
- Eixos do navegador pertencem ao aparelho, não à sala.
- A página registra orientação de tela e calibração inicial.
- Hardware e filtros do iPhone diferem do Samsung Galaxy S II do HAR.
- O resultado é exploratório; distância alta deve aparecer como mudança de
  domínio, não como atividade “errada”.

## Segurança operacional

- Não usar iframe para a captura no iPhone.
- Manter a tela ativa e o Safari em primeiro plano.
- Interromper gravação ao perder visibilidade ou conexão e sinalizar o motivo.
- Preferir lotes de 5–10 amostras a um frame WebSocket por evento.
- Não armazenar gravações sem ação explícita do usuário.
- Manter CSV de demonstração e replay offline como contingência.
- Usar token aleatório temporário, não reutilizá-lo e não divulgar a URL completa.
- Limitar payloads e validar mensagens no servidor antes da retransmissão.
- Manter o dashboard somente leitura e bloquear iframe, cache e scripts externos.

## Estratégia HTTPS

### Apresentação com internet

Servidor local HTTP exposto por túnel HTTPS temporário. É a menor fricção para o
iPhone, mas depende da rede externa e deve usar uma URL efêmera com token. Um
Funnel público deve permanecer ativo somente durante o teste.

### Apresentação sem internet

Servidor HTTPS local com certificado previamente instalado e confiado no
iPhone. Exige preparação anterior, mas mantém todo o tráfego na rede local.

## Critérios de aceite no iPhone real

- Safari abre a página como documento principal e informa `isSecureContext`.
- O toque gera o prompt e retorna permissão concedida.
- Pelo menos 90% dos eventos de uma gravação de 10 s têm rotação e uma fonte de
  aceleração completas; registrar à parte quantos possuem aceleração linear.
- Frequência mediana observada e distribuição dos intervalos são registradas.
- Dashboard recebe lotes, calcula latência e detecta desconexão.
- Bloquear a tela ou trocar de aplicativo interrompe/sinaliza a captura.
- CSV exportado preserva timestamps e unidades.
- Replay do mesmo CSV produz exatamente as mesmas janelas.

## Fontes oficiais

- W3C Device Orientation and Motion:
  <https://www.w3.org/TR/orientation-event/>
- W3C Secure Contexts:
  <https://www.w3.org/TR/secure-contexts/>
- Apple WebKit `DeviceMotionEvent`:
  <https://developer.apple.com/documentation/webkitjs/devicemotionevent>
- WebKit — problema de permissões em iframe no iOS 26:
  <https://bugs.webkit.org/show_bug.cgi?id=301294>
- UCI HAR Smartphones:
  <https://archive.ics.uci.edu/dataset/240/humanactivityrecognitionusingsmartphones>
- UMAP transform:
  <https://umap-learn.readthedocs.io/en/latest/transform.html>
- Tailscale Funnel:
  <https://tailscale.com/docs/features/tailscale-funnel>
