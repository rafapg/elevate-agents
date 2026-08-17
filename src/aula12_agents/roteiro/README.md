# Roteiro de condução — Aula 12: Desenvolvimento de agentes

Este arquivo é a fonte prática para ministrar a Aula 12 a líderes técnicos e
engenheiros seniores. Ele junta a história do incidente, as perguntas, os
artefatos e a operação do laboratório. Não é para ser lido literalmente: é um
mapa de decisões para o instrutor. O público deve sair capaz de escolher a
menor arquitetura que resolve uma incerteza e de explicitar seus controles.

## Tese, promessa e limites da aula

**Tese para dizer em voz alta no começo e no final:** “Um agente é uma máquina
de decisão com autonomia limitada. O modelo pode escolher a próxima
investigação dentro de um espaço permitido; a aplicação controla dados,
ferramentas, estado, limites, verificações, recuperação e efeitos externos.”

Esta não é uma aula para ensinar um framework nem para convencer alguém a usar
multiagentes. É uma aula sobre autoridade: quem escolhe o próximo passo, quem
pode mudar estado e quem autoriza uma ação com efeito fora do sistema.

Não exponha nem solicite cadeia de pensamento do modelo. A explicação deve
usar somente fatos observáveis: objetivo, fonte consultada, ferramenta
permitida, estado, transição, orçamento, resultado tipado, gate e decisão.

### Caso único que atravessa a aula

Após o deploy `2026.08.1`, o checkout apresenta mais respostas 500 e queda de
conversão associada a Safari. Safari é o sensor inicial, não a causa. A causa
provável é uma regressão na retomada de sessão: em certos retornos de pagamento
`session_id` está ausente, uma guarda foi removida e o código falha.

O objetivo seguro não é corrigir ou publicar algo automaticamente. É produzir
uma hipótese rastreável, sua incerteza e a próxima ação segura usando somente
artefatos locais de leitura: relato, diff, CI, logs, issue histórica e runbook.
Uma saída aceitável é: “há hipótese forte de regressão no tratamento de sessão
ausente, sustentada por diff e logs; confirmar incidência por feature flag;
não publicar correção; escalar para Payments ou preparar rascunho para revisão.”

## Como os quatro tipos de material trabalham juntos

Use cada material para uma função diferente. Não transforme slides em notas de
aula, nem terminal em espetáculo.

| Material | Função | Regra prática |
| --- | --- | --- |
| Slide | Faz uma pergunta ou fixa uma frase | Uma ideia; no máximo uma frase curta e um visual. |
| Excalidraw | Mostra relações e fronteiras | Fale enquanto aponta; não leia cada caixa. |
| Código estático | Torna um contrato e sua proteção verificáveis | Trecho de 8–20 linhas; sempre perguntar “o que isto impede?”. |
| Terminal/trace | Dá evidência de que a regra produz consequência | Mostrar só os campos necessários para responder à pergunta. |
| Fala/pergunta | Conecta o artefato à decisão de arquitetura | Pergunte antes de revelar a resposta. |

Ritmo de cada virada: **pergunta individual → previsão curta → artefato ou
comando → leitura guiada → conclusão em uma frase → ponte para a limitação
seguinte**. Aceite respostas breves no chat; não converta cada pergunta em um
debate longo.

## Preparação antes da aula

### Preparação técnica (30–45 min, antes de receber a turma)

1. Entre em `aula-12-agentes/lab` e sincronize as dependências:

   ```bash
   uv sync --group dev
   ```

2. Valide o caminho que será usado na aula. O padrão é `mock`, totalmente
   local, determinístico e sem LLM, rede ou credenciais:

   ```bash
   uv run aula12-agents run
   uv run aula12-agents coordination run supervisor
   uv run aula12-agents coordination run spawn
   uv run aula12-agents coordination run no-spawn
   uv run aula12-agents coordination run cancelamento
   ```

