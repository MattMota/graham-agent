import { session } from "./state.js";
import { leaveView, startNewConversation } from "./screen.js";
import { openThread } from "./history.js";

/* ──────────────────────────────── Aba de conversas ──────────────────────── */

const sidebarToggle = document.getElementById("sidebar-toggle");
const sidebarBackdrop = document.getElementById("sidebar-backdrop");
const threadList = document.getElementById("thread-list");
const threadListEmpty = document.getElementById("thread-list-empty");
const threadSearch = document.getElementById("thread-search");

// Enquanto alguma conversa responde, a lista se atualiza sozinha para o
// indicador apagar quando a resposta acabar, mesmo com a conversa fora da tela.
const THREAD_LIST_POLL_MS = 4000;
let threadListTimer = null;
// Cada atualização ganha um número; uma resposta que chega depois de outra mais
// nova (a busca digitada rápido) é descartada.
let threadListRequest = 0;

const SEARCH_DEBOUNCE_MS = 200;
let searchTimer = null;

const STATUS_LABELS = {
  streaming: "respondendo",
  awaiting_approval: "aguardando confirmação",
};

const RELATIVE_TIME = new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" });
export const SHORT_DATE = new Intl.DateTimeFormat("pt-BR", { day: "numeric", month: "short" });

export function relativeTime(iso) {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "agora";
  if (seconds < 3600) return RELATIVE_TIME.format(-Math.floor(seconds / 60), "minute");
  if (seconds < 86400) return RELATIVE_TIME.format(-Math.floor(seconds / 3600), "hour");
  if (seconds < 7 * 86400) return RELATIVE_TIME.format(-Math.floor(seconds / 86400), "day");
  return SHORT_DATE.format(new Date(iso));
}

function threadItem(item) {
  const li = document.createElement("li");
  li.className = "thread-row";
  li.dataset.id = item.id;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "thread-item";
  button.dataset.id = item.id;

  const title = document.createElement("span");
  title.className = "thread-item-title";
  title.textContent = item.title || "Conversa sem título";
  button.title = title.textContent;
  button.append(title);

  // Na busca, o trecho da mensagem que contém o texto, com ele destacado.
  if (item.snippet) {
    const snippet = document.createElement("span");
    snippet.className = "thread-item-snippet";
    const mark = document.createElement("mark");
    mark.textContent = item.snippet.match;
    snippet.append(item.snippet.before, mark, item.snippet.after);
    button.append(snippet);
  }

  const meta = document.createElement("span");
  meta.className = "thread-item-meta";
  meta.textContent = `${item.is_fork ? "bifurcação · " : ""}${relativeTime(item.updated_at)}`;
  if (item.status) {
    const status = document.createElement("span");
    status.className = `thread-item-status is-${item.status.replace(/_/g, "-")}`;
    status.textContent = STATUS_LABELS[item.status];
    meta.append(status);
  }
  button.append(meta);
  button.addEventListener("click", () => switchThread(item.id));

  const more = document.createElement("button");
  more.type = "button";
  more.className = "thread-more";
  more.setAttribute("aria-label", "Opções da conversa");
  more.setAttribute("aria-haspopup", "menu");
  more.innerHTML =
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">' +
    '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>';
  more.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleThreadMenu(li, item);
  });

  li.append(button, more);
  return li;
}

/* Menu de cada conversa: renomear e apagar. Enquanto ele ou a edição do título
   estão abertos, a lista não é redesenhada por baixo. */

function threadListBusy() {
  return Boolean(threadList.querySelector(".thread-menu, .thread-rename"));
}

function closeThreadMenu() {
  for (const menu of threadList.querySelectorAll(".thread-menu")) menu.remove();
  for (const row of threadList.querySelectorAll(".thread-row.has-menu")) row.classList.remove("has-menu");
}

function menuButton(label, onClick, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `thread-menu-item ${className}`.trim();
  button.setAttribute("role", "menuitem");
  button.textContent = label;
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick();
  });
  return button;
}

function toggleThreadMenu(row, item) {
  const open = row.querySelector(".thread-menu");
  closeThreadMenu();
  if (open) return;

  const menu = document.createElement("div");
  menu.className = "thread-menu";
  menu.setAttribute("role", "menu");
  menu.addEventListener("click", (event) => event.stopPropagation());

  const showActions = () => {
    menu.replaceChildren(
      menuButton("Renomear", () => startRename(row, item)),
      menuButton("Apagar", showConfirm, "is-danger"),
    );
    menu.firstElementChild.focus();
  };

  const showConfirm = () => {
    const question = document.createElement("p");
    question.className = "thread-menu-note";
    question.textContent = "Apagar esta conversa? Ela sai da lista e da memória do agente.";
    const confirm = menuButton("Apagar", () => removeThread(item, menu), "is-danger is-strong");
    menu.replaceChildren(question, confirm, menuButton("Cancelar", showActions));
    confirm.focus();
  };

  row.classList.add("has-menu");
  row.append(menu);
  showActions();
}

