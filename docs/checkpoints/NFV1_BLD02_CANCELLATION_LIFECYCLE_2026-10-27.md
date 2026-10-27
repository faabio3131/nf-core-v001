# BLD-02 — cancelamento vinculado ao lifecycle durável

Dependência: PR #257, HEAD `35d6e4273f179abd873f6a72e36966ab7a80eddf`.
BLD-02 permanece IN_PROGRESS até integração e gates completos desta cadeia.

## Delta de construção

O Portal passa a incluir a referência do documento no cancelamento, além da
chave/protocolo/justificativa tipados. A composição durável confere a associação
document_id → request preparado → tentativa autorizada; exige mesma chave,
protocolo e escopo. Referência inexistente, outra unidade ou protocolo divergente
falham no preflight antes do intent. Sem aplicação/retencão configuradas, o caminho
com document_id falha fechado. Contrato legado sem document_id permanece compatível
para consumidores explícitos; não atribuir sincronização de lifecycle a esse uso.

FiscalCancellationService continua autoridade das transições. Suas etapas puras
prepare/complete agora podem ser usadas pela FiscalApplicationService: grava
CANCEL_REQUESTED antes do I/O; recebe resposta pelo FiscalOperationsClient que
valida identidade; salva evidência e transição terminal na mesma UOW. Aceito leva
a CANCELLED, rejeitado volta a AUTHORIZED, pendente permanece CANCEL_REQUESTED.
Nenhum recibo HTTP autoriza mudança de estado por si. Histórico de autorização
não é reescrito e numeração não é liberada.

Timeout/crash e falha do commit final mantêm CANCEL_REQUESTED; novo dispatch é
bloqueado. Concorrência usa a versão do lifecycle para impedir duas chamadas.
Perda de resposta após commit usa a recuperação da evidência da PR #257. Estado
pendente/desconhecido requer evidência confiável de reconciliação futura; não
inventar protocolo ou usar replay para reenviar cancelamento.

## Provas

Testes SQLite e cenários PostgreSQL descartáveis na CI: accepted/rejected/pending,
claim visível antes da chamada, timeout/restart sem reenvio, concorrência com único
dispatch, rollback de evidência/lifecycle, preflight cross-scope/protocolo e jornada
HTTP autenticada prepare→resume→lifecycle/arquivo→replay. Provider sintético somente
na fronteira dos testes. Casos PostgreSQL são SKIP local por ausência de DSN.

Suítes locais de operações/eventos/recuperação/cancelamento PASS. Ruff global,
Mypy de 227 fontes, lint/typecheck/build e 18 testes frontend PASS. Teste browser
existente ampliado para cancelamento com referência, CSRF e idempotência; execução
Chromium depende da CI. Sem deploy, migration, provider/credencial real ou produção.

## Próximo gate

Integrar em ordem #256 → #257 → este incremento, somente com CI/Governança
pré/pós-merge SUCCESS. Reconciliar o aceite BLD-02 por capacidade, distinguindo
construção interna de publicação/homologação; depois iniciar BLD-03 conforme ledger.
