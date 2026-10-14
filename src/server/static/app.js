// Graham — cliente da interface: conversa com o agente pelo AG-UI e desenha
// os eventos que chegam do servidor.

const app = document.getElementById("app");
const thread = document.getElementById("thread");
const hero = document.getElementById("hero");
const composer = document.getElementById("composer");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");
const newChatButton = document.getElementById("new-chat");
const topbarMark = document.getElementById("topbar-mark");

let streaming = false;

// A leitura de stream em curso nesta tela, e um contador que muda a cada troca
// de conversa: o que chegar de uma conversa que já saiu da tela é descartado.
let currentReading = null;
let currentView = 0;

function leaveView() {
  currentView++;
  currentReading?.abort();
  currentReading = null;
  setStreaming(false);
}

/* ─────────────────────────────── Identidade da conversa ─────────────────── */

// O id da conversa nasce aqui, na primeira pergunta (o AG-UI espera do
// cliente), e o servidor a cria com ele; o navegador o guarda para reabri-la.
const THREAD_KEY = "graham.thread_id";

function storeThreadId(id) {
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

let threadId = savedThreadId();

/* ──────────────────────────────── Estado da tela ────────────────────────── */

function showConversation() {
  app.classList.remove("is-empty");
  hero.hidden = true;
  topbarMark.hidden = false;
}

function clearConversation() {
  for (const node of thread.querySelectorAll(".turn, .fork-note")) node.remove();
}

function showEmpty() {
  clearConversation();
  app.classList.add("is-empty");
  hero.hidden = false;
  topbarMark.hidden = true;
}

function setStreaming(value) {
  streaming = value;
  sendButton.disabled = value;
  app.classList.toggle("is-streaming", value);
}

function startNewConversation() {
  // Uma resposta em andamento segue no servidor; ela volta ao reabrir a conversa.
  leaveView();
  closeSidebar();

  threadId = null;
  storeThreadId(null);

  showEmpty();
  input.value = "";
  resize();
  input.focus();
  window.scrollTo({ top: 0, behavior: "smooth" });
  markCurrentThread();
}

newChatButton.addEventListener("click", startNewConversation);

/* ──────────────────────────────────── Conta ─────────────────────────────── */

const signOutButton = document.getElementById("sign-out");
const authForm = document.getElementById("auth-form");
const authEmail = document.getElementById("auth-email");
const authPassword = document.getElementById("auth-password");
const authError = document.getElementById("auth-error");
const authSubmit = document.getElementById("auth-submit");
const authSwitch = document.getElementById("auth-switch");
const authSwitchText = document.getElementById("auth-switch-text");

const AUTH_MODES = {
  login: {
    submit: "Entrar", switchText: "Não tem conta?", switchLabel: "Criar conta",
    autocomplete: "current-password", invalid: "E-mail ou senha incorretos.",
  },
  signup: {
    submit: "Criar conta", switchText: "Já tem conta?", switchLabel: "Entrar",
    autocomplete: "new-password", invalid: "Use um e-mail válido e uma senha de pelo menos 8 caracteres.",
  },
};

let authMode = "login";

function setAuthMode(mode) {
  authMode = mode;
  const texts = AUTH_MODES[mode];
  authSubmit.textContent = texts.submit;
  authSwitchText.textContent = texts.switchText;
  authSwitch.textContent = texts.switchLabel;
  authPassword.autocomplete = texts.autocomplete;
  authError.hidden = true;
}

function showAuthError(message) {
  authError.textContent = message;
  authError.hidden = false;
}

function signedIn(email) {
  document.body.dataset.auth = "in";
  signOutButton.title = `Sair de ${email}`;
  refreshThreadList();
}

// Sem sessão (nunca entrou, saiu ou ela venceu): só a entrada fica na tela, e
// a conversa aberta sai junto, porque era da conta anterior.
function signedOut() {
  leaveView();
  clearThreadList();
  threadId = null;
  storeThreadId(null);
  showEmpty();
  authPassword.value = "";
  document.body.dataset.auth = "out";
  authEmail.focus();
}

authSwitch.addEventListener("click", () => {
  setAuthMode(authMode === "login" ? "signup" : "login");
  authEmail.focus();
});

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  authSubmit.disabled = true;
  authError.hidden = true;
  try {
    const response = await fetch(`/api/auth/${authMode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: authEmail.value, password: authPassword.value }),
    });
    let body = {};
    try {
      body = await response.json();
    } catch {
      /* sem corpo legível */
    }
    if (!response.ok) {
      // 422: o formato não passou na validação; os outros trazem a mensagem.
      const detail = typeof body.detail === "string" ? body.detail : AUTH_MODES[authMode].invalid;
      showAuthError(detail);
      return;
    }
    authPassword.value = "";
    signedIn(body.email);
    input.focus();
  } catch {
    showAuthError("Sem conexão com o servidor.");
  } finally {
    authSubmit.disabled = false;
  }
});

signOutButton.addEventListener("click", async () => {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } finally {
    setAuthMode("login");
    signedOut();
  }
});

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
const SHORT_DATE = new Intl.DateTimeFormat("pt-BR", { day: "numeric", month: "short" });

function relativeTime(iso) {
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
  if (item.id === threadId) startNewConversation();
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

function markCurrentThread() {
  for (const button of threadList.querySelectorAll(".thread-item")) {
    const current = button.dataset.id === threadId;
    button.classList.toggle("is-current", current);
    if (current) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
}

function clearThreadList() {
  clearTimeout(threadListTimer);
  threadListTimer = null;
  threadListRequest++;
  threadSearch.value = "";
  threadList.replaceChildren();
  threadListEmpty.hidden = true;
}

async function refreshThreadList() {
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
  if (id === threadId) return;
  leaveView();
  threadId = id;
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

function closeSidebar() {
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

/* ────────────────────────────── Chaves de acesso ────────────────────────── */

// Para usar as ferramentas do Graham em outro agente, pelo servidor MCP. A
// chave só aparece na criação: o servidor guarda apenas o hash dela.

const keysDialog = document.getElementById("keys-dialog");
const keyForm = document.getElementById("key-form");
const keyName = document.getElementById("key-name");
const keyWrite = document.getElementById("key-write");
const keyCreated = document.getElementById("key-created");
const keyList = document.getElementById("key-list");
const keyListEmpty = document.getElementById("key-list-empty");
const keysError = document.getElementById("keys-error");
const mcpUrl = document.getElementById("mcp-url");

// Quanto tempo o botão de revogar espera a confirmação.
const REVOKE_CONFIRM_MS = 4000;

function showKeysError(message) {
  keysError.textContent = message;
  keysError.hidden = !message;
}

async function keysRequest(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error("Sem conexão com o servidor.");
  }
  if (response.status === 401) {
    keysDialog.close();
    signedOut();
    throw new Error("Sessão encerrada.");
  }
  if (!response.ok) {
    let detail = null;
    try {
      detail = (await response.json()).detail;
    } catch {
      /* sem corpo legível */
    }
    throw new Error(typeof detail === "string" ? detail : "Não foi possível concluir.");
  }
  return response.status === 204 ? null : response.json();
}

function keyItem(key) {
  const li = document.createElement("li");
  li.className = "key-item";

  const info = document.createElement("div");
  const name = document.createElement("div");
  name.className = "key-item-name";
  name.textContent = key.name;
  const meta = document.createElement("div");
  meta.className = "key-item-meta";
  const access = document.createElement("span");
  access.className = key.can_write ? "is-write" : "";
  access.textContent = key.can_write ? "leitura e escrita" : "só leitura";
  const used = key.last_used_at ? `usada ${relativeTime(key.last_used_at)}` : "nunca usada";
  meta.append(access, ` · criada em ${SHORT_DATE.format(new Date(key.created_at))} · ${used}`);
  info.append(name, meta);

  const revoke = document.createElement("button");
  revoke.type = "button";
  revoke.className = "key-revoke";
  revoke.textContent = "Revogar";
  let timer = null;
  revoke.addEventListener("click", async () => {
    // Primeiro clique pede confirmação; o segundo, dentro do prazo, revoga.
    if (!revoke.classList.contains("is-confirming")) {
      revoke.classList.add("is-confirming");
      revoke.textContent = "Confirmar";
      timer = setTimeout(() => {
        revoke.classList.remove("is-confirming");
        revoke.textContent = "Revogar";
      }, REVOKE_CONFIRM_MS);
      return;
    }
    clearTimeout(timer);
    try {
      await keysRequest(`/api/keys/${key.id}`, { method: "DELETE" });
      showKeysError("");
      await loadKeys();
    } catch (error) {
      showKeysError(error.message);
    }
  });

  li.append(info, revoke);
  return li;
}

async function loadKeys() {
  const data = await keysRequest("/api/keys");
  mcpUrl.textContent = data.mcp_url;
  keyList.replaceChildren(...data.keys.map(keyItem));
  keyListEmpty.hidden = data.keys.length > 0;
}

async function openKeys() {
  closeSidebar();
  keyCreated.hidden = true;
  showKeysError("");
  keyForm.reset();
  keysDialog.showModal();
  keyName.focus();
  try {
    await loadKeys();
  } catch (error) {
    showKeysError(error.message);
  }
}

keyForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = keyName.value.trim();
  if (!name) {
    showKeysError("Dê um nome à chave, para saber depois onde ela está em uso.");
    keyName.focus();
    return;
  }
  const submit = keyForm.querySelector("button[type=submit]");
  submit.disabled = true;
  try {
    const key = await keysRequest("/api/keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, can_write: keyWrite.checked }),
    });
    showKeysError("");
    document.getElementById("key-token").textContent = key.token;
    document.getElementById("key-example").textContent =
      `claude mcp add --transport http graham ${mcpUrl.textContent} --header "Authorization: Bearer ${key.token}"`;
    keyCreated.hidden = false;
    keyForm.reset();
    await loadKeys();
  } catch (error) {
    showKeysError(error.message);
  } finally {
    submit.disabled = false;
  }
});

for (const button of keysDialog.querySelectorAll(".copy-button")) {
  button.addEventListener("click", async () => {
    const text = document.getElementById(button.dataset.copy).textContent;
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "Copiado";
    } catch {
      // Sem acesso à área de transferência: o texto fica selecionado para Ctrl+C.
      const range = document.createRange();
      range.selectNodeContents(document.getElementById(button.dataset.copy));
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      button.textContent = "Selecionado";
    }
    setTimeout(() => { button.textContent = "Copiar"; }, 1600);
  });
}

document.getElementById("open-keys").addEventListener("click", openKeys);
document.getElementById("keys-close").addEventListener("click", () => keysDialog.close());
// Ao fechar, a chave criada sai da tela: ela não pode ficar exposta.
keysDialog.addEventListener("close", () => {
  keyCreated.hidden = true;
  document.getElementById("key-token").textContent = "";
  document.getElementById("key-example").textContent = "";
});

/* ────────────────────────────────── Markdown ────────────────────────────── */

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
}

function inlineMarkdown(text) {
  return text
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

// Uma linha só de hífens e canos: o traço que separa o cabeçalho da tabela.
const TABLE_DIVIDER = /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$/;

function tableCells(line) {
  return line.replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

// Renderizador mínimo: títulos, listas, tabelas, ênfase, código, links e regras.
// O texto é escapado antes de qualquer coisa, então nada do modelo vira HTML.
function renderMarkdown(source) {
  const lines = escapeHtml(source).split("\n");
  let html = "";
  let list = null;

  const closeList = () => {
    if (list) { html += `</${list}>`; list = null; }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();

    if (!line) { closeList(); continue; }

    const heading = line.match(/^(#{1,5})\s+(.*)$/);
    if (heading) {
      closeList();
      html += `<h4>${inlineMarkdown(heading[2])}</h4>`;
      continue;
    }

    // Tabela: cabeçalho seguido do traço. Enquanto o traço não chegou pelo
    // streaming, a linha cai como parágrafo e se reorganiza no token seguinte.
    if (line.startsWith("|") && TABLE_DIVIDER.test((lines[i + 1] || "").trim())) {
      closeList();

      const header = tableCells(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        rows.push(tableCells(lines[i].trim()));
        i++;
      }
      i--; // o for volta a incrementar

      const head = header.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join("");
      const body = rows
        .map((row) => `<tr>${row.map((cell) => `<td>${inlineMarkdown(cell)}</td>`).join("")}</tr>`)
        .join("");

      html += `<div class="table-wrap"><table><thead><tr>${head}</tr></thead>` +
              `<tbody>${body}</tbody></table></div>`;
      continue;
    }

    if (/^---+$/.test(line)) { closeList(); html += "<hr>"; continue; }

    if (/^[-*+]\s+/.test(line)) {
      if (list !== "ul") { closeList(); html += "<ul>"; list = "ul"; }
      html += `<li>${inlineMarkdown(line.replace(/^[-*+]\s+/, ""))}</li>`;
      continue;
    }

    if (/^\d+[.)]\s+/.test(line)) {
      if (list !== "ol") { closeList(); html += "<ol>"; list = "ol"; }
      html += `<li>${inlineMarkdown(line.replace(/^\d+[.)]\s+/, ""))}</li>`;
      continue;
    }

    closeList();
    html += `<p>${inlineMarkdown(line)}</p>`;
  }

  closeList();
  return html;
}

/* ──────────────────────────────── Peças da conversa ─────────────────────── */

const TOOL_NAMES = {
  cotacao_atual_acao: "cotação atual",
  proventos: "proventos",
  desempenho: "desempenho",
  guardar_memoria: "memória",
  buscar_memorias: "busca na memória",
  ver_memoria: "memória",
  esquecer_memoria: "memória",
  ler_skill: "skill",
  noticias_acao: "notícias recentes",
  noticias_tema: "notícias do tema",
  buscar_ticker_por_empresa: "busca de ticker",
  buscar_tickers_por_industria: "triagem por setor",
  resumo_mercado: "resumo de mercado",
  ver_carteira: "carteira",
  ver_watchlist: "watchlist",
};

// Ferramentas que não são consultas: o aviso diz o que aconteceu.
const WORKING_LABELS = {
  guardar_memoria: "guardando na memória",
  esquecer_memoria: "esquecendo memória",
};

const DONE_LABELS = {
  guardar_memoria: "memória · guardada",
  esquecer_memoria: "memória · esquecida",
};

function toolLabel(name) {
  return TOOL_NAMES[name] || name.replace(/_/g, " ");
}

function toolSubject(payload) {
  if (!payload || typeof payload !== "object") return "";
  const value = payload.ticker_name
    || (Array.isArray(payload.tickers) && payload.tickers.join(", "))
    || payload.company_name || payload.industry || payload.query || payload.name || payload.region;
  return value ? ` · ${value}` : "";
}

/* ─────────────────────────── Vistas de resultado ────────────────────────── */

// Algumas ferramentas devolvem dados que se leem melhor como tabela. A vista
// aparece no detalhe da consulta, acima do JSON, que continua lá para inspeção.

const MONEY_FORMATS = new Map();

// `digits` é o máximo de casas decimais: proventos por ação pedem 4
// (R$ 0,1053), valores totais ficam nas 2 de sempre.
function money(value, currency, digits = 2) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const key = `${currency}:${digits}`;
  if (!MONEY_FORMATS.has(key)) {
    let format;
    try {
      format = new Intl.NumberFormat("pt-BR", {
        style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: digits,
      });
    } catch {
      // Moeda que o navegador não conhece: o número, com o código ao lado.
      const plain = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: digits });
      format = { format: (number) => `${plain.format(number)} ${currency || ""}`.trim() };
    }
    MONEY_FORMATS.set(key, format);
  }
  return MONEY_FORMATS.get(key).format(value);
}

const QUANTITY_FORMAT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 8 });
const PERCENT_FORMAT = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function quantity(value) {
  return typeof value === "number" ? QUANTITY_FORMAT.format(value) : "—";
}

// "2025-03-10" vira "10/03/2025", sem passar pelo fuso de quem está olhando.
function isoDate(value) {
  const match = typeof value === "string" && value.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : value || "—";
}

// Resultado em dinheiro com o percentual ao lado, na cor da alta ou da queda.
function resultCell(value, percent, currency) {
  if (typeof value !== "number") return { text: "—", numeric: true };
  const sign = value < 0 ? MINUS : value > 0 ? "+" : "";
  const share = typeof percent === "number"
    ? ` (${percent < 0 ? MINUS : percent > 0 ? "+" : ""}${PERCENT_FORMAT.format(Math.abs(percent))}%)`
    : "";
  return {
    text: `${sign}${money(Math.abs(value), currency)}${share}`,
    numeric: true,
    className: value < 0 ? "is-down" : value > 0 ? "is-up" : "",
  };
}

// Células como texto, nunca HTML: os valores vêm da ferramenta.
function dataTable(caption, columns, rows) {
  const section = document.createElement("div");
  section.className = "tool-view-section";

  const heading = document.createElement("div");
  heading.className = "tool-view-caption";
  heading.textContent = caption;

  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  const head = table.createTHead().insertRow();
  for (const column of columns) {
    const th = document.createElement("th");
    th.textContent = column.label;
    if (column.numeric) th.className = "num";
    head.append(th);
  }
  const body = table.createTBody();
  for (const row of rows) {
    const tr = body.insertRow();
    row.forEach((cell, index) => {
      const td = tr.insertCell();
      const value = typeof cell === "object" && cell !== null ? cell : { text: cell };
      td.textContent = value.text ?? "—";
      td.className = [columns[index].numeric ? "num" : "", value.className || ""].join(" ").trim();
    });
  }
  wrap.append(table);
  section.append(heading, wrap);
  return section;
}

function portfolioView(output) {
  if (!output || !Array.isArray(output.positions)) return null;

  const view = document.createElement("div");
  view.className = "tool-view";

  if (!output.positions.length && !(output.trades || []).length) {
    const empty = document.createElement("p");
    empty.className = "tool-view-empty";
    empty.textContent = "A carteira não tem posições.";
    view.append(empty);
    return view;
  }

  if (output.positions.length) {
    view.append(dataTable(
      "Posições",
      [
        { label: "Ativo" },
        { label: "Quantidade", numeric: true },
        { label: "Preço médio", numeric: true },
        { label: "Investido", numeric: true },
        { label: "Cotação", numeric: true },
        { label: "Valor atual", numeric: true },
        { label: "Resultado", numeric: true },
      ],
      output.positions.map((position) => [
        position.ticker_name,
        quantity(position.quantity),
        money(position.average_price, position.currency),
        money(position.invested, position.currency),
        // A cotação fica na moeda da Yahoo; o resto, na moeda em que o usuário pagou.
        money(position.current_price, position.quote_currency || position.currency),
        money(position.current_value, position.currency),
        resultCell(position.result, position.result_percent, position.currency),
      ]),
    ));
  }

  if ((output.totals || []).length) {
    view.append(dataTable(
      "Totais por moeda",
      [
        { label: "Moeda" },
        { label: "Investido", numeric: true },
        { label: "Valor atual", numeric: true },
        { label: "Resultado", numeric: true },
        { label: "Vendas realizadas", numeric: true },
      ],
      output.totals.map((total) => [
        total.currency,
        money(total.invested, total.currency),
        money(total.current_value, total.currency),
        resultCell(total.result, total.result_percent, total.currency),
        resultCell(total.realized, null, total.currency),
      ]),
    ));
  }

  if ((output.trades || []).length) {
    view.append(dataTable(
      "Operações",
      [
        { label: "Data" },
        { label: "Ativo" },
        { label: "Operação" },
        { label: "Quantidade", numeric: true },
        { label: "Preço", numeric: true },
        { label: "Total", numeric: true },
      ],
      // A ferramenta agrupa por ativo; aqui a leitura é cronológica.
      [...output.trades].sort((a, b) => a.traded_on.localeCompare(b.traded_on)).map((trade) => [
        isoDate(trade.traded_on),
        trade.ticker_name,
        trade.side,
        quantity(trade.quantity),
        money(trade.unit_price, trade.currency),
        money(trade.quantity * trade.unit_price, trade.currency),
      ]),
    ));
  }

  return view;
}

function signedPercent(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const sign = value < 0 ? MINUS : value > 0 ? "+" : "";
  return `${sign}${PERCENT_FORMAT.format(Math.abs(value))}%`;
}

function percentCell(value) {
  return {
    text: signedPercent(value),
    numeric: true,
    className: typeof value !== "number" ? "" : value < 0 ? "is-down" : value > 0 ? "is-up" : "",
  };
}

// Linha de destaques acima das tabelas: rótulo pequeno, valor em evidência.
function statsRow(items) {
  const row = document.createElement("dl");
  row.className = "tool-view-stats";
  for (const [label, value] of items) {
    const item = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value;
    item.append(term, detail);
    row.append(item);
  }
  return row;
}

function emptyNote(text) {
  const empty = document.createElement("p");
  empty.className = "tool-view-empty";
  empty.textContent = text;
  return empty;
}

/* Proventos: de um ativo ou da carteira inteira. */
function incomeView(output) {
  if (!output || (!Array.isArray(output.payments) && !Array.isArray(output.assets))) return null;
  const view = document.createElement("div");
  view.className = "tool-view";

  if (Array.isArray(output.assets)) {
    if (!output.assets.length) {
      view.append(emptyNote(`A carteira não recebeu proventos nos últimos ${output.months} meses.`));
    } else {
      view.append(statsRow(output.totals.map((total) => [
        `Recebido em ${output.months} meses (${total.currency})`, money(total.total, total.currency),
      ])));
      view.append(dataTable(
        "Por ativo",
        [{ label: "Ativo" }, { label: "Pagamentos", numeric: true }, { label: "Recebido", numeric: true }],
        output.assets.map((asset) => [
          asset.ticker_name, String(asset.payments.length), money(asset.total, asset.currency),
        ]),
      ));
      const payments = output.assets
        .flatMap((asset) => asset.payments.map((payment) => ({ ...payment, asset })))
        .sort((a, b) => b.ex_date.localeCompare(a.ex_date));
      view.append(dataTable(
        "Pagamentos",
        [
          { label: "Data ex" }, { label: "Ativo" }, { label: "Por cota", numeric: true },
          { label: "Quantidade", numeric: true }, { label: "Recebido", numeric: true },
        ],
        payments.map((payment) => [
          isoDate(payment.ex_date), payment.asset.ticker_name,
          money(payment.amount, payment.asset.currency, 4), quantity(payment.quantity),
          money(payment.received, payment.asset.currency),
        ]),
      ));
    }
    if ((output.upcoming || []).length) {
      view.append(dataTable(
        "Próximas datas ex",
        [{ label: "Data ex" }, { label: "Ativo" }, { label: "Quantidade", numeric: true }],
        output.upcoming.map((item) => [isoDate(item.next_ex_date), item.ticker_name, quantity(item.quantity)]),
      ));
    }
    return view;
  }

  const currency = output.currency;
  view.append(statsRow([
    ["Últimos 12 meses", money(output.trailing_12m_total, currency)],
    ["Dividend yield (12 meses)", output.dividend_yield_12m == null
      ? "—" : `${PERCENT_FORMAT.format(output.dividend_yield_12m)}%`],
    ["Próxima data ex", output.next_ex_date ? isoDate(output.next_ex_date) : "—"],
  ]));
  if (!output.payments.length) {
    view.append(emptyNote(`Nenhum provento nos últimos ${output.months} meses.`));
  } else {
    view.append(dataTable(
      `Pagamentos em ${output.months} meses`,
      [{ label: "Data ex" }, { label: "Por ação ou cota", numeric: true }],
      output.payments.map((payment) => [isoDate(payment.ex_date), money(payment.amount, currency, 4)]),
    ));
  }
  if (output.your_income) {
    view.append(dataTable(
      `Recebido por você: ${money(output.your_income.total, currency)}`,
      [
        { label: "Data ex" }, { label: "Por cota", numeric: true },
        { label: "Quantidade", numeric: true }, { label: "Recebido", numeric: true },
      ],
      output.your_income.payments.map((payment) => [
        isoDate(payment.ex_date), money(payment.amount, currency, 4),
        quantity(payment.quantity), money(payment.received, currency),
      ]),
    ));
  }
  return view;
}

/* ─────────────────────────────── Gráfico de desempenho ──────────────────── */

const SVG_NS = "http://www.w3.org/2000/svg";
const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

function svgElement(tag, attributes = {}) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  return element;
}

// Passo "redondo" para os rótulos do eixo: 1, 2, 2,5 ou 5 vezes uma potência de 10.
function niceStep(rough) {
  const power = 10 ** Math.floor(Math.log10(rough));
  return [1, 2, 2.5, 5, 10].map((factor) => factor * power).find((step) => step >= rough);
}

function shortDate(time, longSpan) {
  const date = new Date(time);
  const month = MONTHS[date.getUTCMonth()];
  return longSpan
    ? `${month}/${String(date.getUTCFullYear()).slice(2)}`
    : `${String(date.getUTCDate()).padStart(2, "0")} ${month}`;
}

// Último ponto da série até `time`: as séries têm calendários diferentes (cripto
// negocia no fim de semana; a bolsa, não).
function pointAt(points, time) {
  let low = 0;
  let high = points.length - 1;
  if (time <= points[0][0]) return points[0];
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (points[middle][0] <= time) low = middle;
    else high = middle - 1;
  }
  return points[low];
}

// Retorno acumulado de cada ativo, todos partindo de zero na mesma escala.
// As cores seguem a ordem fixa da paleta pela posição do ativo; o índice de
// referência fica em cinza tracejado, recessivo.
function performanceChart(seriesList) {
  const series = seriesList.map((item, index) => ({
    ...item,
    color: item.is_index ? "var(--series-index)" : `var(--series-${index + 1})`,
    points: item.points.map(([day, value]) => [Date.parse(`${day}T00:00:00Z`), value]),
  }));

  const root = document.createElement("figure");
  root.className = "perf-chart";

  const caption = document.createElement("figcaption");
  caption.className = "tool-view-caption";
  caption.textContent = "Retorno acumulado, com proventos";
  root.append(caption);

  if (series.length > 1) {
    const legend = document.createElement("div");
    legend.className = "perf-legend";
    for (const item of series) {
      const entry = document.createElement("span");
      entry.className = "perf-legend-item";
      const swatch = document.createElement("span");
      swatch.className = `perf-swatch${item.is_index ? " is-index" : ""}`;
      swatch.style.setProperty("--swatch", item.color);
      entry.append(swatch, document.createTextNode(item.label));
      legend.append(entry);
    }
    root.append(legend);
  }

  const plot = document.createElement("div");
  plot.className = "perf-plot";
  const tooltip = document.createElement("div");
  tooltip.className = "perf-tooltip";
  tooltip.hidden = true;
  root.append(plot);

  const summary = series
    .map((item) => `${item.label} ${signedPercent(item.points[item.points.length - 1][1])}`)
    .join(", ");

  const draw = () => {
    const width = plot.clientWidth;
    if (!width) return; // ainda escondido: o detalhe da consulta está fechado
    const narrow = width < 480;
    const height = narrow ? 200 : 240;
    const margin = { top: 10, right: narrow ? 92 : 128, bottom: 24, left: 44 };
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;

    const times = series.flatMap((item) => item.points.map(([time]) => time));
    const values = series.flatMap((item) => item.points.map(([, value]) => value));
    const t0 = Math.min(...times);
    const t1 = Math.max(...times);
    const step = niceStep(Math.max((Math.max(...values, 0) - Math.min(...values, 0)) / 4, 0.5));
    const y0 = Math.floor(Math.min(...values, 0) / step) * step;
    const y1 = Math.ceil(Math.max(...values, 0) / step) * step;

    const x = (time) => margin.left + ((time - t0) / (t1 - t0 || 1)) * innerWidth;
    const y = (value) => margin.top + (1 - (value - y0) / (y1 - y0 || 1)) * innerHeight;

    const chart = svgElement("svg", {
      width, height, viewBox: `0 0 ${width} ${height}`, role: "img",
      "aria-label": `Retorno acumulado no período: ${summary}.`,
    });

    // Grade e eixo vertical, recessivos; a linha do zero, um pouco mais firme.
    for (let value = y0; value <= y1 + step / 2; value += step) {
      chart.append(svgElement("line", {
        x1: margin.left, x2: margin.left + innerWidth, y1: y(value), y2: y(value),
        class: Math.abs(value) < step / 2 ? "perf-zero" : "perf-grid",
      }));
      const label = svgElement("text", { x: margin.left - 8, y: y(value), class: "perf-axis", "text-anchor": "end", dy: "0.32em" });
      label.textContent = signedPercent(Math.round(value * 100) / 100).replace(",00", "");
      chart.append(label);
    }

    const longSpan = t1 - t0 > 400 * 864e5;
    const ticks = narrow ? 3 : 5;
    for (let index = 0; index < ticks; index++) {
      const time = t0 + ((t1 - t0) * index) / (ticks - 1);
      const label = svgElement("text", {
        x: x(time), y: height - 6, class: "perf-axis",
        "text-anchor": index === 0 ? "start" : index === ticks - 1 ? "end" : "middle",
      });
      label.textContent = shortDate(time, longSpan);
      chart.append(label);
    }

    // O índice vai por baixo; os ativos, por cima.
    for (const item of [...series].sort((a, b) => Number(b.is_index) - Number(a.is_index))) {
      chart.append(svgElement("path", {
        d: item.points.map(([time, value], index) => `${index ? "L" : "M"}${x(time).toFixed(1)},${y(value).toFixed(1)}`).join(""),
        class: `perf-line${item.is_index ? " is-index" : ""}`,
        style: `stroke: ${item.color}`,
      }));
    }

    // Rótulo direto no fim de cada linha, afastados para não se sobreporem.
    const ends = series
      .map((item) => ({ item, last: item.points[item.points.length - 1] }))
      .map((end) => ({ ...end, labelY: y(end.last[1]) }))
      .sort((a, b) => a.labelY - b.labelY);
    for (let index = 1; index < ends.length; index++) {
      ends[index].labelY = Math.max(ends[index].labelY, ends[index - 1].labelY + 14);
    }
    const overflow = ends.length ? ends[ends.length - 1].labelY - (height - margin.bottom) : 0;
    if (overflow > 0) ends.forEach((end) => { end.labelY -= overflow; });
    for (const { item, last, labelY } of ends) {
      chart.append(svgElement("circle", {
        cx: x(last[0]), cy: y(last[1]), r: 4, class: "perf-dot", style: `fill: ${item.color}`,
      }));
      const label = svgElement("text", { x: margin.left + innerWidth + 10, y: labelY, dy: "0.32em", class: "perf-label" });
      label.textContent = `${narrow ? "" : `${item.label} `}${signedPercent(last[1])}`;
      chart.append(label);
    }

    // Camada de hover: linha vertical e os valores de cada ativo naquela data.
    const crosshair = svgElement("line", { y1: margin.top, y2: margin.top + innerHeight, class: "perf-crosshair" });
    const markers = series.map((item) => svgElement("circle", { r: 4, class: "perf-dot", style: `fill: ${item.color}` }));
    const hover = svgElement("g", { visibility: "hidden" });
    hover.append(crosshair, ...markers);
    chart.append(hover);

    const zone = svgElement("rect", {
      x: margin.left, y: margin.top, width: innerWidth, height: innerHeight, class: "perf-zone",
    });
    zone.addEventListener("pointermove", (event) => {
      const bounds = chart.getBoundingClientRect();
      const time = t0 + ((event.clientX - bounds.left - margin.left) / innerWidth) * (t1 - t0);
      const anchor = pointAt(series[0].points, time)[0];
      crosshair.setAttribute("x1", x(anchor));
      crosshair.setAttribute("x2", x(anchor));

      tooltip.replaceChildren();
      const heading = document.createElement("div");
      heading.className = "perf-tooltip-date";
      heading.textContent = isoDate(new Date(anchor).toISOString());
      tooltip.append(heading);
      series.forEach((item, index) => {
        const [time, value] = pointAt(item.points, anchor);
        markers[index].setAttribute("cx", x(time));
        markers[index].setAttribute("cy", y(value));
        const row = document.createElement("div");
        row.className = "perf-tooltip-row";
        const swatch = document.createElement("span");
        swatch.className = `perf-swatch${item.is_index ? " is-index" : ""}`;
        swatch.style.setProperty("--swatch", item.color);
        const name = document.createElement("span");
        name.textContent = item.label;
        const amount = document.createElement("strong");
        amount.textContent = signedPercent(value);
        row.append(swatch, name, amount);
        tooltip.append(row);
      });

      hover.setAttribute("visibility", "visible");
      tooltip.hidden = false;
      const left = x(anchor) + 12;
      tooltip.style.left = `${left + tooltip.offsetWidth > width ? x(anchor) - tooltip.offsetWidth - 12 : left}px`;
      tooltip.style.top = `${margin.top}px`;
    });
    zone.addEventListener("pointerleave", () => {
      hover.setAttribute("visibility", "hidden");
      tooltip.hidden = true;
    });
    chart.append(zone);

    plot.replaceChildren(chart, tooltip);
  };

  // Desenha quando o quadro ganha largura (o detalhe abre) e a cada mudança dela.
  new ResizeObserver(draw).observe(plot);
  return root;
}

function performanceView(output, artifact) {
  if (!output || !Array.isArray(output.series)) return null;
  const view = document.createElement("div");
  view.className = "tool-view";

  if (artifact?.series?.length) view.append(performanceChart(artifact.series));

  // A tabela é também a leitura acessível do gráfico. Com o mesmo período para
  // todos (o comum), ele vai uma vez só no título, e não em cada linha.
  const span = (item) => `${isoDate(item.from)} a ${isoDate(item.to)}`;
  const shared = new Set(output.series.map(span)).size === 1;
  view.append(dataTable(
    shared ? `Desempenho de ${span(output.series[0])}` : "Desempenho",
    [
      { label: "Ativo" }, ...(shared ? [] : [{ label: "Período" }]), { label: "Preço", numeric: true },
      { label: "Com proventos", numeric: true }, { label: "Ao ano", numeric: true },
      { label: "Volatilidade", numeric: true }, { label: "Maior queda", numeric: true },
    ],
    output.series.map((item) => [
      item.label,
      ...(shared ? [] : [span(item)]),
      percentCell(item.price_return_percent),
      percentCell(item.total_return_percent),
      percentCell(item.annualized_return_percent),
      item.annualized_volatility_percent == null ? "—" : `${PERCENT_FORMAT.format(item.annualized_volatility_percent)}%`,
      percentCell(item.max_drawdown_percent),
    ]),
  ));
  return view;
}

const TOOL_VIEWS = {
  ver_carteira: portfolioView,
  proventos: incomeView,
  desempenho: performanceView,
};

/* ───────────────────────── Detalhe da chamada de ferramenta ─────────────── */

const CHEVRON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M6 9l6 6 6-6"/></svg>';

function codeBox(title) {
  const box = document.createElement("div");
  box.className = "code-box";

  const head = document.createElement("div");
  head.className = "code-head";
  head.innerHTML = `<span>${title}</span><span class="code-lang">JSON</span>`;

  const pre = document.createElement("pre");
  const code = document.createElement("code");
  pre.append(code);
  box.append(head, pre);

  return {
    el: box,
    // textContent, nunca innerHTML: o retorno da ferramenta é dado, não markup.
    set(value) {
      code.textContent = value === undefined || value === null
        ? ""
        : JSON.stringify(value, null, 2);
    },
  };
}

function toolBlock(toolName, input) {
  const root = document.createElement("div");
  root.className = "tool-block";

  const bar = document.createElement("div");
  bar.className = "tool-note is-working";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "tool-toggle";
  toggle.setAttribute("aria-expanded", "false");

  const text = document.createElement("span");
  text.textContent = workingLabel(toolName, input);

  const dot = document.createElement("span");
  dot.className = "dot";

  const chevron = document.createElement("span");
  chevron.className = "tool-chevron";
  chevron.innerHTML = CHEVRON;

  toggle.append(text, dot, chevron);
  bar.append(toggle);

  const detail = document.createElement("div");
  detail.className = "tool-detail";
  detail.hidden = true;

  const args = codeBox("Argumentos");
  const result = codeBox("Resultados");
  args.set(input);
  detail.append(args.el, result.el);

  toggle.addEventListener("click", () => {
    const opening = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(opening));
    detail.hidden = !opening;
  });

  root.append(bar, detail);

  return {
    root,
    // Devolve a vista estruturada do resultado, se a ferramenta tiver uma.
    finish(output, artifact = null) {
      bar.classList.remove("is-working");
      dot.remove();
      // "consulta concluída" evita concordar em gênero com o nome da ferramenta.
      text.textContent = DONE_LABELS[toolName] || `${toolLabel(toolName)} · consulta concluída`;
      result.set(output);
      return TOOL_VIEWS[toolName]?.(output, artifact) || null;
    },
    abort() {
      bar.classList.remove("is-working");
      dot.remove();
      text.textContent = `${toolLabel(toolName)} · consulta interrompida`;
    },
    // Os argumentos chegam aos pedaços, depois do anúncio da consulta.
    update(value) {
      text.textContent = workingLabel(toolName, value);
      args.set(value);
    },
    fail(message) {
      bar.classList.remove("is-working");
      dot.remove();
      text.textContent = `${toolLabel(toolName)} · consulta falhou`;
      result.set(message);
    },
  };
}

/* ─────────────────────────── Rodada de consultas ────────────────────────── */

// Consultas seguidas, sem texto entre elas, formam uma rodada. Com uma só, ela
// aparece como sempre. A partir da segunda, viram um grupo expansível que, no
// cabeçalho, mostra só a consulta em andamento e a contagem.
//
// As vistas estruturadas (a carteira, os proventos, o gráfico de desempenho)
// não ficam dentro do detalhe da consulta: vêm logo depois da rodada, antes do
// texto. Uma só aparece aberta; mais de uma, cada uma recolhida sob um título.

function capitalize(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function workingLabel(name, input) {
  return WORKING_LABELS[name] || `consultando ${toolLabel(name)}${toolSubject(input)}`;
}

// O que distingue, recolhidas, duas vistas da mesma ferramenta: o período.
// Dois desempenhos dos mesmos ativos, um de três meses e outro de três
// semanas, teriam o mesmo título sem ele.
const VIEW_PERIODS = {
  desempenho: (output) => {
    const spans = new Set((output?.series || []).map((item) => `${isoDate(item.from)} a ${isoDate(item.to)}`));
    return spans.size === 1 ? [...spans][0] : null;
  },
  proventos: (output) => (output?.months ? `últimos ${output.months} meses` : null),
};

function viewTitle(name, input, output) {
  const period = VIEW_PERIODS[name]?.(output);
  return `${capitalize(toolLabel(name))}${toolSubject(input)}${period ? ` · ${period}` : ""}`;
}

function viewFold(title, view) {
  const fold = document.createElement("details");
  fold.className = "view-fold";
  const summary = document.createElement("summary");
  summary.className = "view-fold-summary";
  const label = document.createElement("span");
  label.textContent = title;
  const chevron = document.createElement("span");
  chevron.className = "tool-chevron";
  chevron.innerHTML = CHEVRON;
  summary.append(label, chevron);
  fold.append(summary, view);
  return fold;
}

function toolRun() {
  const root = document.createElement("div");
  root.className = "tool-run";
  const slot = document.createElement("div");
  const viewsBox = document.createElement("div");
  viewsBox.className = "tool-views";
  root.append(slot, viewsBox);

  const entries = [];
  const views = [];
  let group = null;

  const buildGroup = () => {
    const bar = document.createElement("div");
    bar.className = "tool-note tool-group-note";

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "tool-toggle";
    toggle.setAttribute("aria-expanded", "false");

    const text = document.createElement("span");
    const count = document.createElement("span");
    count.className = "tool-group-count";
    const dot = document.createElement("span");
    dot.className = "dot";
    const chevron = document.createElement("span");
    chevron.className = "tool-chevron";
    chevron.innerHTML = CHEVRON;
    toggle.append(text, count, dot, chevron);
    bar.append(toggle);

    const detail = document.createElement("div");
    detail.className = "tool-group-detail";
    detail.hidden = true;
    toggle.addEventListener("click", () => {
      const opening = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", String(opening));
      detail.hidden = !opening;
    });

    for (const entry of entries) detail.append(entry.note.root);
    slot.replaceChildren(bar, detail);
    group = { bar, text, count, dot, detail };
  };

  const refresh = () => {
    if (!group) return;
    const total = entries.length;
    const working = entries.filter((entry) => entry.state === "working");
    const finished = total - working.length;
    group.bar.classList.toggle("is-working", working.length > 0);
    group.dot.hidden = working.length === 0;
    if (working.length) {
      // A mais recente das que ainda rodam: é a que o agente acabou de pedir.
      const current = working[working.length - 1];
      group.text.textContent = workingLabel(current.name, current.input);
      group.count.textContent = `${finished} de ${total}`;
    } else {
      const aborted = entries.some((entry) => entry.state === "aborted");
      group.text.textContent = `${total} consultas ${aborted ? "· interrompidas" : "concluídas"}`;
      group.count.textContent = "";
    }
  };

  const placeViews = () => {
    if (views.length === 1) viewsBox.replaceChildren(views[0].el);
    else viewsBox.replaceChildren(...views.map((item) => viewFold(item.title, item.el)));
  };

  return {
    root,
    add(name, input) {
      const note = toolBlock(name, input);
      const entry = { name, input, note, state: "working" };
      entries.push(entry);
      if (entries.length === 1) slot.append(note.root);
      else if (!group) buildGroup();
      else group.detail.append(note.root);
      refresh();

      return {
        update(value) {
          note.update(value);
          entry.input = value;
          refresh();
        },
        finish(output, artifact = null) {
          const view = note.finish(output, artifact);
          entry.state = "done";
          if (view) {
            views.push({ el: view, title: viewTitle(name, entry.input, output) });
            placeViews();
          }
          refresh();
        },
        fail(message) {
          note.fail(message);
          entry.state = "done";
          refresh();
        },
        abort() {
          note.abort();
          entry.state = "aborted";
          refresh();
        },
      };
    },
  };
}

/* ─────────────────────────────── Confirmação ────────────────────────────── */

// Cada operação que grava dados chega como uma interrupção do AG-UI e vira um
// cartão: o usuário confere, corrige se quiser e confirma ou cancela. Quando
// todas as operações do passo estão decididas, as respostas vão juntas, no
// `resume` de uma execução nova, e o turno continua.

// Cartões por tool call, para o resultado da operação encontrar o seu.
const approvalCards = new Map();

const OPERATION_STATUS = {
  pending: "aguardando confirmação",
  approved: "confirmada",
  cancelled: "cancelada",
  completed: "gravada",
  failed: "não gravada",
  expired: "não confirmada",
};

// Campos opcionais chegam como `anyOf: [tipo, null]`; o que interessa é o tipo.
// Os rótulos (`x-labels`) podem estar no campo ou no tipo, conforme o schema.
function fieldSchema(property) {
  const inner = (property.anyOf || []).find((option) => option.type !== "null") || property;
  return {
    ...inner,
    title: property.title || inner.title,
    description: property.description || inner.description,
    "x-labels": property["x-labels"] || inner["x-labels"],
    "x-empty-label": property["x-empty-label"] || inner["x-empty-label"],
  };
}

// Sem acentos e sem caixa: "dolar" encontra "Dólar americano".
function searchable(text) {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

let comboCount = 0;

// Altura máxima da lista aberta, se houver espaço para tanto.
const COMBO_MAX_HEIGHT = 224;

// Lista com busca: digitar filtra pelo código ou pelo nome, e só um valor da
// lista pode ser escolhido. Expõe a mesma interface dos campos nativos
// (`value`, `disabled`, `checkValidity`), então o cartão não distingue os dois.
function comboBox(key, field, value, required) {
  const labels = field["x-labels"] || {};
  const options = [
    // Um campo opcional começa com a opção de deixá-lo em branco.
    ...(required ? [] : [{ value: "", label: field["x-empty-label"] || "Nenhuma" }]),
    ...field.enum.map((option) => ({ value: option, label: labels[option] || option })),
  ];
  const id = `combo-${++comboCount}`;

  const wrap = document.createElement("div");
  wrap.className = "combo";

  const input = document.createElement("input");
  input.type = "text";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", id);

  const list = document.createElement("ul");
  list.id = id;
  list.className = "combo-list";
  list.setAttribute("role", "listbox");
  list.hidden = true;

  // A lista não fica dentro do campo: cada turno da conversa cria o próprio
  // contexto de empilhamento (a animação de entrada usa `transform`), e ela
  // ficaria atrás do turno seguinte e da caixa de pergunta. Aberta, ela vai para
  // o `body` com posição fixa; fechada, sai dele.
  wrap.append(input);

  let current = value ?? "";
  let shown = [];
  let active = -1;

  const labelOf = (option) => options.find((item) => item.value === option)?.label ?? "";

  const highlight = (index) => {
    active = index;
    list.querySelectorAll(".combo-option").forEach((item, position) => {
      item.classList.toggle("is-active", position === index);
    });
    const item = list.querySelector(".combo-option.is-active");
    if (item) {
      input.setAttribute("aria-activedescendant", item.id);
      item.scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  };

  // Abre para o lado com mais espaço na tela: para baixo ou para cima, e
  // alinhada à esquerda do campo ou, se não couber, à direita. O espaço útil
  // desconta o cabeçalho e a caixa de pergunta, que ficam por cima da conversa.
  const place = () => {
    const field = input.getBoundingClientRect();
    const margin = 8;
    const ceiling = (document.querySelector(".topbar")?.getBoundingClientRect().bottom ?? 0) + margin;
    const floor = (document.querySelector(".composer")?.getBoundingClientRect().top ?? window.innerHeight) - margin;

    list.style.minWidth = `${field.width}px`;
    list.style.maxHeight = "";
    const wanted = Math.min(list.scrollHeight, COMBO_MAX_HEIGHT);
    const below = floor - field.bottom - 4;
    const above = field.top - ceiling - 4;
    const down = below >= wanted || below >= above;

    list.style.maxHeight = `${Math.max(Math.min(wanted, down ? below : above), 72)}px`;
    list.style.top = down ? `${field.bottom + 4}px` : "";
    list.style.bottom = down ? "" : `${window.innerHeight - field.top + 4}px`;
    list.dataset.side = down ? "below" : "above";

    const width = list.offsetWidth;
    const right = document.documentElement.clientWidth - margin;
    let left = field.left;
    if (left + width > right) left = Math.max(margin, Math.min(field.right, right) - width);
    list.style.left = `${left}px`;
  };

  const close = () => {
    list.hidden = true;
    list.remove();
    window.removeEventListener("scroll", place, true);
    window.removeEventListener("resize", place);
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    // Texto digitado que não virou escolha some: vale o que está selecionado.
    input.value = labelOf(current);
  };

  const choose = (option) => {
    current = option.value;
    input.setCustomValidity("");
    close();
  };

  const render = (query) => {
    const wanted = searchable(query.trim());
    shown = wanted
      ? options.filter((option) => searchable(`${option.value} ${option.label}`).includes(wanted))
      : options;

    list.replaceChildren(...shown.map((option, index) => {
      const item = document.createElement("li");
      item.id = `${id}-${index}`;
      item.className = "combo-option";
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", String(option.value === current));
      item.textContent = option.label;
      // `mousedown`, e não `click`: o clique tiraria o foco antes e fecharia a lista.
      item.addEventListener("mousedown", (event) => {
        event.preventDefault();
        choose(option);
      });
      return item;
    }));
    if (!shown.length) {
      const empty = document.createElement("li");
      empty.className = "combo-empty";
      empty.textContent = "Nenhuma opção encontrada";
      list.append(empty);
    }
    highlight(wanted ? (shown.length ? 0 : -1) : shown.findIndex((option) => option.value === current));
  };

  const show = () => {
    document.body.append(list);
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    place();
    // A lista acompanha o campo se a página rolar ou a janela mudar de tamanho.
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
  };

  const open = () => {
    if (input.disabled || !list.hidden) return;
    render("");
    show();
    input.select();
  };

  input.addEventListener("focus", open);
  input.addEventListener("click", open);
  input.addEventListener("blur", close);
  input.addEventListener("input", () => {
    render(input.value);
    if (list.hidden) show();
    else place();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (list.hidden) return open();
      if (!shown.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      highlight((active + step + shown.length) % shown.length);
    } else if (event.key === "Enter") {
      if (list.hidden) return;
      event.preventDefault();
      if (shown[active]) choose(shown[active]);
    } else if (event.key === "Escape" && !list.hidden) {
      event.preventDefault();
      close();
    }
  });

  input.value = labelOf(current);

  return {
    element: wrap,
    control: {
      name: key,
      type: "combobox",
      get value() {
        return current;
      },
      set value(option) {
        current = option ?? "";
        input.value = labelOf(current);
      },
      get disabled() {
        return input.disabled;
      },
      set disabled(locked) {
        input.disabled = locked;
        if (locked) close();
      },
      checkValidity() {
        const valid = !required || current !== "";
        input.setCustomValidity(valid ? "" : "Escolha uma opção da lista.");
        return valid;
      },
      reportValidity() {
        input.reportValidity();
      },
    },
  };
}

function fieldControl(key, property, value, required) {
  const field = fieldSchema(property);

  let element;
  let control;
  if (field.enum) {
    ({ element, control } = comboBox(key, field, value, required));
  } else {
    control = document.createElement("input");
    if (field.format === "date") control.type = "date";
    else if (field.type === "number" || field.type === "integer") {
      control.type = "number";
      control.step = "any";
    } else control.type = "text";
    control.name = key;
    control.required = required;
    control.value = value ?? "";
    element = control;
  }

  const label = document.createElement("label");
  label.className = "approval-field";
  if (field.description) label.title = field.description;

  const caption = document.createElement("span");
  caption.textContent = required ? field.title || key : `${field.title || key} (opcional)`;

  label.append(caption, element);
  return { label, control };
}

function approvalCard(request, onDecide) {
  const card = document.createElement("article");
  card.className = "approval-card";

  const head = document.createElement("div");
  head.className = "approval-head";
  const title = document.createElement("span");
  title.className = "approval-title";
  title.textContent = request.title;

  // Os campos travados (o ticker) vão para o cabeçalho, como texto: um ativo
  // errado se resolve cancelando e pedindo a correção ao agente.
  const locked = new Set(request.locked || []);
  for (const key of locked) {
    if (request.args[key] == null) continue;
    const subject = document.createElement("span");
    subject.className = "approval-subject";
    subject.textContent = request.args[key];
    subject.title = "Para trocar o ativo, cancele e peça a correção ao agente.";
    title.append(subject);
  }

  const status = document.createElement("span");
  status.className = "approval-status";
  head.append(title, status);

  const form = document.createElement("div");
  form.className = "approval-fields";
  const required = new Set(request.schema.required || []);
  const controls = Object.entries(request.schema.properties)
    .filter(([key]) => !locked.has(key))
    .map(([key, property]) => {
      const { label, control } = fieldControl(key, property, request.args[key], required.has(key));
      form.append(label);
      return control;
    });

  const message = document.createElement("div");
  message.className = "approval-message";
  message.hidden = true;

  const actions = document.createElement("div");
  actions.className = "approval-actions";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "approval-button";
  cancel.textContent = "Cancelar";
  const confirm = document.createElement("button");
  confirm.type = "button";
  confirm.className = "approval-button is-primary";
  confirm.textContent = "Confirmar";
  actions.append(cancel, confirm);

  card.append(head, form, message, actions);

  const view = {
    root: card,
    request,
    decision: null,

    // Os valores como o usuário os deixou: número vira número, vazio vira nulo.
    values() {
      const args = {};
      for (const key of locked) args[key] = request.args[key];
      for (const control of controls) {
        if (control.value === "") args[control.name] = null;
        else if (control.type === "number") args[control.name] = Number(control.value);
        else args[control.name] = control.value;
      }
      return args;
    },

    setStatus(name, detail = null) {
      card.dataset.status = name;
      status.textContent = OPERATION_STATUS[name];
      message.hidden = !detail;
      message.textContent = detail || "";
    },

    lock(locked) {
      for (const control of controls) control.disabled = locked;
      actions.hidden = locked;
    },

    fill(args) {
      for (const control of controls) control.value = args[control.name] ?? "";
    },
  };

  const decide = (decision) => {
    // Um campo obrigatório vazio é recusado aqui, antes de ir ao servidor.
    if (decision === "approved") {
      const invalid = controls.find((control) => !control.checkValidity());
      if (invalid) {
        invalid.reportValidity();
        return;
      }
    }
    view.decision = decision;
    view.lock(true);
    view.setStatus(decision);
    onDecide();
  };
  cancel.addEventListener("click", () => decide("cancelled"));
  confirm.addEventListener("click", () => decide("approved"));

  approvalCards.set(request.tool_call_id, view);
  view.setStatus("pending");
  return view;
}

// `stored` vem do histórico: decisões e resultados já gravados. Sem ele, o
// grupo acabou de chegar pelo stream e espera o usuário.
function approvalGroup(requests, stored = null) {
  const group = document.createElement("div");
  group.className = "approval-group";
  // As interrupções que o grupo responde: uma pergunta nova as cancela.
  group.interruptIds = requests.map((request) => request.interrupt_id);

  const note = document.createElement("div");
  note.className = "approval-error";
  note.hidden = true;

  const pending = !stored || stored.state === "awaiting_approval";
  group.classList.toggle("is-pending", pending);

  const cards = requests.map((request) => approvalCard(request, () => {
    if (cards.every((card) => card.decision)) submitApprovals(group, note, cards);
  }));
  for (const card of cards) group.append(card.root);
  group.append(note);

  if (!pending) {
    for (const card of cards) {
      const decision = stored.decisions?.[card.request.tool_call_id];
      const result = stored.results?.[card.request.tool_call_id];
      card.lock(true);
      if (!decision) card.setStatus("expired");
      else if (!decision.approved) card.setStatus("cancelled");
      else {
        card.fill(decision.args);
        card.setStatus(result?.status === "failed" ? "failed" : result ? "completed" : "approved", result?.message);
      }
    }
  }
  return group;
}

async function submitApprovals(group, note, cards) {
  // O cartão aparece pouco antes do fim do stream; um clique rápido espera ele fechar.
  while (streaming) await new Promise((resolve) => setTimeout(resolve, 100));
  group.classList.remove("is-pending");
  note.hidden = true;

  // No padrão do AG-UI: `approved` e, confirmada, `editedArgs` com os valores
  // inteiros como o usuário os deixou.
  const resume = cards.map((card) => ({
    interruptId: card.request.interrupt_id,
    status: "resolved",
    payload: card.decision === "approved" ? { approved: true, editedArgs: card.values() } : { approved: false },
  }));

  const body = group.closest(".turn-body");
  await runAgent({ resume }, () => body, {
    onRefused(code, message) {
      if (code === "http_401") return false;
      note.hidden = false;
      note.textContent = message || "Não foi possível enviar a confirmação.";
      if (code === "invalid_args") {
        // Valor recusado: os cartões voltam a ser editáveis para a correção.
        group.classList.add("is-pending");
        for (const card of cards) {
          card.decision = null;
          card.lock(false);
          card.setStatus("pending");
        }
      } else {
        for (const card of cards) card.setStatus("expired");
      }
      return true;
    },
  });
}

// Uma pergunta nova no lugar da resposta ao cartão encerra a confirmação.
// Devolve as interrupções canceladas, que vão no `resume` da pergunta.
function abandonPendingApprovals() {
  const resume = [];
  for (const group of thread.querySelectorAll(".approval-group.is-pending")) {
    resume.push(...group.interruptIds.map((interruptId) => ({ interruptId, status: "cancelled" })));
    group.classList.remove("is-pending");
    for (const card of group.querySelectorAll(".approval-card")) {
      card.querySelectorAll("input, select").forEach((control) => { control.disabled = true; });
      card.querySelector(".approval-actions").hidden = true;
      card.dataset.status = "expired";
      card.querySelector(".approval-status").textContent = OPERATION_STATUS.expired;
    }
  }
  return resume;
}

/* ─────────────────────────── Cartões de ticker ──────────────────────────── */

const PRICE_FORMAT = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const MINUS = "−"; // sinal de menos tipográfico, não hífen

function signedNumber(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const formatted = PRICE_FORMAT.format(Math.abs(value));
  return `${value < 0 ? MINUS : "+"}${formatted}`;
}

// A hora vem com o fuso da bolsa ("…T17:39:03-03:00"). Lemos direto da string
// para não converter para o fuso de quem está olhando.
function quoteTime(iso) {
  if (typeof iso !== "string") return "";
  const match = iso.match(/T(\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?/);
  if (!match) return "";

  const [, time, offset] = match;
  if (!offset || offset === "Z") return `${time} (GMT)`;

  const hours = Number(offset.slice(1, 3));
  const minutes = offset.slice(4, 6);
  const suffix = minutes === "00" ? `${hours}` : `${hours}:${minutes}`;
  return `${time} (GMT${offset[0]}${suffix})`;
}

function tickerCard(data) {
  const card = document.createElement("article");
  card.className = "ticker-card";

  const change = signedNumber(data.change);
  const percent = signedNumber(data.change_percent);
  const direction = typeof data.change === "number" && data.change < 0 ? "is-down" : "is-up";

  const variation = change
    ? `<span class="tc-change ${direction}">${change}${percent ? ` (${percent}%)` : ""}</span>`
    : "<span class=\"tc-change\"></span>";

  card.innerHTML =
    `<span class="tc-currency">${escapeHtml(data.currency || "")}</span>` +
    `<span class="tc-time">${escapeHtml(quoteTime(data.quoted_at))}</span>` +
    `<span class="tc-symbol">${escapeHtml(data.symbol || "")}</span>` +
    `<span class="tc-price">${typeof data.price === "number" ? PRICE_FORMAT.format(data.price) : ""}</span>` +
    `<span class="tc-name"><span class="tc-name-text">${escapeHtml(data.name || "")}</span></span>` +
    variation;

  return card;
}

// O balão só aparece onde o nome realmente não coube. A medição precisa
// acontecer com a grade visível — escondida, scrollWidth vale zero.
function markTruncatedNames(grid) {
  for (const name of grid.querySelectorAll(".tc-name")) {
    const text = name.firstElementChild;
    if (text && text.scrollWidth > text.clientWidth + 1) {
      name.dataset.full = text.textContent;
      name.tabIndex = 0; // alcançável por teclado
    } else {
      delete name.dataset.full;
      name.removeAttribute("tabindex");
    }
  }
}

function tickerPanel(cards) {
  const wrapper = document.createElement("div");
  wrapper.className = "ticker-panel";

  const reveal = document.createElement("div");
  reveal.className = "ticker-reveal";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "reveal-toggle";
  toggle.setAttribute("aria-expanded", "false");
  toggle.innerHTML =
    `<span>Ver ${cards.length === 1 ? "ticker mencionado" : "tickers mencionados"}</span>` +
    '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M6 9l6 6 6-6"/></svg>';

  const grid = document.createElement("div");
  grid.className = "ticker-grid";
  grid.hidden = true;
  for (const data of cards) grid.append(tickerCard(data));

  toggle.addEventListener("click", () => {
    const opening = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(opening));
    grid.hidden = !opening;
    wrapper.classList.toggle("is-open", opening);

    if (opening) {
      markTruncatedNames(grid);
    } else {
      // Ao recolher, o documento encurta e a rolagem pararia num ponto
      // qualquer; trazemos o fim da resposta de volta para a tela.
      const suave = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      reveal.scrollIntoView({ behavior: suave ? "smooth" : "auto", block: "center" });
    }
  });

  reveal.append(toggle);
  wrapper.append(reveal, grid);
  return wrapper;
}

function addTurn(role, label) {
  const turn = document.createElement("section");
  turn.className = `turn turn-${role}`;

  const heading = document.createElement("div");
  heading.className = "turn-label";
  heading.textContent = label;

  const body = document.createElement("div");
  body.className = "turn-body";

  turn.append(heading, body);
  thread.append(turn);
  return body;
}

function scrollToEnd() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

function errorNote(message) {
  const note = document.createElement("div");
  note.className = "error-note";
  note.textContent = message;
  return note;
}

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
function addTurnActions(body, messageId, state, thinkingMs = 0) {
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
function thinkingNote(startedAt) {
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

function forkNote() {
  const note = document.createElement("div");
  note.className = "fork-note";
  note.textContent = "bifurcação · a conversa continua daqui";
  return note;
}

/* ─────────────────────────────────── AG-UI ──────────────────────────────── */

// O agente fala AG-UI: cada execução é um POST com o `RunAgentInput` e volta
// como eventos SSE. O servidor guarda o histórico; daqui vai só a pergunta nova
// (ou a regeneração, ou a resposta à confirmação). Os extras do Graham chegam
// em `metadata.graham` de cada evento e mensagem.

// O AG-UI espera do cliente os ids da conversa, da execução e da mensagem.
// `crypto.randomUUID` só existe em contexto seguro (https ou localhost).
function newId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function extras(item) {
  return item?.metadata?.graham || {};
}

function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// O retorno de uma ferramenta, para o detalhe da consulta: um retorno enorme
// travaria a tela, então vira um aviso.
const MAX_TOOL_PREVIEW = 20_000;

function toolOutput(content) {
  if (typeof content === "string" && content.length > MAX_TOOL_PREVIEW) {
    return { aviso: "Resultado longo demais para exibir por inteiro.", caracteres: content.length };
  }
  return parseJson(content) ?? content;
}

// O cartão de confirmação a partir de uma interrupção do AG-UI.
function approvalRequest(interrupt) {
  const meta = extras(interrupt);
  return {
    interrupt_id: interrupt.id,
    tool_call_id: interrupt.toolCallId,
    name: meta.name,
    args: meta.args || {},
    locked: meta.locked || [],
    title: interrupt.message,
    schema: interrupt.responseSchema.properties.editedArgs,
  };
}

/* ─────────────────────────────── Histórico gravado ──────────────────────── */

// Agrupa as mensagens em turnos: cada pergunta sozinha e, depois dela, as
// mensagens do assistente e das ferramentas até a pergunta seguinte.
function snapshotTurns(messages) {
  const turns = [];
  for (const message of messages) {
    if (message.role === "user" || !turns.length || turns.at(-1)[0].role === "user") turns.push([message]);
    else turns.at(-1).push(message);
  }
  return turns;
}

// `live`: uma execução em andamento continua este turno (a retomada depois de
// uma confirmação); ele ainda não terminou, então fica sem regerar nem bifurcar.
function renderStoredTurn(messages, live = false) {
  const first = messages[0];
  if (first.role === "user") {
    addTurn("user", "Você").textContent = first.content;
    return null;
  }

  const body = addTurn("agent", "Graham Agent");
  const results = new Map();
  for (const message of messages) {
    if (message.role === "tool") results.set(message.toolCallId, message);
  }
  // O resultado de cada operação confirmada ou cancelada, por tool call.
  const operations = {};
  for (const [id, message] of results) {
    const status = extras(message).status;
    operations[id] = { status, message: status === "failed" ? message.content : null };
  }

  let run = null;
  for (const message of messages) {
    if (message.role !== "assistant") continue;
    if (message.content) {
      run = null;
      const text = document.createElement("div");
      text.className = "answer-block";
      text.innerHTML = renderMarkdown(message.content);
      body.append(text);
    }
    for (const call of message.toolCalls || []) {
      // As operações aparecem no cartão de confirmação, não como consulta.
      if (extras(call).approval) continue;
      if (!run) {
        run = toolRun();
        body.append(run.root);
      }
      const note = run.add(call.function.name, parseJson(call.function.arguments));
      const result = results.get(call.id);
      if (!result) note.abort();
      else if (extras(result).status === "failed") note.fail(result.content);
      else note.finish(toolOutput(result.content), extras(result).artifact);
    }
    const approval = extras(message).approval;
    if (approval) {
      run = null;
      body.append(approvalGroup(approval.interrupts.map(approvalRequest), {
        state: extras(message).state,
        decisions: approval.decisions,
        results: operations,
      }));
    }
  }

  // Um turno que parou entre uma ferramenta e outra, sem a mensagem que o
  // fecha, também conta como interrompido — inclusive logo depois de uma
  // confirmação, antes de as operações rodarem.
  const last = messages.at(-1);
  const finished = last.role === "assistant" && !last.toolCalls?.length;
  let state = finished ? extras(last).state : "interrupted";
  if (extras(last).approval && state === "completed") state = "interrupted";
  const thinkingMs = messages.reduce((total, message) => total + (extras(message).thinkingMs || 0), 0);

  body.closest(".turn").dataset.messageId = last.id;
  if (!live && state !== "awaiting_approval") addTurnActions(body, last.id, state, thinkingMs);
  return body;
}

// Redesenha a conversa a partir do `MESSAGES_SNAPSHOT` e devolve onde a
// execução em andamento, se houver, continua escrevendo.
function renderSnapshot(event) {
  const { forkedFromMessageId, activeRunId } = extras(event);
  clearConversation();
  if (!event.messages.length) {
    showEmpty();
    return null;
  }
  showConversation();
  const turns = snapshotTurns(event.messages);
  let lastBody = null;
  turns.forEach((messages, index) => {
    const live = Boolean(activeRunId) && index === turns.length - 1;
    lastBody = renderStoredTurn(messages, live);
    if (messages.at(-1).id === forkedFromMessageId) thread.append(forkNote());
  });
  window.scrollTo({ top: document.body.scrollHeight });
  return lastBody;
}

async function openThread(id) {
  const view = currentView;
  // Religa a conversa: o snapshot gravado e, se houver, a execução em
  // andamento, que continua o último turno ou abre um novo.
  let continued = null;
  await streamTurn(
    (signal) => fetch("/api/agent/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ threadId: id }),
      signal,
    }),
    () => continued || addTurn("agent", "Graham Agent"),
    {
      onSnapshot(event) {
        if (view !== currentView) return;
        threadId = id;
        storeThreadId(id);
        markCurrentThread();
        continued = renderSnapshot(event);
      },
      onRefused(code) {
        if (view !== currentView) return true;
        if (code === "http_401") return false;
        // Conversa de outra sessão ou apagada: começa do zero.
        threadId = null;
        storeThreadId(null);
        showEmpty();
        return true;
      },
    },
  );
}

/* ─────────────────────────────────── Envio ──────────────────────────────── */

// Desenha uma execução do agente dentro de `body`, evento por evento. A
// resposta é montada em blocos na ordem em que acontece: o modelo pode falar,
// consultar ferramentas e voltar a falar.
function liveTurn(body, onRefused) {
  let block = null;
  let blockText = "";

  // A rodada de consultas em curso: termina quando o agente volta a falar.
  let run = null;

  // A linha "pensando" da chamada ao modelo em curso, e o total do turno.
  let thinking = null;
  let thinkingMs = 0;

  // As consultas em andamento, por tool call, com os argumentos que chegam aos
  // pedaços; as operações, que viram cartões na pausa, ficam de fora.
  const calls = new Map();

  // Cartões dos tickers citados, enviados depois que a resposta termina.
  const tickers = [];

  const openBlock = () => {
    if (!block) {
      run = null;
      block = document.createElement("div");
      block.className = "answer-block caret";
      blockText = "";
      body.append(block);
    }
    return block;
  };

  const closeBlock = () => {
    if (block) block.classList.remove("caret");
    block = null;
    blockText = "";
  };

  const turn = {
    // Como a execução terminou: a mensagem que fecha o turno e o estado dele.
    outcome: null,

    handle(event) {
      switch (event.type) {
        case "RUN_STARTED":
          refreshThreadList(); // o indicador de "respondendo" acende
          break;

        case "REASONING_START":
          thinking?.stop();
          closeBlock();
          // A hora de início vem do servidor: quem reconecta no meio continua a contagem.
          thinking = thinkingNote(event.timestamp || Date.now());
          body.append(thinking.el);
          scrollToEnd();
          break;

        case "REASONING_END":
          thinking?.stop();
          thinking = null;
          thinkingMs += extras(event).ms || 0;
          break;

        case "TEXT_MESSAGE_START":
          closeBlock();
          openBlock();
          break;

        case "TEXT_MESSAGE_CONTENT":
          openBlock();
          blockText += event.delta;
          block.innerHTML = renderMarkdown(blockText);
          scrollToEnd();
          break;

        case "TEXT_MESSAGE_END":
          closeBlock();
          break;

        case "TOOL_CALL_START": {
          if (extras(event).approval) break;
          // O que já foi dito fica fechado acima do aviso.
          closeBlock();
          if (!run) {
            run = toolRun();
            body.append(run.root);
          }
          calls.set(event.toolCallId, { note: run.add(event.toolCallName, null), args: "" });
          scrollToEnd();
          break;
        }

        case "TOOL_CALL_ARGS": {
          const call = calls.get(event.toolCallId);
          if (call) call.args += event.delta;
          break;
        }

        case "TOOL_CALL_END": {
          const call = calls.get(event.toolCallId);
          if (call) call.note.update(parseJson(call.args));
          break;
        }

        case "TOOL_CALL_RESULT": {
          const { status, artifact } = extras(event);
          const call = calls.get(event.toolCallId);
          if (call) {
            if (status === "failed") call.note.fail(event.content);
            else call.note.finish(toolOutput(event.content), artifact);
            calls.delete(event.toolCallId);
          } else {
            approvalCards.get(event.toolCallId)?.setStatus(status, status === "failed" ? event.content : null);
          }
          break;
        }

        case "CUSTOM":
          if (event.name === "graham.tickers") tickers.push(...event.value);
          break;

        case "RUN_FINISHED": {
          const interrupts = event.outcome?.type === "interrupt" ? event.outcome.interrupts : null;
          turn.outcome = {
            messageId: extras(event).messageId,
            state: interrupts ? "awaiting_approval" : "completed",
          };
          if (interrupts) {
            closeBlock();
            run = null;
            body.append(approvalGroup(interrupts.map(approvalRequest)));
            scrollToEnd();
          }
          break;
        }

        case "RUN_ERROR":
          // Com `code`, o servidor recusou a entrada sem executar nada (ou parou
          // no meio, `interrupted`); sem ele, a execução falhou.
          turn.outcome = {
            messageId: extras(event).messageId,
            state: event.code === "interrupted" ? "interrupted" : "failed",
            refused: Boolean(event.code) && event.code !== "interrupted",
          };
          if (!(turn.outcome.refused && onRefused?.(event.code, event.message))) {
            body.append(errorNote(event.message));
          }
          break;
      }
    },

    finish() {
      thinking?.stop();
      closeBlock();
      if (tickers.length) body.append(tickerPanel(tickers));
      // Uma ferramenta que nunca respondeu não pode ficar pulsando para sempre.
      for (const call of calls.values()) call.note.abort();
      const outcome = turn.outcome;
      if (outcome?.messageId && outcome.state !== "awaiting_approval" && outcome.state !== "interrupted") {
        addTurnActions(body, outcome.messageId, outcome.state, thinkingMs);
      }
    },
  };
  return turn;
}

// Transmite uma execução: uma pergunta nova, uma resposta regerada, a
// continuação depois da confirmação ou a religação a uma conversa (`connect`).
// `start(signal)` faz o pedido; `target()` diz em que turno a execução escreve,
// e só é chamado quando ela começa. `onRefused(code, message)` recebe as
// recusas (HTTP, como `http_409`, ou `RUN_ERROR` com código) e devolve se as
// tratou; `onSnapshot` recebe o `MESSAGES_SNAPSHOT` de um `connect`.
async function streamTurn(start, target, { onRefused, onSnapshot } = {}) {
  // Trocar de conversa larga esta leitura (a execução segue no servidor); daí
  // em diante, ela não mexe mais na tela nem no estado, que já são de outra.
  const reading = new AbortController();
  currentReading = reading;
  const detached = () => reading.signal.aborted;

  // Uma execução pedida daqui trava o envio já no clique; num `connect`, só se
  // houver uma execução em andamento.
  if (!onSnapshot) {
    setStreaming(true);
    scrollToEnd();
  }

  // A execução que esta leitura desenha, criada no RUN_STARTED dela. Num
  // `connect`, a primeira execução só ressincroniza: o snapshot e o fim.
  let turn = null;
  let body = null;
  let syncing = Boolean(onSnapshot);

  // O id da execução e o do último evento: com os dois, a leitura retoma
  // exatamente de onde parou se a conexão cair.
  let runId = null;
  let lastEventId = null;

  const dispatch = (event) => {
    if (syncing) {
      if (event.type === "MESSAGES_SNAPSHOT") onSnapshot(event);
      else if (event.type === "RUN_FINISHED" || event.type === "RUN_ERROR") syncing = false;
      return;
    }
    if (!turn) {
      body = target();
      turn = liveTurn(body, onRefused);
      setStreaming(true);
      scrollToEnd();
    }
    if (event.type === "RUN_STARTED") runId = event.runId;
    turn.handle(event);
  };

  // Lê um corpo SSE até ele acabar; lança se a conexão cair no meio.
  const read = async (response) => {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;

      buffer += decoder.decode(value, { stream: true });

      // Cada frame SSE termina em linha em branco.
      let split;
      while ((split = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, split);
        buffer = buffer.slice(split + 2);

        // Comentários (`: ping`) só mantêm a conexão viva.
        const raw = frame.match(/^data:\s*(.*)$/m)?.[1];
        if (raw === undefined) continue;
        if (detached()) return;

        const event = parseJson(raw);
        if (!event?.type) continue; // um frame malformado não derruba o resto da resposta
        const id = frame.match(/^id:\s*(.+)$/m)?.[1];
        if (id) lastEventId = id;
        dispatch(event);
      }
    }
  };

  const ended = () => Boolean(turn?.outcome);

  try {
    let response = await start(reading.signal);

    if (response.status === 401 && !onRefused?.("http_401")) {
      signedOut();
      return;
    }
    if (!response.ok || !response.body) {
      let detail = null;
      try {
        detail = (await response.json()).detail;
      } catch {
        /* sem corpo legível */
      }
      if (onRefused?.(`http_${response.status}`, detail)) return;
      throw new Error(typeof detail === "string" ? detail : `O servidor respondeu ${response.status}.`);
    }

    // A execução roda no servidor independente desta conexão. Se ela cair, a
    // leitura reconecta e continua do último evento recebido.
    for (let attempt = 0; !detached(); attempt++) {
      if (attempt > 0) {
        if (!runId || ended() || attempt > 3) break;
        await new Promise((resolve) => setTimeout(resolve, 1000 * attempt));
        if (detached()) break;
        try {
          response = await fetch(`/api/agent/runs/${runId}/events`, {
            headers: lastEventId ? { "Last-Event-ID": lastEventId } : {},
            signal: reading.signal,
          });
        } catch {
          continue;
        }
        if (!response.ok || !response.body) break;
      }
      try {
        await read(response);
        // Sem execução viva (um `connect` só de snapshot), o fim do corpo é o fim.
        if (!turn || ended()) break;
      } catch {
        /* a conexão caiu; a próxima volta reconecta */
      }
    }
    if (turn && !ended() && !detached()) throw new Error("A conexão caiu antes do fim da resposta.");
  } catch (error) {
    if (!detached()) {
      body = body || target();
      body.append(errorNote(`Não foi possível completar a consulta. ${error.message}`));
    }
  } finally {
    if (currentReading === reading) currentReading = null;
    if (!detached()) {
      turn?.finish();
      setStreaming(false);
      input.focus();
      if (turn) refreshThreadList();
    }
  }
  if (detached()) return;

  // O servidor parou no meio da execução: o que ficou gravado (e marcado como
  // interrompido) está no banco.
  if (turn?.outcome?.state === "interrupted" && threadId) await openThread(threadId);
}

// Uma execução nova na conversa atual. Os campos que faltam são os padrões do
// `RunAgentInput`: o servidor ignora ferramentas, contexto e estado do cliente.
function runAgent(input, target, options) {
  const payload = {
    threadId,
    runId: newId(),
    messages: [],
    tools: [],
    context: [],
    state: null,
    forwardedProps: {},
    ...input,
  };
  return streamTurn(
    (signal) => fetch("/api/agent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    }),
    target,
    options,
  );
}

async function ask(question) {
  if (streaming) return;
  showConversation();
  // Uma pergunta nova no lugar da resposta ao cartão encerra a confirmação; o
  // AG-UI pede que ela vá cancelada junto.
  const resume = abandonPendingApprovals();

  // A conversa nasce aqui: o id é do cliente, e o servidor a cria com ele.
  if (!threadId) {
    threadId = newId();
    storeThreadId(threadId);
  }
  addTurn("user", "Você").textContent = question;
  const body = addTurn("agent", "Graham Agent");
  await runAgent(
    { messages: [{ id: newId(), role: "user", content: question }], ...(resume.length ? { resume } : {}) },
    () => body,
  );
}

async function regenerate(turn) {
  if (streaming) return;
  const resume = abandonPendingApprovals();

  // A nova resposta substitui esta e tudo o que veio depois dela: no servidor,
  // ela nasce como irmã desta, e o caminho ativo passa a seguir por ela.
  const messageId = turn.dataset.messageId;
  let node = turn;
  while (node) {
    const next = node.nextElementSibling;
    node.remove();
    node = next;
  }

  const body = addTurn("agent", "Graham Agent");
  await runAgent(
    { forwardedProps: { graham: { regenerate: messageId } }, ...(resume.length ? { resume } : {}) },
    () => body,
  );
}

async function fork(turn) {
  if (streaming) return;

  try {
    const response = await fetch(`/api/threads/${threadId}/fork`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id: turn.dataset.messageId }),
    });
    if (!response.ok) throw new Error(`O servidor respondeu ${response.status}.`);

    const { id } = await response.json();
    leaveView();
    await openThread(id);
    refreshThreadList();
    input.focus();
  } catch (error) {
    turn.querySelector(".turn-body").append(
      errorNote(`Não foi possível bifurcar a conversa. ${error.message}`),
    );
  }
}

/* ────────────────────────────────── Interação ───────────────────────────── */

function submit() {
  const question = input.value.trim();
  if (!question || streaming) return;
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

function resize() {
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
    if (threadId) await openThread(threadId);
  } catch {
    // Sem servidor, fica a entrada; o erro aparece ao tentar entrar.
    signedOut();
  } finally {
    setStreaming(false);
    input.focus();
  }
}

boot();
