# Laboratório de Projeções — HAR real

> **SCC5836 — Visualização Computacional**
>
> **Jader Louis de Souza Gonçalves**
> Rhonner Politzer Ramírez Flores
> Caio César de Sousa Oliveira
> Wanner Martins de Menezes

Adaptação do protótipo GAP para o dataset oficial **Human Activity Recognition
Using Smartphones**, da UCI. O pipeline usa as 10.299 amostras e 561 atributos,
mantém IDs estáveis e exporta PCA, três configurações de t-SNE, três de UMAP,
um UMAP 3D, vizinhos originais e métricas para a interface ECharts + Plotly.

A interface filtra simultaneamente os três painéis por uma faixa de participantes
em slider duplo, conjunto de treino/teste e atividade. Seleção vinculada, lente
de vizinhança, contagens, legenda e reenquadramento respeitam o subconjunto
visível. A aba UMAP 3D reutiliza os mesmos filtros e permite clicar em um ponto
para destacá-lo nas três projeções 2D.

O laboratório possui vistas dedicadas **PCA**, **t-SNE** e **UMAP**. PCA ocupa
um painel amplo; t-SNE compara perplexidades 10/30/50; UMAP compara perfis
local/equilibrado/amplo. O inspetor não interfere nessa demonstração: depois de
selecionar um ponto ou usar o laço, ele só abre pelo botão explícito de detalhes.

## Estrutura

- `src/build_har_data.py`: carrega o ZIP UCI, calcula projeções e gera dados.
- `src/prepare_prototype.py`: preserva e adapta o protótipo GAP.
- `src/add_inspector.py`: adiciona o inspetor contextual ao protótipo.
- `src/bundle_html.py`: cria um HTML único sem dependências de rede.
- `web/index.html`: versão de desenvolvimento com scripts locais.
- `web/har-data.js`: dados reais gerados pelo pipeline.
- `dist/laboratorio-har-real.html`: entrega autocontida.
- `results/metrics.json`: métricas e metadados de reprodutibilidade.
- `ANALISE-PARA-APRESENTACAO.md`: achados quantitativos, interpretação e fala
  pronta sobre atividades estáticas/dinâmicas, PCA, t-SNE e UMAP.
- `results/analysis_interpretavel.json`: resultados numéricos reproduzíveis.
- `web/vendor/plotly-gl3d.min.js`: bundle parcial local usado somente no 3D.
- `web/vendor/LICENSE.plotly.txt`: licença da dependência Plotly vendorizada.
- `tests/smoke_ui.py`: valida filtros, linked selection 2D/3D, CVD e uso offline.

## Protocolo

- Entrada comum: `StandardScaler` sobre os 561 atributos.
- PCA: 50 componentes; PC1 e PC2 alimentam o painel 2D.
- t-SNE: entrada PCA50, perplexidades 10, 30 e 50, seed 42.
- UMAP: perfis local `(10, 0.05)`, equilibrado `(30, 0.10)` e amplo
  `(100, 0.50)`, seed 42.
- UMAP 3D: perfil equilibrado `(30, 0.10)`, métrica euclidiana, inicialização
  espectral e seed 42; as três coordenadas são pré-calculadas em Python.
- Vizinhos originais: aproximação NNDescent nos 561 atributos padronizados.
- Inspetor: seis sinais inerciais com 128 leituras por janela e matriz 10.299 ×
  561 quantizada; ambos são comprimidos no próprio HTML e abertos localmente
  somente após a primeira seleção.
- Métricas: trustworthiness, continuity, overlap k-NN, Spearman de distâncias e
  silhouette secundária, calculadas em subamostra estratificada fixa.
- Rótulos não entram no ajuste das projeções; são usados somente para cor,
  símbolos, acessibilidade e métricas secundárias.

## Execução

```bash
python3 -m venv --system-site-packages .venv
PIP_CACHE_DIR=.cache/pip .venv/bin/pip install -r requirements.txt

.venv/bin/python src/prepare_prototype.py
.venv/bin/python src/build_har_data.py
.venv/bin/python src/bundle_html.py
```

Para abrir a versão de desenvolvimento:

```bash
python3 -m http.server 8000 --directory web
```

Depois acesse `http://localhost:8000`. A entrega em `dist/` abre diretamente no
navegador e não precisa de servidor nem internet.

Na aba **UMAP 3D**, arraste para rotacionar, use a roda para zoom e clique em um
ponto para vinculá-lo aos painéis PCA, t-SNE e UMAP 2D. A câmera é preservada ao
alterar filtros e pode ser restaurada pelo botão da própria aba.

