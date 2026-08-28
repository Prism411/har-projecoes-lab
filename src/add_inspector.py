from __future__ import annotations


def replace_once(source: str, old: str, new: str) -> str:
    if old not in source:
        raise ValueError(f"Trecho do inspetor não encontrado: {old[:100]!r}")
    return source.replace(old, new, 1)


def apply_inspector(html: str) -> str:
    html = replace_once(
        html,
        ".dual-range input[type=range]:focus-visible::-moz-range-thumb{box-shadow:0 0 0 3px #FFFFFF,0 0 0 6px #0072B2}",
        ".dual-range input[type=range]:focus-visible::-moz-range-thumb{box-shadow:0 0 0 3px #FFFFFF,0 0 0 6px #0072B2}\n"
        ".inspector-grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(360px,.85fr);gap:12px}\n"
        ".inspector-card{border:1px solid #D8D8D3;background:#FFFFFF;min-width:0}\n"
        ".inspector-card-head{padding:9px 11px;border-bottom:1px solid #E4E4E0;background:#FAFAF8}\n"
        ".inspector-kicker{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:#5F5F59;font-weight:700}\n"
        ".inspector-meta{display:grid;grid-template-columns:repeat(6,minmax(110px,1fr));border-top:1px solid #D8D8D3;border-left:1px solid #D8D8D3}\n"
        ".inspector-meta>div{padding:8px 10px;border-right:1px solid #D8D8D3;border-bottom:1px solid #D8D8D3;min-width:0}\n"
        ".inspector-chart{height:270px;width:100%}\n"
        "@media(max-width:1050px){.inspector-grid{grid-template-columns:1fr}.inspector-meta{grid-template-columns:repeat(3,minmax(110px,1fr))}}\n"
        "@media(max-width:680px){.inspector-meta{grid-template-columns:repeat(2,minmax(110px,1fr))}.inspector-chart{height:245px}}",
    )

    inspector_template = r'''
    <sc-if value="{{ mostraInspetor }}" hint-placeholder-val="{{ false }}">
      <section data-testid="inspetor-amostra" aria-labelledby="inspetor-titulo" style="flex:0 0 auto;margin:4px 0 12px;border-top:3px solid #121212;padding-top:10px">
        <header style="display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:9px">
          <div style="min-width:0">
            <div class="inspector-kicker">Dados originais por trás do ponto</div>
            <h2 id="inspetor-titulo" style="margin:2px 0 2px;font-size:21px;line-height:1.2;letter-spacing:-.02em">{{ inspectorTitulo }}</h2>
            <p style="margin:0;color:#3F3F3B;font-size:13px;max-width:100ch;text-wrap:pretty">{{ inspectorSubtitulo }}</p>
          </div>
          <span style="flex:0 0 auto;border:1px solid #121212;padding:4px 7px;font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase">janela de 2,56 s · 50 Hz</span>
        </header>

        <div class="inspector-meta">
          <sc-for list="{{ inspectorMeta }}" as="m" hint-placeholder-count="6">
            <div>
              <div class="inspector-kicker">{{ m.k }}</div>
              <div style="margin-top:2px;font-size:13px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{{ m.v }}">{{ m.v }}</div>
            </div>
          </sc-for>
        </div>

        <sc-if value="{{ inspectorCarregando }}" hint-placeholder-val="{{ false }}">
          <div role="status" style="margin-top:10px;border:1px solid #D8D8D3;background:#FAFAF8;padding:14px;font-size:13px">Descompactando localmente os sinais e as 561 características… isso acontece apenas na primeira seleção.</div>
        </sc-if>
        <sc-if value="{{ inspectorErro }}" hint-placeholder-val="{{ false }}">
          <div role="alert" style="margin-top:10px;border:1px solid #D55E00;background:#FFF3E6;padding:14px;font-size:13px">{{ inspectorErro }}</div>
        </sc-if>

        <sc-if value="{{ inspectorPronto }}" hint-placeholder-val="{{ false }}">
          <div class="inspector-grid" style="margin-top:12px">
            <article class="inspector-card">
              <div class="inspector-card-head" style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">
                <div>
                  <div class="inspector-kicker">Sinal original da amostra em foco</div>
                  <strong style="font-size:14px">{{ inspectorSinalTitulo }}</strong>
                </div>
                <div role="group" aria-label="Tipo de sinal" style="display:flex;gap:4px">
                  <sc-for list="{{ segSinal }}" as="o" hint-placeholder-count="2">
                    <button type="button" onClick="{{ o.on }}" aria-pressed="{{ o.pressed }}" style="border:1px solid #121212;padding:5px 9px;font-size:12px;font-weight:700;cursor:pointer;border-radius:2px;background:{{ o.bg }};color:{{ o.fg }}">{{ o.label }}</button>
                  </sc-for>
                </div>
              </div>
              <div ref="{{ refSinal }}" data-testid="sinal-chart" role="img" aria-label="{{ ariaSinal }}" class="inspector-chart"></div>
              <div style="padding:7px 11px;border-top:1px solid #E4E4E0;color:#5F5F59;font-size:12px">X, Y e Z são eixos do smartphone preso à cintura — não coordenadas da pessoa na sala.</div>
            </article>

            <article class="inspector-card">
              <div class="inspector-card-head">
                <div class="inspector-kicker">Oito características dominantes</div>
                <strong style="font-size:14px">Seleção × {{ inspectorReferencia }}</strong>
              </div>
              <div ref="{{ refPerfil }}" data-testid="perfil-chart" role="img" aria-label="{{ ariaPerfil }}" class="inspector-chart"></div>
              <div style="max-height:180px;overflow:auto;border-top:1px solid #E4E4E0">
                <table style="width:100%;font-size:11.5px">
                  <thead><tr><th style="text-align:left;padding:5px 8px;background:#FAFAF8">característica</th><th style="text-align:right;padding:5px 8px;background:#FAFAF8">seleção</th><th style="text-align:right;padding:5px 8px;background:#FAFAF8">referência</th></tr></thead>
                  <tbody>
                    <sc-for list="{{ inspectorFeatures }}" as="f" hint-placeholder-count="8">
                      <tr><td style="padding:4px 8px;border-top:1px solid #EFEFEC;font-family:ui-monospace,monospace">{{ f.nome }}</td><td style="padding:4px 8px;border-top:1px solid #EFEFEC;text-align:right;font-variant-numeric:tabular-nums">{{ f.atual }}</td><td style="padding:4px 8px;border-top:1px solid #EFEFEC;text-align:right;font-variant-numeric:tabular-nums">{{ f.referencia }}</td></tr>
                    </sc-for>
                  </tbody>
                </table>
              </div>
            </article>

            <article class="inspector-card">
              <div class="inspector-card-head">
                <div class="inspector-kicker">Vizinhança em alta dimensão</div>
                <strong style="font-size:14px">Quantos dos 10 vizinhos reais sobreviveram?</strong>
              </div>
              <div style="padding:10px;display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px">
                <sc-for list="{{ inspectorVizinhos }}" as="n" hint-placeholder-count="4">
                  <div style="border:1px solid #D8D8D3;padding:9px;min-width:0">
                    <div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline"><strong style="font-size:13px">{{ n.metodo }}</strong><b style="font-size:17px;font-variant-numeric:tabular-nums">{{ n.valor }}</b></div>
                    <div style="font-size:11px;color:#5F5F59;margin:2px 0 6px">{{ n.nota }}</div>
                    <div style="display:flex;flex-wrap:wrap;gap:3px">
                      <sc-for list="{{ n.ids }}" as="v" hint-placeholder-count="3">
                        <button type="button" onClick="{{ v.on }}" disabled="{{ v.disabled }}" title="{{ v.title }}" style="border:1px solid #B8B8B2;background:#FFFFFF;padding:2px 4px;font:10px ui-monospace,monospace;cursor:pointer;opacity:{{ v.op }}">{{ v.label }}</button>
                      </sc-for>
                    </div>
                  </div>
                </sc-for>
              </div>
            </article>

            <article class="inspector-card">
              <div class="inspector-card-head">
                <div class="inspector-kicker">Composição da seleção</div>
                <strong style="font-size:14px">{{ inspectorComposicaoTitulo }}</strong>
              </div>
              <div style="padding:10px;display:flex;flex-direction:column;gap:7px">
                <sc-for list="{{ inspectorComposicao }}" as="c" hint-placeholder-count="6">
                  <div style="display:grid;grid-template-columns:minmax(105px,1fr) 2.2fr 76px;gap:8px;align-items:center;font-size:12px">
                    <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ c.label }}</span>
                    <span aria-hidden="true" style="height:10px;background:#EFEFEC;border:1px solid #D8D8D3"><span style="display:block;height:100%;width:{{ c.pct }}%;background:{{ c.cor }}"></span></span>
                    <span style="text-align:right;font-variant-numeric:tabular-nums">{{ c.n }} · {{ c.pctTexto }}</span>
                  </div>
                </sc-for>
              </div>
              <div style="padding:7px 10px;border-top:1px solid #E4E4E0;color:#5F5F59;font-size:12px">{{ inspectorComposicaoNota }}</div>
            </article>
          </div>
        </sc-if>
      </section>
    </sc-if>

'''
    html = replace_once(
        html,
        '    <sc-if value="{{ tabelaAberta }}" hint-placeholder-val="{{ false }}">',
        inspector_template + '    <sc-if value="{{ tabelaAberta }}" hint-placeholder-val="{{ false }}">',
    )

    html = replace_once(
        html,
        "ponto: null, aten: null, rotulo: true, filtroSujeitoMin: null, filtroSujeitoMax: null, filtroSplit: 'todos'\n  };",
        "ponto: null, aten: null, rotulo: true, filtroSujeitoMin: null, filtroSujeitoMax: null, filtroSplit: 'todos',\n"
        "    sinalTipo: 'acc', inspetorAberto: false, interpretacaoPronta: false, interpretacaoErro: null\n  };",
    )
    html = replace_once(
        html,
        "  plot3dEl = null;\n  sig3d = null;",
        "  plot3dEl = null;\n"
        "  sig3d = null;\n"
        "  signalRef = React.createRef();\n"
        "  profileRef = React.createRef();\n"
        "  signalChart = null;\n"
        "  profileChart = null;\n"
        "  profileCache = null;\n"
        "  neighborCache = {};",
    )
    html = replace_once(
        html,
        "    this.purgar3d();\n  }",
        "    this.purgar3d();\n"
        "    this.purgarInspetor();\n"
        "  }",
    )
    html = replace_once(
        html,
        "    this.sync3d();\n  }",
        "    this.sync3d();\n"
        "    this.syncInspetor();\n"
        "  }",
    )
    html = replace_once(
        html,
        "    if (this.plot3dEl && window.Plotly && window.Plotly.Plots) window.Plotly.Plots.resize(this.plot3dEl);\n  };",
        "    if (this.plot3dEl && window.Plotly && window.Plotly.Plots) window.Plotly.Plots.resize(this.plot3dEl);\n"
        "    if (this.signalChart && !this.signalChart.isDisposed()) this.signalChart.resize();\n"
        "    if (this.profileChart && !this.profileChart.isDisposed()) this.profileChart.resize();\n"
        "  };",
    )

    methods = r'''
  // ---------- inspetor dos dados originais ----------
  async inflarBase64(texto) {
    if (!window.DecompressionStream) throw new Error('Este navegador não oferece DecompressionStream para abrir os dados locais.');
    const binario = atob(texto), bytes = new Uint8Array(binario.length);
    for (let i = 0; i < binario.length; i += 1) bytes[i] = binario.charCodeAt(i);
    const fluxo = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate'));
    return new Response(fluxo).arrayBuffer();
  }

  carregarInterpretacao() {
    if (this.interpretacaoCarregando || (this.featureData && this.signalData)) return;
    const I = this.D && this.D.interpretacao;
    if (!I || !I.features || !I.signals) {
      this.setState({ interpretacaoErro: 'O arquivo não contém sinais e características para o inspetor.' });
      return;
    }
    this.interpretacaoCarregando = true;
    Promise.all([this.inflarBase64(I.features.data), this.inflarBase64(I.signals.data)])
      .then(buffers => {
        this.featureData = new Int8Array(buffers[0]);
        this.signalData = new Int16Array(buffers[1]);
        const nf = I.features.shape[0] * I.features.shape[1];
        const ns = I.signals.shape[0] * I.signals.shape[1] * I.signals.shape[2];
        if (this.featureData.length !== nf || this.signalData.length !== ns) throw new Error('Dimensão inesperada após descompactar os dados.');
        this.interpretacaoCarregando = false;
        window.__harInterpretacao = { features: this.featureData, signals: this.signalData };
        this.setState({ interpretacaoPronta: true, interpretacaoErro: null });
      })
      .catch(error => {
        this.interpretacaoCarregando = false;
        this.setState({ interpretacaoErro: 'Falha ao preparar o inspetor: ' + error.message });
      });
  }

  purgarInspetor() {
    [this.signalChart, this.profileChart].forEach(chart => { if (chart && !chart.isDisposed()) chart.dispose(); });
    this.signalChart = null; this.profileChart = null;
    window.__inspectorCharts = null;
  }

  garantirChart(ref, atual) {
    const el = ref.current;
    if (!el) { if (atual && !atual.isDisposed()) atual.dispose(); return null; }
    if (atual && !atual.isDisposed() && atual.getDom() === el) return atual;
    if (atual && !atual.isDisposed()) atual.dispose();
    const orfao = window.echarts.getInstanceByDom(el); if (orfao && !orfao.isDisposed()) orfao.dispose();
    el.removeAttribute('_echarts_instance_'); while (el.firstChild) el.removeChild(el.firstChild);
    return window.echarts.init(el, null, { renderer: 'canvas' });
  }

  syncInspetor() {
    if (!this.state.sel.length || !this.state.inspetorAberto) return this.purgarInspetor();
    if (!this.featureData || !this.signalData) { this.carregarInterpretacao(); return; }
    this.signalChart = this.garantirChart(this.signalRef, this.signalChart);
    this.profileChart = this.garantirChart(this.profileRef, this.profileChart);
    if (this.signalChart) { this.signalChart.resize(); this.signalChart.setOption(this.opcaoSinal(), true); }
    if (this.profileChart) { this.profileChart.resize(); this.profileChart.setOption(this.opcaoPerfil(), true); }
    window.__inspectorCharts = [this.signalChart, this.profileChart];
  }

  focoAtual() {
    const id = this.state.anchor || this.state.sel[0];
    return id ? this.byId[id] : null;
  }

  sinalDaAmostra(indice, canal) {
    const I = this.D.interpretacao.signals, passos = I.shape[2], canais = I.shape[1];
    const multiplicador = I.quantization_multipliers[canal];
    const inicio = (indice * canais + canal) * passos, saida = [];
    for (let t = 0; t < passos; t += 1) saida.push([t / I.sampling_hz, this.signalData[inicio + t] / multiplicador]);
    return saida;
  }

  opcaoSinal() {
    const amostra = this.focoAtual(), I = this.D.interpretacao.signals;
    if (!amostra) return { series: [] };
    const inicio = this.state.sinalTipo === 'gyro' ? 3 : 0;
    const unidade = I.channels[inicio].unit, cores = ['#0072B2', '#E69F00', '#009E73'];
    const series = [0, 1, 2].map((offset, index) => ({
      name: ['X', 'Y', 'Z'][index], type: 'line', showSymbol: false, sampling: 'lttb', animation: false,
      data: this.sinalDaAmostra(this.idxOf[amostra.id], inicio + offset), lineStyle: { width: 1.8, color: cores[index] }, itemStyle: { color: cores[index] }
    }));
    return {
      animation: false, color: cores, aria: { enabled: true, description: 'Sinal temporal nos eixos X, Y e Z da amostra ' + amostra.id + '.' },
      legend: { top: 7, left: 10, itemWidth: 18, itemHeight: 3, textStyle: { color: '#3F3F3B', fontSize: 11 } },
      grid: { left: 58, right: 18, top: 38, bottom: 42 },
      xAxis: { type: 'value', min: 0, max: I.window_seconds - 1 / I.sampling_hz, name: 'tempo (s)', nameLocation: 'middle', nameGap: 27, axisLine: { lineStyle: { color: '#8A8A84' } }, splitLine: { lineStyle: { color: '#EFEFEC' } } },
      yAxis: { type: 'value', name: unidade, nameGap: 38, nameLocation: 'middle', axisLine: { show: true, lineStyle: { color: '#8A8A84' } }, splitLine: { lineStyle: { color: '#EFEFEC' } } },
      dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }],
      tooltip: { trigger: 'axis', backgroundColor: '#FFFFFF', borderColor: '#121212', textStyle: { color: '#121212', fontSize: 11 }, valueFormatter: value => this.fmt(value, 4) + ' ' + unidade },
      series: series
    };
  }

  perfilSelecao() {
    if (!this.featureData || !this.state.sel.length) return null;
    if (this.profileCache && this.profileCache.sel === this.state.sel) return this.profileCache.value;
    const I = this.D.interpretacao, nomes = I.feature_names, n = nomes.length;
    const multiplicador = I.features.quantization_multiplier, atual = new Float64Array(n), contagem = {};
    this.state.sel.forEach(id => {
      const indice = this.idxOf[id], amostra = this.byId[id]; if (indice == null || !amostra) return;
      const inicio = indice * n; for (let j = 0; j < n; j += 1) atual[j] += this.featureData[inicio + j] / multiplicador;
      contagem[amostra.label] = (contagem[amostra.label] || 0) + 1;
    });
    const total = Math.max(1, this.state.sel.length); for (let j = 0; j < n; j += 1) atual[j] /= total;
    const referencia = new Float64Array(n), rotulos = Object.keys(contagem);
    rotulos.forEach(label => {
      const media = I.activity_mean_z[label] || [], peso = contagem[label] / total;
      for (let j = 0; j < n; j += 1) referencia[j] += (media[j] || 0) * peso;
    });
    const indices = Array.from({ length: n }, (_, i) => i).sort((a, b) => Math.abs(atual[b]) - Math.abs(atual[a])).slice(0, 8);
    const foco = this.focoAtual(), classe = foco && this.classById[foco.label];
    const referenciaLabel = rotulos.length === 1 ? 'média de ' + ((classe && classe.label_pt) || foco.label) : 'média ponderada das atividades selecionadas';
    const value = { atual: atual, referencia: referencia, indices: indices, referenciaLabel: referenciaLabel, contagem: contagem };
    this.profileCache = { sel: this.state.sel, value: value }; return value;
  }

  nomeFeature(nome) {
    return String(nome || '')
      .replace(/^tBodyAccJerk/, 'tranco acel. · tempo')
      .replace(/^fBodyAccJerk/, 'tranco acel. · frequência')
      .replace(/^tBodyAcc/, 'acel. corporal · tempo')
      .replace(/^fBodyAcc/, 'acel. corporal · frequência')
      .replace(/^tGravityAcc/, 'gravidade · tempo')
      .replace(/^tBodyGyroJerk/, 'tranco giro · tempo')
      .replace(/^tBodyGyro/, 'giroscópio · tempo')
      .replace(/^fBodyGyro/, 'giroscópio · frequência')
      .replace(/-mean\(\)/, ' · média').replace(/-std\(\)/, ' · desvio').replace(/-max\(\)/, ' · máximo').replace(/-min\(\)/, ' · mínimo');
  }

  opcaoPerfil() {
    const perfil = this.perfilSelecao(); if (!perfil) return { series: [] };
    const nomes = perfil.indices.map(i => this.nomeFeature(this.D.interpretacao.feature_names[i]));
    return {
      animation: false, color: ['#0072B2', '#E69F00'], aria: { enabled: true, description: 'Oito características padronizadas mais fortes da seleção e sua referência por atividade.' },
      legend: { top: 6, left: 8, textStyle: { color: '#3F3F3B', fontSize: 10.5 } },
      grid: { left: 168, right: 16, top: 42, bottom: 28 },
      xAxis: { type: 'value', name: 'desvios-padrão', nameLocation: 'middle', nameGap: 22, axisLine: { lineStyle: { color: '#8A8A84' } }, splitLine: { lineStyle: { color: '#EFEFEC' } } },
      yAxis: { type: 'category', inverse: true, data: nomes, axisLabel: { width: 158, overflow: 'truncate', color: '#3F3F3B', fontSize: 10.5 }, axisTick: { show: false }, axisLine: { lineStyle: { color: '#8A8A84' } } },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: '#FFFFFF', borderColor: '#121212', textStyle: { color: '#121212', fontSize: 11 }, valueFormatter: value => this.fmt(value, 2) + 'σ' },
      series: [
        { name: this.state.sel.length === 1 ? 'amostra' : 'seleção', type: 'bar', data: perfil.indices.map(i => perfil.atual[i]), barMaxWidth: 11, itemStyle: { color: '#0072B2' } },
        { name: 'referência', type: 'bar', data: perfil.indices.map(i => perfil.referencia[i]), barMaxWidth: 11, itemStyle: { color: '#E69F00' } }
      ]
    };
  }

  vizinhancaProjetada(id, chave) {
    const cacheId = id + '@' + chave;
    if (this.neighborCache[cacheId]) return this.neighborCache[cacheId];
    const amostra = this.byId[id], ponto = amostra && amostra.projecoes[chave]; if (!ponto) return { preservados: [], projetados: [] };
    const distancias = [];
    (this.D.amostras || []).forEach(s => {
      if (s.id === id) return; const p = s.projecoes[chave]; if (!p) return;
      const dx = p[0] - ponto[0], dy = p[1] - ponto[1]; distancias.push([dx * dx + dy * dy, s.id]);
    });
    distancias.sort((a, b) => a[0] - b[0]);
    const projetados = distancias.slice(0, 10).map(item => item[1]);
    const originais = amostra.vizinhos_originais_k10 || [];
    const preservados = originais.filter(vizinho => projetados.indexOf(vizinho) >= 0);
    const resultado = { preservados: preservados, projetados: projetados };
    this.neighborCache[cacheId] = resultado; return resultado;
  }

  chipVizinho(id) {
    const habilitado = this.passaFiltros(this.byId[id]);
    return { label: id.replace('har_', '#'), disabled: !habilitado, op: habilitado ? 1 : .42, title: habilitado ? 'Selecionar ' + id : id + ' está fora dos filtros atuais', on: () => this.selecionar(id, false) };
  }

  resumoVizinhos() {
    const ids = this.state.sel, foco = this.focoAtual(), chaves = ['pca', 'tsne', 'umap'].map(t => this.state.cfg[t]).filter(Boolean);
    if (!foco) return [];
    if (ids.length === 1) {
      const originais = foco.vizinhos_originais_k10 || [];
      const cards = [{ metodo: 'Original 561D', valor: originais.length + '/10', nota: 'referência nos atributos padronizados', ids: originais.map(id => this.chipVizinho(id)) }];
      chaves.forEach(chave => {
        const r = this.vizinhancaProjetada(foco.id, chave), tecnica = this.nomeTech(chave.split('/')[0]);
        cards.push({ metodo: tecnica, valor: r.preservados.length + '/10', nota: 'vizinhos originais ainda próximos', ids: r.preservados.map(id => this.chipVizinho(id)) });
      });
      return cards;
    }
    const limite = Math.min(12, ids.length), amostraIds = [];
    for (let i = 0; i < limite; i += 1) amostraIds.push(ids[Math.floor(i * ids.length / limite)]);
    const cards = [{ metodo: 'Original 561D', valor: 'K=10', nota: 'referência para cada ponto', ids: [] }];
    chaves.forEach(chave => {
      let soma = 0; amostraIds.forEach(id => { soma += this.vizinhancaProjetada(id, chave).preservados.length; });
      cards.push({ metodo: this.nomeTech(chave.split('/')[0]), valor: this.fmt(soma / amostraIds.length, 1) + '/10', nota: 'média em ' + amostraIds.length + ' pontos da seleção', ids: [] });
    });
    return cards;
  }

  alternarInspetor = () => {
    const abrir = !this.state.inspetorAberto;
    this.setState({ inspetorAberto: abrir }, () => {
      if (!abrir) return;
      setTimeout(() => {
        const alvo = document.querySelector('[data-testid="inspetor-amostra"]');
        if (alvo && alvo.scrollIntoView) alvo.scrollIntoView({ behavior: this.reduz ? 'auto' : 'smooth', block: 'start' });
      }, 80);
    });
  };

  inspectorViewModel() {
    const S = this.state, amostra = this.focoAtual();
    if (!S.sel.length || !amostra) return {
      mostraInspetor: false,
      btnInspetor: { label: 'Detalhes: selecione um ponto', on: this.alternarInspetor, disabled: true, bg: '#FFFFFF', fg: '#5F5F59', op: .45 }
    };
    const btnInspetor = {
      label: S.inspetorAberto ? 'Fechar detalhes da amostra' : 'Abrir detalhes da amostra', on: this.alternarInspetor,
      disabled: false, bg: S.inspetorAberto ? '#121212' : '#FFFFFF', fg: S.inspetorAberto ? '#FFFFFF' : '#121212', op: 1
    };
    if (!S.inspetorAberto) return { mostraInspetor: false, btnInspetor: btnInspetor };
    const classe = this.classById[amostra.label] || {}, perfil = this.perfilSelecao(), cor = this.paleta();
    const contagem = {}; S.sel.forEach(id => { const s = this.byId[id]; if (s) contagem[s.label] = (contagem[s.label] || 0) + 1; });
    const composicao = Object.keys(contagem).sort((a, b) => contagem[b] - contagem[a]).map(label => ({
      label: (this.classById[label] && this.classById[label].label_pt) || label, n: contagem[label], pct: 100 * contagem[label] / S.sel.length,
      pctTexto: this.fmt(100 * contagem[label] / S.sel.length, 1) + '%', cor: cor[label] || '#6E6E68'
    }));
    const participantes = new Set(S.sel.map(id => this.byId[id] && this.byId[id].meta && this.byId[id].meta.subject).filter(Boolean));
    const splits = new Set(S.sel.map(id => this.byId[id] && this.byId[id].meta && this.byId[id].meta.split).filter(Boolean));
    const features = perfil ? perfil.indices.map(i => ({ nome: this.D.interpretacao.feature_names[i], atual: this.fmt(perfil.atual[i], 2) + 'σ', referencia: this.fmt(perfil.referencia[i], 2) + 'σ' })) : [];
    return {
      mostraInspetor: this.modo() === 'laboratorio', btnInspetor: btnInspetor, inspectorPronto: !!(S.interpretacaoPronta && perfil), inspectorCarregando: !S.interpretacaoPronta && !S.interpretacaoErro,
      inspectorErro: S.interpretacaoErro, inspectorTitulo: S.sel.length === 1 ? 'Amostra ' + amostra.id : 'Seleção de ' + S.sel.length.toLocaleString('pt-BR') + ' amostras',
      inspectorSubtitulo: S.sel.length === 1 ? 'Um ponto é uma janela temporal, não uma pessoa nem uma posição física.' : 'O sinal pertence à amostra em foco; perfil, vizinhança e composição resumem a seleção vinculada.',
      inspectorMeta: [
        { k: 'atividade em foco', v: classe.label_pt || amostra.label }, { k: 'participante', v: String((amostra.meta && amostra.meta.subject) || '—') },
        { k: 'conjunto', v: (amostra.meta && amostra.meta.split) || '—' }, { k: 'linha de origem', v: String((amostra.meta && amostra.meta.source_row) || '—') },
        { k: 'seleção', v: S.sel.length.toLocaleString('pt-BR') + ' janela(s)' }, { k: 'abrangência', v: participantes.size + ' participante(s) · ' + Array.from(splits).join('+') }
      ],
      segSinal: this.seg([{ v: 'acc', label: 'Aceleração X/Y/Z' }, { v: 'gyro', label: 'Giroscópio X/Y/Z' }], S.sinalTipo, tipo => this.setState({ sinalTipo: tipo })),
      inspectorSinalTitulo: amostra.id + ' · ' + (classe.label_pt || amostra.label), refSinal: this.signalRef, refPerfil: this.profileRef,
      ariaSinal: 'Sinais X, Y e Z da amostra ' + amostra.id + ' ao longo de 2,56 segundos.', ariaPerfil: 'Comparação das oito características padronizadas dominantes da seleção.',
      inspectorReferencia: perfil ? perfil.referenciaLabel : 'média da atividade', inspectorFeatures: features, inspectorVizinhos: this.resumoVizinhos(),
      inspectorComposicao: composicao, inspectorComposicaoTitulo: S.sel.length === 1 ? 'Uma janela rotulada' : S.sel.length.toLocaleString('pt-BR') + ' janelas por atividade',
      inspectorComposicaoNota: S.sel.length === 1 ? 'A cor é um rótulo posterior; não entrou no ajuste das projeções.' : 'O laço permite verificar se um agrupamento visual corresponde a uma ou várias atividades.'
    };
  }

'''
    html = replace_once(html, "\n  // ---------- navegação ----------", "\n" + methods + "  // ---------- navegação ----------")
    html = replace_once(
        html,
        "    const m3 = ((D.metricas_3d || {})[this.umap3dKey]) || {};",
        "    const m3 = ((D.metricas_3d || {})[this.umap3dKey]) || {};\n"
        "    const inspetor = this.inspectorViewModel();",
    )
    html = replace_once(
        html,
        "      umap3dSelecao: S.sel.length ? S.sel.length + (S.sel.length === 1 ? ' amostra selecionada' : ' amostras selecionadas') : 'nenhuma seleção',",
        "      umap3dSelecao: S.sel.length ? S.sel.length + (S.sel.length === 1 ? ' amostra selecionada' : ' amostras selecionadas') : 'nenhuma seleção',\n"
        "      ...inspetor,",
    )
    html = replace_once(
        html,
        '    <button type="button" onClick="{{ onTabela }}" aria-expanded="{{ tabelaAberta }}" style="border:1px solid #121212;',
        '    <button type="button" onClick="{{ btnInspetor.on }}" disabled="{{ btnInspetor.disabled }}" aria-expanded="{{ mostraInspetor }}" style="border:1px solid #121212;background:{{ btnInspetor.bg }};color:{{ btnInspetor.fg }};padding:5px 10px;font-size:12.5px;font-weight:600;cursor:pointer;border-radius:2px;opacity:{{ btnInspetor.op }}">{{ btnInspetor.label }}</button>\n'
        '    <button type="button" onClick="{{ onTabela }}" aria-expanded="{{ tabelaAberta }}" style="border:1px solid #121212;',
    )
    return html
