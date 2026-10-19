import {
  app, hero, input, newChatButton, sendButton, session, storeThreadId, thread, topbarMark,
} from "./state.js";
import { closeSidebar, markCurrentThread } from "./sidebar.js";
import { resize } from "./main.js";

export function leaveView() {
  session.currentView++;
  session.currentReading?.abort();
  session.currentReading = null;
  setStreaming(false);
}

/* ──────────────────────────────── Estado da tela ────────────────────────── */

export function showConversation() {
  app.classList.remove("is-empty");
  hero.hidden = true;
  topbarMark.hidden = false;
}

export function clearConversation() {
  for (const node of thread.querySelectorAll(".turn, .fork-note")) node.remove();
}

export function showEmpty() {
  clearConversation();
  app.classList.add("is-empty");
  hero.hidden = false;
  topbarMark.hidden = true;
}

export function setStreaming(value) {
  session.streaming = value;
  sendButton.disabled = value;
  app.classList.toggle("is-streaming", value);
}

export function startNewConversation() {
  // Uma resposta em andamento segue no servidor; ela volta ao reabrir a conversa.
  leaveView();
  closeSidebar();

  session.threadId = null;
  storeThreadId(null);

  showEmpty();
  input.value = "";
  resize();
  input.focus();
  window.scrollTo({ top: 0, behavior: "smooth" });
  markCurrentThread();
}

newChatButton.addEventListener("click", startNewConversation);
