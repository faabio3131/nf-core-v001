> **AVISO DE CURRENT (31/10/2026):** as seções de 09–10/10 abaixo são CHECKPOINTS HISTÓRICOS Railway, não o estado atual da Contabo. Para retomar, verificar `main`, `production`, PRs e CI no GitHub e ler `docs/checkpoints/NFV1_CROSS_REPO_ANTI_REWORK_2026-10-31.md`. A auditoria de 31/10 encontrou `main=d68c62d9c7e90581ad5efd387927f83c40a59ba2` **na entrada**, depois a PR #279 integrou `9564406e2c2af6cee99266301309f045dbbd878a`, com CI pós-merge ainda não concluída naquele momento. Não assumir que branches ou containers da Contabo estejam sincronizados nem repetir migrations, backup, P05 ou BLD certificados a partir destas notas antigas.

# CURRENT superior — NFV1-P05-T01 runtime migration authority em branch — 2026-10-10

Revalidado: `main=0fdcce7de18a779ecf7a193fbd01b83d8087c5c5`, PR #162 **MERGED**, CI #762 e Governance #183 **SUCCESS** no SHA da main, 41/41, 2038 Python/Postgres + 14 frontend + 28 Playwright PASS; 27/59 concluídas, primeira pendente P05-T01. Nenhuma PR aberta na entrada desta intervenção. O checkpoint de B05 abaixo reflete o estado **histórico durante a PR #162**, não seu estado final. Auditada rota adicional Cakto: `build_postgres_runtime_composition` chamava `CaktoCommercialDatabase.initialize()` em startup, mesmo com checkout comercial habilitado; a candidata move Cakto v1/v2 para o mesmo `migration_guard --apply` governado e verifica o schema read-only no bootstrap.

Railway read-only novamente: FM NFCORE Staging env label `production` (não é aprovação de produção), API/Portal/DB 1/1, Worker **0/1**, deployments API/Portal `f9b5b2c5...` e Worker `1c34ba00...` (drift em relação à main). API `preDeployCommand` ainda executa `migration_guard.py --apply`; código vigente também chamava `database.initialize()` em API e Worker ao iniciar, criando caminhos de migration sem recibo de backup. Nome da variável `NFCORE_WORKER_ONESHOT` presente; **valor e causa do Worker parado não confirmados**.

**Em execução somente patch interno, branch `fix/nfv1-p05-t01-single-migration-authority`**: API e Worker em staging/produção verificam schema read-only `1..17` e nunca executam `initialize()`; comando `migration_guard --apply` bloqueia contexto de preDeploy Railway, testes de regressão. **Ainda não certificado neste registro**, merge não autorizado. A configuração externa duplicada permanece sem alteração, assim como SQL/backup real PG18, GSM/IAM/bootstrap e Worker. Ver `docs/checkpoints/NFV1_P05_T01_RUNTIME_MIGRATION_AUTHORITY_2026-10-10.md`.

`P05-T01=[ ] bloqueado externo`, `EXTERNAL_SECRET_BACKEND_CERTIFIED=NOT MET`, `STAGING_CURRENT_SHA_E2E_CERTIFIED=NOT MET`, `PRODUCTION_APPROVED=NO`, `COMMERCIAL_LIVE=NO`. Nenhum deploy/redeploy, migração SQL real, backup/restore real, alteração IAM/secret/variável Railway nem operação fiscal.

---

# CURRENT superior — NFV1-P05-T01 B05 patch fail-closed em PR #162 — 2026-10-10

GitHub main de entrada `3a14cf5dff00f892b0c8b3502fb2e12d13be6f87`, CI #753 e Governance #174 SUCCESS; 27/59 tarefas concluídas. Em execução **apenas o patch interno B05** na branch `fix/nfv1-p05-t01-railway-predeploy-failclosed` / PR #162, sem merge ou deploy. A task P05-T01 continua `[ ] bloqueado externo`, pois backup e SQL/restore reais, Google Secret Manager/IAM/bootstrap e Worker runtime real seguem sem certificação.

Correção candidata: provider Railway precisa comprovar backup COMPLETED/retenção, ID de deployment novo, SHA exato e réplicas RUNNING; o driver rejeita dados ausentes, version mismatch e Worker 0/1. Regressões sintéticas e gates CI PR pendentes. Sem prover prova real de schema CLI backup, o driver permanece fail-closed; CI sintética não homologa integração externa. A API tem `preDeployCommand` de migration não reconciliado, logo staging não foi liberado. Checkpoint `docs/checkpoints/NFV1_P05_T01_RAILWAY_PREDEPLOY_FAILCLOSED_PATCH_2026-10-10.md`.

`EXTERNAL_SECRET_BACKEND_CERTIFIED=NOT MET`; `STAGING_CURRENT_SHA_E2E_CERTIFIED=NOT MET`; `PRODUCTION_APPROVED=NO`; `COMMERCIAL_LIVE=NO`. Nenhum IAM, segredo, conta, billing, SQL, backup real, migration real, deploy, DNS ou operação fiscal executado.

---

# CURRENT superior — revalidação real de staging NFV1-P05-T01 (somente leitura) — 2026-10-10

GitHub `main` `088735ed2a34ed1f372e62e4208cad3389c48f1d`; CI #751/Governance #172 SUCCESS; cronograma 27/59 concluídas, primeira pendente T01 **BLOCKED_EXTERNAL**. Railway projeto **FM NFCORE Staging** com ambiente chamado `production` (somente rótulo, não autorização de produção): API 1/1, Portal 1/1, Postgres 1/1 (imagem PostgreSQL18), Worker **0/1 running** apesar de `SUCCESS`/`Online`. Revisões antigas API/Portal `f9b5b2c5...` e Worker `1c34ba00...`, diferentes da main. Driver do staging aceita SUCCESS sem comprovar SHA/réplicas; solicita backup sem aguardar recibo; configuração API ainda invoca `migration_guard.py --apply` por preDeployCommand, potencialmente antes do backup e duplicando a ordem do script. B01 backup comprovado, B02 SQL/restore real, B04/P6-T01-B02 IAM/GSM/Worker, B05 driver/runtime continuam sem prova. Checkpoint novo: `docs/checkpoints/NFV1_P05_T01_READ_ONLY_STAGING_REVALIDATION_2026-10-10.md`.

**Nenhuma alteração externa realizada**; sem token, valor de variável, dados de cliente, DB query, backup, secrets/IAM, deploy ou migration. `EXTERNAL_SECRET_BACKEND_CERTIFIED=NOT MET`, `STAGING_CURRENT_SHA_E2E_CERTIFIED=NOT MET`, `PRODUCTION_APPROVED=NO`, `COMMERCIAL_LIVE=NO`. O ledger de T01 continua aberto; PR apenas documental, sem marcar gate concluído nem avançar para T02.

---

# CURRENT superior — NFV1-P06-T04 certificada internamente pós-merge — 2026-10-10

GitHub reconfirmado: PR #159 MERGED, `main` `d2600c6a6604d9f3f8be3ea3642b78ebbf688832`, head original `0763dc97f6fe3053bf80f22d1eae27095a9d24a0`. CI da PR #747/run38063730623 e Governance #168/run38063730630 SUCCESS; pós-merge CI main #748/run38064965857 e Governance #169/run38064965821 SUCCESS no SHA do merge, 41/41 etapas, 2.022 Python/PostgreSQL PASS, 14 frontend PASS, 28 Playwright PASS, zero FAIL/SKIP e um warning TestClient. Segurança, migrations, containers/SBOM, backup/restore/readiness PASS.

T04 `DONE_CERTIFIED_INTERNAL`: seis classes de falha e rotação certificadas com quatro tipos de segredo, reuso das autoridades canônicas, 85 testes adicionais e bancos SQLite/PostgreSQL. **Nenhum código de produção alterado.** Provas persistidas na PR #159 e no checkpoint `docs/checkpoints/NFV1_P06_T04_ROTATION_FAILURES_2026-10-10.md`. Closeout documental registra 27/59 concluídas **quando integrado**; primeira pendente NFV1-P05-T01, ainda bloqueada.

**P6-T01-B02 BLOCKED_EXTERNAL**: conta/projeto/região/billing/budget/identidade/IAM/bootstrap/canal e acesso GSM real sem prova. `EXTERNAL_SECRET_BACKEND_CERTIFIED=NOT MET`. Último staging somente leitura: API/Portal/PostgreSQL 1/1, Worker 0/1, drift, não reinspecionado neste closeout. `PRODUCTION_APPROVED=NO`; `COMMERCIAL_LIVE=NO`. **P05-T01 não está liberada**, staging/deploy/conta/gasto/credencial/cloud real/fiscal real permanecem sujeitos a autorização e evidência. Este fechamento não inicia P5 e não executa deploy.

---

# CURRENT superior — NFV1-P06-T04 em execução — 2026-10-10

GitHub reconfirmado antes da tarefa: main `0e61a8311253aecf06a3faa48afd3b5b1be073b4`, PR #158 MERGED, zero PRs abertas, CI #746/run38062516241 e Governance #167/run38062516233 SUCCESS no mesmo SHA. Predecessora T03 DONE_CERTIFIED_INTERNAL; ledger com 26/59 concluídas. Primeira pendente T04 — rotação e falha, agora em execução numa branch isolada; **não marcada concluída**.

CURRENT do código: bindings GSM duráveis metadata-only com estado active/revoked, cloud_version pinada, revision/CAS e revalidação de escopo/estado após I/O; adapters de assinatura/fiscal existem. TARGET T04: testes reprodutíveis dos cenários missing, revoked, expired, permission denied, backend unavailable, rotation, inclusive race/replay/CAS e auditoria sanitizada nos dois backends SQL. Não criar nova autoridade nem automatizar acesso cloud. A CI da candidata ainda precisa ser executada.

B02 P6-T01 externo não solucionado: projeto/conta/região/identidade/IAM/bootstrap/canal de prova real GSM sem evidência. Último staging read-only conhecido: API/Portal/PostgreSQL 1/1, Worker 0/1 e drift; **não reinspecionado** nesta etapa. `EXTERNAL_SECRET_BACKEND_CERTIFIED=NOT MET`, `PRODUCTION_APPROVED=NO`, `COMMERCIAL_LIVE=NO`. Sem credenciais, cloud real, conta, gastos, deploy, SQL produtivo, DNS ou emissão fiscal.

---

# CURRENT superior — NFV1-P06-T03 certificada internamente pós-merge — 2026-10-10

Reconsulta ao GitHub: `main` `1f5ec590104c5819173196b7d6dc56e58a2f3a53`; PR #157 MERGED, nenhuma PR aberta antes deste fechamento. Head `36021c5a4aa43d60645084eaae5fd36e2c0954d0`, tree `6860ab7eb3145f461b62736c615b24b326e6950b`. CI #743/run38051172757 e #744/run38055767078 SUCCESS; Governance #164/run38051172760 e #165/run38055767027 SUCCESS. Pós-merge 41/41 etapas, 1.937 Python/PostgreSQL, 14 frontend, 28 Playwright PASS, zero FAIL/zero SKIP, inclusive segurança, containers/SBOM e backup/restore/readiness.

T03 DONE_CERTIFIED **internamente**: 196 casos novos cobrem isolamento de tenant/unidade/ambiente/provider/purpose/version/expiration, integridade de envelope e escopo, expiração/reauditoria, imutabilidade de binding e auditoria sanitizada em SQLite/PostgreSQL. Nenhum código funcional foi alterado pela PR #157. Ledger: 26/59 concluídas; primeira pendente **NFV1-P06-T04 — Rotação e falha**. Esta revisão documental não inicia T04.

P6-T01-B02 segue BLOCKED_EXTERNAL: conta/projeto/região/billing/budget/identidade/IAM/bootstrap/canal e acesso cloud real ao Google Secret Manager não comprovados. Último staging read-only: API/Portal/PostgreSQL 1/1, Worker 0/1 e drift — **não reinspecionado** por este fechamento. `EXTERNAL_SECRET_BACKEND_CERTIFIED=NOT MET`; `PRODUCTION_APPROVED=NO`; `COMMERCIAL_LIVE=NO`. Sem deploy/SQL produtivo, segredos, credenciais, gastos, IAM, emissão fiscal ou Go-Live. Integração desta PR documental continua sujeita a CI/governança/merge específico.

