import { escapeHtml } from "./markdown.js";
import { MINUS } from "./conversation.js";

/* ─────────────────────────── Cartões de ticker ──────────────────────────── */

const PRICE_FORMAT = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

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

export function tickerPanel(cards) {
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
