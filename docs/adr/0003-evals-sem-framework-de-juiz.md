# Evals por checagem objetiva, sem framework de juiz

Os evals do Graham (`tests/evals/`) rodam no pytest e conferem decisões objetivas do modelo: hoje, a primeira ferramenta escolhida para cada pergunta, contra um conjunto de respostas aceitas, com uma taxa mínima de acerto entre várias tentativas. Não usam RAGAS nem DeepEval. Para comparar nomes de ferramenta não é preciso um modelo juiz, e cada métrica com juiz custaria chamadas extras, mandaria telemetria para fora por padrão e acrescentaria uma segunda fonte de não determinismo.

## Considered Options

- **RAGAS**: as métricas centrais dele são de RAG (fidelidade ao contexto recuperado, precisão e cobertura da recuperação). O Graham é um agente com ferramentas; a única peça com cara de RAG é a busca de memórias.
- **DeepEval**: roda dentro do pytest e tem métricas de agente (ferramenta certa, argumentos, tarefa concluída) e critérios em linguagem natural (G-Eval). É a escolha se o Graham passar a julgar a qualidade da resposta final, com a telemetria desligada e sem a plataforma na nuvem (ver ADR 0001).
- **Evaluators da LangSmith**: sem dependência nova, mas cada rodada gasta traces da cota gratuita e os resultados ficam na nuvem.

## Consequences

- **A ordem para ampliar:** primeiro conferir os argumentos das chamadas; depois a trajetória inteira, com o modelo de verdade e as ferramentas devolvendo dados fixos. Só então julgar a resposta final, por exemplo "não afirma datas que não vieram das ferramentas". Esse último passo é o que justifica o DeepEval.
- **O determinismo fica nos testes:** o grafo, a confirmação e o AG-UI são testados com um modelo roteirizado (`tests/fakes.py`), e os evals ficam fora da CI.