---

# CURRENT superior — P06-T03 em execução — 2026-10-10

Main reconfirmada `4855613613eb8d265fe62289fff39fe5ab710c4c`;PR156 MERGED,zeroPRs abertas na entrada. FechamentoT02 certificado:CI742/run37989321439/tentativa3/job114121909282 SUCCESS41/41,1741Python/PostgreSQL,14frontend,28Playwright PASS/0FAIL/0SKIP;Governance163/run37989321416 SUCCESS. DockerHub429 resolvido sem alteração de workflow/teste/registry/credencial. Evidência superior registrada naPR156.

Dono autorizou executar P06-T03 (Pode executar). CURRENT:adapterGSM integrado,prova fiscal detalhada de escopo ainda T03. TARGET:certificação interna de tenant/unidade/ambiente/provider/purpose/version/expiration nos resolvers/vault/bindingadmin existentes,com SQLite/PostgreSQL e payloads sintéticos. Somente testes/documentação;nenhum código deprodução,migration,dependência ou workflow muda. T03 emexecução;25/59 concluídas;T04 não iniciada. Checkpoint `checkpoints/NFV1_P06_T03_SCOPE_CERTIFICATION_2026-10-10.md`;provaHEAD/PR/CI desta revisão será registrada naPR.

Staging somente leitura reconfirmado2026-10-10:mesmos deploymentsAPIc0f8fb2b/Portal35b7aafc/Worker3215f498/Postgresce9b66e7;running1/1,1/1,0/1,1/1. Worker Online não significa processo ativo;patchstaged histórico zerochanges. P6-T01-B02 identidade/IAM/conta/bootstrap/canal/provaGSMreal aberto. Não confundir com CI429resolvida. GateP6 não certificado;PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO. Semdeploy/SQLreal/secretreal/cloudI/O/gasto.

## Snapshot histórico — T02

# CURRENT superior — NFV1-P06-T02 integrado e certificado internamente — 2026-10-09

PR #155 MERGED; HEAD `5eb98614f4dfdc092871bb6e06c1efef7825e6ba`; main `8ad5a20e8ec954ef91f5e2c8f77a17ad09e8e62b`; árvore idêntica `5531ec7f0d7da61c59f92117b08f56807fae8715`. CI #739/run37973027312/job113964215052 (PR), #740/run37978308311/job113982097370 (main), Governance #160/run37973027313 e #161/run37978308448 SUCCESS. PR/main:41/41 etapas;1741 Python/PostgreSQL,14 frontend,28 Playwright PASS/zero FAIL/zero SKIP;um warning TestClient preexistente. Backup/restore PostgreSQL16 sintético, checksum e readiness PASS.

Dono autorizou merge #155 (“Autorizo”) às16:09 America/Sao_Paulo. T02 DONE_CERTIFIED interno condicionado à integração/gates deste fechamento documental.25/59 concluídas após fechamento;próxima NFV1-P06-T03 — Certificar escopo, não iniciada. AdapterGSM, bindings metadata-only e migration17 integrados;assinaturaWorker restrita ao escopo explícito.

Staging read-only inalterado:API/Portal/PostgreSQL1/1,Worker0/1,mesmos deployments históricos. B02 conta/projeto/região/billing/budget/identidade/IAM/canal não confirmado;WIF/bootstrapRailway/providerreal não certificados;gateP6/P5 não satisfeito. PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO;nenhum deploy/SQLreal/conta/gasto/credencialreal executado.

Checkpoint `checkpoints/NFV1_P06_T02_GSM_ADAPTER_2026-10-09.md`. Esta revisão contém somente fechamento T02, sem código/teste/workflow alterado. Prova final da própria PR documental será registrada na PR após seus gates.

## Snapshot histórico — T02 em execução

# CURRENT superior — NFV1-P06-T02 em execução — 2026-10-09

Main de entrada `a32891ca74616e4a435c9c11055e6b4f8ba3bb64`;PR154 MERGED;CI738/run37966054249 e Governance159/run37966054229 SUCCESS;41/41 etapas,1673 Python/PostgreSQL,14frontend,28Playwright,zeroFAIL/SKIP. FechamentoT01 certificado,24/59 concluídas. Dono autorizouT02 (“Executar”);políticaGSM já aprovada integralmente para implementação interna.

PublicaçãoP6-T02-B01 RESOLVIDA: dono autorizou explicitamente divulgar o código no repo público, abrir PR Draft e executar CI (“Autorizado”), em2026-10-09 às15:18 America/Sao_Paulo. PRnãoaberta/CIremota pendente. Resultado local1455PASS/0FAIL/286SKIP porpré-requisitosausentes,1warning;Ruff/Mypy201/planvalidator/secrets/diffPASS. Não certificaPostgreSQL/providerreal.

AdapterGSM interno implementado localmente, ainda não integrado:SDKoficial com identidade explícita e endpointfixo,timeout/retrycontrolado,CRC32C/envelope estrito,versão pinada;bindings duráveis metadata-only na mesmaUOW/SQLite/PostgreSQL,migration17 aditiva;projeçõesref:/sec_preservadas. Composição de assinaturaWorker explícita por escopo,sem bootstrapRailway inferido. PR/HEAD/CI desta entrega serão registrados na própriaPR. T02 não concluída;checkpoint `checkpoints/NFV1_P06_T02_GSM_ADAPTER_2026-10-09.md`.

Providercloud real não testado;semIAM/credencial/conta/custo/deploy. B02externo preservado. Staging históricoAPI/Portal/Postgres1/1,Worker0/1. FaseP6/P5/produção não certificadas. Campos históricos abaixo são superados por este registro e evidênciafinalPR154.

---

# FM NFCORE V1 — Commercial Launch CURRENT

**Canonical status date:** 2026-10-05  
**Canonical NFCore repository:** `faabio3131/kordena-fiscal-engine-v2`  
**Audited base NFCore main:** `9a42045c9690c32dcaf2cf11ead1a0b38843c779`  
**Canonical FM commercial-site repository:** `faabio3131/fm-tecnologia-web-platform`  
**Canonical Site main:** `26bfe05c2891bfc68f680587d0ae47ee36f105b1`

This file is the persistent CURRENT checkpoint for FM NFCORE V1 Commercial Launch. GitHub remains the first technical source of truth and must be revalidated on every resume.

## CURRENT superior — 2026-10-09 — seleção/política P06-T01 aprovada e PR153 integrada

O dono respondeu “Autorizo” em 2026-10-09 à escolha Google Secret Manager, à política proposta como conjunto (incluindo bootstrap restrito ao staging para implementação interna) e à integração da PR #153. P6-T01-B01 RESOLVIDO: POLICY_APPROVED_FOR_INTERNAL_IMPLEMENTATION.

- Main `0ad89d68ac7bb7975d8af1422ce07796eaf625ed`, árvore `b1e1ae3b692e2c325cdd9a2536ad84227ec5ee7e`, idêntica à PR153. CI PR #735/run37958319939 e Governance #156/run37958319968 SUCCESS;41/41 etapas,1673 Python/PostgreSQL,14 frontend,28 Playwright PASS/zero FAIL/zero SKIP.
- Main CI #736/run37961104490/job113923850663 e Governance #157/run37961104464 SUCCESS;41/41 etapas,1673 Python/PostgreSQL,14 frontend,28 Playwright PASS/zero FAIL/zero SKIP;um warning TestClient preexistente. Backup/restore canônico PostgreSQL16 sintético e readiness PASS. T01 selecionada/aprovada e certificada internamente; fechamento documental condicionado à integração/gates próprios.24/59 concluídas neste registro;próxima P06-T02.
- P6-T01-B02 continua gate de operação externa:conta/região/orçamento/IAM/credencial/canal. T02 não iniciada;provider real não certificado;P5 bloqueada.
- Staging read-only deployments inalterados:API/Portal/PostgreSQL1/1,Worker0/1. Nenhum deploy/secret real. PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO.
- Checkpoint `checkpoints/NFV1_P06_T01_SELECTION_2026-10-09.md`; seleção/política nos documentos existentes, sem plano concorrente.

---

## Snapshot histórico — estudo anterior à aprovação

## CURRENT superior — 2026-10-09 — P06-T01 estudo e política propostos

- Entrada main `b87b64567b91b775a6b6a26b06724c33faf82645`, PR #152 MERGED, CI #734/run37952628383 e Governance #155/run37952628603 SUCCESS. Este resultado supera as pendências históricas de CI/main e registro de ordem abaixo.
- “Pode executar” autoriza estudo T01/publicação revisável. Comparação oficial GSM/AWS/Azure/Vault e recomendação Google Secret Manager na proposta `NFV1_P06_T01_SECRET_PROVIDER_POLICY_PROPOSAL_2026-10-09.md`.
- P6-T01-B01: seleção/política sensível aguarda aceitação humana. P6-T01-B02: conta/região/orçamento/bootstrap/IAM/operação real não confirmados. WIF de workload Railway não presumida; proposta de chavebootstrap staging não autoriza uso real ou produção.
- Checkpoint `checkpoints/NFV1_P06_T01_SELECTION_2026-10-09.md`;T01 não concluída,23/59 concluídas;T02 não iniciada. Sem código/migration/workflow alterado.
- Staging read-only permanece API/Portal/PostgreSQL1/1,Worker0/1, sem deployment novo. P5 continua bloqueada. PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO.
- CI/HEAD desta entrega constam na PR; nenhuma integração/conta/custo/secret/deploy executada por esta proposta.

---

## Snapshot histórico — PR151 e ordem P6/P5

## CURRENT superior — 2026-10-09 — PR151 integrada, ordem P6 antes de P5 aprovada

- PR #151 MERGED; main `250afa737fa970411d13fe1f48735b6147f9e13d`, árvore igual ao HEAD8bfa783: `7ff6b29b182e499ca5d1710d84ad43e93c6a4fb8`.
- CI PR #730/run37947093378 e Governance #151/run37947093342 SUCCESS:41/41 etapas,1673 Python/PostgreSQL,14 frontend,28 Playwright,zero FAIL/SKIP;backup/restore canônico em PostgreSQL16 sintético PASS.
- Main CI #731/run37950345107 e Governance #152/run37950345322 em validação na criação deste registro;integração documental da ordem também requer gates próprios.
- “Autorizado” aprova merge151 e antecipação P6. Cronograma/ledger movem os quatro itens P6 antes dos cinco P5;59 IDs preservados,validador inalterado,23/59 concluídos.
- Próxima tarefa após integração/gates do registro: NFV1-P06-T01 — Selecionar provider. P6 ainda não implementada;seleção de conta/provider/IAM/gasto/credencial e operação real exigem decisão específica.
- P05-T01 segue bloqueada: backup/SQL/compatibilidade/bootstrap/driver. Decisão de ordem resolvida;T02 não iniciada.
- Staging read-only inalterado:API/Portal/PostgreSQL1/1,Worker0/1. Sem deploy/migration externa/secret real. PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO.
- Checkpoint `checkpoints/NFV1_P05_T01_PREDEPLOY_2026-10-09.md` atualizado;histórico preservado.

---

## Snapshot histórico — auditoria P5-T01 antes da aprovação

## CURRENT superior — 2026-10-09 — P05-T01 auditado e bloqueado

- PR #150 MERGED; entrada main `5b63449d9ef3bbe7fdf7023e1d9bdfd96235f00c`, CI #728/run37942395431 e Governance #149/run37942395342 SUCCESS;41/41 etapas,1666 Python/PostgreSQL,14 frontend,28 Playwright PASS/zero FAIL/zero SKIP.
- P4 interno certificado;23/59 concluídas;T01 autorizado por “Executar”, iniciado, não concluído;T02 não iniciado.
- Auditoria read-only: API/Portal/PostgreSQL1/1,Worker0/1;SHA API/Portal f9b5b2c...,Worker1c34ba...;API live/ready e Portal HTTP200;rollback apenas candidatos.
- Backup concluído/recibo, SQL/migrations atuais e compatibilidade não confirmados; driver aceita backup solicitado e deployment SUCCESS sem saúde/SHA exato. Bloqueios antes de deploy.
- Correções mínimas de restore/SHA/baseline e provas na CI propostas nesta PR; integração ainda pendente.
- Ciclo P5/P6: Worker contínuo real precisa boundary de assinatura concreta;P6 depende de P5. Proposta de antecipar P6 está no checkpoint, ainda não aprovada nem aplicada.
- Checkpoint `checkpoints/NFV1_P05_T01_PREDEPLOY_2026-10-09.md`;retomar por decisão de dependência e canal operacional governado, sem solicitar segredo no chat.
- Nenhum deploy/migration externa/mutação Railway. PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO.

