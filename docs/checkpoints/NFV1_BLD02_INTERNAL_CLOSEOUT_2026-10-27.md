# NFV1-BLD-02 — aceite de construção fiscal interna

**Estado:** DONE_BUILD_INTERNAL, confirmado após CI/Governança pré e pós-merge SUCCESS.
**Código integrado:** aa04c8b2b63384880e3d6a98f41771b2f0415c8f.
**Árvore integrada:** f9f5d254cae3618fb8094e03231f3ac701a5f6d0, igual à combinação local revisada da candidata com a main anterior, sem conflitos.
**Escopo:** gate BUILD-ONLY do anexo de 18/10: ações internas com estado real ou bloqueio explícito. Não é homologação fiscal, deploy ou liberação comercial.

## Evidências

| PR | HEAD revisado | Merge | CI / Governança |
|---|---|---|---|
| #253 | d4aa0bb88c9545d8303942bb799b11a39a9516b9 | e338ef40345d84a535d9e8bc8b31037f5ff59412 | PR 40518036563 / 40518036451 SUCCESS; main 40520535686 / 40520535562 SUCCESS |
| #254 | e7156bd8df81072cacfd5188e07d56917ff3f1e0 | 4b258afe19af8b532c3a8afc8543bfb1568d11dd | PR 40521826969 / 40521826836 SUCCESS; main 40524003195 / 40524003091 SUCCESS |
| #255 | 2056b7d1917774334b7846ff270f2c6116a7a3dc | 64b460018c0b76e28487dd182d71d1ca2555f4a6 | PR 40524460847 / 40524460912 SUCCESS; main 40527742967 / 40527743159 SUCCESS |
| #258 | 84e3345f284d653756ae046233a0137fde51cd50 | aa04c8b2b63384880e3d6a98f41771b2f0415c8f | PR 40530810061 / 40530809955 SUCCESS; main CI 40533251021 SUCCESS, Governança 40533250901 SUCCESS |

