import { thread } from "./state.js";

/* ──────────────────────────────── Peças da conversa ─────────────────────── */

const TOOL_NAMES = {
  cotacao_atual_acao: "cotação atual",
  proventos: "proventos",
  desempenho: "desempenho",
  agenda_eventos: "agenda de eventos",
  ver_enquadramento: "enquadramento",
  sugerir_rebalanceamento: "rebalanceamento",
  definir_alocacao: "alocação-alvo",
  definir_classe_ativo: "classe do ativo",
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
export const WORKING_LABELS = {
  guardar_memoria: "guardando na memória",
  esquecer_memoria: "esquecendo memória",
};

export const DONE_LABELS = {
  guardar_memoria: "memória · guardada",
  esquecer_memoria: "memória · esquecida",
};

export function toolLabel(name) {
  return TOOL_NAMES[name] || name.replace(/_/g, " ");
}

export function toolSubject(payload) {
  if (!payload || typeof payload !== "object") return "";
  const value = payload.ticker_name
    || (Array.isArray(payload.tickers) && payload.tickers.join(", "))
    || payload.company_name || payload.industry || payload.query || payload.name || payload.region;
  return value ? ` · ${value}` : "";
}

export const MINUS = "−"; // sinal de menos tipográfico, não hífen

export function addTurn(role, label) {
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

export function scrollToEnd() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

export function errorNote(message) {
  const note = document.createElement("div");
  note.className = "error-note";
  note.textContent = message;
  return note;
}
