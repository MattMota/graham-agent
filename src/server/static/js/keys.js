import { signedOut } from "./account.js";
import { closeSidebar, relativeTime, SHORT_DATE } from "./sidebar.js";

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
