/* traz as gravacoes do iphone pra dentro do laboratorio.

   entram como amostras normais, com participante proprio, e so tem
   coordenada na projecao `harlive/comum-128`. o laboratorio ignora amostra
   sem coordenada na projecao em uso, entao as vistas oficiais de 561
   caracteristicas seguem exatamente como estavam.

   quando o laboratorio e servido pelo proprio relay (rota /laboratorio), a
   busca acontece na mesma origem. servido de outro jeito, o passo falha em
   silencio e o laboratorio abre igual. */
(() => {
  "use strict";

  const CAMPOS = {
    pca: "coordenadas_pca",
    umap: "coordenadas",
    tsne: "coordenadas_tsne"
  };
  const PARTICIPANTE = 31;
  const CLASSE = {
    id: "VOCE",
    label_pt: "Sua gravação",
    cor: "#111111",
    cor_cvd: {
      protanopia: "#111111",
      deuteranopia: "#111111",
      tritanopia: "#111111",
      monocromacia: "#111111"
    },
    simbolo: "pin"
  };

  function registrarClasse(dados) {
    const classes = dados.dataset.classes || [];
    if (!classes.some(classe => classe.id === CLASSE.id)) classes.push(CLASSE);
  }

  function inserirGravacoes(dados, gravacoes) {
    if (!gravacoes.length) return 0;
    const chaves = window.HAR_LIVE_CHAVES;
    if (!chaves) return 0;
    registrarClasse(dados);
    let inseridas = 0;
    gravacoes.forEach((gravacao, indiceGravacao) => {
      (gravacao.coordenadas || []).forEach((_, indiceJanela) => {
        const identificador = `voce_${indiceGravacao + 1}_${indiceJanela + 1}`;
        if (dados.amostras.some(amostra => amostra.id === identificador)) return;

        // a mesma janela entra nas tres projecoes do espaco comum. no t-sne a
        // posicao e interpolada entre vizinhos, nao e projecao nova; o
        // rotulo do painel ja deixa isso claro
        const projecoes = {};
        Object.keys(CAMPOS).forEach(tecnica => {
          const lista = gravacao[CAMPOS[tecnica]];
          const ponto = lista && lista[indiceJanela];
          if (ponto) projecoes[chaves[tecnica]] = ponto;
        });
        if (!Object.keys(projecoes).length) return;

        dados.amostras.push({
          id: identificador,
          label: CLASSE.id,
          meta: {
            subject: PARTICIPANTE,
            split: "iphone",
            source_row: indiceJanela + 1,
            atividade_instruida: gravacao.atividade || null,
            situacao: (gravacao.situacoes || [])[indiceJanela] || null
          },
          projecoes: projecoes,
          vizinhos_originais_k10: []
        });
        inseridas += 1;
      });
    });
    return inseridas;
  }

  /* a busca e sincrona de proposito.

     o laboratorio indexa as amostras uma unica vez, ao iniciar: identificador,
     classe, participante, conjunto e chave de projecao. uma gravacao que
     chegasse depois disso entraria na lista mas ficaria fora de todos esses
     indices -- apareceria na contagem e sumiria dos filtros e do desenho.

     como o relay ta na mesma maquina e a resposta e pequena, o bloqueio nem
     se nota e garante que as gravacoes existam antes da indexacao. */
  function buscarGravacoes() {
    /* gravacao e dado pessoal e a rota exige o token de pareamento.
       sem token na url do laboratorio, o dataset do experimento aparece
       normal e as gravacoes simplesmente nao entram. */
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) return [];
    try {
      const requisicao = new XMLHttpRequest();
      requisicao.open("GET", "../api/har-live/gravacoes?token=" + encodeURIComponent(token), false);
      requisicao.send(null);
      if (requisicao.status !== 200) return [];
      return (JSON.parse(requisicao.responseText) || {}).gravacoes || [];
    } catch (erro) {
      return [];  /* laboratorio aberto fora do relay: segue sem as gravacoes */
    }
  }

  const dados = window.HAR_DADOS;
  if (dados && Array.isArray(dados.amostras)) {
    const gravacoes = buscarGravacoes();
    const inseridas = inserirGravacoes(dados, gravacoes);
    if (inseridas) {
      dados.har_live_gravacoes = gravacoes.length;
      dados.dataset.n_amostras_total = dados.amostras.length;
    }
  }
})();