No modo **Laboratório**, clique em um ponto e, somente se desejar sair da
demonstração dos métodos, pressione **Abrir detalhes da amostra**. Aceleração e
giroscópio podem ser alternados; em uma seleção por laço, o sinal permanece
associado à amostra em foco e os demais painéis resumem todo o grupo.

## Observação científica

As distâncias, áreas e densidades aparentes de t-SNE e UMAP não são medidas
diretas da geometria original. A interface compara preservação de vizinhanças e
parâmetros; ela não declara um vencedor universal.

## Spike Participante 31 — iPhone sem aplicativo

O diretório `live/` contém uma primeira superfície móvel para Safari e um
monitor de transmissão para o notebook. `src/live_server.py` serve as duas
páginas e retransmite lotes de sensores por WebSocket.

Instale as dependências do modo ao vivo e inicie o servidor local:

```bash
.venv/bin/pip install -r requirements-live.txt
.venv/bin/python src/live_server.py --host 127.0.0.1 --port 8765
```

Abra no notebook:

```text
http://127.0.0.1:8765/dashboard?session=P31&token=TOKEN_GERADO
```

O servidor imprime as URLs completas e gera um token de pareamento aleatório a
cada inicialização. Não remova esse token nem publique a URL completa. Logs de
acesso ficam desativados para que a query autenticada não seja repetida no
terminal.

No próprio notebook, `http://127.0.0.1` é aceito como contexto local confiável.
No iPhone, porém, `localhost` apontaria para o próprio telefone e o IP comum da
rede local não é um contexto seguro. Por isso a página acessada pelo iPhone
precisa chegar por HTTPS.

### HTTPS privado com Tailscale Serve

O fluxo validado usa `tailscale serve`, restrito à tailnet. Ele fornece
certificado `ts.net` válido e encaminha WSS sem publicar o relay na internet. O
iPhone precisa estar conectado à mesma tailnet com o aplicativo Tailscale ativo.

Uma vez por máquina, se o comando exigir `root`, autorize o usuário local como
operador:

```bash
sudo tailscale set --operator="$USER"
```

Com relay e laboratório escutando somente em loopback, publique-os em portas
HTTPS distintas:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8765
tailscale serve --bg --https=8443 http://127.0.0.1:8000
tailscale serve status
```

As URLs ficam no formato:

```text
https://HOST-FORNECIDO/mobile?session=P31&token=TOKEN_GERADO
https://HOST-FORNECIDO/dashboard?session=P31&token=TOKEN_GERADO
https://HOST-FORNECIDO:8443/
```

Use exatamente a mesma `session` e o mesmo `token` na URL do dashboard. O token
é uma credencial temporária e não deve ser publicada. Abra a URL móvel
diretamente no Safari, toque em **Permitir sensores**, calibre o aparelho parado
e só então grave. O parâmetro adicional `&demo=1` simula sinais para
desenvolvimento sem telefone, mas nunca deve ser usado em resultados.

Para retirar as duas publicações privadas:

```bash
tailscale serve --https=443 off
tailscale serve --https=8443 off
```

`tailscale funnel` não faz parte do fluxo validado. Ele só deve ser considerado
quando o iPhone não puder entrar na tailnet, pois torna o serviço acessível pela
internet pública e exige uma avaliação de risco separada.

### Pacote portátil para o notebook

O pacote `har-live` reúne páginas, relay, laboratório, wheels para Python
3.10–3.13 e scripts de início/parada. Enquanto a entrega privada estiver ativa,
uma máquina conectada à tailnet pode instalar pelo endereço:

```text
https://jader-ms-7d95.tailb93332.ts.net/entrega/
```

Prefira baixar e inspecionar o instalador antes de executá-lo:

```bash
curl -fsSLO https://jader-ms-7d95.tailb93332.ts.net/entrega/instalar.sh
less instalar.sh
bash instalar.sh
```

Depois da instalação em `~/har-live`:

```bash
~/har-live/start-har-live.sh
cat ~/har-live/.run/urls.txt
~/har-live/stop-har-live.sh
```

O arquivo de URLs e o token são recriados a cada início com permissão `0600` e
removidos na parada.

O relay aceita somente tipos de mensagem conhecidos, limita lote e tamanho de
frame, valida números e faixas, mantém o dashboard somente leitura e envia
headers contra cache, iframe e carregamento de scripts externos. Ainda assim,
encerre o modo ao vivo após a demonstração e reinicie-o para invalidar o token
utilizado.

O spike valida captura, estados, CSV e transporte. Ainda não insere a gravação
nas projeções oficiais: `LIVE-IPHONE-SPEC.md` explica por que é necessário
reajustar um pipeline com características extraídas igualmente do HAR bruto e
do iPhone.
