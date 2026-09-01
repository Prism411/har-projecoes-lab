/* Comando da turma.

   Esta página é a única que fala no sentido servidor → aparelhos, e por isso usa
   um token próprio: o token que circula entre os alunos não comanda nada. */
(() => {
  "use strict";

  const query = new URLSearchParams(window.location.search);
  const session = (query.get("session") || "P31").replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 24) || "P31";
  const token = query.get("token") || "";

  const elementos = Object.fromEntries([
    "conexao-dot", "conexao-label", "contagem-turma", "lista-turma",
    "qr-imagem", "qr-link", "btn-ampliar", "btn-reduzir",
    "atividade", "duracao", "contagem", "admin-mensagem",
    "btn-preparar", "btn-iniciar", "btn-parar", "btn-apagar"
  ].map(id => [id, document.getElementById(id)]));

  const estado = {
    websocket: null,
    conectado: false,
    turma: [],
    gravando: new Set()
  };

  function avisar(texto, tom = "") {
    elementos["admin-mensagem"].textContent = texto;
    if (tom) elementos["admin-mensagem"].dataset.tone = tom;
    else delete elementos["admin-mensagem"].dataset.tone;
  }

  function pintarConexao() {
    elementos["conexao-dot"].dataset.state = estado.conectado ? "ok" : "error";
    elementos["conexao-label"].textContent = estado.conectado
      ? `Sala ${session}`
      : "Sem conexão com o relay";
    const n = estado.turma.length;
    elementos["contagem-turma"].textContent =
      `${n} ${n === 1 ? "aparelho" : "aparelhos"}`;
    elementos["btn-iniciar"].disabled = !estado.conectado || n === 0;
  }

  // "Participante 31" é o padrão do servidor para quem não digitou nada.
  function semNome(pessoa) {
    return pessoa.nome === `Participante ${pessoa.participante}`;
  }

  function ordenarPorNome(turma) {
    return turma.slice().sort((a, b) => {
      const anonimoA = semNome(a), anonimoB = semNome(b);
      if (anonimoA !== anonimoB) return anonimoA ? 1 : -1;
      if (anonimoA) return a.participante - b.participante;
      return a.nome.localeCompare(b.nome, "pt-BR", { sensitivity: "base" });
    });
  }

  function pintarTurma() {
    const lista = elementos["lista-turma"];
    lista.innerHTML = "";
    if (!estado.turma.length) {
      const vazio = document.createElement("li");
      vazio.className = "vazio";
      vazio.textContent = "Ninguém conectado ainda. Passe o QR para a turma.";
      lista.appendChild(vazio);
      return;
    }
    // Numa sala, quem conduz procura a pessoa pelo NOME, não pelo número — o
    // número é detalhe do dado. Quem ainda não se identificou vai para o fim,
    // ordenado por número, para não misturar "Participante 12" com nomes reais.
    ordenarPorNome(estado.turma).forEach(pessoa => {
      const item = document.createElement("li");
      if (estado.gravando.has(pessoa.participante)) item.dataset.gravando = "sim";
      const marca = document.createElement("span");
      marca.className = "marca";
      const nome = document.createElement("span");
      nome.className = "nome";
      nome.textContent = pessoa.nome;
      if (semNome(pessoa)) nome.dataset.anonimo = "sim";
      const numero = document.createElement("span");
      numero.className = "numero";
      numero.textContent = pessoa.participante;
      const acoes = document.createElement("span");
      acoes.className = "acoes";
      acoes.append(
        botaoDeGestao("✎", `Corrigir o nome de ${pessoa.nome}`, () => renomear(pessoa)),
        botaoDeGestao("⌫", `Apagar as gravações de ${pessoa.nome}`, () => esquecer(pessoa)),
        botaoDeGestao("✕", `Tirar ${pessoa.nome} da sala`, () => remover(pessoa))
      );
      item.append(marca, nome, numero, acoes);
      lista.appendChild(item);
    });
  }

  function enderecoDoSocket() {
    const protocolo = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocolo}//${window.location.host}/ws/admin`
      + `?session=${encodeURIComponent(session)}&token=${encodeURIComponent(token)}`;
  }

  function comandar(acao) {
    if (!estado.conectado) return avisar("Sem conexão com o relay.", "erro");
    const comando = { type: "comando", acao };
    if (acao === "preparar" || acao === "iniciar") {
      comando.atividade = elementos["atividade"].value;
      comando.duracao_ms = Number(elementos["duracao"].value);
    }
    if (acao === "iniciar") comando.contagem_ms = Number(elementos["contagem"].value);
    estado.websocket.send(JSON.stringify(comando));
  }

  /* Gestão da turma.

     Comando fala com os aparelhos; gestão age no relay. São coisas diferentes
     e por isso saem por funções diferentes, mesmo indo pelo mesmo socket. */
  function gerir(acao, participante, extra) {
    if (!estado.conectado) return avisar("Sem conexão com o relay.", "erro");
    estado.websocket.send(JSON.stringify(
      Object.assign({ acao: acao, participante: participante }, extra || {})
    ));
  }

  function renomear(pessoa) {
    const atual = semNome(pessoa) ? "" : pessoa.nome;
    const novo = window.prompt(`Nome do participante ${pessoa.participante}:`, atual);
    if (novo === null) return;
    const limpo = novo.trim();
    if (!limpo) return avisar("Nome vazio: nada mudou.", "erro");
    gerir("renomear", pessoa.participante, { nome: limpo });
  }

  function remover(pessoa) {
    if (!window.confirm(`Tirar ${pessoa.nome} da sala? O aparelho vai se desconectar.`)) return;
    gerir("remover", pessoa.participante);
  }

  function esquecer(pessoa) {
    if (!window.confirm(`Apagar as gravações de ${pessoa.nome}? Isso não volta.`)) return;
    gerir("esquecer", pessoa.participante);
  }

  function botaoDeGestao(rotulo, titulo, aoClicar) {
    const botao = document.createElement("button");
    botao.type = "button";
    botao.className = "acao-turma";
    botao.textContent = rotulo;
    botao.title = titulo;
    botao.setAttribute("aria-label", titulo);
    botao.addEventListener("click", aoClicar);
    return botao;
  }

  function tratar(mensagem) {
    if (mensagem.type === "gestao-ok") {
      // O relay diz o que REALMENTE mudou. Anunciar sucesso quando nada foi
      // encontrado deixaria quem conduz a aula achando que arrumou a lista.
      if (mensagem.acao === "renomear") {
        const quantas = mensagem.gravacoes;
        avisar(
          `Agora é ${mensagem.nome}` + (quantas ? ` — ${quantas} gravação(ões) corrigida(s).` : "."),
          "ok"
        );
      } else if (mensagem.acao === "remover") {
        avisar(
          mensagem.aparelhos
            ? `Participante ${mensagem.participante} saiu da sala.`
            : `Nenhum aparelho conectado como participante ${mensagem.participante}.`,
          mensagem.aparelhos ? "ok" : "erro"
        );
      } else {
        avisar(
          mensagem.gravacoes
            ? `${mensagem.gravacoes} gravação(ões) apagada(s).`
            : `O participante ${mensagem.participante} não tinha gravações.`,
          mensagem.gravacoes ? "ok" : "erro"
        );
      }
      return;
    }
    if (mensagem.type === "relay-status") {
      estado.turma = mensagem.turma || [];
      pintarConexao();
      pintarTurma();
      return;
    }
    if (mensagem.type === "comando-ok") {
      const rotulos = {
        preparar: "Aviso enviado",
        iniciar: "Partida dada",
        parar: "Gravação interrompida",
        limpar: "Aparelhos limpos"
      };
      avisar(`${rotulos[mensagem.acao] || mensagem.acao} — ${mensagem.aparelhos} aparelho(s).`, "ok");
      return;
    }
    if (mensagem.type === "recording") {
      // acompanha quem está gravando agora, para a lista mostrar o estado
      if (mensagem.status === "started") estado.gravando.add(mensagem.participante);
      else estado.gravando.delete(mensagem.participante);
      pintarTurma();
      return;
    }
    if (mensagem.type === "summary") {
      estado.gravando.delete(mensagem.participante);
      pintarTurma();
      return;
    }
    if (mensagem.type === "projection") {
      avisar(`${mensagem.nome || "Participante " + mensagem.participante} entrou no mapa `
        + `(${mensagem.janelas} janelas).`, "ok");
      return;
    }
    if (mensagem.type === "error") {
      avisar(mensagem.message || "O servidor recusou o comando.", "erro");
    }
  }

  function conectar() {
    if (!token) {
      elementos["conexao-dot"].dataset.state = "error";
      elementos["conexao-label"].textContent = "Token de admin ausente";
      avisar("Abra esta página com o token de admin, que é diferente do token dos alunos.", "erro");
      return;
    }
    const websocket = new WebSocket(enderecoDoSocket());
    estado.websocket = websocket;

    websocket.addEventListener("open", () => {
      estado.conectado = true;
      pintarConexao();
      avisar("Conectado. Aguardando a turma entrar.", "");
    });
    websocket.addEventListener("message", evento => {
      let mensagem;
      try { mensagem = JSON.parse(evento.data); } catch (erro) { return; }
      tratar(mensagem);
    });
    websocket.addEventListener("close", evento => {
      estado.conectado = false;
      pintarConexao();
      if (evento.code === 1008) {
        elementos["conexao-label"].textContent = "Token de admin recusado";
        avisar("Este token não comanda a turma. Use o token de admin.", "erro");
        return;
      }
      window.setTimeout(conectar, 1500);
    });
    websocket.addEventListener("error", () => websocket.close());
  }

  elementos["btn-preparar"].addEventListener("click", () => comandar("preparar"));
  elementos["btn-iniciar"].addEventListener("click", () => comandar("iniciar"));
  elementos["btn-parar"].addEventListener("click", () => comandar("parar"));

  elementos["btn-apagar"].addEventListener("click", async () => {
    if (!window.confirm("Apagar todas as gravações da turma? Não dá para desfazer.")) return;
    try {
      const resposta = await fetch(
        `/api/har-live/gravacoes?token=${encodeURIComponent(token)}`,
        { method: "DELETE" }
      );
      avisar(resposta.ok ? "Gravações apagadas." : "Não consegui apagar.",
             resposta.ok ? "ok" : "erro");
    } catch (erro) {
      avisar("Não consegui apagar.", "erro");
    }
  });

  // O QR é desenhado pelo servidor: assim o link e o token vêm sempre da mesma
  // fonte que o relay usa, sem risco de a tela mostrar um código defasado.
  function montarQr() {
    if (!elementos["qr-imagem"]) return;
    const endereco = `/api/qr?session=${encodeURIComponent(session)}&token=${encodeURIComponent(token)}`;
    elementos["qr-imagem"].src = endereco;
    elementos["qr-imagem"].onerror = () => {
      avisar("Não consegui gerar o QR. Confira se o token de admin está correto.", "erro");
    };
    if (elementos["qr-link"]) {
      elementos["qr-link"].textContent = `${window.location.origin}/mobile?session=${session}&token=…`;
    }
  }

  if (elementos["btn-ampliar"]) {
    elementos["btn-ampliar"].addEventListener("click", () => {
      document.body.classList.toggle("qr-ampliado");
    });
  }
  if (elementos["btn-reduzir"]) {
    elementos["btn-reduzir"].addEventListener("click", () => {
      document.body.classList.remove("qr-ampliado");
    });
  }
  // sair do modo ampliado sem precisar mirar o botão, que fica escondido
  document.addEventListener("click", evento => {
    if (document.body.classList.contains("qr-ampliado") && evento.target.id !== "btn-ampliar") {
      document.body.classList.remove("qr-ampliado");
    }
  });
  document.addEventListener("keydown", evento => {
    if (evento.key === "Escape") document.body.classList.remove("qr-ampliado");
  });

  montarQr();
  pintarConexao();
  pintarTurma();
  conectar();
})();