3. Guarde os cinco `run_id`s e pré-abra, em abas ou terminais separados, a
   projeção segura de cada um. Para o fluxo de agente único:

   ```bash
   uv run aula12-agents show-run <run-id>
   uv run aula12-agents show-events <run-id>
   uv run aula12-agents show-trace <run-id>
   ```

   Para coordenação:

   ```bash
   uv run aula12-agents coordination show-board <run-id>
   uv run aula12-agents coordination show-events <run-id>
   ```

4. Faça capturas redigidas de contingência: resumo do agente único, trace de
   timeout, e um board/eventos para cada cenário. Exiba apenas comando, `run_id`,
   estado, decisão, orçamento, escopo e eventos relevantes. Nunca projete
   `.env`, credenciais, prompts completos, conteúdo bruto de fixtures ou seus
   caminhos pessoais.

5. Abra os seis arquivos em `aula-12-agentes/plano/diagramas/` e deixe-os na
   ordem abaixo. O instrutor deve poder alternar do slide ao Excalidraw em um
   clique.

### Provider opcional: Ollama

Ollama só é uma variação já ensaiada. Não use como dependência da aula. Se for
usar, valide na mesma máquina antes e tenha o output mock pronto. Para uma
máquina lenta, aumente os limites apenas nessa invocação:

```bash
COORDINATION_RUN_TIMEOUT_SECONDS=600 \
OLLAMA_COORDINATION_TIMEOUT_SECONDS=300 \
MODEL_PROVIDER=ollama uv run aula12-agents coordination run supervisor
```

Se a execução demorar, não espere: diga “o mecanismo é o mesmo; vou abrir a
execução já gravada para analisarmos a decisão” e use o `run_id` preparado.
Langfuse é opcional; JSONL local já é suficiente para discutir trajetória.

### Preparação editorial

- Construa slides com pouco texto: uma pergunta, uma frase que deve ficar e,
  quando necessário, um espaço para diagrama, código ou terminal.
- Não exporte os seis diagramas como seis slides obrigatórios. Eles são quadros
  de pensamento para a fala; use o arquivo editável quando a relação importa.
- Congele exatamente quatro blocos de código para projetar. O restante fica
  disponível para perguntas, mas não entra na sequência principal.
- Coloque um cronômetro visível. A pausa de 90–100 e o exercício de 160–180
  protegem a aprendizagem; não os use como margem invisível para demos.

## Mapa de 180 minutos

| Tempo | Virada narrativa | Material dominante | Resultado verificável |
| --- | --- | --- | --- |
| 0–30 | Caminho conhecido versus próxima evidência incerta | slides + diagrama 01 | Turma identifica quem decide a próxima etapa. |
| 30–65 | Agente único como investigação limitada | diagrama 02 + demo mock | Turma justifica uma consulta por redução de incerteza. |
| 65–90 | Contexto, memória e gate como controles | diagrama 03 + código | Turma separa contexto, referência e memória governada. |
| 90–100 | Pausa | slide de pergunta | Turma retorna com uma hipótese para o timeout. |
| 100–130 | Falha, checkpoint e trajetória observável | diagrama 04 + trace | Turma classifica falha e escolhe saída segura. |
| 130–160 | Coordenação somente por ganho marginal | diagramas 05–06 + CLI | Turma defende `no_spawn` ou spawn com contrato. |
| 160–180 | Transferência | slide de exercício | Turma propõe arquitetura, limites, gate e escalonamento. |

---

## Bloco 1 — 0–30 min: incidente e baseline

### 0–5 — Abrir a história, sem apresentar arquitetura

**Slide:** incident packet, com deploy `2026.08.1`, aumento de 500,
queda de conversão, Safari, owner inicial `Payments`, janela de investigação e
“não publicar patch/comentário/issue automaticamente”.

**Pergunta ao público:** “Em 45 segundos, qual decisão segura precisamos
conseguir tomar antes de agir?”

**Resposta esperada:** delimitar a investigação: quais fontes de leitura
consultar, em que ordem, dentro de qual prazo e sem atravessar a fronteira de
escrita. Não aceitar “resolver o bug” como resposta suficiente.

