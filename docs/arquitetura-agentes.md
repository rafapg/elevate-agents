# Arquitetura dos agentes e do workflow

Este laboratório demonstra um workflow multiagente **controlado pela aplicação**. Ele não é uma conversa livre entre personas, nem deixa que um modelo decida quais etapas executar. PydanticAI é usado dentro das etapas que exigem raciocínio e chamadas de ferramenta; o fluxo, a persistência e as decisões de segurança permanecem determinísticos.

## Visão geral

```text
                         ┌───────────────────────────────┐
                         │        RunCoordinator         │
                         │ estado, retry, CAS e transição │
                         └───────────────┬───────────────┘
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        │                                │                                │
        ▼                                ▼                                ▼
┌───────────────┐              ┌───────────────────┐             ┌──────────────────┐
│ Evidence tool │              │ Especialista      │             │ Crítico          │
│ somente leitura│ ─evidências→│ de hipótese       │ ─handoff→   │ sem ferramentas  │
└───────────────┘              │ (PydanticAI)      │             │ (PydanticAI)     │
                               └───────────────────┘             └────────┬─────────┘
                                                                          │
                                                                          ▼
                                                               ┌──────────────────┐
                                                               │ Gate determinístico│
                                                               └───────┬──────────┘
                                                                       │
                                      ┌────────────────────────────────┼──────────────────────────────┐
                                      ▼                                ▼                              ▼
                                concluir                         repetir com limite             escalar a humano
```

O `RunCoordinator` é a autoridade do workflow. Os dois agentes devolvem dados tipados; nenhum deles grava o checkpoint, agenda retry, chama o outro agente ou executa uma ação externa.

## Papéis e limites

| Componente | Responsabilidade | Pode usar ferramentas? | Pode alterar o workflow? |
| --- | --- | ---: | ---: |
| `FixtureGateway` | Coletar o pacote de evidências | Sim, apenas leitura | Não |
| Especialista de hipótese | Formular uma hipótese estruturada com base nas evidências | Sim, apenas o toolset read-only | Não |
| Crítico | Revisar a proposta e recomendar aprovar, repetir ou escalar | Não | Não |
| `RunCoordinator` + gate | Validar, persistir e realizar transições | Não | Sim, de modo determinístico |

Essa assimetria é intencional: o especialista pode buscar fatos, mas o crítico recebe apenas o hand-off tipado. Assim a revisão não cria uma segunda fonte de verdade, não reinicia a investigação por conta própria e não amplia as permissões do fluxo.

## Caminho normal de uma execução

1. A CLI cria um `Incident` e chama `RunCoordinator.start()`.
2. O coordenador cria um `RunCheckpoint` em SQLite na etapa `collect_evidence`.
3. O `ReadOnlyToolGateway` reúne `Evidence` a partir dos fixtures. Em um provider real, o especialista também tem o tool `read_evidence`; ele só pode solicitar esse mesmo pacote limitado.
4. O especialista devolve um draft estruturado. O adapter converte-o para `HypothesisCard` e valida as referências de proveniência.
5. Antes da crítica, a aplicação persiste `hypothesis_card` no checkpoint com `next_step="review_hypothesis"`. Esse é o hand-off durável entre os especialistas.
6. O crítico recebe a proposta e um `EvidencePack` compacto. Ele retorna uma `CritiqueCard` com `approve`, `retry` ou `escalate`.
7. O gate traduz a recomendação em uma transição: concluir, agendar retry ou escalar para revisão humana.

O fluxo padrão da CLI `mock` usa executores determinísticos para manter a aula reproduzível. Ollama e OpenRouter substituem somente os adapters dos especialistas; as transições são as mesmas.

## Os contratos Pydantic

O laboratório deliberadamente separa dados de modelo e artefatos de domínio.

