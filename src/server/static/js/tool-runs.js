import { DONE_LABELS, toolLabel, toolSubject, WORKING_LABELS } from "./conversation.js";
import { isoDate, TOOL_VIEWS } from "./views.js";

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

export function capitalize(text) {
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
  agenda_eventos: (output) => (output?.days ? `próximos ${output.days} dias` : null),
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

export function toolRun() {
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
