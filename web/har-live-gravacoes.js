/* Traz as gravações do iPhone para dentro do laboratório.

   Elas entram como amostras normais, com um participante próprio, e só possuem
   coordenadas na projeção `harlive/comum-128`. O laboratório ignora amostras
   sem coordenada na projeção em uso, então as vistas oficiais de 561
   características seguem exatamente como estavam.

   Quando o laboratório é servido pelo próprio relay (rota /laboratorio), a
   busca acontece na mesma origem. Servido de outra forma, o passo falha em
   silêncio e o laboratório abre igual. */
(() => {
  "use strict";

  window.HAR_LIVE_PRESENTES = window.HAR_LIVE_PRESENTES || [];

  const CAMPOS = {
    pca: "coordenadas_pca",
    umap: "coordenadas",
    tsne: "coordenadas_tsne"
  };
  const PRIMEIRO_PARTICIPANTE = 31;
  const CLASSE_SEM_ATIVIDADE = {
    id: "VOCE",
    label_pt: "Gravação ao vivo",
    cor: "#111111",
    cor_cvd: {
      protanopia: "#111111",
      deuteranopia: "#111111",
      tritanopia: "#111111",
      monocromacia: "#111111"
    },
    simbolo: "pin"
  };

  /* Sentado é sentado.

     A gravação entra na MESMA classe da atividade que foi feita: quem grava
     sentado vira "Sentado" e conta junto na legenda. Separar em "Ao vivo ·
     Sentado" criava uma categoria que não existe — e quem quiser ver só a
     turma tem o filtro "Conjunto", que é a ferramenta certa para isso.

     Só quando não se sabe a atividade é que sobra uma classe própria, porque
     aí não há em qual entrar. */
  function classeDaGravacao(dados, atividade) {
    const classes = dados.dataset.classes || [];
    const daAtividade = atividade
      ? classes.find(classe => classe.id === atividade)
      : null;
    if (daAtividade) return daAtividade;
    if (!classes.some(classe => classe.id === CLASSE_SEM_ATIVIDADE.id)) {
      classes.push(CLASSE_SEM_ATIVIDADE);
    }
    return CLASSE_SEM_ATIVIDADE;
  }

  function inserirGravacoes(dados, gravacoes) {
    if (!gravacoes.length) return 0;
    const chaves = window.HAR_LIVE_CHAVES;
    if (!chaves) return 0;
    // Um índice, e não uma varredura por janela: com a turma inteira entrando,
    // o teste de repetição fazia ~1,9 milhão de comparações contra 180.
    const jaExistem = new Set(dados.amostras.map(amostra => amostra.id));
    let inseridas = 0;
    gravacoes.forEach((gravacao, indiceGravacao) => {
      const classe = classeDaGravacao(dados, gravacao.atividade);
      (gravacao.coordenadas || []).forEach((_, indiceJanela) => {
        const numero = Number.isFinite(gravacao.participante)
          ? gravacao.participante
          : PRIMEIRO_PARTICIPANTE;
        /* O identificador tem que ser único POR GRAVAÇÃO, não pela posição
           na lista recebida. No feed ao vivo cada gravação chega sozinha, e
           com a posição o índice era sempre 1: a segunda gravação da mesma
           pessoa nascia com os ids da primeira e era descartada como
           repetida. Na aula, em que cada aluno grava várias atividades, só a
           primeira teria aparecido. O relay carimba a hora em
           `server_received_at` (ao vivo) e `quando` (lista guardada) — o
           mesmo valor nos dois caminhos, então repetição continua sendo
           reconhecida e gravação nova entra. */
        const marca = gravacao.server_received_at || gravacao.quando || (indiceGravacao + 1);
        const identificador = `p${numero}_g${marca}_j${indiceJanela + 1}`;
        if (jaExistem.has(identificador)) return;
        jaExistem.add(identificador);

        // A mesma janela entra nas três projeções do espaço comum. No t-SNE a
        // posição é interpolada entre vizinhos, e não uma projeção nova; o
        // rótulo do painel diz isso.
        const projecoes = {};
        Object.keys(CAMPOS).forEach(tecnica => {
          const lista = gravacao[CAMPOS[tecnica]];
          const ponto = lista && lista[indiceJanela];
          if (ponto) projecoes[chaves[tecnica]] = ponto;
        });
        if (!Object.keys(projecoes).length) return;

        // Cada aparelho da sala tem seu número. Entrando como `subject`, o
        // laboratório já filtra por faixa e colore por participante sem
        // precisar de nada novo — a mesma máquina dos 30 participantes da UCI.
        const participante = Number.isFinite(gravacao.participante)
          ? gravacao.participante
          : PRIMEIRO_PARTICIPANTE;

        const ponto3d = (gravacao.coordenadas_3d || [])[indiceJanela];
        const projecoes3d = {};
        if (ponto3d && window.HAR_LIVE_CHAVE_3D) {
          projecoes3d[window.HAR_LIVE_CHAVE_3D] = ponto3d;
        }

        dados.amostras.push({
          id: identificador,
          label: classe.id,
          projecoes_3d: projecoes3d,
          meta: {
            subject: participante,
            // o nome vira filtro no laboratório: é assim que se acha um aluno
            // específico no meio da turma
            nome: gravacao.nome || `Participante ${participante}`,
            split: "iphone",
            source_row: indiceJanela + 1,
            atividade_instruida: gravacao.atividade || null,
            // preenchimento simulado: janela real do dataset atribuída a quem
            // estava na sala mas não conseguiu entregar a captura. Fica no
            // dado para que o medido e o preenchido possam ser separados.
            simulado: gravacao.simulado === true,
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

  /* A busca é síncrona de propósito.

     O laboratório indexa as amostras uma única vez, ao iniciar: identificadores,
     classes, participantes, conjuntos e chaves de projeção. Uma gravação que
     chegasse depois disso entraria na lista mas ficaria fora de todos esses
     índices — apareceria na contagem e sumiria dos filtros e do desenho.

     Como o relay está na mesma máquina e a resposta é pequena, o bloqueio é
     imperceptível e garante que as gravações existam antes da indexação. */
  function buscarGravacoes() {
    /* As gravações são dado pessoal e a rota exige o token de pareamento.
       Sem token na URL do laboratório, o dataset do experimento aparece
       normalmente e as gravações simplesmente não entram. */
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) return [];
    try {
      const requisicao = new XMLHttpRequest();
      requisicao.open("GET", "../api/har-live/gravacoes?token=" + encodeURIComponent(token), false);
      requisicao.send(null);
      if (requisicao.status !== 200) return [];
      return (JSON.parse(requisicao.responseText) || {}).gravacoes || [];
    } catch (erro) {
      return [];  /* laboratório aberto fora do relay: segue sem as gravações */
    }
  }

  /* O relay esqueceu tudo: a página tem que esquecer junto.

     As gravações vivem na memória do laboratório depois de absorvidas. Sem
     isto, apagar no /admin sumia com o dado no servidor e a tela continuava
     mostrando as mesmas pessoas até alguém recarregar. */
  function esquecerGravacoes(dados) {
    // A amostra ao vivo agora é reconhecida pela procedência, não pelo rótulo:
    // o rótulo dela é o da própria atividade, igual ao do experimento.
    const sobraram = dados.amostras.filter(
      amostra => !(amostra.meta && amostra.meta.split === "iphone")
    );
    const removidas = dados.amostras.length - sobraram.length;
    if (!removidas) return 0;
    dados.amostras.length = 0;
    sobraram.forEach(amostra => dados.amostras.push(amostra));
    // a classe sai junto: senão a legenda fica com "Gravação ao vivo 0"
    const classes = dados.dataset.classes || [];
    const orfa = classes.findIndex(classe => classe.id === CLASSE_SEM_ATIVIDADE.id);
    if (orfa >= 0) classes.splice(orfa, 1);
    dados.har_live_gravacoes = 0;
    recontar(dados);
    return removidas;
  }

  // O cabeçalho conta amostras e participantes; entrar e sair da turma mexe
  // nos dois, e a conta era feita igual em dois lugares.
  function recontar(dados) {
    dados.dataset.n_amostras_total = dados.amostras.length;
    const numeros = new Set(
      dados.amostras.map(amostra => amostra.meta && amostra.meta.subject).filter(Boolean)
    );
    dados.dataset.participantes = numeros.size;
  }

  function absorver(dados, gravacoes) {
    const inseridas = inserirGravacoes(dados, gravacoes);
    if (!inseridas) return 0;
    dados.har_live_gravacoes = gravacoes.length;
    recontar(dados);
    return inseridas;
  }

  const dados = window.HAR_DADOS;
  if (dados && Array.isArray(dados.amostras)) {
    absorver(dados, buscarGravacoes());
  }

  /* Feed ao vivo.

     A carga inicial acima é uma fotografia. Durante a aula, cada gravação que
     fecha chega por WebSocket e entra no mapa sem ninguém recarregar a página —
     é o que permite acompanhar a turma no laboratório enquanto ela grava. */
  function acompanharAoVivo() {
    const query = new URLSearchParams(window.location.search);
    const token = query.get("token");
    if (!token || !dados) return;
    const sessao = query.get("session") || "P31";
    const protocolo = window.location.protocol === "https:" ? "wss:" : "ws:";
    const endereco = `${protocolo}//${window.location.host}/ws/dashboard`
      + `?session=${encodeURIComponent(sessao)}&token=${encodeURIComponent(token)}`;

    /* Reconciliação: a verdade é sempre a do relay.

       O feed ao vivo só conta o que acontece enquanto o socket está aberto.
       Uma queda de rede, o celular trocando de Wi-Fi para 4G ou um reinício do
       relay deixavam a página parada no tempo: as gravações daquele intervalo
       nunca chegavam, e as apagadas continuavam desenhadas até alguém dar F5.
       A cada (re)conexão a página joga fora o que tem e reconstrói a partir do
       servidor, então ela volta sozinha ao estado certo. */
    let assinatura = null;

    const assinar = gravacoes => gravacoes
      .map(g => `${g.participante}:${(g.coordenadas || []).length}`).join("|");

    const reconciliar = () => {
      fetch("../api/har-live/gravacoes?token=" + encodeURIComponent(token))
        .then(resposta => (resposta.ok ? resposta.json() : null))
        .then(corpo => {
          if (!corpo) return;
          const gravacoes = corpo.gravacoes || [];
          const atual = assinar(gravacoes);
          if (atual === assinatura) return;  // nada mudou: não redesenha à toa
          assinatura = atual;
          esquecerGravacoes(dados);
          absorver(dados, gravacoes);
          if (window.HAR_LIVE_ABSORVER) window.HAR_LIVE_ABSORVER();
        })
        .catch(() => { /* relay fora do ar: a próxima reconexão tenta de novo */ });
    };

    let socket;
    const conectar = () => {
      socket = new WebSocket(endereco);
      socket.addEventListener("open", reconciliar);
      socket.addEventListener("message", evento => {
        let mensagem;
        try { mensagem = JSON.parse(evento.data); } catch (erro) { return; }

        /* Quem está na sala agora.

           O relay reemite `relay-status` a cada entrada e a cada saída, então
           a lista abaixo é o estado corrente da turma — inclusive de quem
           acabou de conectar e ainda não gravou nada. É o que permite ao
           filtro "Quem" mostrar a sala se formando antes da primeira janela. */
        if (mensagem.type === "relay-status") {
          window.HAR_LIVE_PRESENTES = (mensagem.turma || []).filter(
            pessoa => pessoa && typeof pessoa.nome === "string"
          );
          if (window.HAR_LIVE_PRESENCA) window.HAR_LIVE_PRESENCA();
          return;
        }

        if (mensagem.type === "gravacoes-atualizadas") {
          // nome corrigido ou gravação de alguém apagada: refaz do relay
          assinatura = null;
          reconciliar();
          return;
        }

        if (mensagem.type === "gravacoes-apagadas") {
          assinatura = "";
          if (esquecerGravacoes(dados) && window.HAR_LIVE_ABSORVER) {
            window.HAR_LIVE_ABSORVER();
          }
          return;
        }

        if (mensagem.type !== "projection") return;
        // uma gravação fechou: entra como as demais e o laboratório reindexa
        if (absorver(dados, [mensagem]) && window.HAR_LIVE_ABSORVER) {
          assinatura = null;  // força conferir com o relay na próxima conexão
          window.HAR_LIVE_ABSORVER();
        }
      });
      socket.addEventListener("close", () => window.setTimeout(conectar, 3000));
      socket.addEventListener("error", () => socket.close());
    };
    conectar();
  }

  acompanharAoVivo();
})();
