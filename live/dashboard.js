(() => {
  "use strict";

  const query = new URLSearchParams(window.location.search);
  const session = (query.get("session") || "P31").replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 24) || "P31";
  const token = query.get("token") || "";
  const elements = Object.fromEntries([
    "live-dot", "live-label", "session-label", "rate-value", "batch-value", "latency-value",
    "recording-value", "phone-model", "alpha-value", "beta-value", "gamma-value",
    "acceleration-chart", "rotation-chart", "window-fill", "window-label", "dashboard-message",
    "mapa-canvas", "mapa-vizinhanca", "mapa-legenda", "mapa-situacao-rotulo", "mapa-situacao-detalhe"
  ].map(id => [id, document.getElementById(id)]));

  // paleta okabe-ito: legivel tambem pras formas comuns de daltonismo
  const CORES_ATIVIDADE = {
    WALKING: "#0072B2",
    WALKING_UPSTAIRS: "#009E73",
    WALKING_DOWNSTAIRS: "#56B4E9",
    SITTING: "#E69F00",
    STANDING: "#D55E00",
    LAYING: "#CC79A7"
  };

  const NOMES_ATIVIDADE = {
    WALKING: "Andando",
    WALKING_UPSTAIRS: "Subindo escada",
    WALKING_DOWNSTAIRS: "Descendo escada",
    SITTING: "Sentado",
    STANDING: "Em pé",
    LAYING: "Deitado"
  };

  const state = {
    websocket: null,
    mobileConnections: 0,
    samples: [],
    recordingSamples: 0,
    recordingFirstSampleAt: 0,
    recording: false,
    activity: "",
    mobileConnectedAt: 0,
    lastSampleAt: 0,
    mapa: { referencia: null, projecao: null, limites: null }
  };

  function websocketUrl() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/ws/dashboard?session=${encodeURIComponent(session)}&token=${encodeURIComponent(token)}`;
  }

  function setMessage(text, tone = "") {
    elements["dashboard-message"].textContent = text;
    if (tone) elements["dashboard-message"].dataset.tone = tone;
    else delete elements["dashboard-message"].dataset.tone;
  }

  function formatNumber(value, digits = 1) {
    return Number.isFinite(value) ? value.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";
  }

  function formatAngle(value) {
    return Number.isFinite(value) ? `${formatNumber(value, 1)}°` : "—";
  }

  function updateConnection() {
    const connected = state.mobileConnections > 0;
    elements["live-dot"].dataset.state = connected ? "ok" : "warn";
    elements["live-label"].textContent = connected ? "iPhone conectado" : "Aguardando iPhone";
    elements["session-label"].textContent = `sessão ${session}`;
  }

  function connect() {
    if (!token) {
      elements["live-dot"].dataset.state = "error";
      elements["live-label"].textContent = "Token ausente";
      setMessage("Abra a URL completa fornecida pelo servidor, incluindo o token temporário.", "error");
      return;
    }
    const websocket = new WebSocket(websocketUrl());
    state.websocket = websocket;
    websocket.addEventListener("open", () => setMessage("Monitor conectado ao retransmissor. Agora abra a captura no iPhone."));
    websocket.addEventListener("message", event => {
      try {
        handleMessage(JSON.parse(event.data));
      } catch (error) {
        setMessage(`Mensagem inválida: ${error instanceof Error ? error.message : "erro desconhecido"}`, "error");
      }
    });
    websocket.addEventListener("close", event => {
      state.mobileConnections = 0;
      updateConnection();
      if (event.code === 1008) {
        elements["live-dot"].dataset.state = "error";
        elements["live-label"].textContent = "Pareamento recusado";
        setMessage("Token inválido ou protocolo rejeitado pelo servidor.", "error");
        return;
      }
      setMessage("Conexão com o retransmissor perdida. Tentando novamente…", "error");
      window.setTimeout(connect, 1500);
    });
    websocket.addEventListener("error", () => websocket.close());
  }

  function handleMessage(message) {
    if (message.type === "relay-status") {
      const previousConnections = state.mobileConnections;
      state.mobileConnections = Number(message.mobile_connections) || 0;
      if (!previousConnections && state.mobileConnections) state.mobileConnectedAt = Date.now();
      if (!state.mobileConnections) {
        state.mobileConnectedAt = 0;
        state.lastSampleAt = 0;
      }
      updateConnection();
      return;
    }
    if (message.type === "hello") {
      setMessage("iPhone identificado. Ative os sensores e faça a calibração.", "success");
      return;
    }
    if (message.type === "projection") {
      mostrarProjecao(message);
      setMessage("Gravação projetada no mapa HAR live.", "success");
      return;
    }
    if (message.type === "projection-status") {
      mostrarEstadoDaProjecao(message);
      return;
    }
    if (message.type === "status") {
      const statusLabels = {
        "sensors-granted": "Sensores autorizados no iPhone.",
        "calibrating": "Calibração parada em andamento…",
        "calibrated": `Calibração concluída com ${message.sample_count || 0} leituras.`
      };
      const calibrationValid = message.status === "calibrated"
        && message.still === true
        && Number(message.valid_ratio) >= 0.9;
      if (message.status === "calibrated") {
        const validPercent = formatNumber(Number(message.valid_ratio) * 100, 0);
        const linearPercent = formatNumber(Number(message.linear_ratio) * 100, 0);
        const label = calibrationValid ? "Calibração válida" : "Calibração recusada";
        setMessage(`${label}: ${message.sample_count || 0} leituras, ${validPercent}% utilizáveis, ${linearPercent}% com aceleração linear nativa.`, calibrationValid ? "success" : "error");
      } else {
        setMessage(statusLabels[message.status] || `Estado recebido: ${message.status || "—"}`);
      }
      return;
    }
    if (message.type === "recording") {
      state.recording = message.status === "started";
      state.recordingSamples = 0;
      state.recordingFirstSampleAt = 0;
      state.activity = message.activity || "";
      elements["recording-value"].textContent = state.recording ? `gravando · ${state.activity}` : "inativa";
      return;
    }
    if (message.type === "summary") {
      state.recording = false;
      elements["recording-value"].textContent = `concluída · ${message.sample_count || 0} leituras`;
      const validPercent = Number.isFinite(message.valid_ratio) ? `${formatNumber(message.valid_ratio * 100, 0)}% utilizáveis` : "qualidade não informada";
      const linearPercent = Number.isFinite(message.linear_ratio) ? `${formatNumber(message.linear_ratio * 100, 0)}% com aceleração linear nativa` : "origem da aceleração não informada";
      setMessage(`Gravação recebida: ${message.activity || "atividade"}, ${message.sample_count || 0} leituras, ${formatNumber(message.observed_hz)} Hz, ${validPercent}, ${linearPercent}.`, message.valid_ratio >= 0.9 ? "success" : "error");
      return;
    }
    if (message.type === "error") {
      setMessage(message.message || "Erro informado pelo iPhone.", "error");
      return;
    }
    if (message.type === "samples") receiveSamples(message);
  }

  function receiveSamples(message) {
    const samples = Array.isArray(message.samples) ? message.samples : [];
    state.lastSampleAt = Date.now();
    elements["batch-value"].textContent = `${samples.length} amostras`;
    if (Number.isFinite(message.server_received_at)) elements["latency-value"].textContent = `${Math.max(0, Date.now() - message.server_received_at)} ms`;
    if (message.recording) {
      state.recording = true;
      state.recordingSamples += samples.length;
      if (!state.recordingFirstSampleAt && samples.length) state.recordingFirstSampleAt = samples[0].t;
      state.activity = message.activity || state.activity;
      elements["recording-value"].textContent = `gravando · ${state.activity}`;
    }
    state.samples.push(...samples);
    const newest = state.samples.length ? state.samples[state.samples.length - 1].t : 0;
    state.samples = state.samples.filter(sample => newest - sample.t <= 5000).slice(-400);
    updateRate();
    updatePhone(samples[samples.length - 1]);
    updateWindowProgress();
    drawAll();
    window.dispatchEvent(new CustomEvent("har-live-samples", { detail: message }));
  }

  function updateRate() {
    if (state.samples.length < 2) {
      elements["rate-value"].textContent = "0,0 Hz";
      return;
    }
    const duration = (state.samples[state.samples.length - 1].t - state.samples[0].t) / 1000;
    const rate = duration > 0 ? (state.samples.length - 1) / duration : 0;
    elements["rate-value"].textContent = `${formatNumber(rate)} Hz`;
  }

  function updatePhone(sample) {
    if (!sample || !Array.isArray(sample.orientation_deg)) return;
    const [alpha, beta, gamma] = sample.orientation_deg;
    elements["alpha-value"].textContent = formatAngle(alpha);
    elements["beta-value"].textContent = formatAngle(beta);
    elements["gamma-value"].textContent = formatAngle(gamma);
    const a = Number.isFinite(alpha) ? alpha : 0;
    const b = Number.isFinite(beta) ? beta : 0;
    const g = Number.isFinite(gamma) ? gamma : 0;
    elements["phone-model"].style.transform = `rotateZ(${a}deg) rotateX(${b}deg) rotateY(${-g}deg)`;
  }

  function updateWindowProgress() {
    const latest = state.samples.length ? state.samples[state.samples.length - 1].t : 0;
    const elapsed = state.recordingFirstSampleAt && latest >= state.recordingFirstSampleAt
      ? latest - state.recordingFirstSampleAt
      : 0;
    const progress = Math.min(1, elapsed / 2560);
    elements["window-fill"].style.width = `${progress * 100}%`;
    elements["window-label"].textContent = progress >= 1
      ? "2,56 s completos"
      : `${formatNumber(elapsed / 1000, 2)} / 2,56 s`;
  }

  function chartVector(sample, property) {
    if (property !== "acceleration") return sample[property];
    const linear = sample.acceleration;
    if (Array.isArray(linear) && linear.every(Number.isFinite)) return linear;
    return sample.acceleration_gravity;
  }

  function drawChart(canvas, property) {
    const context = canvas.getContext("2d");
    const ratio = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(rect.width * ratio));
    const height = Math.max(1, Math.round(rect.height * ratio));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, width, height);
    context.strokeStyle = "#e5e5e0";
    context.lineWidth = 1 * ratio;
    for (let line = 1; line < 4; line += 1) {
      const y = height * line / 4;
      context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke();
    }
    if (state.samples.length < 2) return;
    const values = state.samples.flatMap(sample => {
      const vector = chartVector(sample, property);
      return Array.isArray(vector) ? vector.filter(Number.isFinite) : [];
    });
    const maxAbs = Math.max(1, ...values.map(value => Math.abs(value))) * 1.12;
    const t0 = state.samples[0].t;
    const t1 = state.samples[state.samples.length - 1].t;
    const colors = ["#005987", "#a34a00", "#007a59"];
    colors.forEach((color, axis) => {
      context.beginPath();
      context.strokeStyle = color;
      context.lineWidth = 1.6 * ratio;
      let started = false;
      state.samples.forEach(sample => {
        const vector = chartVector(sample, property);
        const value = Array.isArray(vector) ? vector[axis] : null;
        if (!Number.isFinite(value)) return;
        const x = t1 === t0 ? 0 : (sample.t - t0) / (t1 - t0) * width;
        const y = height / 2 - value / maxAbs * height * 0.42;
        if (!started) { context.moveTo(x, y); started = true; }
        else context.lineTo(x, y);
      });
      context.stroke();
    });
  }

  function drawAll() {
    drawChart(elements["acceleration-chart"], "acceleration");
    drawChart(elements["rotation-chart"], "rotation_deg_s");
  }

  window.addEventListener("resize", drawAll);
  updateConnection();
  if (token) connect();
  else {
    elements["live-dot"].dataset.state = "error";
    elements["live-label"].textContent = "Token ausente";
    setMessage("Use a URL completa exibida pelo servidor, com o token temporário.", "error");
  }
  // ------------------------------------------------ har live: mapa de projecao

  function limitesDe(coordenadas) {
    let minimoX = Infinity, maximoX = -Infinity, minimoY = Infinity, maximoY = -Infinity;
    for (const [x, y] of coordenadas) {
      if (x < minimoX) minimoX = x;
      if (x > maximoX) maximoX = x;
      if (y < minimoY) minimoY = y;
      if (y > maximoY) maximoY = y;
    }
    const margemX = (maximoX - minimoX) * 0.04 || 1;
    const margemY = (maximoY - minimoY) * 0.04 || 1;
    return {
      minimoX: minimoX - margemX, maximoX: maximoX + margemX,
      minimoY: minimoY - margemY, maximoY: maximoY + margemY
    };
  }

  function projetarNaTela(x, y, limites, largura, altura) {
    const proporcaoX = (x - limites.minimoX) / (limites.maximoX - limites.minimoX);
    const proporcaoY = (y - limites.minimoY) / (limites.maximoY - limites.minimoY);
    return [proporcaoX * largura, altura - proporcaoY * altura];
  }

  function desenharMapa() {
    const canvas = elements["mapa-canvas"];
    if (!canvas || !state.mapa.referencia) return;
    const contexto = canvas.getContext("2d");
    const { width: largura, height: altura } = canvas;
    const escuro = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;

    contexto.clearRect(0, 0, largura, altura);
    contexto.fillStyle = escuro ? "#16181c" : "#fbfbfc";
    contexto.fillRect(0, 0, largura, altura);

    const { coordenadas, atividades } = state.mapa.referencia;
    const limites = state.mapa.limites;

    // fundo: as 10.299 janelas do experimento original
    contexto.globalAlpha = escuro ? 0.5 : 0.42;
    for (let indice = 0; indice < coordenadas.length; indice += 1) {
      const [x, y] = projetarNaTela(coordenadas[indice][0], coordenadas[indice][1], limites, largura, altura);
      contexto.fillStyle = CORES_ATIVIDADE[atividades[indice]] || "#9aa0a6";
      contexto.fillRect(x, y, 2.2, 2.2);
    }
    contexto.globalAlpha = 1;

    const projecao = state.mapa.projecao;
    if (!projecao) return;

    const pontos = projecao.coordenadas.map(([x, y]) =>
      projetarNaTela(x, y, limites, largura, altura));

    // trilha temporal entre as janelas da gravacao
    if (pontos.length > 1) {
      contexto.strokeStyle = escuro ? "rgba(255,255,255,.75)" : "rgba(17,17,17,.7)";
      contexto.lineWidth = 2;
      contexto.setLineDash([5, 4]);
      contexto.beginPath();
      pontos.forEach(([x, y], indice) => indice ? contexto.lineTo(x, y) : contexto.moveTo(x, y));
      contexto.stroke();
      contexto.setLineDash([]);
    }

    // cada janela sua, com halo para destacar do fundo
    pontos.forEach(([x, y], indice) => {
      const ultimo = indice === pontos.length - 1;
      const raio = ultimo ? 9 : 6;
      contexto.beginPath();
      contexto.arc(x, y, raio + 3, 0, Math.PI * 2);
      contexto.fillStyle = escuro ? "rgba(22,24,28,.9)" : "rgba(255,255,255,.9)";
      contexto.fill();
      contexto.beginPath();
      contexto.arc(x, y, raio, 0, Math.PI * 2);
      contexto.fillStyle = CORES_ATIVIDADE[projecao.atividade] || "#111";
      contexto.fill();
      contexto.lineWidth = 2.5;
      contexto.strokeStyle = escuro ? "#f1f3f4" : "#111";
      contexto.stroke();
    });

    // rotulo VOCE na ultima janela
    const [ultimoX, ultimoY] = pontos[pontos.length - 1];
    contexto.font = "600 15px system-ui, sans-serif";
    contexto.textAlign = "center";
    const texto = "VOCÊ";
    const largTexto = contexto.measureText(texto).width;
    contexto.fillStyle = escuro ? "rgba(22,24,28,.92)" : "rgba(255,255,255,.92)";
    contexto.fillRect(ultimoX - largTexto / 2 - 6, ultimoY - 36, largTexto + 12, 21);
    contexto.fillStyle = escuro ? "#f1f3f4" : "#111";
    contexto.fillText(texto, ultimoX, ultimoY - 21);
  }

  function montarLegenda() {
    const lista = elements["mapa-legenda"];
    if (!lista) return;
    lista.innerHTML = "";
    Object.entries(CORES_ATIVIDADE).forEach(([chave, cor]) => {
      const item = document.createElement("li");
      const marca = document.createElement("span");
      marca.className = "marca";
      marca.style.background = cor;
      item.append(marca, document.createTextNode(NOMES_ATIVIDADE[chave] || chave));
      lista.appendChild(item);
    });
    const item = document.createElement("li");
    const marca = document.createElement("span");
    marca.className = "marca voce";
    item.append(marca, document.createTextNode("Sua gravação"));
    lista.appendChild(item);
  }

  function situacaoDaGravacao(situacoes) {
    if (situacoes.includes("fora")) return "fora";
    if (situacoes.includes("limítrofe")) return "limítrofe";
    return "dentro";
  }

  const EXPLICACAO_SITUACAO = {
    dentro: "Suas janelas caem na mesma região ocupada pelo experimento original.",
    "limítrofe": "Parte das janelas está na borda da distribuição do HAR.",
    fora: "Suas janelas caem fora da distribuição: mudança de domínio, não erro de atividade."
  };

  function mostrarProjecao(mensagem) {
    state.mapa.projecao = mensagem;
    const situacao = situacaoDaGravacao(mensagem.situacoes || []);
    elements["mapa-situacao-rotulo"].dataset.state = situacao;
    elements["mapa-situacao-rotulo"].textContent = situacao;
    const captura = mensagem.captura || {};
    elements["mapa-situacao-detalhe"].textContent =
      `${mensagem.janelas} janela(s) · ${captura.duracao_s || "?"} s a ${captura.taxa_observada_hz || "?"} Hz. ` +
      (EXPLICACAO_SITUACAO[situacao] || "");

    const lista = elements["mapa-vizinhanca"];
    lista.innerHTML = "";
    const vizinhanca = mensagem.vizinhanca || [];
    if (!vizinhanca.length) {
      lista.innerHTML = '<li class="vazio">—</li>';
    } else {
      vizinhanca.forEach(entrada => {
        const item = document.createElement("li");
        const nome = document.createElement("span");
        nome.textContent = NOMES_ATIVIDADE[entrada.atividade] || entrada.atividade;
        const valor = document.createElement("span");
        valor.className = "proporcao";
        valor.textContent = `${Math.round(entrada.proporcao * 100)}%`;
        item.append(nome, valor);
        lista.appendChild(item);
      });
    }
    desenharMapa();
  }

  function mostrarEstadoDaProjecao(mensagem) {
    const rotulo = elements["mapa-situacao-rotulo"];
    const detalhe = elements["mapa-situacao-detalhe"];
    if (mensagem.status === "calculando") {
      rotulo.dataset.state = "calculando";
      rotulo.textContent = "calculando";
      detalhe.textContent = "Projetando suas janelas no espaço do HAR…";
      return;
    }
    rotulo.dataset.state = mensagem.status === "indisponivel" ? "vazio" : "falhou";
    rotulo.textContent = mensagem.status === "indisponivel" ? "indisponível" : "falhou";
    detalhe.textContent = mensagem.message || "Não foi possível projetar esta gravação.";
  }

  async function carregarReferencia() {
    try {
      const resposta = await fetch(
        "/api/har-live/referencia?token=" + encodeURIComponent(token),
        { cache: "no-store" }
      );
      if (!resposta.ok) throw new Error("espaço não construído");
      const dados = await resposta.json();
      state.mapa.referencia = dados;
      state.mapa.limites = limitesDe(dados.coordenadas);
      desenharMapa();
    } catch (erro) {
      elements["mapa-situacao-detalhe"].textContent =
        "Espaço HAR live ainda não construído neste computador (rode src/build_live_space.py).";
    }
  }

  montarLegenda();
  carregarReferencia();
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", desenharMapa);
  }

  drawAll();
  window.setInterval(() => {
    const lastActivityAt = state.lastSampleAt || state.mobileConnectedAt;
    if (state.mobileConnections && lastActivityAt && Date.now() - lastActivityAt > 3000) {
      elements["live-dot"].dataset.state = "warn";
      elements["live-label"].textContent = "iPhone conectado, sem dados recentes";
    }
  }, 1000);
})();