---

## Snapshot histórico — fechamento P4

## CURRENT superior — 2026-10-09 — P04-T04 integrado e certificado internamente

PR #149 MERGED; HEAD `732265ed0e7bab21b48e735ea296a2e8a3af7576`; main `d9f4d1d8c7fd60f927b2f3d3ba8f421a72c9bf82`; árvore PR/main idêntica `d7cbdf8baf65013c4f8542ac390c9c581b01ef7b`. CI #725/run37935705861 (PR) e #726/run37938638870 (main), Governance #146/run37935705764 e #147/run37938638865 SUCCESS. PR/main:41/41 etapas;1666 Python/PostgreSQL,14 frontend,28 Playwright PASS,zero FAIL/zero SKIP;29 novos casos incluídos;um warning TestClient preexistente.

- processo contínuo PID1/non-root, SIGTERM/SIGINT, health/runtime contract, drain/restart certificados internamente;
- gate P4 CONTINUOUS_WORKER_CERTIFIED_INTERNAL e23/59 concluídas condicionados à integração/gates deste fechamento documental;
- próxima NFV1-P05-T01 — Pré-deploy, não iniciada até esse fechamento;
- checkpoint `checkpoints/NFV1_P04_T04_WORKER_CONTAINER_2026-10-09.md`;
- fixture sintética somente CI não entra na imagem; CMD sem assinatura/resolver permanece fail-closed;
- assinatura/backend de secrets P6 e staging/operação/monitoramento P5/P9/P11 permanecem pendentes;
- staging read-only API/Portal/PostgreSQL1/1,Worker0/1;deployments históricos e patch staged vazio inalterados;
- sem deploy/operação real. PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO.

---

## Snapshot histórico — início T04

## CURRENT superior — 2026-10-09 — P04-T04 em execução

- entrada main `f1b8503cb8dd09325457907469ec5f049d9d5579`, PR #148 MERGED;
- CI #724/run37932404603 e Governance #145/run37932404514 SUCCESS; T03 encerrada,22/59 concluídas;
- T04 ativa: processo contínuo, SIGTERM/SIGINT, PID1/non-root e health/runtime contract;
- checkpoint `checkpoints/NFV1_P04_T04_WORKER_CONTAINER_2026-10-09.md`;
- certificação depende de CI/merge/main; P5 não iniciada;
- runtime real sem handlers permanece fail-closed; fixture CI não entra na imagem;
- staging read-only API/Portal/PostgreSQL1/1,Worker0/1;drift conhecido;
- sem deploy/operação real. PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO.

---

## Snapshot histórico — T03 encerrada

## CURRENT superior — 2026-10-09 — P04-T03 integrado e certificado internamente

PR #147 MERGED; HEAD `86d144e02c29a7a7881dd1a1afeaaa57b36e08ed`; main `f844aae44bbcc2a240071b269293a1c59f867c36`; árvore PR/main idêntica `561003d239901a6fbae83daa9587c627f89b493e`. CI #721/run37916736004 (PR) e #722/run37918229115 (main), Governance #142/run37916736047 e #143/run37918229137 SUCCESS. PR/main:41/41 etapas;1637 Python/PostgreSQL,14 frontend,28 Playwright PASS,zero FAIL/zero SKIP;32 novos casos incluídos; um warning TestClient preexistente.

- merge #147 autorizado pelo dono; observabilidade ligada ao loop/outbox/UOW canônicos;
- backlog/estados, resultados/falhas/retry/dead-letter e heartbeat/readiness certificados internamente;
- 22/59 tarefas concluídas; P4 ainda em execução;
- fechamento documental aguarda CI/merge/main próprios; próxima NFV1-P04-T04 não iniciada;
- checkpoint `checkpoints/NFV1_P04_T03_WORKER_OBSERVABILITY_2026-10-09.md`;
- contadores process-local, gauges duráveis; freshness/validity explícitas; coleta sem query DB;
- métricas globais internas, sem endpoint/exporter novo ou promoção de integração externa;
- SIGTERM/container contínuo T04, assinatura real P6 e operação/monitoramento P5/P9/P11 pendentes;
- staging read-only pós-merge API/Portal/PostgreSQL1/1, Worker0/1; deployments históricos inalterados;
- nenhum deploy/operação real autorizado. PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO.

---

## Snapshot histórico — início T03

## CURRENT superior — 2026-10-09 — P04-T03 em execução

- entrada main `ee0c14cf0979561bc20f655fd71819552f67bbdf`, PR #146 MERGED;
- CI #720/run37886789334 e Governance #141/run37886789343 SUCCESS; T02 encerrada,21/59 concluídas;
- T03 ativa: backlog durável, resultados/falhas/retry/dead-letter, heartbeat/readiness e isolamento da telemetria;
- checkpoint `checkpoints/NFV1_P04_T03_WORKER_OBSERVABILITY_2026-10-09.md`;
- certificação T03 depende de CI/merge/main; T04/P9 não iniciadas;
- métricas internas, sem exporter/rota nova; poll readiness não promove integração externa;
- staging read-only API/Portal/PostgreSQL1/1, Worker0/1, drift conhecido;
- sem deploy/operação real. PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO.

---

## Snapshot histórico — T02 encerrada

## CURRENT superior — 2026-10-09 — P04-T02 integrado e certificado internamente

PR #145 MERGED; HEAD `49201706c1b6ad80d128aaa788827b64ab1d63e7`; main `4e5657cfda9cd89d03fec1d3e2b1471f79b36b2b`; árvore PR/main idêntica `41f72f38660ac1c1d6611c7c99251d265deff0d3`. CI #717/run37883903575 (PR) e #718/run37885060792 (main), Governance #138/run37883903581 e #139/run37885060691 SUCCESS. PR/main:41/41 etapas;1605 Python/PostgreSQL,14 frontend,28 Playwright PASS,zero FAIL/zero SKIP;18 novos casos incluídos; um warning TestClient existente.

- merge #145 autorizado pelo dono; estado/attempt comparados atomicamente na mesma outbox;
- poll/dispatch/retry/backoff/dead-letter/shutdown/restart/replay/inbox certificados internamente;
- 21/59 tarefas concluídas; P4 ainda em execução;
- fechamento documental aguarda CI/merge/main próprios; próxima NFV1-P04-T03 não iniciada;
- checkpoint `checkpoints/NFV1_P04_T02_WORKER_RECOVERY_2026-10-09.md`;
- transporte at-least-once; deduplicação de efeito externo não presumida;
- assinatura real P6, observabilidade T03, container contínuo T04 e staging P5/P9/P11 pendentes;
- staging read-only pós-merge: API/Portal/PostgreSQL1/1, Worker0/1; deployments históricos inalterados;
- nenhum deploy/operação real autorizado. PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO.

---

## Snapshot histórico — início T02

## CURRENT superior — 2026-10-09 — P04-T02 em execução

- entrada main `8385be0ee80e434a922e9ad10b11a4f15c2188db`, PR #144 MERGED;
- CI #716/run37882569950 e Governance #137/run37882569961 SUCCESS; T01 encerrada,20/59 concluídas;
- T02 ativa: outbox/inbox/background, recovery e disputa de escrita status/attempt;
- checkpoint `checkpoints/NFV1_P04_T02_WORKER_RECOVERY_2026-10-09.md`;
- certificação T02 pendente de CI/merge/main; T03/T04 não iniciadas;
- entrega at-least-once; efeito único externo exige idempotência/inbox do destinatário;
- staging read-only API/Portal/PostgreSQL1/1, Worker0/1, drift conhecido;
- sem deploy/segredo/operação real. PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO.

---

## Snapshot histórico — T01 encerrada

## CURRENT superior — 2026-10-09 — P04-T01 integrado e certificado internamente

PR #143 MERGED; HEAD `1d0dcc17b7d18016d5060ff2e3fd0c88aedd81b0`; main `d1007064c6997a0c303ae09e606e565e04ab1677`; árvore PR/main idêntica `dd82679dff6c59ee40dc14a96d6503ebc12122b2`. CI #713/run37879189354 (PR) e #714/run37880543365 (main), Governance #134/run37879189376 e #135/run37880543403 SUCCESS. PR/main:41/41 etapas,1587 Python/PostgreSQL,14 frontend,28 Playwright PASS,zero FAIL/zero SKIP;16 novos casos incluídos; warning TestClient existente.

- merge #143 autorizado pelo dono; registry canônico reutiliza handler/outbox/UOW/egress existentes;
- 20/59 tarefas concluídas internamente; P4 ainda em execução;
- fechamento documental aguarda CI/merge/main próprios; próxima NFV1-P04-T02 não iniciada;
- checkpoint `checkpoints/NFV1_P04_T01_HANDLER_REGISTRY_2026-10-09.md`;
- ausência de assinatura/configuração continua fail-closed; secret backend real P6 não certificado;
- staging read-only após merge: API/Portal/PostgreSQL1/1, Worker0/1, deployments históricos inalterados;
- runtime contínuo/recuperação/observabilidade/container e drift staging permanecem T02/T03/T04/P5/P9/P11;
- nenhum deploy/operação real autorizado. PRODUCTION_APPROVED=NO; COMMERCIAL_LIVE=NO.

---

## Snapshot histórico — início P04-T01

## CURRENT superior — 2026-10-09 — P04-T01 em execução

- main de entrada `4c3838f0c35e728f36f9c15ac1c3f62c42cd35d2`;
- PR #142 MERGED; CI #711/Governance #132 SUCCESS; P3 interna certificada;
- tarefa ativa NFV1-P04-T01, registry explícito do handler SignedWebhookOutboxHandler;
- entrypoint usa composição canônica com dependências de assinatura injetadas;
  mesma outbox/egress/UOW, sem provider/handler comercial inventado;
- ausência de dependência continua fail-closed; resolver de segredo real P6 não certificado;
- checkpoint `checkpoints/NFV1_P04_T01_HANDLER_REGISTRY_2026-10-09.md`;
- T01 IN_PROGRESS, CI/merge/main pendentes; T02/T03/T04 não iniciadas;
- staging read-only: API/Portal/PostgreSQL1/1, Worker0/1, drift conhecido;
- nenhum deploy/operação real autorizado. PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO.

---

## Snapshot histórico — P3 fechado

## CURRENT superior — 2026-10-08 — Lifecycle comercial integrado e certificado

- PR #141 MERGED por autorização específica do dono (“Aprovado”);
- HEAD `32755fd1e3b7563561017c82cdb2f1871ccb7bca`;
- main implementação `b8b25fda37a6682bc57eb2349f132770e46b0362`;
- árvore PR/main idêntica `9f6eeed928faa5ab020570ce16491eecc0fc0d35`;
- CI #708/run37872723397 (PR) e #709/run37875267814 (main) SUCCESS;
- Governance #129/run37872723403 e #130/run37875267800 SUCCESS;
- PR/main:41/41 etapas;1571 Python/PostgreSQL,14 frontend,28 Playwright PASS;
  zero FAIL, zero SKIP;35 casos novos; warning TestClient existente;
- lifecycle de nove eventos, período/uso canônicos, invoice deduplicada,
  termos originais, validade/carência, terminalidade/identidade/histórico,
  replay/restart/concorrência e upgrade aditivo16 certificados internamente;
- T05/P3 internos certificados condicionados à integração/gates deste fechamento;
- próxima tarefa NFV1-P04-T01 — Handler registry canônico, não iniciada;
- checkpoint `checkpoints/NFV1_P03_T05_IMPLEMENTATION_2026-10-08.md`;
- staging reconfirmado somente leitura: API/Portal/PostgreSQL1/1, Worker0/1;
  deployments históricos inalterados, VERSION_DRIFT_PRESENT;
