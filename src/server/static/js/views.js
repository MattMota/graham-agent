import { MINUS } from "./conversation.js";
import { performanceChart } from "./chart.js";
import { capitalize } from "./tool-runs.js";

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
export function isoDate(value) {
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

export function signedPercent(value) {
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

/* Agenda: resultados, datas ex e pagamentos, em ordem de data. */
const EVENT_LABELS = { resultado: "Resultado", data_ex: "Data ex", pagamento: "Pagamento de provento" };

function eventDate(event) {
  const span = event.until ? `${isoDate(event.date)} a ${isoDate(event.until)}` : isoDate(event.date);
  return event.estimated ? `${span} (prevista)` : span;
}

function agendaView(output) {
  if (!output || !Array.isArray(output.events)) return null;
  const view = document.createElement("div");
  view.className = "tool-view";

  if (!(output.tickers || []).length) {
    view.append(emptyNote("A carteira e a watchlist estão vazias."));
    return view;
  }
  if (!output.events.length) {
    view.append(emptyNote(`Nenhum evento conhecido nos próximos ${output.days} dias.`));
  } else {
    // A origem só existe quando há usuário; sem ela, as duas colunas sobram.
    const mine = output.events.some((event) => event.origin);
    view.append(dataTable(
      `De ${isoDate(output.from)} a ${isoDate(output.to)}`,
      [
        { label: "Data" }, { label: "Ativo" }, { label: "Evento" },
        ...(mine ? [{ label: "Origem" }, { label: "Quantidade", numeric: true }] : []),
      ],
      output.events.map((event) => [
        eventDate(event),
        event.ticker_name,
        EVENT_LABELS[event.type] || event.type,
        ...(mine ? [(event.origin || []).join(" e ") || "—", quantity(event.quantity)] : []),
      ]),
    ));
  }
  if ((output.without_events || []).length) {
    view.append(emptyNote(`Sem evento conhecido no período: ${output.without_events.join(", ")}.`));
  }
  if ((output.unavailable || []).length) {
    view.append(emptyNote(`Não consultados: ${output.unavailable.join(", ")}.`));
  }
  return view;
}

/* Enquadramento e rebalanceamento: pesos em reais contra a alocação-alvo. */
const ALLOCATION_STATUS = { dentro: "Dentro", acima: "Acima", abaixo: "Abaixo" };

function points(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const sign = value < 0 ? MINUS : value > 0 ? "+" : "";
  return `${sign}${PERCENT_FORMAT.format(Math.abs(value))} p.p.`;
}

function percent(value) {
  return typeof value === "number" && Number.isFinite(value) ? `${PERCENT_FORMAT.format(value)}%` : "—";
}

function allocationView(output) {
  if (!output || !Array.isArray(output.classes) || !("in_range" in output)) return null;
  const view = document.createElement("div");
  view.className = "tool-view";
  const currency = output.base_currency || "BRL";

  if (!output.total_value) {
    view.append(emptyNote(output.note || "A carteira não tem posições em aberto."));
    return view;
  }
  view.append(statsRow([
    ["Valor na alocação", money(output.total_value, currency)],
    ["Situação", output.in_range == null ? "Sem alocação-alvo" : output.in_range ? "Enquadrada" : "Desenquadrada"],
    ["Banda de tolerância", output.tolerance == null ? "—" : `± ${PERCENT_FORMAT.format(output.tolerance)} p.p.`],
  ]));
  const targets = output.has_targets;
  view.append(dataTable(
    "Por classe",
    [
      { label: "Classe" }, { label: "Valor", numeric: true }, { label: "Peso", numeric: true },
      ...(targets ? [{ label: "Alvo", numeric: true }, { label: "Desvio", numeric: true }, { label: "Situação" }] : []),
    ],
    output.classes.map((item) => [
      item.label, money(item.value, currency), percent(item.weight_percent),
      ...(targets ? [
        percent(item.target_percent),
        { text: points(item.deviation_pp), numeric: true },
        { text: ALLOCATION_STATUS[item.status] || "—", className: item.status === "dentro" ? "" : "is-down" },
      ] : []),
    ]),
  ));
  if ((output.assets || []).length) {
    const labels = Object.fromEntries(output.classes.map((item) => [item.asset_class, item.label]));
    view.append(dataTable(
      "Por ativo",
      [
        { label: "Ativo" }, { label: "Classe" }, { label: "Origem" },
        { label: "Valor", numeric: true }, { label: "Peso", numeric: true },
      ],
      output.assets.map((item) => [
        item.ticker_name, labels[item.asset_class] || item.asset_class,
        item.class_source === "usuario" ? "sua escolha" : "automática",
        money(item.value, currency), percent(item.weight_percent),
      ]),
    ));
  }
  // `fora`: o usuário tirou o ativo da conta; `outros`: as regras não o reconheceram.
  const outside = output.outside_allocation || [];
  const chosen = outside.filter((item) => item.asset_class === "fora").map((item) => item.ticker_name);
  const unknown = outside.filter((item) => item.asset_class !== "fora").map((item) => item.ticker_name);
  if (chosen.length) view.append(emptyNote(`Fora da alocação, por escolha sua: ${chosen.join(", ")}.`));
  if (unknown.length) view.append(emptyNote(`Fora da alocação, classe não reconhecida: ${unknown.join(", ")}.`));
  if ((output.unavailable || []).length) {
    view.append(emptyNote(`Sem cotação agora: ${output.unavailable.join(", ")}.`));
  }
  return view;
}

function rebalanceView(output) {
  if (!output || !Array.isArray(output.orders)) return null;
  const view = document.createElement("div");
  view.className = "tool-view";
  const currency = output.base_currency || "BRL";

  view.append(statsRow([
    ["Aporte", money(output.contribution, currency)],
    ["Sobra", money(output.cash_left, currency)],
    ["Vendas", output.allow_sales ? "Permitidas" : "Não"],
  ]));
  if (output.orders.length) {
    view.append(dataTable(
      "Ordens sugeridas",
      [
        { label: "Operação" }, { label: "Ativo" }, { label: "Quantidade", numeric: true },
        { label: "Preço", numeric: true }, { label: "Valor", numeric: true },
      ],
      output.orders.map((order) => [
        capitalize(order.side), order.ticker_name, quantity(order.quantity),
        money(order.price, order.currency), money(order.amount, currency),
      ]),
    ));
  } else {
    view.append(emptyNote("Nenhuma ordem: a carteira já está no alvo ou o valor não compra uma unidade."));
  }
  for (const pending of output.unassigned || []) {
    const candidates = pending.watchlist_candidates.length
      ? ` Na watchlist: ${pending.watchlist_candidates.join(", ")}.` : "";
    view.append(emptyNote(`${pending.label}: ${money(pending.amount, currency)} sem ativo na carteira.${candidates}`));
  }
  view.append(dataTable(
    "Pesos por classe",
    [{ label: "Classe" }, { label: "Alvo", numeric: true }, { label: "Antes", numeric: true }, { label: "Depois", numeric: true }],
    output.classes.map((item) => [item.label, percent(item.target_percent), percent(item.weight_before), percent(item.weight_after)]),
  ));
  return view;
}

export const TOOL_VIEWS = {
  ver_carteira: portfolioView,
  proventos: incomeView,
  desempenho: performanceView,
  agenda_eventos: agendaView,
  ver_enquadramento: allocationView,
  sugerir_rebalanceamento: rebalanceView,
};
