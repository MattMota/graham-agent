import { session, thread } from "./state.js";
import { runAgent } from "./send.js";

/* ─────────────────────────────── Confirmação ────────────────────────────── */

// Cada operação que grava dados chega como uma interrupção do AG-UI e vira um
// cartão: o usuário confere, corrige se quiser e confirma ou cancela. Quando
// todas as operações do passo estão decididas, as respostas vão juntas, no
// `resume` de uma execução nova, e o turno continua.

// Cartões por tool call, para o resultado da operação encontrar o seu.
export const approvalCards = new Map();

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
export function approvalGroup(requests, stored = null) {
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
  while (session.streaming) await new Promise((resolve) => setTimeout(resolve, 100));
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
export function abandonPendingApprovals() {
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
