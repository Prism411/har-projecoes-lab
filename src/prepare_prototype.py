from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZipFile

from add_inspector import apply_inspector
from add_method_views import apply_method_views


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZIP = Path.home() / "Downloads" / "Projeções UMAP e visualização de dados (1).zip"
HTML_MEMBER = "Laboratório de Projeções - HAR.dc.html"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adapta o protótipo GAP ao HAR real.")
    parser.add_argument("--prototype-zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--root", type=Path, default=ROOT)
    return parser.parse_args()


def replace_required(source: str, old: str, new: str) -> str:
    if old not in source:
        raise ValueError(f"Trecho esperado não encontrado: {old[:90]!r}")
    return source.replace(old, new)


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    web = root / "web"
    reference = root / "reference"
    web.mkdir(parents=True, exist_ok=True)
    reference.mkdir(parents=True, exist_ok=True)

    with ZipFile(args.prototype_zip) as archive:
        html = archive.read(HTML_MEMBER).decode("utf-8")
        support = archive.read("support.js")
        mock = archive.read("har-data.js")

    (reference / "prototipo-original.dc.html").write_text(html, encoding="utf-8")
    (reference / "har-data.mock.js").write_bytes(mock)
    (reference / "support.js").write_bytes(support)
    support_text = support.decode("utf-8")
    support_text = replace_required(
        support_text,
        "if (!window.__resources) {\n      fetch(location.href)",
        "if (!window.__resources && location.protocol !== \"file:\") {\n      fetch(location.href)",
    )
    (web / "support.js").write_text(support_text, encoding="utf-8")

    html = replace_required(
        html,
        '<script src="./support.js"></script>',
        '<script src="./vendor/react.production.min.js"></script>\n'
        '<script src="./vendor/react-dom.production.min.js"></script>\n'
        '<script src="./support.js"></script>\n'
        '<script src="./har-data.js"></script>\n'
        '<script src="./vendor/plotly-gl3d.min.js"></script>\n'
        '<script src="./vendor/echarts.min.js"></script>',
    )
    html = replace_required(
        html,
        '<script src="./har-data.js"></script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/echarts@6.0.0/dist/echarts.min.js"></script>',
        '',
    )
    html = replace_required(
        html,
        'height:100vh;overflow:hidden;display:flex;flex-direction:column',
        'height:100dvh;min-height:100dvh;overflow:hidden;display:flex;flex-direction:column',
    )
    html = replace_required(
        html,
        '@media (prefers-reduced-motion: reduce){*{animation-duration:.001ms !important;transition-duration:.001ms !important}}',
        '@media (prefers-reduced-motion: reduce){*{animation-duration:.001ms !important;transition-duration:.001ms !important}}\n'
        'button,select,input{transition:filter 180ms ease,transform 120ms ease,outline-color 180ms ease}\n'
        'button:hover:not(:disabled),select:hover,input:hover{filter:brightness(.96)}\n'
        'button:active:not(:disabled){transform:translateY(1px)}\n'
        'button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #0072B2;outline-offset:2px}\n'
        '.dual-range{position:relative;width:250px;height:28px;flex:0 0 250px}\n'
        '.dual-range-track,.dual-range-fill{position:absolute;left:0;right:0;top:12px;height:4px;border-radius:999px}\n'
        '.dual-range-track{background:#D8D8D3;border:1px solid #B8B8B2}\n'
        '.dual-range-fill{background:#0072B2;border:1px solid #005987}\n'
        '.dual-range input[type=range]{position:absolute;left:0;top:2px;width:100%;height:24px;margin:0;padding:0;appearance:none;-webkit-appearance:none;background:transparent;pointer-events:none;outline:none}\n'
        '.dual-range input[type=range]::-webkit-slider-runnable-track{height:4px;background:transparent}\n'
        '.dual-range input[type=range]::-moz-range-track{height:4px;background:transparent}\n'
        '.dual-range input[type=range]::-webkit-slider-thumb{width:18px;height:18px;margin-top:-7px;border:2px solid #121212;border-radius:50%;background:#FFFFFF;box-shadow:0 0 0 2px #FFFFFF;appearance:none;-webkit-appearance:none;pointer-events:auto;cursor:grab}\n'
        '.dual-range input[type=range]::-moz-range-thumb{width:14px;height:14px;border:2px solid #121212;border-radius:50%;background:#FFFFFF;box-shadow:0 0 0 2px #FFFFFF;pointer-events:auto;cursor:grab}\n'
        '.dual-range input[type=range]:focus-visible::-webkit-slider-thumb{box-shadow:0 0 0 3px #FFFFFF,0 0 0 6px #0072B2}\n'
        '.dual-range input[type=range]:focus-visible::-moz-range-thumb{box-shadow:0 0 0 3px #FFFFFF,0 0 0 6px #0072B2}',
    )
    html = replace_required(
        html,
        'Arquivo carregado agora: {{ nCarregadas }} amostras (mock de interface — os números não representam a geometria real do HAR).',
        'Arquivo carregado agora: {{ nCarregadas }} amostras reais processadas pelo pipeline Python.',
    )
    html = replace_required(
        html,
        "'Os números deste arquivo de mock são placeholders de interface: não extraia deles nenhuma conclusão sobre o HAR.'",
        "'Os resultados foram calculados sobre o HAR oficial; parâmetros, seed e protocolo permanecem visíveis para auditoria.'",
    )
    html = replace_required(
        html,
        "'PCA mostra o quanto preserva (variância explicada) mas achata a estrutura local.'",
        "'PCA quantifica variância explicada no modelo linear, mas duas componentes ainda descartam informação.'",
    )
    html = replace_required(
        html,
        "'Em t-SNE e UMAP, distância entre grupos, tamanho de grupo e área vazia não são interpretáveis.'",
        "'Em t-SNE e UMAP, distância entre grupos, tamanho de grupo e área vazia exigem cautela e não são réguas fiéis do espaço original.'",
    )
    html = replace_required(
        html,
        "' · ' + L.ausentes + ' id(s) da lista sem coordenadas neste arquivo (mock)'",
        "' · ' + L.ausentes + ' id(s) sem coordenadas nesta configuração'",
    )
    html = replace_required(
        html,
        "'PCA → UMAP → t-SNE, subamostra estável de '",
        "'PCA → UMAP → t-SNE, conjunto estável de '",
    )
    html = replace_required(
        html,
        '<svg viewBox="-7 -7 14 14" width="17" height="17" aria-hidden="true" style="flex:0 0 auto"><path d="{{ c.glifo }}" fill="{{ c.cor }}" stroke="#121212" stroke-width="0.9"></path></svg>',
        '<span aria-hidden="true" style="width:17px;text-align:center;flex:0 0 auto;color:{{ c.cor }};font-size:17px;line-height:1;text-shadow:0 0 0 #121212">{{ c.glifoTexto }}</span>',
    )
    html = replace_required(
        html,
        '<svg viewBox="-7 -7 14 14" width="16" height="16" aria-hidden="true"><path d="{{ c.glifo }}" fill="{{ c.cor }}" stroke="{{ c.traco }}" stroke-width="0.9"></path></svg>',
        '<span aria-hidden="true" style="width:16px;text-align:center;color:{{ c.cor }};font-size:16px;line-height:1">{{ c.glifoTexto }}</span>',
    )
    html = replace_required(
        html,
        '<svg viewBox="-7 -7 14 14" width="16" height="16" aria-hidden="true"><path d="{{ c.glifo }}" fill="#6E6E68" stroke="#121212" stroke-width="0.9"></path></svg>',
        '<span aria-hidden="true" style="width:16px;text-align:center;color:#6E6E68;font-size:16px;line-height:1">{{ c.glifoTexto }}</span>',
    )
    html = replace_required(
        html,
        '<svg viewBox="-7 -7 14 14" width="15" height="15" aria-hidden="true"><path d="{{ r.glifo }}" fill="{{ r.cor }}" stroke="#121212" stroke-width="0.9"></path></svg>{{ r.atividade }}',
        '<span aria-hidden="true" style="display:inline-block;width:15px;text-align:center;color:{{ r.cor }};font-size:15px;line-height:1">{{ r.glifoTexto }}</span>{{ r.atividade }}',
    )
    html = replace_required(
        html,
        "const cfg = {}; this.techs.forEach(t => cfg[t] = this.porTech[t][0]);\n"
        "    const tsne = this.cfgKeys.filter(k => k.indexOf('tsne') === 0)[0];\n"
        "    const pca = this.cfgKeys.filter(k => k.indexOf('pca') === 0)[0];",
        "const cfg = {}; this.techs.forEach(t => cfg[t] = this.porTech[t][0]);\n"
        "    const tsnePadrao = this.cfgKeys.find(k => k.indexOf('tsne/perplexidade-30/') === 0);\n"
        "    const umapPadrao = this.cfgKeys.find(k => k.indexOf('umap/equilibrado/') === 0);\n"
        "    if (tsnePadrao) cfg.tsne = tsnePadrao;\n"
        "    if (umapPadrao) cfg.umap = umapPadrao;\n"
        "    const tsne = tsnePadrao || this.cfgKeys.filter(k => k.indexOf('tsne') === 0)[0];\n"
        "    const pca = this.cfgKeys.filter(k => k.indexOf('pca') === 0)[0];",
    )
    html = html.replace(
        "progressive: 0, data: arr,",
        "progressive: 700, progressiveThreshold: 1200, data: arr,",
    )
    html = replace_required(
        html,
        "  extensao(keys) {",
        "  glifoTexto(c) {\n"
        "    const s = (c && c.simbolo) || 'circle';\n"
        "    if (s.indexOf('path://') === 0) return '✚';\n"
        "    return ({ circle: '●', rect: '■', roundRect: '▣', triangle: '▲', diamond: '◆' })[s] || '●';\n"
        "  }\n\n"
        "  extensao(keys) {",
    )
    html = replace_required(
        html,
        "label: c.label_pt, cor: S.corPor === 'none' ? '#6E6E68' : cor[c.id], glifo: this.glifo(c),",
        "label: c.label_pt, cor: S.corPor === 'none' ? '#6E6E68' : cor[c.id], glifoTexto: this.glifoTexto(c),",
    )
    html = replace_required(
        html,
        "id: id, atividade: c.label_pt || s.label || '—', glifo: this.glifo(c),",
        "id: id, atividade: c.label_pt || s.label || '—', glifoTexto: this.glifoTexto(c),",
    )
    html = replace_required(
        html,
        "  </div>\n\n  <sc-if value=\"{{ avancadoAberto }}\" hint-placeholder-val=\"{{ false }}\">",
        "  </div>\n\n"
        "  <sc-if value=\"{{ ehLab }}\" hint-placeholder-val=\"{{ true }}\">\n"
        "    <div aria-label=\"Filtros do dataset\" style=\"flex:0 0 auto;display:flex;flex-wrap:wrap;align-items:center;gap:7px 16px;padding:7px 20px;border-bottom:1px solid #D8D8D3;background:#FFFFFF\">\n"
        "      <span style=\"font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:#5F5F59;font-weight:700\">Filtrar amostras</span>\n"
        "      <div role=\"group\" aria-labelledby=\"faixa-participantes-label\" style=\"display:flex;align-items:center;gap:10px;min-width:390px\">\n"
        "        <span id=\"faixa-participantes-label\" style=\"font-size:12.5px;font-weight:600\">Participantes</span>\n"
        "        <div class=\"dual-range\">\n"
        "          <div class=\"dual-range-track\" aria-hidden=\"true\"></div>\n"
        "          <div class=\"dual-range-fill\" aria-hidden=\"true\" style=\"left:{{ faixaInicioPct }}%;right:{{ faixaFimPct }}%\"></div>\n"
        "          <input id=\"filtro-sujeito-min\" type=\"range\" min=\"1\" max=\"{{ maxSujeito }}\" step=\"1\" value=\"{{ filtroSujeitoMinValor }}\" onChange=\"{{ onFiltroSujeitoMin }}\" aria-label=\"Primeiro participante da faixa\" aria-valuetext=\"{{ filtroSujeitoMinTexto }}\" style=\"z-index:{{ faixaMinZ }}\">\n"
        "          <input id=\"filtro-sujeito-max\" type=\"range\" min=\"1\" max=\"{{ maxSujeito }}\" step=\"1\" value=\"{{ filtroSujeitoMaxValor }}\" onChange=\"{{ onFiltroSujeitoMax }}\" aria-label=\"Último participante da faixa\" aria-valuetext=\"{{ filtroSujeitoMaxTexto }}\" style=\"z-index:{{ faixaMaxZ }}\">\n"
        "        </div>\n"
        "        <output for=\"filtro-sujeito-min filtro-sujeito-max\" style=\"min-width:84px;font-size:12.5px;font-weight:700;font-variant-numeric:tabular-nums\">{{ faixaRotulo }}</output>\n"
        "      </div>\n"
        "      <label for=\"filtro-split\" style=\"display:flex;align-items:center;gap:7px;font-size:12.5px;font-weight:600\">Conjunto\n"
        "        <select id=\"filtro-split\" value=\"{{ filtroSplitValor }}\" onChange=\"{{ onFiltroSplit }}\" style=\"min-width:150px;border:1px solid #121212;background:#FFFFFF;color:#121212;font-size:12.5px;padding:5px 7px;border-radius:2px\">\n"
        "          <sc-for list=\"{{ filtroSplitOpcoes }}\" as=\"o\" hint-placeholder-count=\"3\">\n"
        "            <option value=\"{{ o.v }}\">{{ o.label }}</option>\n"
        "          </sc-for>\n"
        "        </select>\n"
        "      </label>\n"
        "      <span role=\"status\" style=\"font-size:12.5px;color:#3F3F3B;font-variant-numeric:tabular-nums\">{{ filtroResumo }}</span>\n"
        "      <button type=\"button\" onClick=\"{{ onLimparFiltros }}\" disabled=\"{{ filtrosLimpos }}\" style=\"border:1px solid #121212;background:#FFFFFF;color:#121212;padding:5px 10px;font-size:12.5px;font-weight:600;cursor:pointer;border-radius:2px;opacity:{{ opLimparFiltros }}\">Limpar filtros</button>\n"
        "      <span style=\"font-size:12px;color:#5F5F59\">Atividades: clique nos itens da legenda.</span>\n"
        "    </div>\n"
        "  </sc-if>\n\n"
        "  <sc-if value=\"{{ avancadoAberto }}\" hint-placeholder-val=\"{{ false }}\">",
    )
    html = replace_required(
        html,
        "    ponto: null, aten: null, rotulo: true\n  };",
        "    ponto: null, aten: null, rotulo: true, filtroSujeitoMin: null, filtroSujeitoMax: null, filtroSplit: 'todos'\n  };",
    )
    html = replace_required(
        html,
        "    this.maxSujeito = 1;\n"
        "    (D.amostras || []).forEach(s => { const v = s.meta && s.meta.subject; if (typeof v === 'number' && v > this.maxSujeito) this.maxSujeito = v; });",
        "    this.maxSujeito = 1;\n"
        "    (D.amostras || []).forEach(s => { const v = s.meta && s.meta.subject; if (typeof v === 'number' && v > this.maxSujeito) this.maxSujeito = v; });\n"
        "    this.sujeitos = Array.from(new Set((D.amostras || []).map(s => Number(s.meta && s.meta.subject)).filter(Boolean))).sort((a, b) => a - b);\n"
        "    this.splits = Array.from(new Set((D.amostras || []).map(s => s.meta && s.meta.split).filter(Boolean))).sort();",
    )
    html = replace_required(
        html,
        "  nomeTech(t) { return ({ pca: 'PCA', tsne: 't-SNE', umap: 'UMAP' })[t] || String(t).toUpperCase(); }",
        "  filtroSujeitoMinAtual() { const v = Number(this.state.filtroSujeitoMin); return v >= 1 ? v : 1; }\n"
        "  filtroSujeitoMaxAtual() { const v = Number(this.state.filtroSujeitoMax); return v >= 1 ? v : this.maxSujeito; }\n"
        "  filtroSplitAtual() { return this.state.filtroSplit || 'todos'; }\n"
        "  faixaCompleta() { return this.filtroSujeitoMinAtual() === 1 && this.filtroSujeitoMaxAtual() === this.maxSujeito; }\n\n"
        "  passaFiltrosBasicos(s, sujeitoMin, sujeitoMax, split) {\n"
        "    if (!s) return false;\n"
        "    const inicio = sujeitoMin == null ? this.filtroSujeitoMinAtual() : Number(sujeitoMin);\n"
        "    const fim = sujeitoMax == null ? this.filtroSujeitoMaxAtual() : Number(sujeitoMax);\n"
        "    const splitAtivo = split == null ? this.filtroSplitAtual() : split;\n"
        "    const sujeito = Number(s.meta && s.meta.subject);\n"
        "    if (sujeito < inicio || sujeito > fim) return false;\n"
        "    if (splitAtivo !== 'todos' && (!s.meta || s.meta.split !== splitAtivo)) return false;\n"
        "    return true;\n"
        "  }\n\n"
        "  passaFiltros(s, sujeitoMin, sujeitoMax, split, ocultas) {\n"
        "    if (!this.passaFiltrosBasicos(s, sujeitoMin, sujeitoMax, split)) return false;\n"
        "    const classesOcultas = ocultas == null ? this.state.ocultas : ocultas;\n"
        "    return classesOcultas.indexOf(s.label) < 0;\n"
        "  }\n\n"
        "  filtroKey() { return this.filtroSujeitoMinAtual() + '-' + this.filtroSujeitoMaxAtual() + '|' + this.filtroSplitAtual() + '|' + this.state.ocultas.slice().sort().join(','); }\n"
        "  totalVisivel() { return (this.D.amostras || []).reduce((n, s) => n + (this.passaFiltros(s) ? 1 : 0), 0); }\n"
        "  contagemClasse(id) { return (this.byClass[id] || []).reduce((n, ix) => n + (this.passaFiltrosBasicos(this.D.amostras[ix]) ? 1 : 0), 0); }\n\n"
        "  aplicarFiltros = (sujeitoMin, sujeitoMax, split) => {\n"
        "    const inicio = Math.max(1, Math.min(this.maxSujeito, Number(sujeitoMin) || 1));\n"
        "    const fim = Math.max(inicio, Math.min(this.maxSujeito, Number(sujeitoMax) || this.maxSujeito));\n"
        "    const splitAtivo = split || 'todos', ocultas = this.state.ocultas;\n"
        "    const visivel = id => this.passaFiltros(this.byId[id], inicio, fim, splitAtivo, ocultas);\n"
        "    const sel = this.state.sel.filter(visivel);\n"
        "    const anchor = this.state.anchor && visivel(this.state.anchor) ? this.state.anchor : (sel[0] || null);\n"
        "    this.desarmarBrush();\n"
        "    this.setState({ filtroSujeitoMin: inicio, filtroSujeitoMax: fim, filtroSplit: splitAtivo, sel: sel, anchor: anchor }, this.reenquadrar);\n"
        "  };\n\n"
        "  alterarFaixa = (ponta, valor) => {\n"
        "    let inicio = this.filtroSujeitoMinAtual(), fim = this.filtroSujeitoMaxAtual();\n"
        "    if (ponta === 'min') inicio = Math.min(Math.max(1, Number(valor) || 1), fim);\n"
        "    else fim = Math.max(Math.min(this.maxSujeito, Number(valor) || this.maxSujeito), inicio);\n"
        "    this.aplicarFiltros(inicio, fim, this.filtroSplitAtual());\n"
        "  };\n\n"
        "  limparFiltros = () => {\n"
        "    this.desarmarBrush();\n"
        "    this.setState({ filtroSujeitoMin: null, filtroSujeitoMax: null, filtroSplit: 'todos', ocultas: [], sel: [], anchor: null }, this.reenquadrar);\n"
        "  };\n\n"
        "  alternarClasse(id, visivelAgora) {\n"
        "    const ocultas = visivelAgora ? this.state.ocultas.concat([id]) : this.state.ocultas.filter(x => x !== id);\n"
        "    const passa = amostraId => this.passaFiltros(this.byId[amostraId], this.filtroSujeitoMinAtual(), this.filtroSujeitoMaxAtual(), this.filtroSplitAtual(), ocultas);\n"
        "    const sel = this.state.sel.filter(passa);\n"
        "    const anchor = this.state.anchor && passa(this.state.anchor) ? this.state.anchor : (sel[0] || null);\n"
        "    this.setState({ ocultas: ocultas, sel: sel, anchor: anchor });\n"
        "  }\n\n"
        "  nomeTech(t) { return ({ pca: 'PCA', tsne: 't-SNE', umap: 'UMAP' })[t] || String(t).toUpperCase(); }",
    )
    html = replace_required(
        html,
        "    const id = keys.join('|');",
        "    const id = keys.join('|') + '@' + this.filtroKey();",
    )
    html = replace_required(
        html,
        "    (this.D.amostras || []).forEach(s => keys.forEach(k => {\n"
        "      const p = s.projecoes[k]; if (!p) return;",
        "    (this.D.amostras || []).forEach(s => {\n"
        "      if (!this.passaFiltros(s)) return;\n"
        "      keys.forEach(k => {\n"
        "      const p = s.projecoes[k]; if (!p) return;",
    )
    html = replace_required(
        html,
        "    }));\n    if (!isFinite(x0))",
        "      });\n    });\n    if (!isFinite(x0))",
    )
    html = replace_required(
        html,
        "    const cid = anchorId + '@' + k;",
        "    const cid = anchorId + '@' + k + '@' + this.filtroKey();",
    )
    html = replace_required(
        html,
        "    const a = this.byId[anchorId]; if (!a) return null;",
        "    const a = this.byId[anchorId]; if (!a || !this.passaFiltros(a)) return null;",
    )
    html = replace_required(
        html,
        "    const presentes = lista.filter(id => this.byId[id] && this.byId[id].projecoes[k]);",
        "    const presentes = lista.filter(id => this.byId[id] && this.passaFiltros(this.byId[id]) && this.byId[id].projecoes[k]);",
    )
    html = replace_required(
        html,
        "      if (s.id === anchorId) return; const p = s.projecoes[k]; if (!p) return;",
        "      if (s.id === anchorId || !this.passaFiltros(s)) return; const p = s.projecoes[k]; if (!p) return;",
    )
    html = replace_required(
        html,
        "lenteNota = '· ' + L.perdidos.length + ' distante(s)' + (L.ausentes ? ' · ' + L.ausentes + ' id(s) sem coordenadas nesta configuração' : '');",
        "lenteNota = '· ' + L.perdidos.length + ' distante(s)' + (L.ausentes ? ' · ' + L.ausentes + ' vizinho(s) fora do filtro ou sem coordenadas' : '');",
    )
    html = replace_required(
        html,
        "'. ' + (this.D.amostras || []).length + ' amostras carregadas, ' + nCls + ' atividades, '",
        "'. ' + this.totalVisivel() + ' amostras visíveis, ' + nCls + ' atividades, '",
    )
    html = replace_required(
        html,
        "        const s = D.amostras[ix], pr = s.projecoes[k]; if (!pr) return;",
        "        const s = D.amostras[ix]; if (!this.passaFiltros(s)) return; const pr = s.projecoes[k]; if (!pr) return;",
    )
    html = replace_required(
        html,
        "      const s = this.byId[id]; if (!s) return; const pr = s.projecoes[k]; if (!pr) return;",
        "      const s = this.byId[id]; if (!s || !this.passaFiltros(s)) return; const pr = s.projecoes[k]; if (!pr) return;",
    )
    html = replace_required(
        html,
        "    if (S.anchor && this.byId[S.anchor] && this.byId[S.anchor].projecoes[k]) {",
        "    if (S.anchor && this.byId[S.anchor] && this.passaFiltros(this.byId[S.anchor]) && this.byId[S.anchor].projecoes[k]) {",
    )
    html = replace_required(
        html,
        "    if (S.cvd !== 'padrao') partes.push('Simulação de visão de cores: ' + S.cvd + ' (paleta vem pronta do dado).');",
        "    const filtrosAtivos = [];\n"
        "    if (!this.faixaCompleta()) filtrosAtivos.push('participantes ' + this.filtroSujeitoMinAtual() + '–' + this.filtroSujeitoMaxAtual());\n"
        "    if (this.filtroSplitAtual() !== 'todos') filtrosAtivos.push(this.filtroSplitAtual() === 'train' ? 'treino' : 'teste');\n"
        "    if (S.ocultas.length) filtrosAtivos.push((this.D.dataset.classes || []).length - S.ocultas.length + ' atividade(s) ativa(s)');\n"
        "    partes.push(this.totalVisivel().toLocaleString('pt-BR') + ' de ' + (this.D.amostras || []).length.toLocaleString('pt-BR') + ' amostras visíveis' + (filtrosAtivos.length ? ' — ' + filtrosAtivos.join(', ') : '') + '.');\n"
        "    if (S.cvd !== 'padrao') partes.push('Simulação de visão de cores: ' + S.cvd + ' (paleta vem pronta do dado).');",
    )
    html = replace_required(
        html,
        "const rot = { comparar: 'comparar três projeções', umap: 'parâmetros do UMAP', morph: 'morph entre projeções', contraste: 'bonito vs. fiel', ficha: 'ficha do dataset', encerramento: 'encerramento' };",
        "const rot = { comparar: 'comparar três projeções', umap: 'parâmetros do UMAP', umap3d: 'UMAP em três dimensões', morph: 'morph entre projeções', contraste: 'bonito vs. fiel', ficha: 'ficha do dataset', encerramento: 'encerramento' };",
    )
    html = replace_required(
        html,
        "    if (!S.sel.length) partes.push('Nenhuma amostra selecionada — clique em um ponto ou use o laço.');",
        "    if (!S.sel.length) partes.push(this.vista() === 'umap3d' ? 'Nenhuma amostra selecionada — clique em um ponto no espaço 3D.' : 'Nenhuma amostra selecionada — clique em um ponto ou use o laço.');",
    )
    html = replace_required(
        html,
        "      paineis: ps, legenda: legenda, lenteOn: this.lenteOn() && !!S.anchor,",
        "      paineis: ps, legenda: legenda, lenteOn: v !== 'umap3d' && this.lenteOn() && !!S.anchor,",
    )
    html = replace_required(
        html,
        "      dica: (modo === 'apresentacao' ? '← → cenas · clique seleciona · ' : 'clique seleciona (shift soma) · ') + 'arraste move · roda dá zoom · laço/retângulo no canto do painel (Esc solta a ferramenta e limpa)'",
        "      dica: v === 'umap3d' ? 'arraste rotaciona · roda aproxima · clique seleciona (shift soma) · duplo clique restaura a câmera' : (modo === 'apresentacao' ? '← → cenas · clique seleciona · ' : 'clique seleciona (shift soma) · ') + 'arraste move · roda dá zoom · laço/retângulo no canto do painel (Esc solta a ferramenta e limpa)'",
    )
    html = replace_required(
        html,
        "        n: (this.byClass[c.id] || []).length, visivel: vis, traco: vis ? '#121212' : '#8A8A84',",
        "        n: this.contagemClasse(c.id), visivel: vis, traco: vis ? '#121212' : '#8A8A84',",
    )
    html = replace_required(
        html,
        "        on: () => this.setState({ ocultas: vis ? S.ocultas.concat([c.id]) : S.ocultas.filter(x => x !== c.id) })",
        "        on: () => this.alternarClasse(c.id, vis)",
    )
    html = replace_required(
        html,
        "      cvdOpcoes: this.CVD, cvdValor: S.cvd, onCvd: e => this.setState({ cvd: e.target.value }),",
        "      cvdOpcoes: this.CVD, cvdValor: S.cvd, onCvd: e => this.setState({ cvd: e.target.value }),\n"
        "      filtroSujeitoMinValor: this.filtroSujeitoMinAtual(), filtroSujeitoMaxValor: this.filtroSujeitoMaxAtual(),\n"
        "      filtroSujeitoMinTexto: 'Participante ' + this.filtroSujeitoMinAtual(), filtroSujeitoMaxTexto: 'Participante ' + this.filtroSujeitoMaxAtual(),\n"
        "      onFiltroSujeitoMin: e => this.alterarFaixa('min', e.target.value), onFiltroSujeitoMax: e => this.alterarFaixa('max', e.target.value),\n"
        "      faixaInicioPct: ((this.filtroSujeitoMinAtual() - 1) / Math.max(1, this.maxSujeito - 1)) * 100,\n"
        "      faixaFimPct: 100 - ((this.filtroSujeitoMaxAtual() - 1) / Math.max(1, this.maxSujeito - 1)) * 100,\n"
        "      faixaMinZ: this.filtroSujeitoMinAtual() >= this.maxSujeito - 1 ? 4 : 3, faixaMaxZ: 4,\n"
        "      faixaRotulo: this.faixaCompleta() ? 'Todos (1–' + this.maxSujeito + ')' : (this.filtroSujeitoMinAtual() === this.filtroSujeitoMaxAtual() ? 'Somente ' + this.filtroSujeitoMinAtual() : this.filtroSujeitoMinAtual() + '–' + this.filtroSujeitoMaxAtual()),\n"
        "      filtroSplitValor: this.filtroSplitAtual(),\n"
        "      filtroSplitOpcoes: [{ v: 'todos', label: 'Treino e teste' }].concat(this.splits.map(v => ({ v: v, label: v === 'train' ? 'Treino' : (v === 'test' ? 'Teste' : v) }))),\n"
        "      onFiltroSplit: e => this.aplicarFiltros(this.filtroSujeitoMinAtual(), this.filtroSujeitoMaxAtual(), e.target.value),\n"
        "      filtroResumo: this.totalVisivel().toLocaleString('pt-BR') + ' de ' + (D.amostras || []).length.toLocaleString('pt-BR') + ' amostras visíveis',\n"
        "      filtrosLimpos: this.faixaCompleta() && this.filtroSplitAtual() === 'todos' && !S.ocultas.length,\n"
        "      opLimparFiltros: this.faixaCompleta() && this.filtroSplitAtual() === 'todos' && !S.ocultas.length ? 0.45 : 1,\n"
        "      onLimparFiltros: this.limparFiltros,",
    )
    html = replace_required(
        html,
        "'PCA → UMAP → t-SNE, conjunto estável de ' + (D.amostras || []).length + ' pontos.'",
        "'PCA → UMAP → t-SNE, conjunto estável de ' + this.totalVisivel() + ' pontos visíveis.'",
    )
    html = replace_required(
        html,
        "    const D = this.D, ps = this.paineis(), v = this.vista(), modo = this.modo();\n    const cor = this.paleta();",
        "    const D = this.D, ps = this.paineis(), v = this.vista(), modo = this.modo();\n"
        "    const cor = this.paleta();\n"
        "    const m3 = ((D.metricas_3d || {})[this.umap3dKey]) || {};",
    )
    html = replace_required(
        html,
        "      ehFicha: v === 'ficha', ehEncerramento: v === 'encerramento',\n"
        "      ehMorph: v === 'morph' && modo === 'laboratorio',\n"
        "      temPaineis: ps.length > 0, mostraLegenda: ps.length > 0,",
        "      ehFicha: v === 'ficha', ehEncerramento: v === 'encerramento',\n"
        "      ehMorph: v === 'morph' && modo === 'laboratorio', ehUmap3d: v === 'umap3d',\n"
        "      temPaineis: ps.length > 0, mostraLegenda: ps.length > 0 || v === 'umap3d',",
    )
    html = replace_required(
        html,
        "      segVista: this.seg([{ v: 'comparar', label: 'Comparar' }, { v: 'morph', label: 'Morph' }, { v: 'contraste', label: 'Bonito vs. fiel' }], S.vistaLab, x => this.setState({ vistaLab: x })),",
        "      segVista: this.seg([{ v: 'comparar', label: 'Comparar' }, { v: 'umap3d', label: 'UMAP 3D' }, { v: 'morph', label: 'Morph' }, { v: 'contraste', label: 'Bonito vs. fiel' }], S.vistaLab, x => this.setState({ vistaLab: x })),",
    )
    html = replace_required(
        html,
        "      btnLente: this.botao('Lente de vizinhança', () => this.setState({ lente: !this.lenteOn() }), this.lenteOn()),",
        "      ref3d: this.plot3dRef, onResetCamera3d: this.resetCamera3d,\n"
        "      umap3dParams: 'n_components 3 · n_neighbors 30 · min_dist 0,10 · entrada 561D padronizada · seed 42',\n"
        "      umap3dMetricas: [\n"
        "        { k: 'pontos', v: this.totalVisivel().toLocaleString('pt-BR') },\n"
        "        { k: 'trust k10', v: this.fmt(m3.trustworthiness_k10, 3) },\n"
        "        { k: 'cont k10', v: this.fmt(m3.continuity_k10, 3) },\n"
        "        { k: 'tempo', v: this.fmtTempo(m3.tempo_ms) }\n"
        "      ],\n"
        "      aria3d: 'UMAP tridimensional pré-calculado com ' + this.totalVisivel() + ' amostras visíveis e ' + S.sel.length + ' selecionada(s). Eixos sem escala semântica; use a tabela para leitura textual.',\n"
        "      umap3dSelecao: S.sel.length ? S.sel.length + (S.sel.length === 1 ? ' amostra selecionada' : ' amostras selecionadas') : 'nenhuma seleção',\n\n"
        "      btnLente: this.botao('Lente de vizinhança', () => this.setState({ lente: !this.lenteOn() }), this.lenteOn()),",
    )
    html = replace_required(
        html,
        '<button type="button" onClick="{{ btnLente.on }}" aria-pressed="{{ btnLente.pressed }}" style="border:1px solid #121212;',
        '<button type="button" onClick="{{ btnLente.on }}" aria-pressed="{{ btnLente.pressed }}" style="display:{{ displayControles2d }};border:1px solid #121212;',
    )
    html = replace_required(
        html,
        '<button type="button" onClick="{{ btnLigacoes.on }}" aria-pressed="{{ btnLigacoes.pressed }}" style="border:1px solid #121212;',
        '<button type="button" onClick="{{ btnLigacoes.on }}" aria-pressed="{{ btnLigacoes.pressed }}" style="display:{{ displayControles2d }};border:1px solid #121212;',
    )
    html = replace_required(
        html,
        "      ref3d: this.plot3dRef, onResetCamera3d: this.resetCamera3d,",
        "      ref3d: this.plot3dRef, onResetCamera3d: this.resetCamera3d, displayControles2d: v === 'umap3d' ? 'none' : 'inline-block',",
    )
    html = replace_required(
        html,
        "  reenquadrar = () => this.charts.forEach(c => {\n"
        "    if (!c || c.isDisposed()) return;\n"
        "    c.dispatchAction({ type: 'dataZoom', dataZoomId: 'dzx', start: 0, end: 100 });\n"
        "    c.dispatchAction({ type: 'dataZoom', dataZoomId: 'dzy', start: 0, end: 100 });\n"
        "  });",
        "  reenquadrar = () => {\n"
        "    if (this.vista() === 'umap3d') return this.resetCamera3d();\n"
        "    this.charts.forEach(c => {\n"
        "      if (!c || c.isDisposed()) return;\n"
        "      c.dispatchAction({ type: 'dataZoom', dataZoomId: 'dzx', start: 0, end: 100 });\n"
        "      c.dispatchAction({ type: 'dataZoom', dataZoomId: 'dzy', start: 0, end: 100 });\n"
        "    });\n"
        "  };",
    )
    html = replace_required(
        html,
        "  slots = [React.createRef(), React.createRef(), React.createRef()];\n"
        "  selRefs = [React.createRef(), React.createRef(), React.createRef()];",
        "  slots = [React.createRef(), React.createRef(), React.createRef()];\n"
        "  selRefs = [React.createRef(), React.createRef(), React.createRef()];\n"
        "  plot3dRef = React.createRef();\n"
        "  plot3dEl = null;\n"
        "  sig3d = null;",
    )
    html = replace_required(
        html,
        "    this.ros.forEach((r, i) => { if (r) r.disconnect(); this.ros[i] = null; });\n  }",
        "    this.ros.forEach((r, i) => { if (r) r.disconnect(); this.ros[i] = null; });\n"
        "    this.purgar3d();\n"
        "  }",
    )
    html = replace_required(
        html,
        "  iniciar(D) {\n    this.D = D;",
        "  iniciar(D) {\n"
        "    this.D = D;\n"
        "    this.umap3dKey = (D.protocolo && D.protocolo.umap_3d && D.protocolo.umap_3d.chave) || 'umap3d/equilibrado/seed-42';",
    )
    html = replace_required(
        html,
        "      this.charts[i].setOption(this.opcao(ps[i], i, el.clientHeight || 0), { replaceMerge: ['series', 'visualMap'] });\n"
        "    });\n"
        "  }\n\n"
        "  onResize = () => this.charts.forEach(c => c && c.resize());",
        "      this.charts[i].setOption(this.opcao(ps[i], i, el.clientHeight || 0), { replaceMerge: ['series', 'visualMap'] });\n"
        "    });\n"
        "    this.sync3d();\n"
        "  }\n\n"
        "  simbolo3d(c) {\n"
        "    const classes = this.D.dataset.classes || [];\n"
        "    const i = Math.max(0, classes.findIndex(item => item.id === c.id));\n"
        "    return ['circle', 'square', 'diamond', 'cross', 'x', 'circle-open'][i % 6];\n"
        "  }\n\n"
        "  dados3d() {\n"
        "    const S = this.state, cor = this.paleta(), base = Math.max(2.4, this.ponto() * 0.46);\n"
        "    const temSel = S.sel.length > 0, opacidade = temSel ? Math.max(0.08, this.aten()) : 0.84;\n"
        "    const traces = (this.D.dataset.classes || []).map(c => {\n"
        "      const x = [], y = [], z = [], subjects = [], custom = [];\n"
        "      (this.byClass[c.id] || []).forEach(ix => {\n"
        "        const s = this.D.amostras[ix]; if (!this.passaFiltros(s)) return;\n"
        "        const p = s.projecoes_3d && s.projecoes_3d[this.umap3dKey]; if (!p) return;\n"
        "        x.push(p[0]); y.push(p[1]); z.push(p[2]); subjects.push((s.meta && s.meta.subject) || 0);\n"
        "        custom.push([s.id, c.label_pt || s.label, (s.meta && s.meta.subject) || '—', (s.meta && s.meta.split) || '—']);\n"
        "      });\n"
        "      const marker = { size: base, opacity: opacidade, symbol: this.simbolo3d(c), color: S.corPor === 'none' ? '#6E6E68' : cor[c.id] };\n"
        "      if (S.corPor === 'subject') Object.assign(marker, { color: subjects, cmin: 1, cmax: this.maxSujeito, colorscale: [[0,'#2C3E7B'],[.25,'#3E8FA8'],[.5,'#7FB069'],[.75,'#D79A3C'],[1,'#A33A2A']], showscale: false });\n"
        "      return { type: 'scatter3d', mode: 'markers', meta: 'classe', name: c.label_pt, x: x, y: y, z: z, customdata: custom, marker: marker, showlegend: false, hovertemplate: '<b>%{customdata[0]}</b><br>%{customdata[1]}<br>participante %{customdata[2]} · %{customdata[3]}<extra></extra>' };\n"
        "    });\n"
        "    const sx = [], sy = [], sz = [], st = [], sc = [];\n"
        "    S.sel.forEach(id => {\n"
        "      const s = this.byId[id]; if (!s || !this.passaFiltros(s)) return;\n"
        "      const p = s.projecoes_3d && s.projecoes_3d[this.umap3dKey]; if (!p) return;\n"
        "      const c = this.classById[s.label] || {};\n"
        "      sx.push(p[0]); sy.push(p[1]); sz.push(p[2]); st.push(id === S.anchor && S.rotulo ? id : '');\n"
        "      sc.push([s.id, c.label_pt || s.label, (s.meta && s.meta.subject) || '—', (s.meta && s.meta.split) || '—']);\n"
        "    });\n"
        "    traces.push({ type: 'scatter3d', mode: S.rotulo ? 'markers+text' : 'markers', meta: 'selecao', x: sx, y: sy, z: sz, text: st, textposition: 'top center', customdata: sc, showlegend: false, hovertemplate: '<b>%{customdata[0]}</b><br>%{customdata[1]}<br>participante %{customdata[2]} · %{customdata[3]}<extra></extra>', marker: { size: base * 2.15, color: '#FFFFFF', symbol: 'circle-open', opacity: 1, line: { color: '#121212', width: 4 } }, textfont: { color: '#121212', size: 12, family: 'ui-monospace,monospace' } });\n"
        "    return traces;\n"
        "  }\n\n"
        "  sync3d() {\n"
        "    if (this.vista() !== 'umap3d') return this.purgar3d();\n"
        "    const el = this.plot3dRef.current; if (!el || !window.Plotly) return;\n"
        "    if (this.plot3dEl && this.plot3dEl !== el) this.purgar3d();\n"
        "    this.plot3dEl = el; window.__plot3d = el;\n"
        "    const sig = [this.filtroKey(), this.state.corPor, this.state.cvd, this.ponto(), this.aten(), this.state.anchor || '', this.state.sel.join(',')].join('|');\n"
        "    if (sig === this.sig3d) { if (window.Plotly.Plots) window.Plotly.Plots.resize(el); return; }\n"
        "    this.sig3d = sig;\n"
        "    const total = this.totalVisivel();\n"
        "    const axis = titulo => ({ title: { text: titulo, font: { size: 11, color: '#5F5F59' } }, showbackground: true, backgroundcolor: '#FAFAF8', gridcolor: '#D8D8D3', zerolinecolor: '#B8B8B2', showticklabels: false, showspikes: false });\n"
        "    const layout = {\n"
        "      margin: { l: 0, r: 0, t: 8, b: 0 }, paper_bgcolor: '#FFFFFF', plot_bgcolor: '#FFFFFF', showlegend: false, uirevision: 'har-umap3d-camera-v1',\n"
        "      scene: { xaxis: axis('UMAP-1'), yaxis: axis('UMAP-2'), zaxis: axis('UMAP-3'), aspectmode: 'data', dragmode: 'orbit', camera: { eye: { x: 1.45, y: 1.45, z: 1.15 } } },\n"
        "      hoverlabel: { bgcolor: '#FFFFFF', bordercolor: '#121212', font: { color: '#121212', size: 12, family: 'Helvetica Neue,Helvetica,sans-serif' } },\n"
        "      annotations: total ? [] : [{ text: 'Nenhuma amostra corresponde aos filtros', x: .5, y: .5, xref: 'paper', yref: 'paper', showarrow: false, font: { size: 16, color: '#5F5F59' } }]\n"
        "    };\n"
        "    const config = { responsive: true, scrollZoom: true, displaylogo: false, doubleClick: 'reset', toImageButtonOptions: { format: 'png', filename: 'umap-3d-har', scale: 2 } };\n"
        "    window.Plotly.react(el, this.dados3d(), layout, config).then(() => {\n"
        "      if (el.__harLinked || !el.on) return;\n"
        "      el.on('plotly_click', ev => {\n"
        "        const point = ev && ev.points && ev.points[0], cd = point && point.customdata;\n"
        "        const id = Array.isArray(cd) ? cd[0] : cd; if (!id) return;\n"
        "        const original = ev && ev.event;\n"
        "        this.selecionar(id, !!(original && (original.shiftKey || original.metaKey || original.ctrlKey)));\n"
        "      });\n"
        "      el.__harLinked = true;\n"
        "    });\n"
        "  }\n\n"
        "  purgar3d() {\n"
        "    if (this.plot3dEl && window.Plotly) window.Plotly.purge(this.plot3dEl);\n"
        "    if (window.__plot3d === this.plot3dEl) window.__plot3d = null;\n"
        "    this.plot3dEl = null; this.sig3d = null;\n"
        "  }\n\n"
        "  resetCamera3d = () => {\n"
        "    if (!this.plot3dEl || !window.Plotly) return;\n"
        "    window.Plotly.relayout(this.plot3dEl, { 'scene.camera': { eye: { x: 1.45, y: 1.45, z: 1.15 }, center: { x: 0, y: 0, z: 0 }, up: { x: 0, y: 0, z: 1 } } });\n"
        "  };\n\n"
        "  onResize = () => {\n"
        "    this.charts.forEach(c => c && c.resize());\n"
        "    if (this.plot3dEl && window.Plotly && window.Plotly.Plots) window.Plotly.Plots.resize(this.plot3dEl);\n"
        "  };",
    )
    html = replace_required(
        html,
        "    <sc-if value=\"{{ temPaineis }}\" hint-placeholder-val=\"{{ true }}\">",
        "    <sc-if value=\"{{ ehUmap3d }}\" hint-placeholder-val=\"{{ false }}\">\n"
        "      <section data-testid=\"umap-3d\" style=\"flex:1 1 auto;min-height:420px;display:flex;flex-direction:column;border:1px solid #D8D8D3;background:#FFFFFF;margin:6px 0 8px\">\n"
        "        <header style=\"flex:0 0 auto;padding:9px 12px;border-bottom:1px solid #E4E4E0;background:#FAFAF8;display:flex;align-items:flex-start;justify-content:space-between;gap:18px\">\n"
        "          <div style=\"min-width:0;display:flex;flex-direction:column;gap:4px\">\n"
        "            <div style=\"display:flex;align-items:center;gap:8px;flex-wrap:wrap\">\n"
        "              <h2 style=\"margin:0;font-size:18px;font-weight:700;letter-spacing:-.015em\">UMAP 3D</h2>\n"
        "              <span style=\"font-size:9.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;border:1px solid #121212;padding:2px 5px;border-radius:2px\">pré-calculado</span>\n"
        "              <span style=\"font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#0072B2\">WebGL</span>\n"
        "            </div>\n"
        "            <div style=\"font-size:11.5px;color:#3F3F3B;font-variant-numeric:tabular-nums\">{{ umap3dParams }}</div>\n"
        "            <div style=\"display:flex;gap:13px;flex-wrap:wrap;font-size:12px;font-variant-numeric:tabular-nums\">\n"
        "              <sc-for list=\"{{ umap3dMetricas }}\" as=\"m\" hint-placeholder-count=\"4\">\n"
        "                <span><span style=\"color:#5F5F59\">{{ m.k }}</span> <b>{{ m.v }}</b></span>\n"
        "              </sc-for>\n"
        "            </div>\n"
        "          </div>\n"
        "          <button type=\"button\" onClick=\"{{ onResetCamera3d }}\" style=\"flex:0 0 auto;border:1px solid #121212;background:#FFFFFF;color:#121212;padding:5px 10px;font-size:12.5px;font-weight:600;cursor:pointer;border-radius:2px\">Restaurar câmera</button>\n"
        "        </header>\n"
        "        <div ref=\"{{ ref3d }}\" role=\"img\" aria-label=\"{{ aria3d }}\" style=\"flex:1 1 auto;min-height:330px;width:100%;position:relative\"></div>\n"
        "        <footer style=\"flex:0 0 auto;display:flex;justify-content:space-between;gap:18px;padding:7px 12px;border-top:1px solid #E4E4E0;background:#FAFAF8;font-size:12px;color:#3F3F3B\">\n"
        "          <span>arraste para rotacionar · roda para aproximar · clique seleciona · shift soma · duplo clique restaura</span>\n"
        "          <span style=\"font-variant-numeric:tabular-nums;font-weight:600;white-space:nowrap\">{{ umap3dSelecao }}</span>\n"
        "        </footer>\n"
        "      </section>\n"
        "    </sc-if>\n\n"
        "    <sc-if value=\"{{ temPaineis }}\" hint-placeholder-val=\"{{ true }}\">",
    )

    html = apply_inspector(html)
    html = apply_method_views(html)
    (web / "index.html").write_text(html, encoding="utf-8")
    print(f"Protótipo adaptado salvo em {web / 'index.html'}")


if __name__ == "__main__":
    main()