- Secret Manager, emissor Command, checkout/delivery reais P6/P8 não certificados;
  worker contínuo P4, staging P5/P9/P11 e homologação/produção seguem pendentes;
- fechamento documental requer merge específico; nenhum deploy autorizado.

PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO.

---

## Snapshot histórico — Command

## CURRENT superior — 2026-10-08 — Command integrado e pós-merge certificado

- PR #137 MERGED por autorização explícita;HEAD `1404cdc5f12525e15c5e887c0b8a4579e3e75793`;
- main implementação `bfb31e5f8d6924f4fff8f92c37c8e420b04c871f`, árvore PR/main idêntica `c683b03891a5d0421260e18d85234f0d33d2c711`;
- CI #692/run37850360972 (PR) e #693/run37857702520 (main) SUCCESS;
- Governance #113/run37850360981 e #114/run37857702555 SUCCESS;
- PR/main:1504 Python/PostgreSQL,14 frontend,28 Playwright PASS;zero FAIL/zero SKIP;41/41 etapas main PASS;
- receiver Command configurável por produto/ambiente/key/reference/version; HMAC existente e contrato estrito;
- migração aditiva15, inbox e correlações duráveis; replay/restart/concurrency/rollback/recovery internos provados;
- aquisição/fulfillment/claim/provisioning/activation canônicos reutilizados; pagamento não concede OWNER/platform_admin/autoridade fiscal;
- T03 DONE_CERTIFIED interno condicionado à integração/gates deste registro documental;
- checkpoint existente atualizado: `checkpoints/NFV1_P03_T03_IMPLEMENTATION_2026-10-08.md`;
- próxima tarefa NFV1-P03-T04 — Purchase readiness, ainda não iniciada; P3 incompleta até T04/T05;
- worker contínuo P4; secret backend/transportes reais e homologação comercial externa seguem fases próprias;
- staging não reconfirmado; último checkpoint indica drift; nenhum deploy realizado.

PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO.

---

## Snapshot histórico — Trial

## CURRENT superior — 2026-10-08 — Trial integrado e pós-merge certificado

- PR #135 MERGED por autorização explícita; HEAD `5ef259e380a1814c82f5067e1d3962f30922472b`;
- main implementação `129e4f69eb7917ccd8b282a86b711542223d4390`, árvore idêntica `076a16ebc721db00a980b1b5e55bbf56c8f191ff`;
- CI #685/#686 e Governance #106/#107 SUCCESS; main41/41 etapas PASS;
- PR/main:1453 Python/PostgreSQL,14 frontend,28 Playwright PASS;zero FAIL/zero SKIP;
- Trial preserva OWNER/subscription/activation canônicos e reserva durável;
- concorrência entre réplicas, duplicatas, reinício e recuperação certificados internamente;
- T02 DONE_CERTIFIED interno condicionado à integração/gates deste registro documental;
- checkpoint `checkpoints/NFV1_P03_T02_CLOSEOUT_2026-10-08.md`;
- próxima tarefa NFV1-P03-T03; P3 permanece incompleta até T03..T05;
- diretriz de configuração externa aprovada persistida no cronograma;
- provider/secret/delivery operacionais não certificados; último checkpoint de staging indica drift;
- staging não foi reconfirmado nesta integração; nenhum deploy executado.

PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO.

---

## Snapshot histórico — aquisição first-party

## CURRENT superior — 2026-10-08 — NFV1-P03-T01 closeout interno

- PR #133 MERGED por autorização explícita; HEAD `0a1397328db3aa315433389c0aad858a2d097caa`;
- main implementação `e13dd86c1782f759f66d9369493735467496b8f7`, árvore PR/main idêntica;
- CI #681/#682 e Governance #102/#103 SUCCESS nos SHAs exatos;
- PR/main:1429 Python/PostgreSQL,14 frontend,28 Playwright PASS;zero FAIL/zero SKIP;
- aquisição autenticada composta no runtime com serviços/persistência canônicos;
- oferta bloqueada sem security/starter/serviço de aquisição compatível;
- persistência/replay após reinício,assinatura/rate limit/dependências/expiração/
  perdas de resposta/falha de escrita e ausência de provisioning provados internamente;
- T01 DONE_CERTIFIED interno condicionado à integração/gates deste closeout;
- checkpoint `checkpoints/NFV1_P03_T01_CLOSEOUT_2026-10-08.md`;
- próxima Task NFV1-P03-T02 — Trial,ainda não iniciada; gate de fase P3 ainda não concluído;
- checkout/chave/delivery sintéticos; provider/secret/delivery operacionais não certificados;
- staging em drift,deployments históricos inalterados; nenhum patch pendente na consulta atual.

PRODUCTION_APPROVED=NO;COMMERCIAL_LIVE=NO. Nenhum deploy/cobrança real realizado.

---

## Snapshot histórico — T07/P2 closeout interno

## CURRENT superior — 2026-10-08 — T07/P2 closeout interno

- PR #131 MERGED por autorização explícita; HEAD `7518662a188aba98c3d1b615ccb5ba3408286e41`;
- main implementação `3d7b4698629c312cdb5ee6b04791bf57d05e2179`, árvore PR/main idêntica;
- CI #676/#677 e Governance #97/#98 SUCCESS nos HEADs exatos;
- PR/main:1413 Python/PostgreSQL,14 frontend,28 Playwright PASS;zero FAIL/zero SKIP;
- política T07-B01 aprovada e implementada nos receipts canônicos,24h/mesma conta/
  epoch/scope/permissão,claim atômico,key original backend,sem browser storage;
- reload/perda de resposta/concorrência provados internamente; unknown outcome
  exige evidência/reconciliação,sem redispatch automático;
- seis capturas PR e seis main320/390/1280px baixadas,digests conferidos e inspecionadas;
- T07 = DONE_CERTIFIED e PORTAL_COMMERCIAL_PARITY_CERTIFIED interno condicionados
  ao merge/gates PR/main deste closeout documental;
- checkpoint `checkpoints/NFV1_P02_T07_CLOSEOUT_2026-10-08.md` supersede candidatas;
- P0/P1/P2 internos certificados após closeout; próxima Task NFV1-P03-T01,
  P3 não iniciada. Staging em drift,sem deploy/secret/provider/homologação real.

PRODUCTION_APPROVED=NO; COMMERCIAL_LIVE=NO. Nenhuma promoção operacional externa.

---

## Snapshot histórico da reconstrução candidata

## CURRENT superior — 2026-10-08 — recuperação T07 candidata em validação

Main de entrada `82e05f7af6ffca031f457ff93f43ae875ad05122`; PR #131 Draft,
branch `feat/nfv1-p02-t07-fiscal-recovery`. Política integral, implementação/testes
 e publicação autorizados pelo dono. Commits locais anteriores indisponíveis:
não reutilizar resultados anteriores como prova da reconstrução. Reutilizar
receipts canônicos; sem browser storage. Runtime local faa6970:1255 PASS/158 SKIP/zero FAIL, frontend14 PASS; PostgreSQL/Playwright/CI final pendentes. T07 em execução, P2 NOT MET, P3 não iniciada.
Checkpoint: `checkpoints/NFV1_P02_T07_FISCAL_RECOVERY_IMPLEMENTATION_2026-10-08.md`.
Gates da candidata/CI/visual/integração pendentes. Merge/deploy não autorizados.

---

## Snapshot histórico da parcela integrada

## CURRENT superior — 2026-10-08 — NFV1-P02-T07 parcela integrada / T07-B01

- PR #129 MERGED; HEAD `95c8e4b85bf61cf1d761d3a0785e1e6da79c9340`;
- main da parcela `3181dcdf614d8b22d8fab9e2238050d0c2207772`, árvore idêntica;
- CI PR #665 (37733283484)/Governance #86 (37733283404) SUCCESS;
- CI main #666 (37733952353)/Governance #87 (37733952332) SUCCESS;
- 1371 Python/PostgreSQL, 14 frontend e 26 Playwright PASS/zero SKIP em PR/main;
- support sanitizado/filtros reais, detalhes mobile/teclado, labels, bloqueios,
  read retry/submit lock e preservação da key após consulta integrados;
- screenshots 320/390/1280px baixadas, digest conferido e inspeção visual concluída;
- T07 continua `[ ] bloqueado interno`: T07-B01 exige aprovação da política DRAFT
  server-side de recuperação após reload/crash; browser storage permanece proibido;
- checkpoint: `checkpoints/NFV1_P02_T07_PARTIAL_CLOSEOUT_POLICY_GATE_2026-10-08.md`;
- closeout documental exige seus próprios gates PR/main verdes; não certifica T07;
- primeira incompleta T07; P2 NOT MET; P3 não iniciada; staging READ-ONLY em drift.

PRODUCTION_APPROVED=NO; COMMERCIAL_LIVE=NO. Nenhuma operação externa realizada.

---

## Snapshot histórico — 2026-10-08 — NFV1-P02-T07 candidata / T07-B01

- main de entrada `fdf9855c7b8048870ff89d91d4d03797d2f11c49`, zero PRs abertas;
- T06 DONE_CERTIFIED, #127/#128 MERGED; CI main #662 e Governance #83 SUCCESS;
- 1359 Python/PostgreSQL, 14 frontend e 21 Playwright PASS/zero SKIP no HEAD de entrada;
- primeira incompleta T07; parcela independente candidata de UX/mobile/acessibilidade/
  suporte sanitizado e estados de bloqueio; gates/PR/main desta parcela pendentes;
- T07-B01 exige política de recuperação de intento após reload/crash; proposta DRAFT
  `NFV1_P02_T07_FISCAL_INTENT_RECOVERY_POLICY_PROPOSAL_2026-10-08.md`;
- storage no navegador permanece proibido; política nova não implementada;
- checkpoint: `checkpoints/NFV1_P02_T07_UX_AND_POLICY_GATE_2026-10-08.md`;
- T07 não certificada; P2 NOT MET; P3 não iniciada. Staging READ-ONLY em drift.

PRODUCTION_APPROVED=NO; COMMERCIAL_LIVE=NO. Sem ações externas.

---

## Snapshot histórico — 2026-10-08 — NFV1-P02-T06 CLOSEOUT

- PR #127 MERGED; HEAD `c92bcf5fe56df09ffa3f5bfd7101c9d6f7489abb`;
- implementação main `e03201bc01bc1f6acbeca6c161d02ea157512d43`;
- CI #659/#660 e Plan Governance #80/#81 SUCCESS nos HEADs exatos;
- 1359 Python/PostgreSQL, 14 frontend e 21 Playwright PASS, zero SKIP em PR/main;
- jornada própria de Inutilização no mesmo Portal/router/path, contrato canônico e
  acompanhamento sanitizado de outbox por tenant/unit/host/environment;
- RBAC, sessão, CSRF, Idempotency-Key e retry existentes preservados; sem migrations;
- estado da fila/2xx não confirma inutilização fiscal; handler sintético somente nos testes;
- closeout: `checkpoints/NFV1_P02_T06_CLOSEOUT_2026-10-08.md`;
- T06 = DONE_CERTIFIED após este closeout integrar main e seus próprios gates verdes;
- próxima Task **NFV1-P02-T07 — Premium UX**, ainda não iniciada;
- P2 continua em execução; PORTAL_COMMERCIAL_PARITY_CERTIFIED = NOT MET.

Staging somente READ-ONLY, drift STG-B01..B08 preservado. Sem deploy, segredo real,
fiscal oficial, homologação ou produção. PRODUCTION_APPROVED=NO; COMMERCIAL_LIVE=NO.

---

## Snapshot histórico — 2026-10-08 — NFV1-P02-T06 EM EXECUÇÃO

- entrada revalidada: main `6506e3c50dec9e1f948311a13301c6524e26d1b0`, zero PRs abertas;
- CI main #658 e Plan Governance #79 SUCCESS; predecessor P02-T05 DONE_CERTIFIED;
- branch `feat/nfv1-p02-t06-inutilization`; próxima tarefa incompleta T06;
- candidata: jornada Inutilização no Portal existente, formulário sem JSON, validação
  por InutilizationRequest, outbox sanitizada por tenant/unit/host/env e filtro antes de paginação;
