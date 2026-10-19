import { session, storeThreadId, thread } from "./state.js";
import { clearConversation, showConversation, showEmpty } from "./screen.js";
import { markCurrentThread } from "./sidebar.js";
import { renderMarkdown } from "./markdown.js";
import { addTurn } from "./conversation.js";
import { toolRun } from "./tool-runs.js";
import { approvalGroup } from "./approval.js";
import { addTurnActions, forkNote } from "./turn-actions.js";
import { approvalRequest, extras, parseJson, toolOutput } from "./agui.js";
import { streamTurn } from "./send.js";

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

export async function openThread(id) {
  const view = session.currentView;
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
        if (view !== session.currentView) return;
        session.threadId = id;
        storeThreadId(id);
        markCurrentThread();
        continued = renderSnapshot(event);
      },
      onRefused(code) {
        if (view !== session.currentView) return true;
        if (code === "http_401") return false;
        // Conversa de outra sessão ou apagada: começa do zero.
        session.threadId = null;
        storeThreadId(null);
        showEmpty();
        return true;
      },
    },
  );
}