| Camada | Modelo | Significado |
| --- | --- | --- |
| Entrada do modelo | `agent.contracts.HypothesisDraft` | Saída estruturada, mas ainda não confiável, do especialista PydanticAI. |
| Domínio | `domain.models.HypothesisDraft` | Afirmação estruturada já normalizada pela aplicação. |
| Domínio | `HypothesisCard` | Proposta com decisão, incerteza, próxima ação e referências de evidência. |
| Entrada do crítico | `HypothesisReviewContext` | Hand-off imutável: draft mais pacote de evidências. |
| Saída do crítico | `HypothesisReview` | Recomendação do modelo em formato de adapter. |
| Domínio | `CritiqueCard` | Recomendação normalizada e persistível do crítico. |
| Persistência | `RunCheckpoint` | Estado canônico e versionado da execução. |

Há propositalmente dois tipos chamados `HypothesisDraft`, em módulos diferentes. O de `agent.contracts` representa o que chega do LLM; o de `domain.models` é o valor usado pelo domínio após conversão. A distinção garante que uma saída sintaticamente válida do modelo não seja automaticamente uma decisão de negócio. Para navegação no código, sempre prefira o import qualificado ou verifique o módulo de origem.

As conversões ficam em `application/conversion.py`. Elas fazem a ponte entre os modelos do adapter e os modelos de domínio, e são o lugar adequado para rejeitar formatos ou referências inválidas.

## Evidência e proveniência

Cada `Evidence` possui uma `EvidenceRef`: identificador, origem, artefato, hash de conteúdo e instante de captura. Antes de aceitar uma hipótese, `_enforce_provenance()` verifica que toda referência citada pelo agente existe no pacote read-only fornecido naquela execução.

O `EvidenceGate` acrescenta regras de segurança do domínio. Portanto, "o modelo respondeu JSON válido" não é uma condição suficiente para concluir o workflow; a proposta ainda precisa ser coerente com o conjunto de evidências permitido.

## Retry, retomada e concorrência

Checkpoint não significa recuperar uma chamada LLM interrompida no meio. O laboratório persiste fronteiras seguras entre estágios e pode reiniciar uma etapa a partir do último artefato completo.

```text
checkpoint da hipótese ──timeout do crítico──> waiting_retry/review_hypothesis
                                                    │
                                                    ▼
                                           aula12-agents resume <run-id>
                                                    │
                                                    ▼
                                  reidrata evidência read-only + reexecuta só o crítico
```

- Tentativas são limitadas por estágio (`investigate` e `critic`).
- A retomada do crítico reutiliza a `HypothesisCard` persistida; não volta ao especialista.
- A evidência é reidratada apenas por referências e validada outra vez.
- SQLite usa compare-and-swap (CAS) por `revision`. Um worker tardio não consegue sobrescrever um checkpoint que outro worker já avançou.
- Depois de esgotar o orçamento, o fluxo escala em vez de insistir indefinidamente.

Os cenários executáveis estão em `tests/e2e/test_hypothesis_critic_gate.py` e `tests/e2e/test_multistage_resume_resilience.py`.

## Observabilidade

Cada execução compartilha o mesmo `run_id` entre checkpoint, eventos de workflow e observações de ferramenta.

- JSONL local é sempre a base operacional e permite inspeção/replay sem rede.
- Langfuse é opcional. Quando configurado, recebe a instrumentação nativa de PydanticAI e os eventos de estágio/gate.
- As observações de ferramenta são gravadas apenas no JSONL para não duplicar spans de modelo/ferramenta no Langfuse.
- O trace aplica redaction antes de persistir ou exportar; prompts e segredos não são capturados por padrão.

Use `show-events` e `show-trace` para inspecionar uma execução sem consultar o backend remoto.

## O que este exemplo não faz

- Não executa escrita automática ou efeitos externos.
- Não implementa um scheduler de produção; a retomada é manual pela CLI.
- Não promete durabilidade no meio de uma requisição LLM.
- Não trata agentes como controladores autônomos do workflow.

Esses limites são parte do objetivo pedagógico: primeiro tornar explícitos estado, contrato, permissão e recuperação; depois discutir como uma engine durável ou uma camada de aprovação humana poderia ampliar o desenho.