- permissões e autoridades existentes preservadas; nenhuma operação externa ativada;
- testes sintéticos e gates/PR/main/closeout pendentes; T06 não certificada, T07 não iniciada;
- staging READ-ONLY permanece drift: API/Portal deployments anteriores 1/1, Worker 0/1;
- checkpoint: `checkpoints/NFV1_P02_T06_INUTILIZATION_2026-10-08.md`.

P2 gate NOT MET; sem deploy/secret/certificado real/produção/operação fiscal oficial.
PRODUCTION_APPROVED=NO; COMMERCIAL_LIVE=NO. Snapshots abaixo são históricos.

---

## CURRENT superior — 2026-10-07 — NFV1-P02-T05 CLOSEOUT

- PR #125 MERGED; HEAD `d0a81ca9cf641295498b3ef92db256d4b3f417c0`;
- merge/main da implementação `7332943467dd876c6c72c163d73a9c3454e05828`;
- CI PR #655 e CI main #656 SUCCESS;
- Plan Governance PR #76 e main #77 SUCCESS;
- Billing/Planos/Uso agora são projeções read-only de autoridades comerciais canônicas;
- OWNER/ADMIN/AUDITOR/BILLING usam `billing.read`; OPERATOR falha fechado;
- tenant deriva exclusivamente da sessão;
- provider/gateway externo permanece adapter e referências externas não são projetadas;
- ausência de subscription/pricing retorna vazio, sem fabricar estado;
- nenhum preço/plano/promoção/provider real foi inferido ou hardcoded;
- closeout: `checkpoints/NFV1_P02_T05_CLOSEOUT_2026-10-07.md`;
- T05 = DONE_CERTIFIED após este closeout integrar main e seus próprios gates completos verdes;
- próxima Task: **NFV1-P02-T06 — Inutilização**;
- P0/P1 certificados; P2 continua em execução; gate PORTAL_COMMERCIAL_PARITY_CERTIFIED = NOT MET.

Sem deploy, staging write, billing externo, checkout real, segredo/credencial real,
produção fiscal, DNS ou Go-Live. PRODUCTION_APPROVED=NO; COMMERCIAL_LIVE=NO.

---

## CURRENT superior — 2026-10-07 — NFV1-P02-T05 EM EXECUÇÃO

- entrada revalidada: main `acc8510f3df11fb284386f951e427dffdeeef242`, zero PRs abertas;
- FM NFCORE V1 CI #654 e NFCore Plan Governance #75 SUCCESS no exact main;
- predecessor P02-T04 DONE_CERTIFIED; P02-T05 é o primeiro item incompleto do ledger;
- branch `feat/nfv1-p02-t05-billing-plans-usage`;
- T05 expõe somente leitura de Billing/Planos/Uso a partir de subscription durável e pricing publicado;
- OWNER/ADMIN/AUDITOR/BILLING usam `billing.read`; OPERATOR permanece negado;
- tenant é derivado da sessão; ausência de estado canônico retorna vazio;
- provider/gateway externo permanece adapter e suas referências externas não são projetadas;
- nenhum preço/plano/promoção/provider real foi criado ou decidido;
- checkpoint: `checkpoints/NFV1_P02_T05_BILLING_PLANS_USAGE_2026-10-07.md`;
- gates locais focados e Mypy verdes; PostgreSQL real será autoridade na CI;
- T05 permanece IN_PROGRESS; T06 não iniciada; gate P2 NOT MET.

Sem deploy, staging write, billing externo, checkout, segredo/credencial real,
operação fiscal/financeira externa, produção, DNS ou Go-Live.
PRODUCTION_APPROVED=NO; COMMERCIAL_LIVE=NO.

---

## CURRENT superior — 2026-10-07 — NFV1-P02-T04 CLOSEOUT

- PR #123 MERGED; HEAD `14e27b269344b9bec549d13dd96434e8a41ad8aa`;
- merge/main da implementação `459f7d1d4fd54997345d9458e1b365d49a50e31d`;
- CI PR #651 SUCCESS; Plan Governance PR #72 e main #73 SUCCESS;
- política T04 explicitamente aprovada pelo dono em 2026-10-07 e reconciliada contra o merge concorrente;
- OWNER administra OWNER/ADMIN/OPERATOR/AUDITOR/BILLING no próprio tenant;
- ADMIN administra somente OPERATOR/AUDITOR/BILLING; demais papéis falham fechado;
- tenant/unit são server-side; platform_admin permanece separado e não concedível;
- updates incrementam session_epoch, revogam sessões/resets e protegem o último OWNER ativo;
- criação não recebe senha arbitrária nem retorna senha/token; usa recovery canônico;
- users durável + createUser/updateUser + audit sanitizado + UI integrada;
- navegação filtrada por permissão backend e audit restrito por unit_ids;
- CI main #652 da implementação ficou presa em infraestrutura no Install Chromium e não é prova final;
- closeout: `checkpoints/NFV1_P02_T04_CLOSEOUT_2026-10-07.md`;
- T04 = DONE_CERTIFIED somente após este closeout integrar main e seus próprios gates completos verdes;
- próxima Task: **NFV1-P02-T05 — Billing/Planos/Uso**; não iniciada neste closeout;
- P0/P1 certificados; P2 continua em execução; gate PORTAL_COMMERCIAL_PARITY_CERTIFIED = NOT MET.

Sem deploy, staging write, migration externa, segredo/credencial real, e-mail real,
operação fiscal/financeira, homologação, produção, DNS ou Go-Live.
PRODUCTION_APPROVED=NO; COMMERCIAL_LIVE=NO.

---


## CURRENT superior — 2026-10-07 — NFV1-P02-T04 EM EXECUÇÃO

- entrada revalidada: main `d8d958a33a7a2364e005cb5742baecae9ed1e341`, zero PRs abertas;
- FM NFCORE V1 CI #650 e NFCore Plan Governance #71 SUCCESS no exact main;
- predecessor P02-T03 DONE_CERTIFIED; P02-T04 é o primeiro item incompleto do ledger;
- branch `feat/nfv1-p02-t04-users-rbac` criada exatamente do main certificado;
- implementação candidata reutiliza HumanAccount/PortalRole/PortalPermission e `user.manage`;
- política T04 aprovada pelo dono em 2026-10-07: OWNER administra todos os papéis do tenant; ADMIN administra somente OPERATOR/AUDITOR/BILLING; OPERATOR/AUDITOR/BILLING não administram usuários;
- tenant deriva da sessão, unit scope não pode ampliar, cross-tenant falha sem disclosure;
- `platform_admin` não é papel novo e não pode ser concedido/mutado pela administração do tenant;
- criação não retorna senha/token; ativação continua pelo fluxo canônico de recuperação;
- update é versionado, replay-safe, revoga sessões/resets e registra audit atômico no PostgreSQL;
- backend agora filtra `available_surfaces` pela permissão real antes da navegação;
- checkpoint: `checkpoints/NFV1_P02_T04_USERS_RBAC_2026-10-07.md`;
- gates locais dirigidos e frontend verdes; suíte integral/CI/PR/main ainda pendentes;
- T04 permanece IN_PROGRESS, T05 não iniciada, gate P2 NOT MET.

Sem deploy, staging write, migration externa, segredo/credencial real, e-mail real,
operação fiscal/financeira, homologação, produção ou Go-Live. PRODUCTION_APPROVED=NO;
COMMERCIAL_LIVE=NO.

---

## CURRENT superior — 2026-10-06 — NFV1-P02-T03 CLOSEOUT

- PR #121 MERGED; HEAD certificado `2e7333f02d3673196d18c25702b1ab39fbfb5eb8`;
- main certificado da entrega `1e9c102ab250b822c89cfbb5c3d185ba3c62d9ea`;
- CI PR #647 / main #648 SUCCESS; Plan Governance PR #68 / main #69 SUCCESS;
- 1277 Python/PostgreSQL PASS/zero SKIP, 12 frontend e 18 Playwright PASS nas duas CIs;
- T03 DONE_CERTIFIED após este closeout integrar main e seus gates verdes;
- cinco formulários/comandos compostos com autoridades existentes, schema aditivo 14;
- política integral aprovada pelo dono: pedido separado de aprovação canônica de plataforma,
  scope/versão/expiry, auditoria durável, fail-closed no delivery/retry e DNS/IP/SNI/TLS;
- outbox fornece telemetria sanitizada; cadastro/aprovação não comprovam tráfego real;
- closeout: `checkpoints/NFV1_P02_T03_CLOSEOUT_2026-10-06.md`;
- staging READ-ONLY pós-merge inalterado: API/Portal f9b5b2c 1/1, Worker 1c34ba0 0/1;
- próxima Task: **NFV1-P02-T04 — Usuários e RBAC**, somente após closeout/main verdes;
- T04 não iniciada nesta entrega. P0/P1 certificados; P2 em execução; gate NOT MET.

Sem deploy/migration externa/destino/tráfego/secret/certificado real/custo/operação
fiscal/financeira/homologação/piloto/cutover/Go-No-Go. PRODUCTION_APPROVED=NO;
COMMERCIAL_LIVE=NO. Registros abaixo são históricos; prevalecem GitHub e este closeout.

---

## CURRENT superior — 2026-10-06 — P02-T03 política aprovada / implementação interna

- main revalidado: `e203adc111d5e503c68a88bf6104df905b8fe18f`; PR #120 MERGED;
- FM NFCORE V1 CI #643 / Plan Governance #64 SUCCESS no exact HEAD;
- zero PRs abertas na revalidação; predecessor P02-T02 DONE_CERTIFIED;
- dono: `POLICY_APPROVED_FOR_INTERNAL_IMPLEMENTATION`, proposta T03 aprovada como conjunto;
- T03-B01 RESOLVIDO como decisão; implementação/PR/main/closeout ainda PENDENTES;
- branch: `feat/nfv1-p02-t03-approved-config`; cinco formulários e comandos governados;
- schema aditivo 14: versões/recibos de comando e metadados de aprovação na tabela de destinos;
- auditoria/valor/versão/recibo na mesma UoW; handler/outbox/Worker existentes;
- policy por delivery/retry + DNS por tentativa + transport HTTPS com IP validado e SNI/TLS;
- nenhum destino/secret/tráfego externo, deploy, migration externa ou custo executado;
- staging READ-ONLY: API/Portal f9b5b2c 1/1, Worker 1c34ba0 0/1, drift permanece;
- T03 não DONE_CERTIFIED; T04 não iniciada; P2 gate NOT MET;
- checkpoint candidato: `checkpoints/NFV1_P02_T03_APPROVED_IMPLEMENTATION_2026-10-06.md`.

Registros abaixo são históricos. Aprovação de política não certifica código, entrega,
homologação, produção ou prontidão comercial. PRODUCTION_APPROVED=NO; COMMERCIAL_LIVE=NO.

---

## CURRENT superior — 2026-10-06 — P02-T03 consulta integrada / T03-B01

- main certificado da parcela de consulta: `db2a8fb71097eb4e1f6e5919e1eb544c8a3167ac`;
- PR #119 MERGED; HEAD certificado `c908848dff0d2ff7f45e33dfa5b2ff51943f54f9`;
- CI PR #640/main #641 SUCCESS; Plan Governance #61/#62 SUCCESS;
- 1173 Python/PostgreSQL PASS/zero SKIP, 11 Playwright PASS; todos os gates completos;
- P02-T01/T02 DONE_CERTIFIED; P02-T03 **[ ] BLOQUEADO EXTERNO**, não certificada;
- cinco consultas de configuração conectadas no mesmo Portal; 16 surfaces genéricas
  duráveis, cinco restantes atribuídas a T04/T05/T07;
- nenhuma escrita nova; formulários/mutações/configuração integral permanecem T03;
- T03-B01 HUMAN_SECURITY_DECISION_REQUIRED: dono aprovar/ajustar política DRAFT
  `NFV1_P02_T03_WEBHOOK_SECURITY_POLICY_PROPOSAL_2026-10-06.md`;
- AGENTS.md e padrão mestre §6 exigem decisão antes de mudança sensível de segurança;
- checkpoint da parcela: `checkpoints/NFV1_P02_T03_READ_ONLY_CHECKPOINT_2026-10-06.md`;
- este registro documental também condicionado a merge/gates; não certifica Task inteira;
- nenhuma Task posterior liberada; continuar T03 após decisão; P2 gate NOT MET.