**Fala sugerida:** “Safari é o sensor inicial, não a explicação. O trabalho
não é transformar correlação em causa; é reduzir incerteza sem publicar nada.”

**Instrutor faz:** dê 45–90 segundos de silêncio ou chat; recolha duas
respostas. Não abra código. O slide sustenta a pergunta; a fala corrige a
pressa por solução.

### 5–12 — Workflow determinístico

**Slide:** `relato → validação → dedupe → rota Payments`, com a frase
“quando o caminho é conhecido, o código decide”.

**Pergunta:** “Quem valida campos, deduplica e roteia esse ticket?”

**Conclusão:** regras e código. Adaptar com LLM aqui adiciona variabilidade,
custo e auditoria onde uma regra testável resolve melhor.

**Não mostrar:** framework, prompt ou arquivo de implementação. Esta é uma
distinção de autoridade, não uma demo de código.

### 12–20 — Workflow com LLM, ainda sem agente

**Slide:** o mesmo relato entrando em um `BugReport` tipado. Destaque apenas
duas setas: “modelo interpreta texto” e “código escolhe rota”.

**Pergunta:** “O modelo decidiu a próxima etapa?”

**Conclusão:** não. Ele transforma linguagem ambígua em estrutura; o
workflow continua com sequência fixa. Isso é útil, mas ainda não é a decisão
adaptativa que justificará um agente.

**Comentário, não código:** mencionar que schema tipado reduz ambiguidade e
facilita testes. Não gastar mais de 3 minutos em Pydantic aqui: o código de
schema será útil depois, no card/gate.

### 20–30 — Nomear a mudança de problema

**Excalidraw:** `01-escada-de-autoridade.excalidraw`.

**Pergunta:** “Agora que o relato está normalizado, qual fonte reduz mais a
nossa incerteza: logs, diff, CI, issue antiga ou runbook?”

**Conclusão:** essa escolha depende do que foi observado; o caminho deixou de
ser conhecido. Isso abre espaço para agente, mas não obriga coordenação.

**Fala sugerida:** “Não é uma escada obrigatória de maturidade. É o menor
mecanismo suficiente para a incerteza observada.”

**Leitura do diagrama:** aponte em cada caixa quem possui a autoridade: código
no workflow; modelo só interpreta no workflow com LLM; modelo escolhe ação
dentro de limites no agente único; aplicação agenda e aceita resultados na
coordenação. Não explique cada tecnologia; use 4 minutos.

**Checagem (últimos 3 min):** ofereça três mini-casos e peça classificação pela
autoridade. Corrija quem disser “tem LLM, portanto é agente”.

---

## Bloco 2 — 30–65 min: agente único, limitado e verificável

### 30–35 — Mostrar o contrato antes da execução

**Excalidraw:** `02-loop-de-agente-limitado.excalidraw`.

**Pergunta:** “Qual fonte vocês consultariam primeiro, e qual hipótese essa
consulta poderia derrubar?”

**Conclusão:** a escolha pode variar; a qualidade está em explicitar fonte,
custo, hipótese que seria afetada e condição de parar. O agente não recebe
‘o mundo’; recebe ferramentas e contexto autorizados.

**Fala sugerida:** “O modelo escolhe uma observação. Política, orçamento,
permissões e aceitação ficam fora dele.”

**Material:** neste momento, mostre apenas o objetivo da investigação,
allowlist, budget, formato do hypothesis card e saída segura. Não execute ainda.

### Bloco de código A — contrato de ferramenta read-only (35–39, 4 min)

**O que é:** a fronteira que torna uma consulta uma capacidade limitada, e não
acesso genérico ao ambiente. No laboratório, `FixtureGateway` atende somente
artefatos sintéticos e de leitura; os adapters recebem um gateway delimitado.

**Por que importa:** uma ferramenta define o que o agente pode observar e,
portanto, que ações ele pode escolher. Sem essa fronteira, uma promessa verbal
no prompt não impede leitura indevida, escrita, custo ilimitado ou entrada
hostil transformada em instrução.

**Tempo recomendado:** 4 min. Se houver curiosidade sobre segurança, acrescente
2 min, retirando tempo da leitura de alternativas — não da demo de falha.

