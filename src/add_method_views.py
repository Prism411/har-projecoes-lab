from __future__ import annotations


def replace_once(source: str, old: str, new: str) -> str:
    if old not in source:
        raise ValueError(f"Trecho das vistas não encontrado: {old[:100]!r}")
    return source.replace(old, new, 1)


def replace_scenes(html: str) -> str:
    start = html.find("  CENAS = [")
    if start < 0:
        raise ValueError("Bloco CENAS não encontrado.")
    end = html.find("\n  ];", start)
    if end < 0:
        raise ValueError("Fim do bloco CENAS não encontrado.")
    end += len("\n  ];")
    scenes = r'''  CENAS = [
    { vista: 'ficha', titulo: 'Ficha do dataset', nota: '10.299 janelas, 561 características, seis atividades e 30 participantes. Cada ponto resume 2,56 segundos de sensores; não é uma posição física.', estado: { sel: [], anchor: null, lente: false, corPor: 'label', cvd: 'padrao' } },
    { vista: 'comparar', titulo: 'O mesmo dado, três perguntas diferentes', nota: 'Sem cor de classe: PCA procura variância linear, t-SNE preserva vizinhanças probabilísticas e UMAP preserva um grafo local. O dado é o mesmo; o objetivo matemático muda.', estado: { sel: [], anchor: null, lente: false, corPor: 'none' } },
    { vista: 'comparar', titulo: 'Revelando as atividades', nota: 'As cores entram somente depois do ajuste. Elas ajudam a verificar como os rótulos externos aparecem em cada projeção, mas não provam que os algoritmos descobriram classes.', estado: { sel: [], anchor: null, lente: false, corPor: 'label' } },
    { vista: 'pca', titulo: 'PCA: o melhor plano linear', nota: 'PC1 e PC2 são combinações ortogonais das 561 características que concentram a maior variância possível. A variância acumulada no cabeçalho quantifica quanto esse plano reteve.', estado: { sel: [], anchor: null, lente: false, corPor: 'label' } },
    { vista: 'tsne', titulo: 't-SNE: a escala da vizinhança muda o mapa', nota: 'Perplexidades 10, 30 e 50 foram calculadas com a mesma entrada PCA50 e a mesma seed. Compare quais vizinhanças permanecem e como a organização global pode mudar.', estado: { sel: [], anchor: null, lente: false, corPor: 'label' } },
    { vista: 'umap', titulo: 'UMAP: do grafo local ao embedding', nota: 'Perfis local, equilibrado e amplo mudam n_neighbors e min_dist. Observe a troca entre detalhe local, compactação e organização em escalas maiores.', estado: { sel: [], anchor: null, lente: false, corPor: 'label' } },
    { vista: 'comparar', titulo: 'Uma janela, três posições', nota: 'Selecione um ponto: o mesmo ID reaparece nas três projeções. A posição muda porque cada método preserva relações diferentes.', estado: { lente: false, corPor: 'label' }, ancora: true },
    { vista: 'comparar', titulo: 'Vizinhos originais: o que cada método preservou?', nota: 'As dez conexões vêm do espaço padronizado de 561 dimensões. Anel contínuo indica vizinho preservado; quadrado tracejado indica vizinho afastado pela projeção.', estado: { lente: true, ligacoes: true, corPor: 'label' }, ancora: true },
    { vista: 'comparar', titulo: 'A leitura sobrevive sem a cor original?', nota: 'A simulação de deuteranopia altera a paleta, enquanto símbolos e contornos continuam redundantes. A comparação metodológica não deve depender apenas de cor.', estado: { lente: false, corPor: 'label', cvd: 'deuteranopia' } },
    { vista: 'encerramento', titulo: 'Toda projeção escolhe o que preservar', nota: 'PCA, t-SNE e UMAP não competem por uma verdade única. Eles oferecem leituras complementares e exigem parâmetros, métricas e limites de interpretação explícitos.', estado: { sel: [], anchor: null, lente: false } }
  ];'''
    return html[:start] + scenes + html[end:]