Staging READ-ONLY pós-merge: deployments inalterados; API/Portal em f9b5b2c, 1/1;
Worker em 1c34ba0, 0/1; Postgres 18/1/1/5000 MB; staged patch vazio. Drift permanece
P4/P5/P9/P11. Sem deploy/migration externa/secret real/entrega externa/custo/Go-No-Go.
PRODUCTION_APPROVED=NO; COMMERCIAL_LIVE=NO. Leitura persistida não comprova segredo
resolvido, provider operacional, entrega, homologação ou produção. Snapshots abaixo
são históricos; prevalecem GitHub e este checkpoint superior.

---

## CURRENT superior — 2026-10-06 — NFV1-P02-T02 CLOSEOUT

- PR #117 MERGED; HEAD certificado `06def0c237dcbc0856441e88c811443e902b7c34`;
- main certificado da entrega `f5bfbbb91ac7766a31a144c3626376f50b15646a`;
- CI PR #626 / main #627 SUCCESS; Plan Governance PR #55 / main #56 SUCCESS;
- 1149 Python/PostgreSQL PASS, zero SKIP; 10 Playwright PASS; todos os gates completos;
- P02-T02 DONE_CERTIFIED após closeout integrar main e seus gates verdes;
- closeout: `checkpoints/NFV1_P02_T02_CLOSEOUT_2026-10-06.md`;
- cinco vistas fiscais conectadas; Portal 12 surfaces genéricas duráveis, nove restantes;
- migração aditiva 13 conserva scope de reservas novas; legado sem ownership excluído;
- readiness delegado ou blocked; nenhuma homologação/emissão externa certificada;
- retry na mesma página conserva key; reload/crash permanece P2-G13/P02-T07;
- próximo item: **NFV1-P02-T03 — Configuração do cliente**, após closeout/gates;
- P0/P1 certificados; P2 em execução; PORTAL_COMMERCIAL_PARITY_CERTIFIED = NOT MET.

Staging READ-ONLY pós-merge: deployments inalterados; API/Portal em `f9b5b2c5b436045947159f1e76be9303f5a95d90`, 1/1 cada; Worker `1c34ba001935952f83ec0b065144e0b8311a5650`, 0/1; Postgres 18/volume 5000 MB/1/1. STAGING_REAL / VERSION_DRIFT_PRESENT / NOT_CERTIFIED_AGAINST_CURRENT.
Sem deploy/migration externa/secrets reais/decisão comercial. PRODUCTION_APPROVED=NO; COMMERCIAL_LIVE=NO.
Snapshots abaixo são históricos; prevalecem GitHub e este closeout.

---

## CURRENT superior — 2026-10-06 — NFV1-P02-T01 CLOSEOUT

- main certificado da entrega: `d38226b66b4a56bbd507b4b74ed20f9d6b94e0fb`;
- PR #115 MERGED; HEAD `46b92811d52ab03864dd35377f3f918c31e5f83b`;
- CI PR #620 / main #621 SUCCESS; Plan Governance PR #49 / main #50 SUCCESS;
- NFV1-P02-T01: DONE_CERTIFIED após este registro integrar main;
- matriz: `NFCORE_V1_P02_FRONTEND_BACKEND_MATRIX_2026-10-06.md`;
- closeout: `checkpoints/NFV1_P02_T01_CLOSEOUT_2026-10-06.md`;
- próximo item: **NFV1-P02-T02 — Superfícies fiscais**, somente após closeout mergeado/gates verdes;
- P0/P1 certificados; P2 em execução; PORTAL_COMMERCIAL_PARITY_CERTIFIED = NOT MET;
- gaps P2-G01..G18 continuam atribuídos; nenhuma superfície foi implementada nesta tarefa.

Staging revalidado READ-ONLY pós-merge: deployments inalterados; API/Portal
`f9b5b2c5b436045947159f1e76be9303f5a95d90`, 1/1 cada; Worker
`1c34ba001935952f83ec0b065144e0b8311a5650`, 0/1; Postgres 18/volume 5000 MB/1/1.
STAGING_REAL / VERSION_DRIFT_PRESENT / NOT_CERTIFIED_AGAINST_CURRENT.
Sem deploy ou operação externa. PRODUCTION_APPROVED=NO; COMMERCIAL_LIVE=NO.
Snapshots abaixo são históricos e não substituem este closeout nem o GitHub.

---

## CURRENT superior — 2026-10-06 — NFV1-P02-T01 em execução

Este checkpoint prevalece sobre os snapshots históricos abaixo. O GitHub foi
reconsultado antes de iniciar P02-T01; nenhum SHA histórico foi usado para rollback.

- main de entrada: `0e5be77267a800384d111c03e30705d95bdb0d28`;
- PR #114 MERGED; PRs abertas na entrada: 0;
- FM NFCORE V1 CI #618 SUCCESS; NFCore Plan Governance #47 SUCCESS, ambos no exact main;
- P0/P1: DONE_CERTIFIED; P01-T01..T04 concluídas no ledger;
- `FISCAL_RUNTIME_COMPOSED_AND_CERTIFIED_INTERNAL = MET`;
- P02-T01: IN_PROGRESS; demais tarefas P2: PENDING;
- matriz: `NFCORE_V1_P02_FRONTEND_BACKEND_MATRIX_2026-10-06.md`;
- checkpoint: `checkpoints/NFV1_P02_T01_FRONTEND_BACKEND_MATRIX_2026-10-06.md`.

P1 compôs o único path fiscal para Portal e Bridge. Isso certifica encaminhamento,
autoridade e contratos internos; handlers/provider/secret/signer reais permanecem
não configurados/fail-closed. Não representa execução fiscal externa real.

Portal CURRENT: 7 superfícies genéricas duráveis; 14 sem projeção; plataforma com
pricing/release e checkout opcional. Gaps P2-G01..G18 foram atribuídos a Task IDs.
`PORTAL_COMMERCIAL_PARITY_CERTIFIED = NOT MET`.

Railway READ-ONLY: API/Portal em `f9b5b2c5b436045947159f1e76be9303f5a95d90`, 1/1 cada;
Worker em `1c34ba001935952f83ec0b065144e0b8311a5650`, 0/1 running; Postgres 18,
volume 5000 MB, 1/1. Sem alterações staged substantivas; pendingWork patch vazio.
STAGING_REAL / VERSION_DRIFT_PRESENT / NOT_CERTIFIED_AGAINST_CURRENT.

Merge técnico interno está autorizado por instrução explícita de 2026-10-06,
condicionado aos gates verdes e proteção pelo exact HEAD; deploy/operação externa
continuam exigindo autorização específica. Nenhum deploy foi realizado.
`PRODUCTION_APPROVED=NO`; `COMMERCIAL_LIVE=NO`.

Próxima ação: PR/CI/merge/main/closeout T01; depois NFV1-P02-T02. Não avançar antes
da certificação do predecessor. Snapshots abaixo permanecem históricos.

---

## 0A0. CURRENT authoritative checkpoint — 2026-10-06 — P01-T01 CLOSEOUT

This subsection is authoritative over older execution-state wording below. GitHub CURRENT was revalidated immediately before the closeout.

### GitHub CURRENT

- canonical repository: `faabio3131/kordena-fiscal-engine-v2`;
- canonical branch: `main`;
- main HEAD: `4f896762674508498e3261aaf2d36480f284dfa2`;
- PR #107 — `NFV1-P01-T01 — identificar composição fiscal canônica`: **MERGED**;
- PR #107 certified HEAD before merge: `f3f0337cc3c8633b788e4ab7337f3cc24f7fd034`;
- post-merge **FM NFCORE V1 CI #603 — SUCCESS** on exact main HEAD;
- post-merge **NFCore Plan Governance #32 — SUCCESS** on exact main HEAD;
- open PRs at the start of this closeout: **0**;
- repository visibility: **PUBLIC**.

### Execution state

- P0: **DONE_CERTIFIED**;
- P1: **IN_PROGRESS**;
- `NFV1-P01-T01 — Identificar composição canônica`: **DONE_CERTIFIED**;
- `NFV1-P01-T02 — Implementar composition root`: **PENDING / NEXT_CANONICAL_TASK**;
- `NFV1-P01-T03 — Certificar autoridade`: **PENDING**;
- `NFV1-P01-T04 — Certificar API fiscal`: **PENDING**;
- all later tasks remain not started unless separately evidenced by the ledger.

### T01 certified result

T01 identified and froze the canonical fiscal composition without introducing runtime code:

- `runtime.api:create_runtime_app` remains the single runtime entrypoint;
- `build_postgres_runtime_composition` / `RuntimeComposition` remains the durable composition root to extend;
- Bridge and Portal remain ingress adapters over one fiscal application execution path;
- S2S reuses `WorkloadAuthenticator + S2SAuthorizer`;
- Portal reuses existing human identity/session/RBAC/CSRF authority;
- capability, provider routing, signing, vault and production authority reuse their existing canonical boundaries;
- no second API, second runtime, second tenant/unit authority, second provider registry, second vault or second production authority was created.

### What T01 did not implement

The following remain TARGET for later scheduled tasks and must not be represented as CURRENT:

- concrete production `BridgeSecurityBoundary`;
- concrete production `BridgeRequestExecutor`;
- concrete production `PortalOperationExecutor`;
- real `FiscalProviderTransport`;
- concrete external `ExternalSecretClient`;
- fiscal production activation;
- official fiscal homologation.

Therefore the P1 phase gate `FISCAL_RUNTIME_COMPOSED_AND_CERTIFIED_INTERNAL` is **NOT MET** yet.

### External/runtime state

T01 and this closeout do not authorize or claim:

- deploy;
- Railway reconciliation;
- migration production;
- real secret/certificate/CSC;
- real fiscal provider activation;
- official homologation;
- production;
- commercial Go-Live.

`PRODUCTION_APPROVED=NO` and `COMMERCIAL_LIVE=NO` remain unchanged.

### Next canonical action

After this closeout is merged and its Plan Governance/CI are green, the next allowed task is:

`NFV1-P01-T02 — Implementar composition root`.

Do not start P01-T03, P01-T04 or P2 before the predecessor chain is certified.

---

## 0AA. CURRENT authoritative checkpoint — 2026-10-05 — POST-GOVERNANCE BOOTSTRAP

This subsection is the authoritative persisted checkpoint for the 2026-10-05 execution baseline. GitHub and Railway were re-audited read-only immediately before task `NFV1-P00-T01` started. Older sections below remain historical evidence only when they conflict with this checkpoint.

### GitHub CURRENT

- canonical repository: `faabio3131/kordena-fiscal-engine-v2`;
- audited pre-task main: `9a42045c9690c32dcaf2cf11ead1a0b38843c779`;
- certified post-merge main for `NFV1-P00-T01`: `824842f2ed5586351a75cd57fc765c716899bb9e`;
- certified post-merge main for `NFV1-P00-T02`: `09dd77798122202ba1b7e548818b879556bec0ae`;
- certified post-merge main for `NFV1-P00-T03`: `3837d1e6b5a3c38e3aa2ceb032fb952fab700a4c`;
- PR #100: **MERGED** into main;
- latest main technical CI for the P0 closeout baseline: **FM NFCORE V1 CI #597 — SUCCESS** on `3837d1e6b5a3c38e3aa2ceb032fb952fab700a4c`;
- latest main plan-governance CI for the P0 closeout baseline: **NFCore Plan Governance #26 — SUCCESS** on the same exact SHA;
- open PRs at the start of `NFV1-P00-T01`: **0**;
- repository visibility: **PUBLIC**.

The governance bootstrap is therefore integrated into main. It contains the canonical completion schedule, the execution ledger, AGENTS rules, PR template and machine validator.

### Canonical execution control

The active execution authorities are:

- `docs/NFCORE_V1_COMPLETION_MASTER_EXECUTION_SCHEDULE_2026-10-05.md`;
- `docs/NFCORE_V1_EXECUTION_LEDGER.md`;
- `docs/standards/FM_AI_MASTER_PLAN_EXECUTION_STANDARD.md`;
- `AGENTS.md`.

The schedule contains phases P0-P12 and 59 task IDs `NFV1-Pxx-Tyy`. The ledger is the state/proof record. Git/GitHub, CI and runtime remain superior to documentation for determining technical CURRENT.