**Como apresentar:** código + Excalidraw; não é necessário um slide adicional.
No slide anterior, deixe somente a pergunta “o que esta ferramenta impede?”.

**Trecho a preparar (8–15 linhas):** do gateway/porta que expõe operações como
`search_commits`, `read_ci_summary`, `search_issues`, `query_error_logs` e
`read_runbook`, ou da interface que recebe o leitor de evidência. Se usar um
trecho real, prefira `infrastructure/fixtures/gateway.py` e a porta usada pelo
coordenador; corte detalhes de arquivo e parsing.

**Pergunta enquanto o código está na tela:** “O que este código impede que um
prompt não impediria?”

**Resposta/conclusão esperada:** impede capacidades fora da allowlist e mantém
a investigação no modo read-only. Ainda não decide se uma hipótese é boa; só
limita o espaço de observação.

**Não fazer:** afirmar que read-only resolve segurança inteira. Ele não
substitui redaction, autorização, rate limit, orçamento, gate de escrita ou
isolamento de dados.

### 39–48 — Executar o agente único mock

**Terminal (principal):**

```bash
cd aula-12-agentes/lab
uv run aula12-agents run
```

**O que observar:** `run_id`, estado, `next_step` e decisão resumida. Não
projete prompt, resposta bruta ou qualquer suposta explicação interna do modelo.

**Perguntas de leitura:**

1. “Qual fonte apareceu e o que ela mudou?”
2. “O que ainda seria apenas correlação?”
3. “Qual seria a próxima consulta de maior valor?”

**Conclusão:** Safari e a issue histórica são contexto. O CI verde não prova
ausência de defeito, porque não cobre retorno sem sessão. Diff e logs formam a
base para a hipótese de guarda removida e `session_id` ausente.

**Fallback:** abra um `show-run <run-id>` preparado e diga que a equivalência
do mock é intencional: discutimos a decisão e as transições, não a velocidade
do provider.

### 48–58 — Ler o hypothesis card

**Slide:** uma imagem limpa do card, com cinco zonas: objetivo; fatos com
fontes; hipótese; incertezas; próxima ação/decisão. Use uma frase só:
“Uma hipótese madura também declara o que ainda não sabe.”

**Pergunta:** “O que ainda falta para agir?”

**Conclusão:** fonte, limitação e parada são parte do resultado, não burocracia.
Uma hipótese plausível sem provenance não é conclusão. Investigação também não
é autorização para publicar correção.

**Artefato secundário:** terminal ou `show-run` somente se precisar mostrar que
o card vem de estado persistido; não leia JSON inteiro.

### 58–65 — Fechar o bloco pela fronteira de capacidade

**Volte ao código A ou à allowlist em slide curto.**

**Pergunta:** “Se o agente tivesse acesso a todos os documentos e todos os
comandos, qual decisão ficaria melhor? Qual risco ficaria maior?”

**Conclusão:** dados sem relação com a decisão viram ruído; capacidade ampla
amplia superfície de risco. Ferramenta é capacidade, não ‘acesso ao mundo’.

**Ponte:** se comportamento depende do que entra na decisão, contexto e memória
não são detalhes de prompt: são parte do controle.

---

## Bloco 3 — 65–90 min: contexto, memória e gate

### 65–72 — Contexto é seleção, não acúmulo

**Excalidraw:** `03-contexto-como-pacote.excalidraw`.

**Pergunta:** “O que precisa entrar nesta decisão e o que deve ficar como
referência por ID?”

**Conclusão:** o pacote contém objetivo atual, estado tipado, política,
orçamento, evidências relevantes e referência ao original. Não contém todos os
logs, a thread inteira ou instruções encontradas em conteúdo não confiável.

**Fala sugerida:** “Contexto é uma seleção governada; não é o histórico inteiro
colado no prompt.”

**Como apresentar:** Excalidraw, 5 min; depois uma tela antes/depois com
‘artefatos extensos’ versus ‘context pack’. Evite mostrar prompt real.

