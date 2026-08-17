# Laboratório: agentes com PydanticAI

Um laboratório executável para a Aula 12: workflow multiagente com evidências somente-leitura, checkpoint explícito da aplicação, gates determinísticos e observabilidade local.

O projeto roda em modo `mock` por padrão: não requer chave de API, Ollama ou Langfuse para acompanhar a aula e executar os testes.

## Arquitetura

- [Arquitetura dos agentes e do workflow](docs/arquitetura-agentes.md): papéis, hand-offs Pydantic, gate, checkpoint, retomada e observabilidade.
- [Arquitetura Clean/Hexagonal do repositório](docs/arquitetura-hexagonal.md): camadas, portas, adapters e composição pela CLI.

## Setup

Requer Python 3.11 a 3.13 e [uv](https://docs.astral.sh/uv/).

```bash
cd aula-12-agentes/lab
uv sync --group dev
```

Copie o exemplo de configuração apenas se quiser usar um provider ou observabilidade externa:

```bash
cp .env.example .env
```

Não versione o arquivo `.env`: ele pode conter chaves de API.

## Validação local

Estes são os comandos padronizados do projeto e do CI:

```bash
uv run python scripts/check_secrets.py
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy
uv run pytest -q
```

## Executando o laboratório

O fluxo completo em modo mock não chama nenhum LLM:

```bash
uv run aula12-agents run
```

O workflow segue esta sequência:

```text
evidências read-only → especialista de hipótese → checkpoint → crítico sem ferramentas → gate determinístico
```

O especialista propõe uma hipótese estruturada. O crítico recebe apenas o hand-off tipado; ele não possui ferramentas. A aplicação, e não o modelo, decide as transições, persiste checkpoints e impede escritas fora do gate humano.

## Cenários da aula

Os testes de ponta a ponta mostram quatro comportamentos que podem ser explorados sem um provider externo:

| Cenário | O que observar |
| --- | --- |
| Hipótese aprovada | O crítico aprova e o workflow conclui com uma decisão segura. |
| Evidência insuficiente | O fluxo escalona para revisão humana, sem executar escrita. |
| Timeout e retomada do crítico | O checkpoint da hipótese é reutilizado; o especialista não é executado novamente. |
| Resultado tardio | Uma atualização baseada em checkpoint antigo é rejeitada por controle otimista de concorrência (CAS). |

Para executar os cenários isoladamente:

```bash
uv run pytest -q tests/e2e/test_hypothesis_critic_gate.py
uv run pytest -q tests/e2e/test_multistage_resume_resilience.py
```

## Observando checkpoints e traces

Cada execução local grava artefatos na pasta `runs/`:

- SQLite guarda o estado do workflow e seus checkpoints;
- JSONL registra eventos estruturados, incluindo estágios, decisões de gate, retry e rejeição de resultados obsoletos.

Depois de executar o laboratório, use a CLI de inspeção:

```bash
uv run aula12-agents list-runs
uv run aula12-agents show-run <run-id>
uv run aula12-agents show-events <run-id>
uv run aula12-agents show-trace <run-id>
```

Esses comandos reaplicam redaction e não exigem conexão com Langfuse. O objetivo da aula é tornar visíveis o estado persistido e cada transição; o JSONL continua disponível mesmo sem Langfuse.

## Providers opcionais

Defina `MODEL_PROVIDER` no `.env` para escolher o provider. O valor padrão é `mock`.

### Ollama local

```dotenv
MODEL_PROVIDER=ollama
OLLAMA_MODEL=gemma4:26b-mlx
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
```

Com o Ollama em execução, valide o contrato opt-in:

```bash
RUN_OLLAMA_CONTRACT=1 uv run pytest -q -m provider -k ollama_supports
```

### OpenRouter

```dotenv
MODEL_PROVIDER=openrouter
OPENROUTER_API_KEY=...
OPENROUTER_PRIMARY_MODEL=provider/model
OPENROUTER_BACKUP_MODEL=provider/model
OPENROUTER_REASONING_ENABLED=false
```

O backup é usado somente quando o OpenRouter responde com créditos insuficientes (`HTTP 402`), e não mascara outros erros. O contrato pago é explicitamente opt-in:

```bash
MODEL_PROVIDER=openrouter RUN_OPENROUTER_CONTRACT=1 \
  uv run pytest -q -m provider -k openrouter
```

## Langfuse opcional

Configure as variáveis `LANGFUSE_*` no `.env` conforme sua instalação. Quando configurado, o Langfuse recebe a instrumentação nativa do PydanticAI e os eventos de estágio/gate do workflow. Quando não estiver configurado, a aplicação continua registrando JSONL local.

Para validar a integração sem torná-la obrigatória para os alunos:

```bash
RUN_LANGFUSE_SMOKE=1 uv run pytest -q -m integration -k langfuse
```

Para executar o workflow completo com Ollama, SQLite, JSONL e Langfuse em conjunto:

```bash
RUN_OLLAMA_LANGFUSE_WORKFLOW_CONTRACT=1 \
  uv run pytest -q -m "provider and integration" -k langfuse
```

## Limites e segurança do exemplo

- ferramentas do agente são apenas de leitura;
- a aplicação controla orçamento, transições e retomada;
- hand-offs entre agentes são modelos Pydantic, não texto livre;
- nenhuma ação de escrita é executada automaticamente pelo workflow.

## Contribuindo

Leia [CONTRIBUTING.md](CONTRIBUTING.md) para o fluxo de desenvolvimento, a matriz de testes opt-in e a política de segredos e artefatos locais.
