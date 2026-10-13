# Skills do servidor MCP

Roteiros que o servidor MCP publica de três formas: pela extensão de skills do MCP (SEP-2640, `skill://<grupo>/<nome>/SKILL.md`), como prompts de mesmo nome e no prompt do próprio Graham, que as lista e as carrega com `ler_skill`. O código que serve está em `../skills_extension.py`; o que carrega e valida, em `skill.py`.

## Estrutura

```
skills/
├── __init__.py              SKILLS: junta os grupos
├── skill.py                 load(), Argument, Variants
└── <grupo>/                 um domínio: analise, carteira
    ├── __init__.py          SKILLS: junta as skills do grupo
    └── <nome_da_skill>/     pacote Python, em snake_case
        ├── SKILL.md         o roteiro; o frontmatter é a fonte do nome e da descrição
        ├── referencias/     arquivos de apoio, se houver
        └── __init__.py      SKILL = load(__file__, ...)
```

Uma skill existe no servidor quando o `__init__.py` do grupo a importa: o registro é explícito, sem varredura de pastas.

## Criar uma skill

1. **Escolha o grupo** pelo domínio; um domínio novo é uma pasta nova com o seu `__init__.py` e uma entrada em `skills/__init__.py`.
2. **Crie a pasta** com o nome em snake_case (`analisar_ativo`).
3. **Escreva o `SKILL.md`**: frontmatter com `name` (o nome da pasta com `_` trocado por `-`) e `description` (o que faz e quando usar, porque é o que o agente lê para decidir carregá-la). O corpo são passos em ordem, cada um terminando num critério de pronto, citando as ferramentas pelo nome.
4. **Escreva o `__init__.py`** com `SKILL = load(__file__, arguments=..., tools=...)`: os argumentos do prompt e as ferramentas que o roteiro usa.
5. **Registre** a skill no `SKILLS` do grupo.

Pronta quando o servidor sobe e `uv run scripts/mcp_inspector.py --email <conta> -- --cli --method skills/list` a lista; `load()` recusa na subida o que estiver fora do padrão.

## Regras

- **O frontmatter é a fonte única** de nome e descrição. A listagem da SEP-2640 publica o frontmatter como está, e o cliente rejeita a skill se a listagem e o arquivo divergirem; o `__init__.py` declara só o que o Markdown não carrega.
- **Nomes** seguem o padrão Agent Skills: minúsculas, números e hífens. O nome também é o do prompt, então é único entre todos os grupos.
- **Ferramentas** citadas em `tools` existem no catálogo (`src/tools/catalog.py`). Cada roteiro usa só o que as ferramentas entregam: um passo que pede um dado sem ferramenta vira uma nova ferramenta primeiro.
- **Conteúdo servido** é todo arquivo da pasta, exceto o `__init__.py` e o `__pycache__`. Arquivos de apoio são Markdown, citados pelo `SKILL.md` com caminho relativo (`referencias/fii.md`).
- **Argumentos** do prompt chegam sempre como texto; validar o valor é tarefa do roteiro.

## Variantes

Quando a mesma tarefa pede estratégias diferentes conforme um argumento (analisar uma ação, um FII ou um ETF), o conteúdo de cada estratégia vai num arquivo de apoio, e a escolha fica em dois lugares que dizem a mesma coisa:

- **No `SKILL.md`**, para o agente que carrega a skill sozinho: a parte comum e a regra de qual referência ler ("se for FII, leia `referencias/fii.md`").
- **No `__init__.py`**, para o prompt, que recebe o argumento: `variants=Variants("tipo", {"acao": "referencias/acao.md", "fii": "referencias/fii.md"})`. O prompt devolve o `SKILL.md` com a variante do valor pedido anexada; `load()` confere que o argumento foi declarado e que cada arquivo existe.

A escolha é um mapa declarado de valor para arquivo, previsível e testável. Cada variante cobre uma estratégia que as ferramentas conseguem executar.