### 72–79 — Separar quatro coisas chamadas de memória

**Slide:** quatro cartões, sem texto explicativo longo: estado atual; resumo
curto; memória durável; artefato original por referência.

**Pergunta:** “Qual desses itens exige fonte, autoridade, confiança e
expiração?”

**Resposta:** memória durável. O estado da investigação tem ciclo de vida do
run; o artefato original não precisa caber na janela; resumo não é verdade
eterna.

**Conclusão:** memória é estado que sobrevive sob política. Ticket, log e chat
são dados não confiáveis e não podem alterar ferramentas ou policy.

### Bloco de código B — schema do hypothesis card e gate (79–88, 9 min)

**O que é:** o `HypothesisCard` é uma saída estruturada de investigação. O
`EvidenceGate` é código determinístico que aceita, pede retry ou manda escalar
de acordo com evidência, provenance e limitação explícita.

**Por que importa:** separa “um texto parece convincente” de “a aplicação
aceita uma conclusão”. O modelo pode propor; um contrato validável e um gate
externo controlam o que atravessa a próxima fronteira.

**Tempo recomendado:** 9 min: 4 min para o card, 3 min para o gate, 2 min para
previsão da turma. É o bloco de código central da aula.

**Como apresentar:** slide de uma frase + código + pequena simulação verbal.
Use o slide “Plausível não é aceitável”; mostre código por 7 min; não use
terminal aqui, a menos que já tenha um card reprovado preparado.

**Trecho a preparar:**

- `domain/models.py`, definição de `HypothesisCard`: campos de decisão,
  evidências e lacunas/limitações;
- `domain/policies.py`, `EvidenceGate.allows`/`enforce`: critério explícito.

Corte validators, imports e detalhes de Pydantic. O objetivo não é ensinar a
sintaxe do schema, mas localizar a regra que impede aceitação sem evidência.

**Pergunta:** “Se o card traz uma causa elegante, mas não traz duas fontes
independentes e uma limitação, o que deveria acontecer?”

**Resposta/conclusão:** replanejar, limitar ou escalar. Nunca pedir ao modelo
para reescrever com mais confiança.

**Contraste a verbalizar:** o gate não ‘entende’ a causa melhor que o modelo;
ele protege um critério de qualidade que é previsível, testável e auditável.

### 88–90 — Ponte para falha

**Slide:** apenas “E quando a fonte mais útil não responde?”

**Fala:** “Mesmo boa política, bom contexto e boa evidência encontram timeout.
O próximo tema não é como eliminar falhas; é como falhar sem ampliar risco ou
perder a decisão já construída.”

---

## 90–100 min: pausa

Deixe na tela: **“Diante de timeout de CI: retry, replanejar ou escalar?”**
Não continue o diagnóstico no intervalo. Isso cria uma previsão que será usada
na volta.

---

## Bloco 4 — 100–130 min: falha, checkpoint e observabilidade

### 100–106 — Classificar antes de responder

**Slide:** timeout de CI no centro e cinco etiquetas: transitório; schema;
informação/decisão ausente; limite atingido; defeito desconhecido.

**Pergunta:** “Qual resposta é segura para timeout de CI? E quando ela deixa de
ser segura?”

**Conclusão:** timeout transitório pode receber retry limitado e backoff. Erro
de schema pede estado estruturado/replanejamento; ausência de decisão pede
pause ou humano; limite pede parada; defeito desconhecido precisa continuar
visível. Retry não é resposta universal.

### 106–115 — Linha do tempo de recuperação

**Excalidraw:** `04-recuperacao-segura.excalidraw`.

**Terminal ou output congelado:** execute o cenário de timeout/retomada já
ensaiado, ou abra seu `show-events`/`show-trace` preparado. O laboratório tem
testes de ponta a ponta para esse comportamento; se a CLI do ensaio terminou
em `waiting_retry`, a retomada é manual:

```bash
uv run aula12-agents resume <run-id>
```

**Pergunta:** “O que foi preservado para retomarmos sem refazer a investigação?”

