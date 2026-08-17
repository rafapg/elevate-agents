# Demonstração local de coordenação

A referência de coordenação executa quatro cenários inteiramente locais. Ela
usa especialistas determinísticos e fixtures sintéticas: não chama um modelo,
não precisa de rede e não lê credenciais.

Execute a partir de `aula-12-agentes/lab`:

```bash
uv run aula12-agents coordination run supervisor
uv run aula12-agents coordination run spawn
uv run aula12-agents coordination run no-spawn
uv run aula12-agents coordination run cancelamento
```

Com Ollama, cada execução tem até cinco minutos no total e cada especialista
tem até três minutos para responder. Em uma máquina mais lenta, os dois
limites podem ser aumentados sem mudar o código:

```bash
COORDINATION_RUN_TIMEOUT_SECONDS=600 \
OLLAMA_COORDINATION_TIMEOUT_SECONDS=300 \
MODEL_PROVIDER=ollama uv run aula12-agents coordination run supervisor
```

Cada comando imprime um resumo seguro em JSON. O estado completo permanece no
SQLite local e a linha do tempo é gravada em JSONL. A saída curta mostra o
identificador da execução, o cenário, a revisão final, a decisão e um resumo
das tarefas; ela não exibe prompts, conteúdo bruto de fixtures ou segredos.

Depois de executar qualquer cenário, copie o `run_id` exibido e inspecione o
quadro persistido e seus eventos, sem executar novamente o cenário nem alterar
o SQLite:

```bash
uv run aula12-agents coordination show-board <run_id>
uv run aula12-agents coordination show-events <run_id>
```

`show-board` exibe o estado, orçamento, prazo, permissões de leitura e estado
de cada tarefa. Quando existe um resultado, mostra apenas a quantidade de
evidências e sua cobertura; não mostra o conteúdo das fixtures. `show-events`
apresenta a ordem dos eventos com revisão, estado, cenário e total de tarefas.
Esses dois comandos abrem o banco em modo somente leitura.

## Ordem sugerida

Comece com `supervisor`: ele abre duas tarefas independentes, com permissões e
limites próprios, e reúne somente respostas com fontes válidas.

Em seguida, execute `spawn`. A tarefa extra não nasce por preferência por uma
arquitetura maior; ela é criada porque falta uma evidência específica para
fechar a cobertura.

Compare com `no-spawn`. Neste caso a cobertura já foi atingida, então o
coordenador registra que não há motivo para gastar tempo e orçamento em outra
tarefa.

Termine com `cancelamento`. Uma evidência nova invalida uma investigação,
cancela a tarefa que dependia dela e recusa a resposta que chega depois. A
recusa acontece por estado e revisão persistidos, não porque o especialista
"lembrou" de ignorar a própria resposta.

## O que observar

- As permissões, prazo e orçamento pertencem a cada tarefa e são definidos pelo
  código do coordenador.
- Especialistas só consultam fixtures locais e devolvem relatórios tipados.
- A decisão de criar, não criar, cancelar ou aceitar trabalho é determinística.
- Eventos JSONL tornam cada transição auditável mesmo sem uma ferramenta externa
  de observabilidade.

## Langfuse opcional

Com as credenciais Langfuse configuradas, a mesma execução pode enviar somente
os eventos de negócio da coordenação. O JSONL local continua obrigatório e o
conteúdo de prompts, respostas e fixtures permanece redigido.

No Langfuse, cada execução de coordenação aparece como uma raiz e as transições
do quadro de tarefas aparecem abaixo dela. Spans de modelo e de ferramentas não
são criados pela coordenação: eles continuam sendo responsabilidade da
instrumentação nativa do PydanticAI, evitando duplicação.

O smoke test externo é opt-in e não roda por padrão:

```bash
RUN_COORDINATION_LANGFUSE_SMOKE=1 uv run pytest -q -m integration -k coordination_langfuse
```
