/* ─────────────────────────────────── AG-UI ──────────────────────────────── */

// O agente fala AG-UI: cada execução é um POST com o `RunAgentInput` e volta
// como eventos SSE. O servidor guarda o histórico; daqui vai só a pergunta nova
// (ou a regeneração, ou a resposta à confirmação). Os extras do Graham chegam
// em `metadata.graham` de cada evento e mensagem.

// O AG-UI espera do cliente os ids da conversa, da execução e da mensagem.
// `crypto.randomUUID` só existe em contexto seguro (https ou localhost).
export function newId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function extras(item) {
  return item?.metadata?.graham || {};
}

export function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// O retorno de uma ferramenta, para o detalhe da consulta: um retorno enorme
// travaria a tela, então vira um aviso.
const MAX_TOOL_PREVIEW = 20_000;

export function toolOutput(content) {
  if (typeof content === "string" && content.length > MAX_TOOL_PREVIEW) {
    return { aviso: "Resultado longo demais para exibir por inteiro.", caracteres: content.length };
  }
  return parseJson(content) ?? content;
}

// O cartão de confirmação a partir de uma interrupção do AG-UI.
export function approvalRequest(interrupt) {
  const meta = extras(interrupt);
  return {
    interrupt_id: interrupt.id,
    tool_call_id: interrupt.toolCallId,
    name: meta.name,
    args: meta.args || {},
    locked: meta.locked || [],
    title: interrupt.message,
    schema: interrupt.responseSchema.properties.editedArgs,
  };
}
