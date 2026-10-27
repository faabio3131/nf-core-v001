# BLD-02 — validação de eventos antes do intent

Base: `4b258afe19af8b532c3a8afc8543bfb1568d11dd`, PR #254 integrada após
CI `40521826969` e Governança `40521826836` SUCCESS. Pós-merge CI
`40524003195` em andamento durante implementação; Gov `40524003091` SUCCESS.
PR #255 contém somente o retorno visual das operações e continuidade anterior.

## Delta

Cancelamento e inutilização validavam contratos apenas durante o resume, depois
do claim persistido. Entrada inválida deixava um intent em resultado desconhecido
mesmo sem I/O externo. Os handlers agora reutilizam a construção dos requests no
preflight read-only, antes de reservar o intent; a execução revalida o request.
Modelo inválido é normalizado como FiscalValidationError, não ValueError/500.
O wrapper já usado pela emissão/reconciliação foi movido para fiscal_runtime e
reutilizado; não há segunda autoridade de validação, emissão ou recuperação.

Seis regressões HTTP autenticadas com SQLite durável cobrem chave inválida,
protocolo ausente, justificativa curta, modelo inválido, booleano e faixa invertida.
Rejeição não grava intent nem chama provider; correção com a mesma chave pode
prosseguir e replay não reenvia. Fronteira de provider é sintética apenas em teste.
Ruff e Mypy global PASS; testes dirigidos de eventos, wiring, NFS-e e referências
preparadas PASS. CI remota obrigatória antes de integração.

## Pendências de construção identificadas

- O recibo T07 é deliberadamente metadata-only. Não inserir resultado bruto nele:
  política aprovada em `NFV1_P02_T07_FISCAL_INTENT_RECOVERY_POLICY_PROPOSAL_2026-10-08.md`.
- Handlers genéricos de eventos validam resposta do provider, mas a auditoria ainda
  não demonstrou persistência do protocolo e sincronização do cancelamento com
  lifecycle durável. Reutilizar FiscalCancellationService/arquivo/UOW; não promover
  BLD-02 a DONE enquanto essa integração interna não estiver resolvida ou seu
  bloqueio de escopo demonstrado. Recibo recorded não certifica sucesso fiscal.
- Provider, credenciais e homologação permanecem externos; não bloqueiam correções
  independentes de construção. Não houve deploy, migration ou operação oficial.

BLD-02 IN_PROGRESS. Próximo: gates destas alterações e ligação canônica dos
resultados de eventos, seguida da matriz de fechamento interno.
