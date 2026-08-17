# Cenários de coordenação pré-executados

Estes arquivos são exemplos didáticos sintéticos. Eles não foram produzidos por
uma execução real, não chamam um modelo e não substituem o fluxo executável do
laboratório. O objetivo é permitir que a aula mostre decisões de coordenação
sem rede, credenciais ou uma plataforma adicional de multiagentes.

Cada linha dos arquivos `.jsonl` é um evento de trace seguro para projeção:
não há prompts, respostas de modelo, conteúdo bruto de evidência ou segredos.
Todos os eventos trazem `synthetic: true` nos atributos.

## Ordem de uso sugerida

1. Compare o agente único já executado no laboratório com
   `01-supervisor-fixo.jsonl`: o que melhora ao separar CI e mudanças recentes?
2. Abra `02-spawn-saudavel.jsonl` somente quando a turma identificar uma
   lacuna objetiva: a correlação por feature flag.
3. Use `03-no-spawn.jsonl` como contraste: a cobertura já é suficiente e a
   tarefa adicional é recusada antes de consumir orçamento.
4. Termine com `04-cancelamento-resultado-tardio.jsonl`: uma hipótese é
   invalidada, o trabalho dependente é cancelado e sua resposta tardia não é
   agregada.

## O que observar

- `task_id` e `parent_task_id`: qual trabalho foi aberto e por quem;
- `allowed_profile` e `tool_scope`: quem pode fazer o quê;
- `budget_steps` e `deadline_seconds`: limites definidos pela aplicação;
- `evidence_sources`, `has_provenance` e `has_limitation`: cobertura válida,
  não quantidade de texto;
- `decision` e `reason`: por que agregar, não abrir, cancelar ou rejeitar.

Os identificadores e horários são fixos para que os exemplos sejam
reproduzíveis. Para validar os arquivos, execute `uv run pytest -q
tests/contract/fixtures/test_coordination_traces.py`.

Para apresentá-los em formato legível, sem iniciar agentes ou serviços externos:

```bash
uv run python scripts/show_coordination_scenario.py supervisor
uv run python scripts/show_coordination_scenario.py spawn
uv run python scripts/show_coordination_scenario.py no-spawn
uv run python scripts/show_coordination_scenario.py cancelamento
```
