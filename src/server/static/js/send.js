import { input, session, storeThreadId } from "./state.js";
import { leaveView, setStreaming, showConversation } from "./screen.js";
import { signedOut } from "./account.js";
import { refreshThreadList } from "./sidebar.js";
import { renderMarkdown } from "./markdown.js";
import { addTurn, errorNote, scrollToEnd } from "./conversation.js";
import { toolRun } from "./tool-runs.js";
import { abandonPendingApprovals, approvalCards, approvalGroup } from "./approval.js";
import { tickerPanel } from "./tickers.js";
import { addTurnActions, thinkingNote } from "./turn-actions.js";
import { approvalRequest, extras, newId, parseJson, toolOutput } from "./agui.js";
import { openThread } from "./history.js";

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
export async function streamTurn(start, target, { onRefused, onSnapshot } = {}) {
  // Trocar de conversa larga esta leitura (a execução segue no servidor); daí
  // em diante, ela não mexe mais na tela nem no estado, que já são de outra.
  const reading = new AbortController();
  session.currentReading = reading;
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
    if (session.currentReading === reading) session.currentReading = null;
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
  if (turn?.outcome?.state === "interrupted" && session.threadId) await openThread(session.threadId);
}

// Uma execução nova na conversa atual. Os campos que faltam são os padrões do
// `RunAgentInput`: o servidor ignora ferramentas, contexto e estado do cliente.
export function runAgent(input, target, options) {
  const payload = {
    threadId: session.threadId,
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

export async function ask(question) {
  if (session.streaming) return;
  showConversation();
  // Uma pergunta nova no lugar da resposta ao cartão encerra a confirmação; o
  // AG-UI pede que ela vá cancelada junto.
  const resume = abandonPendingApprovals();

  // A conversa nasce aqui: o id é do cliente, e o servidor a cria com ele.
  if (!session.threadId) {
    session.threadId = newId();
    storeThreadId(session.threadId);
  }
  addTurn("user", "Você").textContent = question;
  const body = addTurn("agent", "Graham Agent");
  await runAgent(
    { messages: [{ id: newId(), role: "user", content: question }], ...(resume.length ? { resume } : {}) },
    () => body,
  );
}

export async function regenerate(turn) {
  if (session.streaming) return;
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

export async function fork(turn) {
  if (session.streaming) return;

  try {
    const response = await fetch(`/api/threads/${session.threadId}/fork`, {
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
