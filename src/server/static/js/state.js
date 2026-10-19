// O estado que os módulos dividem: os elementos fixos da página, a identidade
// da conversa aberta e a sessão. Não importa nada, para ser avaliado primeiro.

export const app = document.getElementById("app");
export const thread = document.getElementById("thread");
export const hero = document.getElementById("hero");
export const composer = document.getElementById("composer");
export const input = document.getElementById("input");
export const sendButton = document.getElementById("send");
export const newChatButton = document.getElementById("new-chat");
export const topbarMark = document.getElementById("topbar-mark");

/* ─────────────────────────────── Identidade da conversa ─────────────────── */

// O id da conversa nasce aqui, na primeira pergunta (o AG-UI espera do
// cliente), e o servidor a cria com ele; o navegador o guarda para reabri-la.
const THREAD_KEY = "graham.thread_id";

export function storeThreadId(id) {
  try {
    if (id) localStorage.setItem(THREAD_KEY, id);
    else localStorage.removeItem(THREAD_KEY);
  } catch {
    // Navegação privativa ou storage bloqueado: a conversa vive só nesta aba.
  }
}

function savedThreadId() {
  try {
    return localStorage.getItem(THREAD_KEY);
  } catch {
    return null;
  }
}

// O que muda ao longo da sessão e mais de um módulo lê e escreve. Fica num
// objeto porque um módulo não pode reatribuir uma variável que importou.
export const session = {
  // Há uma resposta sendo transmitida: o envio fica bloqueado.
  streaming: false,
  // A leitura de stream em curso nesta tela, e um contador que muda a cada
  // troca de conversa: o que chegar de uma conversa que já saiu da tela é
  // descartado.
  currentReading: null,
  currentView: 0,
  // A conversa aberta; nula numa conversa nova, até a primeira pergunta.
  threadId: savedThreadId(),
};
