(() => {
  "use strict";

  const query = new URLSearchParams(window.location.search);
  const session = (query.get("session") || "P31").replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 24) || "P31";
  const token = query.get("token") || "";

  // O número separa um aparelho do outro na mesma sala. Vem da URL quando quem
  // conduz a aula já distribuiu os códigos, e pode ser ajustado antes de gravar.
  const PRIMEIRO_PARTICIPANTE = 31;
  const ULTIMO_PARTICIPANTE = 999;

  /* O nome precisa estar no campo antes da primeira conexão: o aparelho se
     apresenta ao relay no `open` do socket. O número não vem mais daqui —
     quem atribui é o servidor, e ninguém digita o próprio.

     O nome também sobrevive a um recarregar. Sem isso, uma página que
     recarrega (o iOS faz isso sozinho quando precisa de memória) devolvia o
     aluno à sala como "Participante N", e a gravação dele entraria no mapa
     sem nome nenhum. Fica só nesta aba, e some quando ela fecha. */
  const MEMORIA_DO_NOME = "har-live-nome";
  const MEMORIA_DO_NUMERO = "har-live-numero";
  const MEMORIA_DA_CHAVE = "har-live-chave";

  function guardar(caixa, valor) {
    try { window.sessionStorage.setItem(caixa, valor); } catch (erro) { /* aba privada */ }
  }

  function guardado(caixa) {
    try { return window.sessionStorage.getItem(caixa) || ""; } catch (erro) { return ""; }
  }

  function lembrarNome(nome) { guardar(MEMORIA_DO_NOME, nome); }
  function nomeLembrado() { return guardado(MEMORIA_DO_NOME); }

  (() => {
    const campoNome = document.getElementById("nome-input");
    if (!campoNome) return;
    const nomeDaUrl = query.get("nome");
    const inicial = nomeDaUrl || nomeLembrado();
    if (inicial) campoNome.value = inicial.slice(0, 24);
  })();

  // O servidor decide o número final: numa sala o mesmo QR abre em vários
  // aparelhos, e dois alunos com o mesmo número teriam as amostras somadas.
  function receberNumero(mensagem) {
    state.participanteConfirmado = mensagem.participante;
    // A chave prova, na volta, que este número é deste aparelho. Sem ela o
    // relay entrega um número novo — números não são reciclados, então
    // ninguém herda o identificador (nem as gravações) de outra pessoa.
    if (mensagem.chave) {
      guardar(MEMORIA_DO_NUMERO, String(mensagem.participante));
      guardar(MEMORIA_DA_CHAVE, mensagem.chave);
    }
    if (modelo.numero) modelo.numero.textContent = String(mensagem.participante);
    if (mensagem.trocado) {
      setMessage(`O número ${mensagem.pedido} já estava em uso. Você é o participante ${mensagem.participante}.`, "");
    }
  }

  // Só o que o aluno realmente digitou. Sem nome, o aparelho não inventa um a
  // partir do número local: o hello sai antes de o servidor responder com o
  // número reservado, então "Participante 31" seria carimbado em todo mundo.
  // Quem sabe o número final é o servidor, e ele já preenche o padrão.
  function nomeAtual() {
    const campo = document.getElementById("nome-input");
    const bruto = (campo ? campo.value : query.get("nome")) || "";
    return bruto.trim().slice(0, 24);
  }

  // Só um palpite: o número que vale é o que o relay reserva e devolve em
  // `participante-atribuido`. Se esta aba já teve um, ele vem primeiro — com a
  // chave junto, é assim que se reave o mesmo número depois de recarregar.
  function participanteAtual() {
    const numero = Number.parseInt(guardado(MEMORIA_DO_NUMERO) || query.get("participante"), 10);
    if (!Number.isFinite(numero)) return PRIMEIRO_PARTICIPANTE;
    return Math.min(ULTIMO_PARTICIPANTE, Math.max(PRIMEIRO_PARTICIPANTE, numero));
  }
  const demoMode = query.get("demo") === "1";
  const elements = Object.fromEntries([
    "secure-dot", "secure-label", "socket-dot", "socket-label", "sensor-dot", "sensor-label",
    "message", "permission-button",
    "stop-button", "timer", "sample-rate", "acceleration-value",
    "acceleration-source", "rotation-value", "export-button"
  ].map(id => [id, document.getElementById(id)]));

  const state = {
    travaDeTela: null,
    websocket: null,
    connected: false,
    permission: false,
    listening: false,
    orientation: [null, null, null],
    pending: [],
    sequence: 0,
    eventTimes: [],
    recording: false,
    countingDown: false,
    recordingSamples: [],
    recordingStartedAt: 0,
    recordingDurationMs: 10000,
    recordingTimer: 0,
    countdownTimer: 0,
    demoTimer: 0,
    duracaoComandada: 0,
    // Atividade e duração pertencem a quem conduz a aula. O aparelho guarda o
    // que foi comandado; campos na tela, quando existirem, são só reflexo.
    atividadeComandada: "",
    participanteConfirmado: 0,
    sensorWatchdog: 0,
    receivedMotionEvents: 0,
    validMotionEvents: 0,
    completeMotionEvents: 0
  };

  function numberOrNull(value) {
    return Number.isFinite(value) ? Number(value) : null;
  }

  function vector(source, keys) {
    return keys.map(key => numberOrNull(source && source[key]));
  }

  /* A conexão com a sala precisa ser visível fora do mobile.js.

     Sem isto, o aluno chegava à tela "Pronto" só por ter sensores — e ficava
     esperando a partida de um relay que nunca o viu, numa tela dizendo que
     estava tudo certo. */
  function marcarConexao() {
    document.body.dataset.conectado = state.connected ? "1" : "0";
  }

  function setDot(name, status, label) {
    elements[`${name}-dot`].dataset.state = status;
    elements[`${name}-label`].textContent = label;
  }

  function setMessage(text, tone = "") {
    elements.message.textContent = text;
    if (tone) elements.message.dataset.tone = tone;
    else delete elements.message.dataset.tone;
  }

  function websocketUrl(role) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/ws/${role}`
      + `?session=${encodeURIComponent(session)}`
      + `&token=${encodeURIComponent(token)}`
      + `&participante=${encodeURIComponent(participanteAtual())}`
      + (guardado(MEMORIA_DA_CHAVE)
          ? `&chave=${encodeURIComponent(guardado(MEMORIA_DA_CHAVE))}` : "");
  }

  function send(message) {
    if (!state.websocket || state.websocket.readyState !== WebSocket.OPEN) return false;
    state.websocket.send(JSON.stringify(message));
    return true;
  }

  /* Batimento.

     O relay precisa distinguir uma página viva de uma aba congelada ou fechada
     que o túnel ainda mantém aberta. O ping do WebSocket não serve: quem
     responde é o navegador, mesmo com a página parada. Este aviso sai daqui,
     do JavaScript, então some junto com a página — e o servidor tira da sala
     quem ficou em silêncio. */
  const BATIMENTO_MS = 15000;

  function baterCoracao() {
    pararCoracao();
    state.coracao = window.setInterval(() => {
      if (state.websocket && state.websocket.readyState === WebSocket.OPEN) {
        send({ type: "keepalive" });
      }
    }, BATIMENTO_MS);
  }

  function pararCoracao() {
    if (state.coracao) { window.clearInterval(state.coracao); state.coracao = null; }
  }

  // A apresentação ao relay sai de um lugar só: ela acontece na conexão e de
  // novo quando o aluno confirma o nome, e as duas versões precisam ser a
  // mesma coisa.
  function saudacao() {
    const aviso = {
      type: "hello", role: "mobile", session,
      user_agent: navigator.userAgent.slice(0, 180),
      secure: window.isSecureContext
    };
    const nome = nomeAtual();
    if (nome) aviso.nome = nome;
    return aviso;
  }

  function connect() {
    if (!token) {
      setDot("socket", "error", "Token de pareamento ausente");
      setMessage("Abra a URL completa fornecida pelo servidor, incluindo o token temporário.", "error");
      return;
    }
    if (state.websocket && state.websocket.readyState < WebSocket.CLOSING) return;
    const websocket = new WebSocket(websocketUrl("mobile"));
    state.websocket = websocket;
    setDot("socket", "warn", "Conectando ao notebook");
    websocket.addEventListener("open", () => {
      state.connected = true;
      marcarConexao();
      setDot("socket", "ok", `Conectado · sessão ${session}`);
      send(saudacao());
      baterCoracao();
      updateControls();
    });
    websocket.addEventListener("message", evento => {
      let mensagem;
      try { mensagem = JSON.parse(evento.data); } catch (erro) { return; }
      if (mensagem && mensagem.type === "comando") obedecer(mensagem);
      if (mensagem && mensagem.type === "participante-atribuido") receberNumero(mensagem);
    });
    websocket.addEventListener("close", event => {
      state.connected = false;
      marcarConexao();
      pararCoracao();
      if (state.recording || state.countingDown) stopRecording("connection-lost");
      if (event.code === 1008) {
        setDot("socket", "error", "Pareamento recusado");
        setMessage("Token de pareamento inválido ou mensagem rejeitada pelo servidor.", "error");
        updateControls();
        return;
      }
      setDot("socket", "error", "Conexão perdida — tentando novamente");
      updateControls();
      window.setTimeout(connect, 1500);
    });
    websocket.addEventListener("error", () => websocket.close());
  }

  function observedRate() {
    const times = state.eventTimes;
    if (times.length < 2) return 0;
    const seconds = (times[times.length - 1] - times[0]) / 1000;
    return seconds > 0 ? (times.length - 1) / seconds : 0;
  }

  function formatVector(values) {
    return values.map(value => value == null ? "—" : value.toFixed(2)).join(" · ");
  }

  function updateRate(timestamp) {
    state.eventTimes.push(timestamp);
    while (state.eventTimes.length && timestamp - state.eventTimes[0] > 4000) state.eventTimes.shift();
    elements["sample-rate"].textContent = `${observedRate().toLocaleString("pt-BR", { maximumFractionDigits: 1 })} Hz observados`;
  }

  function enqueue(sample) {
    state.pending.push(sample);
    if (state.pending.length >= 5) flush();
  }

  function flush() {
    if (!state.pending.length) return;
    const samples = state.pending.splice(0, 25);
    const sequence = state.sequence;
    const delivered = send({
      type: "samples",
      session,
      sequence,
      sent_at: Date.now(),
      recording: state.recording,
      activity: atividadeAtual(),
      samples
    });
    if (!delivered) state.pending = samples.concat(state.pending).slice(-25);
    else {
      state.sequence += 1;
      if (state.pending.length) window.setTimeout(flush, 0);
    }
  }

  function completeVector(values) {
    return Array.isArray(values) && values.length === 3 && values.every(Number.isFinite);
  }

  function hasMeasuredMotion(sample) {
    return [sample.acceleration, sample.acceleration_gravity, sample.rotation_deg_s]
      .some(values => Array.isArray(values) && values.some(Number.isFinite));
  }

  function usableAcceleration(sample) {
    if (completeVector(sample.acceleration)) return { values: sample.acceleration, source: "linear" };
    if (completeVector(sample.acceleration_gravity)) return { values: sample.acceleration_gravity, source: "com gravidade" };
    return null;
  }

  function completeForCapture(sample) {
    return Boolean(usableAcceleration(sample)) && completeVector(sample.rotation_deg_s);
  }

  function completeWithLinearAcceleration(sample) {
    return completeVector(sample.acceleration) && completeVector(sample.rotation_deg_s);
  }

  function processSample(sample) {
    state.receivedMotionEvents += 1;
    if (!hasMeasuredMotion(sample)) return;
    state.validMotionEvents += 1;
    const acceleration = usableAcceleration(sample);
    if (completeForCapture(sample)) {
      const primeiraLeituraCompleta = state.completeMotionEvents === 0;
      state.completeMotionEvents += 1;
      window.clearTimeout(state.sensorWatchdog);
      setDot("sensor", "ok", "Aceleração e rotação ativas");
      if (primeiraLeituraCompleta) updateControls();
    } else {
      setDot("sensor", "warn", "Leituras parciais do aparelho");
    }
    const timestamp = sample.t;
    updateRate(timestamp);
    elements["acceleration-value"].textContent = formatVector(acceleration ? acceleration.values : sample.acceleration);
    elements["acceleration-source"].textContent = acceleration ? acceleration.source : "indisponível";
    elements["rotation-value"].textContent = formatVector(sample.rotation_deg_s);
    if (state.recording) state.recordingSamples.push(sample);
    enqueue(sample);
  }

  function onMotion(event) {
    processSample({
      t: Date.now(),
      interval_ms: numberOrNull(event.interval),
      acceleration: vector(event.acceleration, ["x", "y", "z"]),
      acceleration_gravity: vector(event.accelerationIncludingGravity, ["x", "y", "z"]),
      rotation_deg_s: vector(event.rotationRate, ["alpha", "beta", "gamma"]),
      orientation_deg: state.orientation.slice()
    });
  }

  // ------------------------------------------- o aparelho em 3D, na tela de espera
  //
  // Enquanto aguarda a partida, o aluno vê o próprio aparelho girando conforme
  // ele mexe. Serve de confirmação honesta de que o sensor está entregando dado
  // — melhor que um "aguardando" parado, que não distingue pronto de travado.
  // O desenho é o mesmo do painel do notebook, alimentado pela orientação local.
  const modelo = {
    elemento: null,
    numero: null,
    quadroPedido: false,
    ultimoDesenho: 0
  };

  function desenharAparelho() {
    modelo.quadroPedido = false;
    if (!modelo.elemento) return;
    const [alpha, beta, gamma] = state.orientation || [0, 0, 0];
    const a = Number.isFinite(alpha) ? alpha : 0;
    const b = Number.isFinite(beta) ? beta : 0;
    const g = Number.isFinite(gamma) ? gamma : 0;
    modelo.elemento.style.transform =
      `rotateZ(${a.toFixed(1)}deg) rotateX(${b.toFixed(1)}deg) rotateY(${(-g).toFixed(1)}deg)`;
  }

  function pedirQuadro() {
    if (modelo.quadroPedido) return;
    // os sensores chegam a 50 Hz; a tela não precisa de mais que ~30 quadros
    const agora = Date.now();
    if (agora - modelo.ultimoDesenho < 33) return;
    modelo.ultimoDesenho = agora;
    modelo.quadroPedido = true;
    window.requestAnimationFrame(desenharAparelho);
  }

  function prepararModelo3d() {
    modelo.elemento = document.getElementById("phone-model");
    modelo.numero = document.getElementById("phone-model-numero");
    if (modelo.numero) modelo.numero.textContent = String(participanteAtual());
  }

  function onOrientation(event) {
    state.orientation = [numberOrNull(event.alpha), numberOrNull(event.beta), numberOrNull(event.gamma)];
    pedirQuadro();
  }

  function startListening() {
    if (state.listening) return;
    state.listening = true;
    window.addEventListener("devicemotion", onMotion);
    window.addEventListener("deviceorientation", onOrientation);
    if (demoMode) startDemoMotion();
  }

  function startDemoMotion() {
    let phase = 0;
    window.clearInterval(state.demoTimer);
    state.demoTimer = window.setInterval(() => {
      phase += 0.11;
      state.orientation = [phase * 8 % 360, Math.sin(phase) * 8, Math.cos(phase * 0.7) * 5];
      pedirQuadro();
      processSample({
        t: Date.now(), interval_ms: 20,
        acceleration: [Math.sin(phase) * 1.8, Math.cos(phase * 0.9) * 0.7, Math.sin(phase * 2) * 0.35],
        acceleration_gravity: [Math.sin(phase) * 1.8, 9.81 + Math.cos(phase * 0.9) * 0.7, Math.sin(phase * 2) * 0.35],
        rotation_deg_s: [Math.cos(phase) * 18, Math.sin(phase * 0.7) * 10, Math.cos(phase * 0.4) * 6],
        orientation_deg: state.orientation.slice()
      });
    }, 20);
  }

  async function requestPermissions() {
    try {
      if (!window.isSecureContext && !demoMode) throw new Error("Esta página precisa ser aberta por HTTPS.");
      if (window.top !== window.self && !demoMode) throw new Error("Abra a página diretamente no Safari, fora de iframe.");
      if (!demoMode && typeof DeviceMotionEvent === "undefined") throw new Error("DeviceMotionEvent não está disponível neste navegador.");

      const motionPromise = !demoMode && typeof DeviceMotionEvent.requestPermission === "function"
        ? DeviceMotionEvent.requestPermission()
        : Promise.resolve("granted");
      const orientationPromise = !demoMode && typeof DeviceOrientationEvent !== "undefined" && typeof DeviceOrientationEvent.requestPermission === "function"
        ? DeviceOrientationEvent.requestPermission()
        : Promise.resolve("granted");
      const orientationResult = Promise.resolve(orientationPromise).catch(() => "unavailable");
      const [motionPermission] = await Promise.all([motionPromise, orientationResult]);
      if (motionPermission !== "granted") throw new Error("Permissão de movimento não concedida.");

      state.permission = true;
      startListening();
      setDot("sensor", "warn", demoMode ? "Iniciando sinais simulados" : "Permissão concedida · aguardando leitura");
      setMessage("Permissão concedida. Aguardando a primeira leitura real do aparelho.");
      state.sensorWatchdog = window.setTimeout(() => {
        if (!state.validMotionEvents) {
          setDot("sensor", "error", "Nenhuma leitura recebida");
          setMessage("A permissão foi concedida, mas o Safari não entregou dados. Mantenha a página visível e confira os ajustes de movimento.", "error");
        } else if (!state.completeMotionEvents) {
          setDot("sensor", "error", "Leituras incompletas");
          setMessage("O Safari entregou dados parciais, mas faltam aceleração ou rotação X/Y/Z para a captura.", "error");
        }
      }, 2500);
      send({ type: "status", status: "sensors-granted", demo: demoMode });
      updateControls();
    } catch (error) {
      state.permission = false;
      setDot("sensor", "error", "Sensores indisponíveis");
      setMessage(error instanceof Error ? error.message : "Não foi possível ativar os sensores.", "error");
      updateControls();
    }
  }


  function updateTimer() {
    if (!state.recording) return;
    const elapsed = Date.now() - state.recordingStartedAt;
    const remaining = Math.max(0, state.recordingDurationMs - elapsed);
    elements.timer.textContent = `00:${(remaining / 1000).toFixed(1).padStart(4, "0")}`;
    if (remaining <= 0) stopRecording("completed");
  }

  function beginRecording(opcoes = {}) {
    const imediato = opcoes.imediato === true;
    if (!state.permission || !state.connected || state.recording) return;
    if (!imediato && state.countingDown) return;
    if (imediato) return gravarAgora();
    let countdown = 3;
    state.countingDown = true;
    state.recordingSamples = [];
    elements["export-button"].disabled = true;
    setMessage(`Prepare-se: ${countdown}`);
    state.countdownTimer = window.setInterval(() => {
      countdown -= 1;
      if (countdown > 0) {
        setMessage(`Prepare-se: ${countdown}`);
        return;
      }
      window.clearInterval(state.countdownTimer);
      state.countingDown = false;
      gravarAgora();
    }, 1000);
  }

  /* Trava de tela.

     A instrução é prender o aparelho na cintura — e aí a tela apaga sozinha,
     a página fica oculta e a gravação era abortada com meia dúzia de leituras,
     abaixo do mínimo de 64 para formar uma janela. Uma aula inteira gravou
     assim, sem nada chegar do outro lado. Com a trava, a tela não apaga
     durante a captura. */
  async function segurarTela() {
    try {
      if (navigator.wakeLock && !state.travaDeTela) {
        state.travaDeTela = await navigator.wakeLock.request("screen");
        state.travaDeTela.addEventListener("release", () => { state.travaDeTela = null; });
      }
    } catch (erro) { /* navegador sem suporte: o aviso na tela cobre o resto */ }
  }

  function soltarTela() {
    if (!state.travaDeTela) return;
    try { state.travaDeTela.release(); } catch (erro) { /* já solta */ }
    state.travaDeTela = null;
  }

  function gravarAgora() {
    state.recording = true;
    segurarTela();
    state.recordingSamples = [];
    state.recordingStartedAt = Date.now();
    state.recordingDurationMs = duracaoAtualMs();
    elements.timer.textContent = `00:${(state.recordingDurationMs / 1000).toFixed(1).padStart(4, "0")}`;
    state.recordingTimer = window.setInterval(updateTimer, 50);
    send({
      type: "recording", status: "started",
      activity: atividadeAtual(),
      duration_ms: state.recordingDurationMs
    });
    setMessage("Gravando. Execute a atividade com segurança.");
    updateControls();
  }

  // ------------------------------------------------ comandos vindos do professor
  //
  // A gravação da turma precisa começar junto. Quem dá a partida é o painel de
  // admin; aqui o aparelho apenas obedece, e só depois de o aluno ter permitido
  // os sensores — nenhum comando liga sensor sem o toque dele.
  function obedecer(comando) {
    if (comando.acao === "parar") {
      if (state.recording || state.countingDown) stopRecording("manual");
      setMessage("O professor encerrou a gravação.", "");
      return;
    }
    if (comando.acao === "limpar") {
      state.recordingSamples = [];
      updateControls();
      return;
    }
    if (comando.atividade) {
      state.atividadeComandada = comando.atividade;
      const campo = document.getElementById("activity-select");
      if (campo) campo.value = comando.atividade;
    }
    if (comando.duracao_ms) {
      state.duracaoComandada = comando.duracao_ms;
      const campo = document.getElementById("duration-select");
      if (campo) {
        const segundos = String(Math.round(comando.duracao_ms / 1000));
        const opcao = Array.from(campo.options).find(o => o.value === segundos);
        if (opcao) campo.value = segundos;
      }
    }
    if (comando.acao === "preparar") {
      setMessage(`Prepare-se: ${rotuloAtividade(comando.atividade)}. Aguarde a partida.`, "");
      return;
    }
    if (comando.acao === "iniciar") {
      if (!state.permission) {
        setMessage("Toque em Permitir sensores antes da partida.", "error");
        return;
      }
      iniciarComContagem(Number(comando.contagem_ms) || 0);
    }
  }

  const DURACAO_PADRAO_MS = 10000;

  // Leitura única de atividade e duração: o comando do admin manda; o campo do
  // DOM é consultado só se existir; e há um padrão para quando não há nenhum.
  function atividadeAtual() {
    if (state.atividadeComandada) return state.atividadeComandada;
    const campo = document.getElementById("activity-select");
    return (campo && campo.value) || "WALKING";
  }

  function duracaoAtualMs() {
    if (state.duracaoComandada) return state.duracaoComandada;
    const campo = document.getElementById("duration-select");
    return campo ? Number(campo.value) * 1000 : DURACAO_PADRAO_MS;
  }

  const NOMES_DE_ATIVIDADE = {
    WALKING: "andar", WALKING_UPSTAIRS: "subir escada",
    WALKING_DOWNSTAIRS: "descer escada", SITTING: "sentar",
    STANDING: "ficar em pé", LAYING: "deitar"
  };

  function rotuloAtividade(chave) {
    return NOMES_DE_ATIVIDADE[chave] || chave || "a atividade combinada";
  }

  function iniciarComContagem(contagemMs) {
    if (state.recording || state.countingDown) return;
    window.clearInterval(state.countdownTimer);
    state.countingDown = true;
    updateControls();

    const fim = Date.now() + contagemMs;
    const tique = () => {
      const faltam = Math.ceil((fim - Date.now()) / 1000);
      if (faltam > 0) {
        setMessage(`Começa em ${faltam}…`, "");
        return;
      }
      window.clearInterval(state.countdownTimer);
      state.countingDown = false;
      beginRecording({ imediato: true });
    };
    tique();
    state.countdownTimer = window.setInterval(tique, 200);
  }

  function stopRecording(reason = "manual") {
    soltarTela();
    if (reason === "page-hidden" && state.recording) {
      setMessage("A gravação parou porque a tela apagou ou você saiu da página. "
        + "Mantenha a tela ligada e peça para repetir.", "error");
    }
    window.clearInterval(state.recordingTimer);
    window.clearInterval(state.countdownTimer);
    if (state.countingDown && !state.recording) {
      state.countingDown = false;
      setMessage("Contagem regressiva cancelada.");
      updateControls();
      return;
    }
    if (!state.recording && !state.recordingSamples.length) {
      updateControls();
      return;
    }
    state.recording = false;
    flush();
    const duration = state.recordingSamples.length > 1
      ? state.recordingSamples[state.recordingSamples.length - 1].t - state.recordingSamples[0].t
      : 0;
    const rate = duration > 0 ? (state.recordingSamples.length - 1) * 1000 / duration : 0;
    const completeCount = state.recordingSamples.filter(completeForCapture).length;
    const validRatio = state.recordingSamples.length ? completeCount / state.recordingSamples.length : 0;
    const linearCount = state.recordingSamples.filter(completeWithLinearAcceleration).length;
    const linearRatio = state.recordingSamples.length ? linearCount / state.recordingSamples.length : 0;
    send({
      type: "summary",
      reason,
      activity: atividadeAtual(),
      sample_count: state.recordingSamples.length,
      duration_ms: duration,
      observed_hz: rate,
      valid_ratio: validRatio,
      linear_ratio: linearRatio
    });
    elements.timer.textContent = "00:00.0";
    elements["export-button"].disabled = !state.recordingSamples.length;
    const tone = validRatio >= 0.9 ? "success" : "error";
    setMessage(`Gravação concluída: ${state.recordingSamples.length} leituras a ${rate.toFixed(1)} Hz; ${(validRatio * 100).toFixed(0)}% utilizáveis e ${(linearRatio * 100).toFixed(0)}% com aceleração linear nativa.`, tone);
    updateControls();
  }

  function exportCsv() {
    if (!state.recordingSamples.length) return;
    const columns = ["t", "interval_ms", "ax", "ay", "az", "agx", "agy", "agz", "rot_alpha", "rot_beta", "rot_gamma", "ori_alpha", "ori_beta", "ori_gamma"];
    const rows = state.recordingSamples.map(sample => [
      sample.t, sample.interval_ms, ...sample.acceleration, ...sample.acceleration_gravity,
      ...sample.rotation_deg_s, ...sample.orientation_deg
    ].map(value => value == null ? "" : value).join(","));
    const blob = new Blob([[columns.join(","), ...rows].join("\n")], { type: "text/csv;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `har-${session}-${atividadeAtual().toLowerCase()}-${Date.now()}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  function updateControls() {
    const campoNome = document.getElementById("nome-input");
    if (campoNome) campoNome.disabled = state.permission;
    elements["permission-button"].disabled = state.permission;
    elements["permission-button"].textContent = state.permission ? "Sensores permitidos" : "Permitir sensores";
    elements["stop-button"].hidden = !state.recording;
    // os campos podem nem existir depois da reestruturação em etapas
    const campoAtividade = document.getElementById("activity-select");
    const campoDuracao = document.getElementById("duration-select");
    if (campoAtividade) campoAtividade.disabled = state.recording || state.countingDown;
    if (campoDuracao) campoDuracao.disabled = state.recording || state.countingDown;
  }

  function initialize() {
    const secure = window.isSecureContext || demoMode;
    setDot("secure", secure ? "ok" : "error", secure ? (demoMode ? "Modo de demonstração" : "HTTPS ativo") : "HTTPS obrigatório");
    if (!secure) setMessage("O Safari só libera movimento em uma página HTTPS.", "error");
    if (window.top !== window.self) setMessage("Abra esta página diretamente no Safari, fora de iframe.", "error");
    if (token) connect();
    else {
      setDot("socket", "error", "Token de pareamento ausente");
      setMessage("Use a URL completa mostrada pelo servidor. Ela contém um token temporário.", "error");
    }
    updateControls();
    window.setInterval(flush, 120);
  }

  prepararModelo3d();
  const campoNomeInicial = document.getElementById("nome-input");
  if (campoNomeInicial) {
    // O aluno costuma digitar o nome depois que a página já se apresentou ao
    // relay. Sem reapresentar, o painel da turma ficaria preso em "Participante
    // 31" até a próxima reconexão.
    const reapresentar = () => {
      if (!state.connected) return;
      const nome = nomeAtual();
      if (!nome) return;   // sem nome digitado, o servidor mantém o padrão dele
      lembrarNome(nome);
      send(saudacao());
    };
    campoNomeInicial.addEventListener("change", reapresentar);
    campoNomeInicial.addEventListener("blur", reapresentar);
  }


  elements["permission-button"].addEventListener("click", requestPermissions);
  elements["stop-button"].addEventListener("click", () => stopRecording("manual"));
  elements["export-button"].addEventListener("click", exportCsv);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && state.recording) return stopRecording("page-hidden");
    // o sistema solta a trava sozinho ao voltar do segundo plano
    if (!document.hidden && state.recording) segurarTela();
  });
  /* Sair tem que devolver o número na hora.

     Sem fechar o socket, um simples recarregar deixava a conexão antiga presa
     até a varredura de silêncio (45 s): nesse intervalo a mesma pessoa
     aparecia duas vezes na turma — a nova com o nome e a velha como
     "Participante N" — e ainda queimava um número. Fechando aqui, o relay
     libera o lugar imediatamente e o aluno volta com o mesmo número. */
  window.addEventListener("pagehide", () => {
    flush();
    if (state.recording) stopRecording("page-hidden");
    pararCoracao();
    if (state.websocket) {
      try { state.websocket.close(1000, "página saiu"); } catch (erro) { /* já fechado */ }
    }
  });

  marcarConexao();
  initialize();
})();
