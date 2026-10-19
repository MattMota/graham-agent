// Graham — cliente da interface: conversa com o agente pelo AG-UI e desenha
// os eventos que chegam do servidor. Este módulo liga o envio e abre a sessão;
// cada parte da tela está no seu módulo.

import { composer, input, session } from "./state.js";
import { setStreaming } from "./screen.js";
import { signedIn, signedOut } from "./account.js";
import { openThread } from "./history.js";
import { ask } from "./send.js";
// Só liga os eventos da janela de chaves: ninguém usa o que ela teria a exportar.
import "./keys.js";

/* ────────────────────────────────── Interação ───────────────────────────── */

function submit() {
  const question = input.value.trim();
  if (!question || session.streaming) return;
  input.value = "";
  resize();
  ask(question);
}

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  submit();
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submit();
  }
});

export function resize() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
}

input.addEventListener("input", resize);

for (const button of document.querySelectorAll(".suggestion")) {
  button.addEventListener("click", () => {
    input.value = button.textContent.trim();
    submit();
  });
}

// A tela só aparece depois de conferida a sessão: com ela, a conversa; sem
// ela, a entrada. Até lá, o envio fica bloqueado.
async function boot() {
  setStreaming(true);
  try {
    const response = await fetch("/api/auth/me");
    if (!response.ok) {
      signedOut();
      return;
    }
    signedIn((await response.json()).email);
    if (session.threadId) await openThread(session.threadId);
  } catch {
    // Sem servidor, fica a entrada; o erro aparece ao tentar entrar.
    signedOut();
  } finally {
    setStreaming(false);
    input.focus();
  }
}

boot();