[PR #258](https://github.com/faabio3131/nf-core-v001/pull/258) · [CI da candidata](https://github.com/faabio3131/nf-core-v001/actions/runs/40530810061) · [CI da main](https://github.com/faabio3131/nf-core-v001/actions/runs/40533251021).

As revisões #256/#257 foram consolidadas integralmente em #258; não repetir seus merges. Foram encerradas como substituídas após sucesso pós-merge. A consolidação foi registrada na PR #258.

## Matriz código → API → Web → persistência

| Capacidade | Autoridade e integração | Prova interna |
|---|---|---|
| Documentos/arquivo | Superfícies autorizadas, queryArchiveReference e FiscalArchiveStore; conteúdo bruto não exposto | test_nfv1_internal_archive_handler.py, test_portal_api.py e superfícies P02; baseline 2911cb2/2f0de7c preservado |
| Consulta fiscal | FiscalOperationsClient valida identidade; formulário tipado; Portal conserva status/chave/protocolo como texto | test_nfv1_provider_query_handler.py; três cenários browser authorized/pending/not_found na #255 |
| Preparação NF-e/NFC-e/NFS-e | Numeração, lifecycle, idempotência e arquivo canônicos antes do I/O; codec NFS-e revalida namespace/fingerprint | Suítes issuance, test_nfv1_durable_issuance.py, test_nfv1_nfse_preparation_recovery.py; #249/#253/#254 |
| Emissão/recuperação | Referência preparada no Portal, preflight e claim durável; consulta validada sem retransmissão após resultado desconhecido | test_nfv1_prepared_reference_preflight.py, emissão durável, NFS-e e browser de recuperação |
| Cancelamento vinculado | document_id/chave/protocolo conferidos na autorização persistida; CANCEL_REQUESTED antes de I/O; evidência e estado terminal na mesma UOW | test_nfv1_durable_cancellation.py: HTTP autenticado, estados, concorrência, timeout/restart, rollback; browser com referência/CSRF/idempotência |
| Inutilização | Request canônico de faixa validado antes do intent; evidência normalizada no arquivo; fila distinta do resultado fiscal | test_nfv1_provider_event_handlers.py, test_nfv1_event_evidence_recovery.py, P02-T06/T07 e browser de inutilização |
| Erros/reconciliação | Estados duráveis e projeções rejected/pending; evidência exata recupera referência sem dispatch | HTTP das projeções e testes de eventos; CANCEL_REQUESTED permanece visível em Emissões |
| Certificados/providers/webhooks/settings | Referências/configurações versionadas existentes; segredo fora do browser; aprovação de egress separada de entrega | test_p02_t03_configuration_surfaces.py e configuration_durable.spec.js; baseline d9c1892 protegido pela CI atual |
| Escopo/bloqueios | Portal/Bridge canônicos; tenant/unidade/host/ambiente/RBAC/CSRF no servidor; dependência ausente bloqueia | Suítes P02, preflight, recovery e wiring; nenhum fake habilitado no runtime |

CI da candidata: **2563 PASS / 3 SKIP / zero FAIL** em Python, **36 PASS** Playwright, **18 PASS** frontend, Ruff, Mypy de 227 fontes, lint/typecheck/build, auditorias e checks de containers SUCCESS. A CI configura PostgreSQL descartável; SKIP local por ausência de DSN não foi utilizado como prova. Provider sintético somente na fronteira de testes, sem alegar operação fiscal oficial.

## Limites

- Composição durável exige aplicação/retenção e clientes explicitamente configurados. Não seleciona provider, jurisdição, segredo ou produção por padrão.
- Portal cancela por referência de documento. Contrato legado sem document_id permanece compatível para consumidores explícitos, mas não recebe certificação de sincronização do lifecycle.
- Pendente/timeout mantém estado não terminal e bloqueia novo envio. Reconciliação externa exige evidência confiável; nenhum protocolo é inventado. Adapter municipal NFS-e/provider oficial e homologação pertencem aos gates externos/BLD-05.
- Recibo T07 continua metadata-only, mesma conta/session_epoch, sem bypass. Resultado normalizado fica no arquivo; surfaces expõem somente campos autorizados. Dados de testes sintéticos.
- Nenhuma solicitação de deploy, alteração de schema compartilhado, credencial, preço/trial ou operação fiscal real. Web publicada e staging ficam em BLD-08 após autorização específica. Checkboxes das 59 tarefas intactos.
- O ambiente local ficou indisponível durante a espera da CI, depois de todo o código ter sido integrado ao GitHub. O fechamento continua pelo conector GitHub; não reconstruir código já persistido.

## Próximo bloco

Primeiro bloco aberto após o fechamento interno do BLD-02: **NFV1-BLD-03**. Backend público e GovernedTrialService já existem; não reconstruir. Delta identificado: página de cadastro no NFCore e jornada browser segura. Auditar PR #237 antes de reaproveitar o teste PostgreSQL. Catálogo, trial_days, binding administrativo, origens e publicação reais continuam governados; construir parametrizável sem inventar oferta nem expor segredo S2S.


## Bloqueio de publicação automática identificado no fechamento

Após integrar #258, a inspeção read-only confirmou publicação automática do Portal de staging: Railway deployment `bfd5978e-30c1-4a25-8049-42ca9f3c020e`, status `SUCCESS`, commit `aa04c8b2b63384880e3d6a98f41771b2f0415c8f`, criado em 2026-10-27T15:40:07Z. Projeto `b84b290d-f3b4-46a1-9023-0b761cb96b0d` (FM NFCORE Staging), ambiente `c9878b9b-62b2-4a97-b8ba-743c8a3e99ec`, serviço `1e459bbb-9903-4ece-bc9d-2c50e271cd1e` (nfcore-portal). A fonte segue `faabio3131/nf-core-v001:main`, com `checkSuites=false`. O efeito foi identificado depois dos merges; não afirmar ausência de deploy nesta execução. Não houve comando manual de deploy nem prova de jornada fiscal externa.

O AGENTS.md exige “Não fazer deploy por consequência do merge” e autorização específica para deploy/infraestrutura. Portanto, novos merges ficam retidos até resolver esse vínculo; a PR #259 preserva o fechamento interno no repositório. Proposta para decisão humana: fixar somente o Portal desse ambiente no commit já publicado `aa04c8b2b63384880e3d6a98f41771b2f0415c8f`, mantendo futuras publicações explícitas. A aplicação da mudança pode reconstruir/publicar o mesmo commit; não foi executada. Nenhuma configuração Railway foi alterada.

A primeira CI da #259 (`40535706729`) falhou em três testes de governança que pressupunham exatamente BLD-02 aberto. Os casos negativos agora usam ledger sintético fixo, preservando rejeição de salto, múltiplos blocos ativos e falta de evidência; um teste separado continua validando o ledger real. O validador de governança não foi enfraquecido. A nova revisão exige CI própria antes de Ready.
