import { fork, regenerate } from "./send.js";

/* ─────────────────────────────── Ações do turno ─────────────────────────── */

const ICONS = {
  regenerate:
    '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>',
  fork:
    '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="8" r="2.5"/>' +
    '<path d="M6 8.5v7M18 10.5c0 4-4 5-9.5 6"/></svg>',
};

const STATE_FLAGS = {
  interrupted: "Resposta interrompida",
  failed: "Resposta com erro",
};

function actionButton(icon, label, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "action-button";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.innerHTML = ICONS[icon];
  button.addEventListener("click", onClick);
  return button;
}

// Regerar e bifurcar, embaixo de cada resposta. `messageId` é a última
// mensagem do turno: a partir dela o fork continua, e dela o servidor sobe até
// a pergunta que será respondida de novo.
export function addTurnActions(body, messageId, state, thinkingMs = 0) {
  const turn = body.closest(".turn");
  turn.dataset.messageId = messageId;

  const bar = document.createElement("div");
  bar.className = "turn-actions";

  if (STATE_FLAGS[state]) {
    turn.classList.add("is-interrupted");
    const flag = document.createElement("span");
    flag.className = "turn-flag";
    flag.textContent = STATE_FLAGS[state];
    bar.append(flag);
  }

  bar.append(
    actionButton("regenerate", "Regerar resposta", () => regenerate(turn)),
    actionButton("fork", "Bifurcar conversa a partir daqui", () => fork(turn)),
  );
  if (thinkingMs >= 1000) {
    const thought = document.createElement("span");
    thought.className = "turn-thought";
    thought.textContent = `pensou por ${duration(thinkingMs)}`;
    thought.title = "Tempo em que o modelo raciocinou antes de responder e de chamar as ferramentas";
    bar.append(thought);
  }
  turn.append(bar);
}

// "12 s", "1 min 05 s": quanto o modelo pensou.
function duration(milliseconds) {
  const seconds = Math.max(1, Math.round(milliseconds / 1000));
  if (seconds < 60) return `${seconds} s`;
  return `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, "0")} s`;
}

// Enquanto o modelo pensa antes de responder ou de chamar uma ferramenta, a
// tela não fica parada: uma linha diz que ele está pensando, e há quanto tempo.
export function thinkingNote(startedAt) {
  const note = document.createElement("div");
  note.className = "tool-note is-working thinking-note";
  const text = document.createElement("span");
  const dot = document.createElement("span");
  dot.className = "dot";
  note.append(text, dot);

  const tick = () => {
    const elapsed = Date.now() - startedAt;
    text.textContent = elapsed >= 1000 ? `pensando · ${duration(elapsed)}` : "pensando";
  };
  tick();
  const timer = setInterval(tick, 1000);
  return {
    el: note,
    stop() {
      clearInterval(timer);
      note.remove();
    },
  };
}

export function forkNote() {
  const note = document.createElement("div");
  note.className = "fork-note";
  note.textContent = "bifurcação · a conversa continua daqui";
  return note;
}
