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

  // etapa 2 → 3: sensores confirmados (mobile.js marca sensor-dot como "ok"
  // quando aceleração e rotação estão realmente chegando, não só permitidas)
  const pontoSensor = document.getElementById("sensor-dot");
  if (pontoSensor) {
    const observadorSensor = new MutationObserver(() => {
      if (atual === 2 && pontoSensor.dataset.state === "ok") mostrar(3);
    });
    observadorSensor.observe(pontoSensor, { attributes: true, attributeFilter: ["data-state"] });
  }


})();
