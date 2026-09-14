// Graham — cliente da interface: envia perguntas e desenha os eventos SSE
// que chegam do servidor.

const app = document.getElementById("app");
const thread = document.getElementById("thread");
const hero = document.getElementById("hero");
const composer = document.getElementById("composer");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");
const newChatButton = document.getElementById("new-chat");
const topbarMark = document.getElementById("topbar-mark");

let streaming = false;

/* ─────────────────────────────── Identidade da conversa ─────────────────── */

const THREAD_KEY = "graham.thread_id";

function storeThreadId(id) {
  try {
    localStorage.setItem(THREAD_KEY, id);
  } catch {
    // Navegação privativa ou storage bloqueado: a conversa vive só nesta aba.
  }
}

function initialThreadId() {
  try {
    const saved = localStorage.getItem(THREAD_KEY);
    if (saved) return saved;
  } catch {
    /* segue com um id novo */
  }
  const fresh = crypto.randomUUID();
  storeThreadId(fresh);
  return fresh;
}

let threadId = initialThreadId();

/* ──────────────────────────────── Estado da tela ────────────────────────── */

function showConversation() {
  app.classList.remove("is-empty");
  hero.hidden = true;
  topbarMark.hidden = false;
}

function startNewConversation() {
  if (streaming) return;

  threadId = crypto.randomUUID();
  storeThreadId(threadId);

  for (const turn of thread.querySelectorAll(".turn")) turn.remove();

  app.classList.add("is-empty");
  hero.hidden = false;
  topbarMark.hidden = true;
  input.value = "";
  resize();
  input.focus();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

newChatButton.addEventListener("click", startNewConversation);

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
  noticias_acao: "notícias recentes",
  buscar_ticker_por_empresa: "busca de ticker",
  buscar_tickers_por_industria: "triagem por setor",
  resumo_mercado: "resumo de mercado",
};

function toolLabel(name) {
  return TOOL_NAMES[name] || name.replace(/_/g, " ");
}

function toolSubject(payload) {
  if (!payload || typeof payload !== "object") return "";
  const value = payload.ticker_name || payload.company_name || payload.industry || payload.region;
  return value ? ` · ${value}` : "";
}

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
  text.textContent = `consultando ${toolLabel(toolName)}${toolSubject(input)}`;

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
    finish(output) {
      bar.classList.remove("is-working");
      dot.remove();
      // "consulta concluída" evita concordar em gênero com o nome da ferramenta.
      text.textContent = `${toolLabel(toolName)} · consulta concluída`;
      result.set(output);
    },
    abort() {
      bar.classList.remove("is-working");
      dot.remove();
      text.textContent = `${toolLabel(toolName)} · consulta interrompida`;
    },
  };
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

/* ─────────────────────────────────── Envio ──────────────────────────────── */

async function ask(question) {
  if (streaming) return;
  streaming = true;
  sendButton.disabled = true;
  showConversation();

  addTurn("user", "Você").textContent = question;

  const body = addTurn("agent", "Graham Agent");
  scrollToEnd();

  // A resposta é montada em blocos na ordem em que acontece: o modelo pode
  // falar, consultar ferramentas e voltar a falar.
  let block = null;
  let blockText = "";

  // O agente dispara várias ferramentas de uma vez, então cada aviso pendente
  // é guardado por nome — a lista cobre o caso da mesma ferramenta repetida.
  const pendingNotes = new Map();

  // Cartões dos tickers citados, enviados depois que a resposta termina.
  const tickers = [];

  const openBlock = () => {
    if (!block) {
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

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question, thread_id: threadId }),
    });

    if (!response.ok || !response.body) {
      throw new Error(`O servidor respondeu ${response.status}.`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Cada frame SSE termina em linha em branco.
      let split;
      while ((split = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, split);
        buffer = buffer.slice(split + 2);

        const name = frame.match(/^event:\s*(.+)$/m)?.[1];
        const raw = frame.match(/^data:\s*(.*)$/m)?.[1];
        if (!name || raw === undefined) continue;

        const data = JSON.parse(raw);

        if (name === "token") {
          openBlock();
          blockText += data.text;
          block.innerHTML = renderMarkdown(blockText);
          scrollToEnd();

        } else if (name === "tool_start") {
          // O que já foi dito fica fechado acima do aviso.
          closeBlock();

          const note = toolBlock(data.name, data.input);
          body.append(note.root);

          const queue = pendingNotes.get(data.name) || [];
          queue.push(note);
          pendingNotes.set(data.name, queue);
          scrollToEnd();

        } else if (name === "tool_end") {
          pendingNotes.get(data.name)?.shift()?.finish(data.output);

        } else if (name === "ticker") {
          tickers.push(data);

        } else if (name === "error") {
          const note = document.createElement("div");
          note.className = "error-note";
          note.textContent = data.message;
          body.append(note);
        }
      }
    }
  } catch (error) {
    const note = document.createElement("div");
    note.className = "error-note";
    note.textContent = `Não foi possível completar a consulta. ${error.message}`;
    body.append(note);
  } finally {
    closeBlock();
    if (tickers.length) body.append(tickerPanel(tickers));
    // Uma ferramenta que nunca respondeu não pode ficar pulsando para sempre.
    for (const queue of pendingNotes.values()) {
      for (const note of queue) note.abort();
    }
    streaming = false;
    sendButton.disabled = false;
    input.focus();
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

input.focus();
