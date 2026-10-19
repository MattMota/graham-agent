import { input, session, storeThreadId } from "./state.js";
import { leaveView, showEmpty } from "./screen.js";
import { clearThreadList, refreshThreadList } from "./sidebar.js";

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

export function signedIn(email) {
  document.body.dataset.auth = "in";
  signOutButton.title = `Sair de ${email}`;
  refreshThreadList();
}

// Sem sessão (nunca entrou, saiu ou ela venceu): só a entrada fica na tela, e
// a conversa aberta sai junto, porque era da conta anterior.
export function signedOut() {
  leaveView();
  clearThreadList();
  session.threadId = null;
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