Execution state at the start of this checkpoint:

- P0: **DONE_CERTIFIED**;
- gate de saída: **CURRENT_RECONCILED_2026_10_05**;
- `NFV1-P00-T01 — Reconciliar documentação CURRENT`: **DONE_CERTIFIED**;
- `NFV1-P00-T02 — Congelar matriz de capacidades`: **DONE_CERTIFIED**;
- `NFV1-P00-T03 — Registrar staging drift`: **DONE_CERTIFIED**;
- P1: **IN_PROGRESS**;
- `NFV1-P01-T01 — Identificar composição canônica`: **IN_PROGRESS**;
- next task remains blocked until T01 closeout: `NFV1-P01-T02 — Implementar composition root`;
- all later tasks remain not started unless separately evidenced by historical implementation; historical implementation does not mark a task complete in the new ledger.

### P1 canonical fiscal composition — T01 snapshot

The canonical composition decision for P1 is persisted in:

- `docs/NFCORE_V1_P01_CANONICAL_FISCAL_COMPOSITION_2026-10-05.md`;
- `docs/checkpoints/NFV1_P01_T01_CANONICAL_COMPOSITION_2026-10-05.md`.

Binding decisions:

- canonical runtime entrypoint remains `runtime.api:create_runtime_app`;
- canonical durable composition remains `build_postgres_runtime_composition` / `RuntimeComposition`;
- Bridge and Portal are ingress adapters only and must delegate to one fiscal application execution path;
- S2S reuses `WorkloadAuthenticator + S2SAuthorizer`;
- Portal reuses existing session/RBAC/CSRF authority;
- provider/readiness/signing/vault/production authority reuse their existing certified boundaries;
- no concrete production `BridgeRequestExecutor` / `PortalOperationExecutor` is present yet;
- no real `FiscalProviderTransport` or concrete `ExternalSecretClient` is certified in CURRENT;
- P01-T02 must implement composition without enabling fiscal production automatically.

### Railway staging drift register — T03 snapshot

Authoritative drift evidence for this task is persisted in:

- `docs/NFCORE_V1_STAGING_DRIFT_2026-10-05.md`;
- `docs/checkpoints/NFV1_P00_T03_STAGING_DRIFT_2026-10-05.md`.

Current exact comparison:

- main: `eccb40058992023514eeaac5ecfecb7e551df763`;
- API: `f9b5b2c5b436045947159f1e76be9303f5a95d90` — 36 commits behind;
- Portal: `f9b5b2c5b436045947159f1e76be9303f5a95d90` — 36 commits behind;
- Worker: `1c34ba001935952f83ec0b065144e0b8311a5650` — 118 commits behind and 0/1 running;
- Postgres: PostgreSQL 18, 5000 MB persistent volume, migrations 1–12 with `cakto_schema=2`;
- all service `stagedChangeCount` values are 0; Railway `pendingWork` still exposes one empty `EnvironmentPatch` record with `changes=[]`, so there is no substantive staged configuration change to apply;
- tracing Railway remains disabled;
- no custom domains exist for API/Portal.

This records drift only. It does not authorize reconciliation deploy.

### Railway staging CURRENT — read-only verification

Project: `FM NFCORE Staging`.

The Railway environment is named `production`, but this is only the environment label inside the staging project and does **not** mean NFCore production is approved.

Verified live services:

- PostgreSQL: online, 1/1 replica, persistent volume present;
- `nfcore-api`: online, 1/1 replica, latest deployed commit `f9b5b2c5b436045947159f1e76be9303f5a95d90`;
- `nfcore-portal`: online, 1/1 replica, latest deployed commit `f9b5b2c5b436045947159f1e76be9303f5a95d90`;
- `nfcore-worker`: Railway service state online, latest deployed commit `1c34ba001935952f83ec0b065144e0b8311a5650`, but replica status is **0 running / 1 total**.

Version drift therefore remains between audited main and staging.

Additional verified runtime facts:

- Railway tracing is disabled for PostgreSQL, API, Portal and Worker;
- API and Portal use Railway service domains only; no custom domain is present;
- one Railway environment patch is reported as staged with an empty `changes` list;
- no active Railway warning or critical notification was reported in the 24-hour environment health read.

Detailed drift registration and closure belong to `NFV1-P00-T03` / P5 as defined by the schedule. This task records the observed CURRENT but does not claim those later tasks complete.

### Confirmed completion gaps carried into the schedule

The 2026-10-05 audit remains authoritative for the following gaps:

1. fiscal Bridge security/execution and Portal operation executors are not composed in the canonical runtime app;
2. Portal durable surfaces expose only a subset of the functionality represented in the frontend;
3. acquisition, trial and provider webhook ingress are implemented but not wired into the canonical runtime app;
4. continuous Worker execution lacks the explicit real handler composition required by the entrypoint;
5. a real fiscal transport provider and a concrete external Secret Manager adapter are not certified;
6. operational tracing/exporters are not active in Railway;
7. official fiscal homologation, controlled pilot, production infrastructure and commercial Go-Live remain unproven.

### Classification

- functional/domain foundation: strong but not end-to-end integrated;
- staging: **REAL / VERSION_DRIFT_PRESENT / NOT_CERTIFIED_AGAINST_CURRENT**;
- production: **NOT PROVEN / NOT APPROVED**;
- commercial status: **NO-GO**;
- `PRODUCTION_APPROVED`: **NO**;
- `COMMERCIAL_LIVE`: **NO**.



## 0A. CURRENT override — 2026-10-01

This subsection is authoritative over older Railway/status wording below. GitHub and Railway were re-audited read-only.

### GitHub

- NFCore main: `f2fd8a875bdf8ae5327d7f716209603f60d34570`;
- latest main CI: **FM NFCORE V1 CI #519 — SUCCESS**;
- repository remains **PUBLIC**;
- Site FM main: `26bfe05c2891bfc68f680587d0ae47ee36f105b1`;
- Site Validation #553 and Cloudflare Worker Validation #127: **SUCCESS**.

### Railway real state

The dedicated project `FM NFCORE Staging` now exists. Its Railway default environment is labeled
`production`; this label is inside the staging project and does **not** mean NFCore production is
approved.

Services:

- `nfcore-api`: **SUCCESS** on older SHA `11cec7991c5345e03ef54e58b1fa6b5fbcd51801`;
- `nfcore-worker`: **CRASHED** on the same older SHA;
- `nfcore-portal`: **SUCCESS** on older SHA `5201eaa663b029d304a89131c28d501e444f730d`.

The worker fails closed with `durable worker runtime requires PostgreSQL persistence`.

There is currently:

- no PostgreSQL service;
- no configured runtime variables/secrets on API/worker/portal;
- no public Railway domain attached to API or portal;
- no deployment of current main `f2fd8a875bdf8ae5327d7f716209603f60d34570`;
- no certified rollback rehearsal;
- no real staging commercial E2E.

Therefore:

- CL-15 = **IN_PROGRESS / BLOCKED_EXTERNAL**;
- `STAGING_DEPLOYED_AND_E2E_VALIDATED=false`;
- CL-16 = **NOT_STARTED_OPERATIONALLY**;
- CL-17 = **NOT_STARTED_OPERATIONALLY**;
- CL-18 = **NOT_STARTED**;
- `PRODUCTION_APPROVED=NO`.

### Activation delivery boundary

The existing API already exposes the injected provider-neutral `PasswordResetDelivery` port.
`SecureActivationEmailDelivery` is compatible with this contract. No new Core authority or
provider-specific domain code is required before choosing/configuring a real outbound delivery
provider.

See `docs/NFCORE_CL15_STAGING_CURRENT_AUDIT_2026-10-01.md`.

---

## 0. CURRENT reconciliation — 2026-09-30

This section is authoritative over stale status language below while preserving historical audit
records. GitHub CURRENT must be revalidated on every resume.

### Canonical phase state

- CL-12: `IMPLEMENTED / TESTED / MERGED / CERTIFIED`;
- CL-13: `IMPLEMENTED / TESTED / MERGED / CERTIFIED`;
- CL-14: `IMPLEMENTED / TESTED / MERGED / CERTIFIED`;
- CL-15: `IN_PROGRESS / BLOCKED_EXTERNAL`;
- CL-16: `NOT_STARTED_OPERATIONALLY`; internal harness only: `PREPARED_NOT_ACTIVE`;
- CL-17: `NOT_STARTED_OPERATIONALLY`; reusable historical authorities do not count as execution;
- CL-18: `NOT_STARTED`;
- `PRODUCTION_APPROVED`: **NO**;
- NFCore -> Kordena cutover: **NOT AUTHORIZED**.

### Railway capacity update — 2026-09-30

Railway Hobby capacity is now sufficient to create the dedicated NFCore project and the
secretless API/worker/portal service scaffold. The previous free-plan resource-limit blocker
is resolved.

The repository remains public by deliberate CI-continuity decision. No real database or
runtime/provider/fiscal secret is introduced while that public-repository guard remains in
force. The new truthful state is:

`RAILWAY_CAPACITY_RESOLVED / SECRETLESS_SCAFFOLD_PREPARED / REAL_STAGING_SECRET_BOUNDARY_DEFERRED`

This does not satisfy `STAGING_DEPLOYED_AND_E2E_VALIDATED`.

### CL-15 exact truth

Railway staging-provider contract preparation exists, but the dedicated NFCore staging project was
not provisioned because Railway rejected the creation attempt with a free-plan resource-limit
blocker. No real NFCore staging deploy, staging database, real provider secret, real activation
provider delivery, real staging E2E or rollback rehearsal is evidenced.

The activation-delivery adapter from PR #79 is implemented and unit-tested. It is not currently
imported, instantiated or exposed by the canonical `RuntimeComposition`. Therefore its correct
state is `IMPLEMENTED_AND_UNIT_TESTED`, not `INTEGRATED`.

The CL-15 gate `STAGING_DEPLOYED_AND_E2E_VALIDATED` remains **NOT MET**.

### CL-16 exact truth

PR #80 added a fail-closed internal validation/evidence harness. The harness requires the exact
CL-15 staging state before it can become ready for a real provider exercise. Its canonical state is
`INTERNAL_HARNESS_AVAILABLE / PREPARED_NOT_ACTIVE`.

This does not mean CL-16 started operationally and does not provide
`COMMERCIAL_CHANNEL_READY`.

### CL-17 / CL-18 boundary

Existing V2-15/POST-WEB-12 fiscal governance may be reused in the future to avoid duplicate
engineering. Reuse readiness is not phase execution. CL-17 remains
`NOT_STARTED_OPERATIONALLY` until predecessor gates and real official external prerequisites are
available. CL-18 remains `NOT_STARTED`.

No CI result, synthetic matrix, internal harness or documentation update is official
SEFAZ/prefeitura/provider homologation, a real controlled pilot or `PRODUCTION_APPROVED`.

### Cross-repository reconciliation

Site FM PR #24 is retained. It adds post-merge validation on `main` and updates the patched
`undici` dependency; its merge commit `26bfe05c2891bfc68f680587d0ae47ee36f105b1`
passed both Site Validation and Cloudflare Worker Validation.

Kordena is explicitly out of scope for writes in this reconciliation. Protected checkpoint:
`faabio3131/fm-ai-platform` / `staging/kordena-premium@57bbf18cacdc443d329308e6d9328c57aa55ed0a`.

See `docs/NFCORE_CONTEXT_INCIDENT_RECONCILIATION_2026-09-30.md`.

## 1. Confirmed integration state

### NFCore

PR #66 — **CL-10R — restore commercial provider independence** — is **MERGED**.

- certified PR HEAD: `f792ef7ca12369d3444a6760c799c77477e6f653`;
- merge/main commit: `19f1102d64a956de3eefa6cb2d6f2f0ddefb0f09`;
- candidate `FM NFCORE V1 CI` #438: **SUCCESS**;
- post-merge `FM NFCORE V1 CI` #439: **SUCCESS** on exact main;
- compare certified HEAD -> merge commit: zero file changes.

CL-10R restored the canonical provider-neutral checkout/commercial contract without replacing billing, pricing, tenant, provisioning or fiscal authorities.

### Site FM