async function removeThread(item, menu) {
  let response = null;
  try {
    response = await fetch(`/api/threads/${item.id}`, { method: "DELETE" });
  } catch {
    /* sem servidor: cai no aviso abaixo */
  }
  if (!response?.ok) {
    let detail = "Não foi possível apagar a conversa.";
    try {
      detail = (await response.json()).detail || detail;
    } catch {
      /* sem corpo legível */
    }
    const note = document.createElement("p");
    note.className = "thread-menu-note is-error";
    note.textContent = detail;
    menu.replaceChildren(note, menuButton("Fechar", closeThreadMenu));
    return;
  }
  closeThreadMenu();
  if (item.id === session.threadId) startNewConversation();
  refreshThreadList();
}

function startRename(row, item) {
  closeThreadMenu();
  const form = document.createElement("form");
  form.className = "thread-rename";
  const field = document.createElement("input");
  field.type = "text";
  field.maxLength = 80;
  field.value = item.title || "";
  field.setAttribute("aria-label", "Título da conversa");
  form.append(field);

  row.querySelector(".thread-item").hidden = true;
  row.prepend(form);
  field.focus();
  field.select();

  let settled = false;
  const finish = async (save) => {
    if (settled) return;
    settled = true;
    const title = field.value.trim();
    if (save && title && title !== item.title) {
      try {
        const response = await fetch(`/api/threads/${item.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title }),
        });
        if (response.ok) item.title = (await response.json()).title;
      } catch {
        /* o título antigo continua */
      }
    }
    const fresh = threadItem(item);
    row.replaceWith(fresh);
    markCurrentThread();
    fresh.querySelector(".thread-item").focus();
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    finish(true);
  });
  field.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      finish(false);
    }
  });
  field.addEventListener("blur", () => finish(true));
}

document.addEventListener("click", closeThreadMenu);

export function markCurrentThread() {
  for (const button of threadList.querySelectorAll(".thread-item")) {
    const current = button.dataset.id === session.threadId;
    button.classList.toggle("is-current", current);
    if (current) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
}

export function clearThreadList() {
  clearTimeout(threadListTimer);
  threadListTimer = null;
  threadListRequest++;
  threadSearch.value = "";
  threadList.replaceChildren();
  threadListEmpty.hidden = true;
}

export async function refreshThreadList() {
  clearTimeout(threadListTimer);
  threadListTimer = null;
  const request = ++threadListRequest;
  const query = threadSearch.value.trim();

  // Menu ou edição abertos: tenta de novo daqui a pouco, sem tirá-los da tela.
  if (threadListBusy()) {
    threadListTimer = setTimeout(refreshThreadList, THREAD_LIST_POLL_MS);
    return;
  }

  let threads;
  try {
    const url = query ? `/api/threads?q=${encodeURIComponent(query)}` : "/api/threads";
    const response = await fetch(url);
    if (!response.ok) return;
    threads = (await response.json()).threads;
  } catch {
    return; // sem servidor, a lista fica como estava
  }
  if (request !== threadListRequest || document.body.dataset.auth !== "in") return;
  if (threadListBusy()) {
    threadListTimer = setTimeout(refreshThreadList, THREAD_LIST_POLL_MS);
    return;
  }

  threadList.replaceChildren(...threads.map(threadItem));
  threadListEmpty.textContent = query ? "Nenhuma conversa encontrada." : "Suas conversas aparecem aqui.";
  threadListEmpty.hidden = threads.length > 0;
  markCurrentThread();

  if (threads.some((item) => item.status === "streaming")) {
    threadListTimer = setTimeout(refreshThreadList, THREAD_LIST_POLL_MS);
  }
}

threadSearch.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(refreshThreadList, SEARCH_DEBOUNCE_MS);
});

async function switchThread(id) {
  closeSidebar();
  if (id === session.threadId) return;
  leaveView();
  session.threadId = id;
  markCurrentThread();
  try {
    await openThread(id);
  } catch {
    // Sem servidor: a conversa anterior já saiu; o erro aparece ao perguntar.
  }
}

function openSidebar() {
  document.body.classList.add("sidebar-open");
  sidebarToggle.setAttribute("aria-expanded", "true");
  refreshThreadList();
}

export function closeSidebar() {
  document.body.classList.remove("sidebar-open");
  sidebarToggle.setAttribute("aria-expanded", "false");
}

sidebarToggle.addEventListener("click", () => {
  if (document.body.classList.contains("sidebar-open")) closeSidebar();
  else openSidebar();
});
sidebarBackdrop.addEventListener("click", closeSidebar);
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (threadList.querySelector(".thread-menu")) closeThreadMenu();
  else closeSidebar();
});
