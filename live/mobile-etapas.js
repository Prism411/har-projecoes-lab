/* Navegação em etapas da página /mobile.

   Este script não conhece o estado interno de mobile.js — ele só observa o
   que mobile.js já escreve no DOM (data-state dos pontos de status, o
   atributo disabled do botão de gravar) e mostra uma seção .stage por vez.
   Se mobile.js mudar de forma, este arquivo continua funcionando: o pior
   caso é a navegação automática não avançar, nunca um erro de JS. */
(() => {
  "use strict";

  const PASSOS = [1, 2, 3];
  const secoes = Object.fromEntries(
    PASSOS.map(passo => [passo, document.querySelector(`.stage[data-passo="${passo}"]`)])
  );
  const marcos = Array.from(document.querySelectorAll("#lista-passos li"));
  let atual = 1;

  function mostrar(passo) {
    if (passo === atual || !secoes[passo]) return;
    atual = passo;
    PASSOS.forEach(p => {
      if (secoes[p]) secoes[p].hidden = p !== passo;
    });
    marcos.forEach(li => {
      const p = Number(li.dataset.passo);
      li.classList.toggle("passo-atual", p === passo);
      li.classList.toggle("passo-feito", p < passo);
    });
    const titulo = secoes[passo].querySelector("h2");
    if (titulo) titulo.focus();
  }

  // etapa 1 → 2: só quando o aluno digitou um nome
  const botaoContinuar = document.getElementById("passo1-continuar");
  const campoNome = document.getElementById("nome-input");
  if (botaoContinuar && campoNome) {
    botaoContinuar.addEventListener("click", () => {
      if (!campoNome.value.trim()) {
        campoNome.focus();
        return;
      }
      mostrar(2);
    });
  }

  /* etapa 2 → 3: sensores confirmados E conectado à sala.

     Sensor entregando não basta. Sem o relay do outro lado, o aluno chegava a
     uma tela dizendo "Pronto — aguarde o professor" e esperava por uma partida
     que nunca chegaria: a sala inteira parecia certa e nada era gravado.
     Conexão é condição para dizer que ele está pronto. */
  const pontoSensor = document.getElementById("sensor-dot");
  const conectado = () => document.body.dataset.conectado === "1";
  const sensorOk = () => pontoSensor && pontoSensor.dataset.state === "ok";

  function talvezAvancar() {
    if (atual === 2 && sensorOk() && conectado()) mostrar(3);
  }

  if (pontoSensor) {
    new MutationObserver(talvezAvancar)
      .observe(pontoSensor, { attributes: true, attributeFilter: ["data-state"] });
  }
  new MutationObserver(talvezAvancar)
    .observe(document.body, { attributes: true, attributeFilter: ["data-conectado"] });


})();