**Conclusão:** objetivo, evidências, card, tentativas, falha, estado e próxima
etapa. O checkpoint limita repetição e preserva a decisão já feita.

**Tempo:** 9 min. Gaste no máximo 2 min rodando comando; a leitura é o centro.

### Bloco de código C — checkpoint, revisão e retomada (115–121, 6 min)

**O que é:** um checkpoint é estado persistido de uma execução, com revisão e
próxima etapa. A atualização usa comparação otimista de revisão (CAS), para
que um resultado baseado em estado antigo não avance o run atual.

**Por que importa:** sem estado durável, retry pode repetir trabalho caro ou
cruzar uma fronteira errada; sem revisão, um resultado tardio pode sobrescrever
uma decisão mais nova. Checkpoint é a base de recuperação observável.

**Tempo recomendado:** 6 min. Mostre uma transição e uma regra, não a camada
inteira de SQLite.

**Como apresentar:** Excalidraw + código, sem slide novo. Use
`infrastructure/persistence/sqlite.py` para `compare_and_swap` ou
`domain/models.py` para os campos de `RunCheckpoint`. Destaque que a revisão
avança exatamente uma vez.

**Pergunta:** “O checkpoint torna uma publicação externa idempotente?”

**Resposta/conclusão:** não. Ele preserva estado para a próxima decisão.
Escrita externa ainda exige chave idempotente, autorização, payload revisável,
aprovação e, quando necessário, compensação.

### 121–130 — Trace é trajetória, não pensamento interno

**Terminal:**

```bash
uv run aula12-agents show-trace <run-id>
```

**Pergunta:** “Um resultado final bom basta para chamar o run de bom?”

**Leitura guiada:** peça que encontrem estágio/transição, erro, tentativa,
duração, budget/política e decisão de gate. Mostre que JSONL local continua
quando Langfuse não está configurado.

**Conclusão:** avaliamos resultado e trajetória: aderência à política, fontes,
custo, repetição, cancelamento, escalonamento e recuperação. O trace não é uma
transcrição fiel ou necessária do raciocínio interno do modelo.

---

## Bloco 5 — 130–160 min: coordenação como hipótese a provar

### 130–135 — Começar pela métrica, não por agentes

**Slide:** “Que ganho marginal justifica outra tarefa?” e a métrica: cobertura
de evidência válida no mesmo orçamento e prazo. Para o caso, o card precisa de
ao menos duas fontes independentes, provenance válido e limitação explícita.

**Pergunta:** “Que lacuna de evidência o agente único ainda não cobre, sem
receber mais orçamento?”

**Conclusão:** coordenação não é coleção de personas. É uma topologia que só
vale se melhorar cobertura, qualidade ou latência de maneira mensurável.

### 135–142 — Supervisor fixo

**Excalidraw:** `05-quadro-de-coordenacao.excalidraw`.

**Terminal:**

```bash
uv run aula12-agents coordination run supervisor
uv run aula12-agents coordination show-board <run-id>
```

**Pergunta:** “Por que as tarefas de CI e mudanças recentes podem coexistir?”

**Leitura:** aponte perfis, escopos, budgets, prazo e o fato de cada tarefa
devolver `EvidenceReport`. O agregador é externo aos especialistas e aceita
somente relatórios válidos e atuais.

**Conclusão:** coordenação operável tem task board como fonte de verdade. Não
é uma conversa livre entre agentes.

### Bloco de código D — contrato Task/EvidenceReport (142–146, 4 min)

**O que é:** `CoordinationTask` descreve uma unidade de trabalho: id, pai,
perfil aprovado, escopo permitido, orçamento, prazo, tentativas, estado e token
de despacho. `EvidenceReport` descreve o resultado tipado, incluindo fontes e
o token da tarefa que o produziu.

**Por que importa:** dinâmica pode criar trabalho, mas não permissões novas.
O contrato impede que uma tarefa improvisada mude escopo, que um especialista
devolva texto sem proveniência, ou que resultado de uma execução antiga seja
aceito como atual.

**Tempo recomendado:** 4 min. O público é sênior; deixe a profundidade de
Pydantic para perguntas posteriores.

