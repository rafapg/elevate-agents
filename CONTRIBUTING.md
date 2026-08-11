# Contribuindo

Obrigado por contribuir com o laboratório. Mantenha as mudanças pequenas, tipadas e acompanhadas por testes proporcionais ao comportamento alterado.

## Ambiente e validação

Na raiz de `lab/`, instale as dependências de desenvolvimento e execute antes de abrir uma mudança:

```bash
uv sync --group dev
uv run python scripts/check_secrets.py
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy
uv run pytest -q
```

Esses são os mesmos checks executados pelo CI e não precisam de modelo, credencial ou serviço externo.

O scanner verifica somente os arquivos rastreados pelo Git e nunca exibe o
valor de um achado. Ele é uma proteção de baixo custo para padrões comuns; não
substitui a revisão do diff antes de publicar.

## Testes com serviços externos

Os testes marcados como `provider` ou `integration` são opt-in. Eles não rodam no CI, pois dependem de um Ollama local, de créditos no OpenRouter ou de um projeto Langfuse configurado. Consulte o README para os comandos e as variáveis necessárias.

Não inclua esses testes em uma suíte obrigatória sem um modo explícito de opt-in e sem um custo/previsibilidade adequados.

## Segurança e artefatos locais

Nunca versione arquivos `.env`, chaves, tokens, bases SQLite, diretórios `runs/` ou traces JSONL. Use `.env.example` somente como modelo sem segredos.

Também evite inserir prompts, respostas de modelos ou evidências reais em fixtures e logs. Os exemplos do laboratório devem ser sintéticos e os traces precisam preservar a política de redaction.
