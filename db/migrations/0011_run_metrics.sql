-- Uma linha por execução do agente (uma pergunta, uma retomada depois da
-- confirmação ou uma regeneração): quanto demorou, quanto custou em tokens e
-- como terminou. Fica no Postgres, na máquina do usuário; os traces da
-- LangSmith são opcionais e mais detalhados.

CREATE TABLE agent.run_metrics (
    run_id          text        PRIMARY KEY,
    thread_id       uuid        NOT NULL REFERENCES agent.threads (id),
    user_id         uuid        NOT NULL REFERENCES core.users (id),
    started_at      timestamptz NOT NULL,
    -- 'completed', 'awaiting_approval', 'failed' ou 'interrupted'.
    outcome         text        NOT NULL,
    model           text        NOT NULL,
    duration_ms     integer     NOT NULL,
    -- Do início da execução à primeira saída do modelo (texto ou tool call).
    first_output_ms integer,
    model_calls     integer     NOT NULL,
    input_tokens    integer,
    output_tokens   integer,
    tool_calls      integer     NOT NULL,
    tool_errors     integer     NOT NULL
);

CREATE INDEX run_metrics_user_idx ON agent.run_metrics (user_id, started_at);