**Como apresentar:** código + diagrama 05; não precisa de slide novo. Use o
trecho de `domain/models.py` com `EvidenceReport` e `CoordinationTask`,
incluindo a validação que exige token/resultado coerente com `completed`.

**Pergunta:** “Qual desses campos impede uma subtarefa de virar um agente com
autoridade ilimitada?”

**Resposta:** escopo, perfil permitido, budget, deadline, estado e token;
nenhum isoladamente substitui os outros.

### 146–149 — Spawn saudável

**Terminal:**

```bash
uv run aula12-agents coordination run spawn
uv run aula12-agents coordination show-events <run-id>
```

**Pergunta:** “Que lacuna autorizou a tarefa adicional?”

**Conclusão:** a correlação por feature flag justifica investigador efêmero de
logs segmentados. Antes de ler a resposta, aponte quota e deadline. A tarefa
foi autorizada pelo contrato, não por improviso.

**Se o tempo estiver apertado:** não execute; use board/eventos gravados. O
cenário opcional é `spawn`, não `no-spawn`.

### 149–153 — No-spawn é uma decisão de qualidade

**Terminal:**

```bash
uv run aula12-agents coordination run no-spawn
```

**Pergunta:** “O que ganhamos ao não abrir outra tarefa?”

**Conclusão:** custo e prazo são preservados porque o limiar de cobertura já
foi atingido. Multiagente não é uma etapa obrigatória nem sinal de sofisticação.

**Fala sugerida:** “Se a nossa arquitetura sempre abre subagentes, ela não está
decidindo; ela está encenando coordenação.”

### 153–158 — Cancelamento causal e resultado tardio

**Excalidraw:** `06-cancelamento-causal.excalidraw`.

**Terminal:**

```bash
uv run aula12-agents coordination run cancelamento
uv run aula12-agents coordination show-board <run-id>
uv run aula12-agents coordination show-events <run-id>
```

**Pergunta antes do output:** “Uma tarefa dependente pode começar antes de sua
premissa ser válida? Se a resposta chega depois do cancelamento, o texto bom
deveria vencer?”

**Leitura guiada:** pai concluído; dependente criada/despachada com token;
nova evidência invalida premissa; dependente cancelada; relatório tardio chega;
board rejeita por estado/revisão/token supersedidos.

**Conclusão:** estado persistido vence eloquência de resultado. Cancelamento é
uma regra causal do sistema, não uma lembrança do especialista.

### 158–160 — Fechar a coordenação

**Slide:** três linhas: “modelo analisa evidência”; “coordenador transiciona,
reserva e aceita”; “gate autoriza fronteira externa”.

**Pergunta:** “Quem analisa, quem muda estado e quem autoriza efeito?”

**Conclusão:** multiagente é topologia a justificar, não maturidade automática.

---

## Bloco 6 — 160–180 min: transferência, exercício e encerramento

### 160–165 — ADR curto individual

**Slide:** enunciado de um novo caso e oito campos, sem framework como opção:

1. escolha arquitetural;
2. baseline rejeitado;
3. incerteza e evidência que justificam a escolha;
4. ferramentas/fontes permitidas;
5. escopo e orçamento;
6. gate;
7. condição de parada;
8. escalonamento/efeito proibido.

**Instrução:** “Escreva no máximo dez linhas. Uma escolha de workflow bem
justificada vale mais que um multiagente decorativo.”

### 165–170 — Ler contra a rubrica

**Rubrica em slide:**

| Adequado | Forte |
| --- | --- |
| Escolhe pelo tipo de incerteza; nomeia limite e saída segura. | Também compara baseline, ganho marginal, custo e evidência. |

Leia uma ou duas respostas voluntárias. Pergunte primeiro “qual incerteza isso
reduz?” e só depois comente ferramenta ou framework.

### 170–175 — Transferir o mecanismo, não o domínio

**Slide:** três cartões: code review (diff/testes → rascunho); documentação
(fonte/versão → proposta); exceção comercial (margem/alçada → recomendação sem
efeito financeiro). 