PR #22 — **NFCore — restore provider-neutral checkout contract** — is **MERGED**.

- certified PR HEAD: `124892f8af689c25dbcf280bdd4075adfa5bd9f2`;
- merge/main commit: `8e25261a74b8dd4d7b5f335de76366bd24920d45`;
- Site Validation #530: **SUCCESS** on certified PR HEAD;
- Cloudflare Worker Validation #104: **SUCCESS** on certified PR HEAD;
- compare certified HEAD -> merge commit: zero file changes.

CURRENT Site workflows do not trigger on `push: main`; therefore no post-merge Site workflow exists for this merge. This is a governance gap to correct separately, not evidence of a failed merge.

### Superseded CL-11

PR #65 — **SUPERSEDED — CL-11 post-purchase provisioning bridge design** — is **CLOSED / NOT MERGED**.

Its Cakto-specific acquisition/callback design must not be used as implementation authority.

No CL-11 production code from PR #65 entered `main`.

## 2. Architecture authority reconciled

FM architecture requires one evolving application line and keeps external providers behind infrastructure/adapters.

The canonical NFCore separation is:

`Domain/Core -> Application -> Infrastructure/Adapters -> External Systems`

Commercial authorities remain separate:

`Pricing != Checkout != Billing/Entitlement != Commercial Release != Fiscal Production Authority`

Supported customer/provider differences are configuration. A previously unsupported provider protocol may require one reusable adapter; account, offer, product, endpoint and secret differences do not justify customer-specific source forks.

## 3. Provider-neutral commercial CURRENT

The canonical checkout contract is `src/kordena_fiscal/product/checkout.py`:

- `CommercialCheckoutProjector`;
- `CommercialCheckoutProjection`;
- `CommercialCheckoutItem`;
- `CommercialCheckoutStatus`.

The canonical public commercial-offer path does not depend on Cakto types.

Cakto remains a provider-specific optional adapter. It may own:

- Cakto webhook authentication/parsing;
- provider-local product/offer bindings;
- provider-local inbox/retry/dead-letter/reconciliation;
- provider-local external customer references;
- provider-specific admin surface;
- provider-specific external-state evidence.

It must not own canonical NFCore organization identity, billing authority, tenant authority, login/RBAC or fiscal production authority.

## 4. Site FM commercial boundary

The Site consumes:

`Browser -> /api/nfcore/commercial-offer -> NFCORE_API_URL/v1/commercial/offer`

The Site contract:

- accepts a governed provider identifier;
- has no Cakto-only provider literal;
- has no Cakto-only checkout host requirement;
- validates checkout URLs as absolute HTTPS without embedded credentials;
- keeps `NFCORE_API_URL` server-side;
- fails closed when upstream state is absent/invalid;
- cannot create pricing, commercial approval, payment approval or fiscal authority.

## 5. Confirmed functional foundations

The integrated main contains:

- canonical auth/session/RBAC;
- tenant/unit authority and anti-spoofing boundaries;
- durable Control Plane and PostgreSQL;
- zero-code fiscal provider/configuration bindings;
- external secret boundaries;
- generic pricing with `external_price_reference`;
- human Commercial Release Authority;
- provider-neutral checkout projection;
- generic billing-domain contracts (`CommercialPlan`, `CommercialSubscription`, quotas/status);
- trusted `CommercialCustomerProvisioningService`;
- first OWNER provisioning;
- password recovery/one-time activation mechanics;
- authenticated portal;
- tenant-scoped basic unit onboarding;
- observability contracts;
- container/security/backup/restore CI gates;
- staging/production promotion contracts that remain fail-closed without external infrastructure.

## 6. New CURRENT blocker — CL-11

The remaining internally solvable commercial gap is now defined as:

**CL-11 — Provider-Neutral Commercial Acquisition & Provisioning**

Formal design candidate:

`docs/CL_11_PROVIDER_NEUTRAL_COMMERCIAL_ACQUISITION_PROVISIONING_DESIGN.md`

### B1 — validated payment is not connected to canonical provisioning

CURRENT has two independent capabilities:

```text
external provider event -> provider-specific commercial state
```

and

```text
CommercialCustomerProvisioningService
-> canonical organization
-> first OWNER
-> activation reset
```

There is no provider-neutral application orchestration joining those paths end-to-end.

### B2 — purchase can become enabled before the post-purchase journey is operational

CURRENT `purchase_enabled` checks:

- human commercial approval;
- configured checkout projection;
- checkout items;
- provider processing configured.

It does not yet require:

- canonical post-purchase orchestration readiness;
- durable provider-neutral subscription/entitlement readiness;
- provisioning readiness;
- activation-delivery readiness.

Until CL-11 closes this, real paid checkout must not be treated as commercially launch-ready.

### B3 — durable canonical billing/subscription runtime is incomplete

The provider-neutral billing domain exists, but CURRENT repository structure has no equivalent provider-neutral durable subscription/entitlement persistence/runtime authority.

Provider-specific Cakto commercial persistence therefore must not be promoted into canonical NFCore billing.

CL-11 must extend the existing generic billing model with durable provider-neutral application/persistence authority.

### B4 — provider-local customer identity must remain provider-local

Cakto currently has a provider-local commercial tenant/customer mapping derived from its external customer ID.

That identity may remain useful for adapter reconciliation, but it must never become the canonical NFCore tenant/organization identity.

The same invariant applies to every provider.

## 7. Frozen CL-11 invariants

Before implementation, CL-11 must preserve:

1. canonical organization/tenant identity is NFCore-owned;
2. external provider IDs are adapter-local references;
3. browser input is never payment, tenant, entitlement or fiscal authority;
4. adapters authenticate/validate/translate provider events;
5. one provider-neutral canonical subscription/entitlement authority governs NFCore commercial access;
6. existing provider state may remain for reconciliation/audit only;
7. provisioning is idempotent and retry-safe;
8. duplicate/replayed events cannot duplicate org, OWNER, subscription or entitlement;
9. payment never grants fiscal production authority;
10. activation delivery is part of paid-journey readiness;
11. first-party Site purchase and externally initiated marketplace purchase must both be supportable;
12. no sales channel becomes mandatory architecture.

## 8. CL-11 target

```text
Cakto / Hotmart / Kax / Site / Marketplace / Future channel
                           |
                           v
                 Provider-specific adapter
                           |
                           v
                Validated Commercial Event
                           |
                           v
             Commercial Acquisition Orchestrator
                           |
             +-------------+--------------+
             |                            |
             v                            v
 canonical subscription/entitlement   identity resolution
             |                            |
             +-------------+--------------+
                           |
                           v
          CommercialCustomerProvisioningService
                           |
                  organization + OWNER
                           |
                           v
                  activation delivery
                           |
                           v
                  login + onboarding
```

Provider-specific callback/metadata mechanics belong to adapters and are not canonical business authority.

## 9. Purchase-readiness target

After CL-11, public purchase must remain fail-closed unless the end-to-end journey is operational.

At minimum the readiness decision must account for:

- commercial approval;
- published pricing;
- configured checkout provider;
- complete checkout mapping;
- provider event processing;
- canonical acquisition/subscription runtime;
- trusted provisioning runtime;
- activation delivery readiness.

Exact API/data shape requires design approval and implementation review.

## 10. Trial status

`trial_enabled` remains explicitly **false** in CURRENT and is a separate authority.

Trial must not be inferred from `trial_days` in pricing.

No trial launch may be claimed until a governed trial acquisition/provisioning journey exists and is certified.

## 11. Portal/branding audit finding

CURRENT portal/login still uses:

`portal/assets/fm-nfcore-mark.svg`

while Site FM uses newer approved NFCore image assets.

The existing Brand Kit still declares the old SVG asset canonical.

This is a confirmed brand-documentation/UI drift.

Required treatment:

- reconcile the latest approved NFCore identity;
- update the canonical Brand Kit/assets;
- apply it to login, sidebar, favicon and portal on the same application;
- preserve auth/RBAC/tenant/API behavior;
- rerun visual/accessibility gates.

This is not part of CL-11 domain implementation and must not cause a frontend rebuild.

## 12. Portal checkout-admin finding

The portal contains a provider-specific `Checkout Cakto` administration surface.

CURRENT backend only adds that surface for a platform admin when the Cakto administration adapter is composed. Therefore it is not a universal customer authority.

Future UX should organize provider-specific configuration under a neutral capability such as:

`Canais de Venda / Checkout -> provider adapters`

This is a UI/admin refinement, not a blocker to CL-11 domain design.

## 13. Site CI governance finding

CURRENT Site workflows run on pull requests, but their `push` branch filters do not include `main`.

Required separate correction:

- add `main` to Site Validation push trigger;
- add `main` to Cloudflare Worker Validation push trigger;
- preserve the existing PR gates.

The already merged PR #22 remains evidenced by green exact PR HEAD plus zero-file-diff to merge commit.

## 14. Staging and production CURRENT

NFCore contains governed workflows for staging and production promotion.

CURRENT facts:

- staging workflow is manual;
- real deployment requires external HTTPS URL, PostgreSQL, deploy driver, IAM and external secret backend;
- default provider driver is unconfigured/fail-closed;
- no real staging deployment evidence exists;
- no production promotion evidence exists;
- production requires explicit `PRODUCTION_APPROVED`;
- fiscal Go-Live remains separate from software deployment.

Therefore:

`STAGING_READY_FOR_PROVISIONING / BLOCKED_EXTERNAL`

is the maximum valid staging classification.

## 15. Commercial readiness classification

### A — Functional readiness

Strong internal fiscal/web/auth/configuration foundation. Paid acquisition is internally incomplete until CL-11.

### B — Commercial parity

Provider-neutral Site/checkout contract is integrated. Paid post-purchase provisioning and trial remain incomplete.

### C — Production technical readiness

Internal deployment/security/recovery contracts exist. Real staging/production infrastructure is not evidenced.

### D — Operational readiness

Internal observability/runbook/backup contracts exist. Real external monitoring, infrastructure credentials and cutover evidence remain absent.

### E — Commercial readiness

**NOT COMMERCIAL LIVE.**

A customer must not be charged through a real public path before CL-11 proves that the paid acquisition can reach a usable activated NFCore account.

## 16. External/human dependencies after CL-11 internal closure

Depending on selected launch channels:

- approved real prices/plans/promotions;
- selected commercial provider account(s);
- product/offer IDs and provider configuration;
- provider API/webhook secrets in approved Secret Manager/Vault;
- public HTTPS callbacks where required;
- real activation email/SMS provider and credentials;
- staging/production hosting, PostgreSQL, ingress and TLS;
- fiscal certificates/CSC/provider credentials;
- exact launch fiscal cells;
- official homologation evidence;
- controlled fiscal pilot;
- legal/LGPD operational review;
- final human Go/No-Go / `PRODUCTION_APPROVED`;
- authorized deploy/DNS/cutover/smoke.

No external commercial provider is mandatory by architecture.

## 17. Repository visibility

NFCore and Site FM remain **PUBLIC temporarily** due the previous private GitHub Actions quota constraint.

Until returned to PRIVATE:

- never commit real secrets, certificates, CSC, passwords, provider tokens or cloud credentials;
- keep secret/dependency/vulnerability scanning mandatory;
- use only synthetic provider IDs in tests.

Return to PRIVATE before introducing real production credentials/configuration into connected infrastructure.

## 18. Next execution order

1. review/approve or amend the CL-11 provider-neutral design;
2. only after human architectural approval, implement CL-11 on a dedicated implementation branch;
3. add durable provider-neutral acquisition/subscription persistence and migrations;
4. connect at least one authenticated adapter event to the canonical commercial orchestrator;
5. integrate canonical provisioning + OWNER + activation delivery readiness;
6. update Site first-party purchase flow without making Site mandatory for marketplace sales;
7. prove end-to-end paid acquisition/replay/refund/identity-failure cases;
8. correct Site `push: main` CI governance;
9. reconcile the approved NFCore brand assets on the existing portal;
10. re-audit all internally solvable gaps;
11. only then provision external staging/providers/secrets/activation delivery;
12. execute fiscal homologation/pilot;
13. final production-readiness audit -> human Go/No-Go -> authorized cutover.

No later block may convert `BLOCKED_EXTERNAL` into READY without reproducible external evidence.