def apply_method_views(html: str) -> str:
    html = replace_scenes(html)
    html = replace_once(
        html,
        '<div role="group" aria-label="Vista" style="display:flex;gap:4px">',
        '<div role="group" aria-label="Vista" style="display:flex;gap:4px;flex-wrap:wrap">',
    )
    html = replace_once(
        html,
        '    <sc-if value="{{ ehFicha }}" hint-placeholder-val="{{ false }}">',
        '    <sc-if value="{{ mostraMetodoNota }}" hint-placeholder-val="{{ false }}">\n'
        '      <div style="flex:0 0 auto;display:flex;align-items:baseline;gap:12px;padding:8px 0 4px;border-bottom:1px solid #D8D8D3">\n'
        '        <span class="inspector-kicker">Demonstração do método</span>\n'
        '        <strong style="font-size:15px">{{ metodoTitulo }}</strong>\n'
        '        <span style="font-size:12.5px;color:#3F3F3B;text-wrap:pretty">{{ metodoNota }}</span>\n'
        '      </div>\n'
        '    </sc-if>\n\n'
        '    <sc-if value="{{ ehFicha }}" hint-placeholder-val="{{ false }}">',
    )
    html = replace_once(
        html,
        "    if (v === 'contraste') return [S.cmpA, S.cmpB].filter(Boolean);\n"
        "    if (v === 'umap') return (this.porTech['umap'] || []).slice(0, 3);",
        "    if (v === 'contraste') return [S.cmpA, S.cmpB].filter(Boolean);\n"
        "    if (v === 'pca') return (this.porTech['pca'] || []).slice(0, 1);\n"
        "    if (v === 'tsne') return (this.porTech['tsne'] || []).slice(0, 3);\n"
        "    if (v === 'umap') return (this.porTech['umap'] || []).slice(0, 3);",
    )
    html = replace_once(
        html,
        "        ref: this.slots[i], selRef: this.selRefs[i], tecnica: this.nomeTech(t), cfgKey: k, params: this.descreve(k) || '—',\n"
        "        metricas: this.metricasDe(k), opcoes: this.opcoesPara(k, i), ext: ext,",
        "        ref: this.slots[i], selRef: this.selRefs[i], tecnica: this.nomeTech(t), cfgKey: k, params: this.descreve(k) || '—',\n"
        "        metricas: this.metricasDe(k), opcoes: this.opcoesPara(k, i), ext: ext, selDisabled: v === 'pca' || v === 'tsne' || v === 'umap',",
    )
    html = replace_once(
        html,
        '<select ref="{{ p.selRef }}" value="{{ p.cfgKey }}" onChange="{{ p.onCfg }}" aria-label="{{ p.selLabel }}" style=',
        '<select ref="{{ p.selRef }}" value="{{ p.cfgKey }}" onChange="{{ p.onCfg }}" disabled="{{ p.selDisabled }}" aria-label="{{ p.selLabel }}" style=',
    )
    html = replace_once(
        html,
        "    const rot = { comparar: 'comparar três projeções', umap: 'parâmetros do UMAP', umap3d: 'UMAP em três dimensões', morph: 'morph entre projeções', contraste: 'bonito vs. fiel', ficha: 'ficha do dataset', encerramento: 'encerramento' };",
        "    const rot = { comparar: 'comparar três projeções', pca: 'PCA em foco', tsne: 'parâmetros do t-SNE', umap: 'parâmetros do UMAP', umap3d: 'UMAP em três dimensões', morph: 'morph entre projeções', contraste: 'bonito vs. fiel', ficha: 'ficha do dataset', encerramento: 'encerramento' };",
    )
    html = replace_once(
        html,
        "      segVista: this.seg([{ v: 'comparar', label: 'Comparar' }, { v: 'umap3d', label: 'UMAP 3D' }, { v: 'morph', label: 'Morph' }, { v: 'contraste', label: 'Bonito vs. fiel' }], S.vistaLab, x => this.setState({ vistaLab: x })),",
        "      segVista: this.seg([{ v: 'comparar', label: 'Comparar' }, { v: 'pca', label: 'PCA' }, { v: 'tsne', label: 't-SNE' }, { v: 'umap', label: 'UMAP' }, { v: 'umap3d', label: 'UMAP 3D' }, { v: 'morph', label: 'Morph' }, { v: 'contraste', label: 'Bonito vs. fiel' }], S.vistaLab, x => this.setState({ vistaLab: x })),",
    )
    html = replace_once(
        html,
        "      maxSujeito: this.maxSujeito,",
        "      maxSujeito: this.maxSujeito,\n"
        "      mostraMetodoNota: modo === 'laboratorio' && (v === 'pca' || v === 'tsne' || v === 'umap'),\n"
        "      metodoTitulo: ({ pca: 'PCA · projeção linear', tsne: 't-SNE · três perplexidades', umap: 'UMAP · três escalas de vizinhança' })[v] || '',\n"
        "      metodoNota: ({ pca: 'Um painel amplo destaca PC1 × PC2 e a variância explicada.', tsne: 'Compare perplexidade 10, 30 e 50 lado a lado.', umap: 'Compare perfis local, equilibrado e amplo lado a lado.' })[v] || '',",
    )
    return html