**Conclusão:** sensores e gates variam; autoridade, limites, estado e saída
segura permanecem.

### 175–180 — Dúvidas e síntese final

Registre confusões recorrentes: autonomia versus ferramenta; trace versus
cadeia de pensamento; memória versus histórico; coordenação versus personas.

**Frase final:** “O modelo pode ajudar a escolher a próxima investigação. O
sistema responsável escolhe os limites, conserva o estado, verifica a saída e
decide quando não agir.”

## Ordem de slides recomendada (briefing para Gamma)

Use 19 slides principais. Cada item abaixo é uma intenção editorial, não uma
prescrição visual rígida.

| # | Momento | Conteúdo mínimo | Artefato complementar |
| ---: | --- | --- | --- |
| 1 | Abertura | “Antes de agir, qual decisão segura precisamos tomar?” | incident packet |
| 2 | Caso | Safari é sensor, não causa | relato/dados do incidente |
| 3 | Baseline | “Quem decide a próxima etapa?” | diagrama 01 |
| 4 | Workflow | Caminho conhecido → código decide | fluxo simples |
| 5 | LLM no workflow | Modelo interpreta; código roteia | `BugReport` ilustrativo |
| 6 | Virada | “Qual evidência consultar agora?” | diagrama 02 |
| 7 | Limite | Ferramenta é capacidade | código A |
| 8 | Resultado | Hipótese com fonte, limite e próxima ação | hypothesis card |
| 9 | Contexto | Contexto não é histórico | diagrama 03 |
| 10 | Memória | Estado que sobrevive sob política | quatro cartões |
| 11 | Aceitação | “Plausível não é aceitável” | código B |
| 12 | Falha | Retry, replanejar ou escalar? | diagrama 04 |
| 13 | Recuperação | Checkpoint preserva decisão, não autoriza escrita | código C/trace |
| 14 | Métrica | Que ganho marginal justifica coordenação? | comparação baseline |
| 15 | Supervisor | Contratos, não conversa livre | diagrama 05 + board |
| 16 | Spawn | Lacuna explícita, quota e prazo | eventos |
| 17 | No-spawn | Não criar trabalho também é decisão | CLI resumida |
| 18 | Cancelamento | Estado atual vence resultado tardio | diagrama 06 + eventos |
| 19 | Fechamento | Menor desenho suficiente | exercício/síntese |

Slides de contingência: rubrica do exercício; matriz workflow/LLM/agente/
coordenação; trace anotado; transferência para os três domínios.

## Cartão de contingência do instrutor

| Situação | Decisão imediata | Nunca sacrificar |
| --- | --- | --- |
| Provider/terminal lento | Abrir output mock congelado | Pergunta, leitura e conclusão. |
| Só há tempo para três cenários de coordenação | `supervisor`, `no-spawn`, `cancelamento` | `no-spawn` e cancelamento. |
| Turma quer detalhes de framework | Responder em 60 segundos e voltar à autoridade | Caso, gates e recuperação. |
| Turma quer “dar todos os dados” | Perguntar qual decisão cada item mudaria | Contexto mínimo governado. |
| Turma pede cadeia de pensamento | Redirecionar para fontes, transições e limites observáveis | Não inferir processo interno do modelo. |
| Discussão vira patch automático | Reafirmar que investigação é read-only | Separação entre análise e efeito. |

## Checklist de qualidade antes de entrar em sala

- [ ] Cada slide responde uma pergunta de engenharia e não repete uma demo.
- [ ] O caso Safari/`session_id` aparece do início ao fim, sem prometer patch.
- [ ] Há um output mock e um `run_id` preparado para cada execução.
- [ ] Os seis Excalidraw estão abertos e na ordem da narrativa.
- [ ] Apenas os blocos de código A–D serão projetados; arquivos inteiros não.
- [ ] `no-spawn` está no roteiro principal, não como apêndice.
- [ ] O trace será lido como trajetória, não como pensamento interno.
- [ ] A última frase preserva a opção de escolher menos autonomia.
