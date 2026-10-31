# FM NFCORE V1 — PLANO OPERACIONAL DE PENDÊNCIAS RTC + COMMERCIAL LAUNCH

**Versão:** 2026-10-31 · **Estado:** EM_EXECUCAO / DOCUMENTADO_PENDENTE_INTEGRACAO · **Executor:** agentes vinculados ao repositório canônico.  
**Escopo:** pendências de Reforma Tributária (RTC-00..12), BUILD-ONLY (BLD-03..08), Web/Contabo, certificação e dependências externas; COG-01 como trilha independente.  
**Não substitui:** `AGENTS.md`, cronograma mestre RTC `docs/NFCORE_RTC_MASTER_EXECUTION_SCHEDULE_2026-10-30.md`, plano de 59 tarefas `docs/NFCORE_V1_COMPLETION_MASTER_EXECUTION_SCHEDULE_2026-10-05.md`, `docs/NFCORE_V1_EXECUTION_LEDGER.md` e ledger BUILD. IDs `NFC-EXEC-xx` são **orquestração de pendências**, não uma segunda definição de regra ou checklist das 59 tarefas.

## 0. Snapshot auditado — não confundir com CURRENT futuro

- Repositório: `faabio3131/nf-core-v001` (mesmo repository ID do nome anterior `kordena-fiscal-engine-v2`).
- `main`: `d1b86063939350208625e97d25e33cf381155323`. CI pós-merge `41231440835` SUCCESS; Governança `41231440812` SUCCESS. Prova de código e regressão interna **não** equivale a Web/Contabo/produção funcional.
- `production`: `a3a2b3c97d26780b1e2b7581b4c93b6f07e86a70`, diferente de main. SHA real de containers Contabo **NÃO VERIFICADO**.
- RTC: #267 (RTC-00), #268/#270 (RTC-01), #269/#271/#272 (RTC-02), #273/#274/#280 (RTC-03), #275/#278 (RTC-09 inicial) **MERGED**. Os WPs RTC-00..03 e 09 **NÃO** estão automaticamente 100% certificados: são entregas parciais.
- BUILD: BLD-00/01/02 certificados **internamente**. #260 e #279 (BLD-03), #281 e patch de segurança BLD-04 integrados; BLD-03/04 permanecem parciais até aceitar jornada inteira.
- PRs não integradas relevantes: NFCore #284 (deploy Contabo); site canônico `faabio3131/fm-site-novo` #12 (trial, Draft). Reabrir status e HEAD antes de qualquer ação.
- Core Cognitivo: implementação em `faabio3131/cognitivo-nfcore-inteligencia-fiscal` @ `ca3235036254d1d5113c891902bcbd1aaa1cb022`, patch de integração recebido; **ausente na main NFCore deste snapshot**, não está certificado nem ativado.
- Uso do ambiente: **Contabo**, não Railway. Documentos históricos Railway não são CURRENT.

## 1. Invariantes e algoritmo de execução

1. Ao iniciar **cada sessão ou novo bloco**, ler este documento, `AGENTS.md`, cronogramas RTC/BUILD e ledgers; obter GitHub **ao vivo**: main/production SHA, PRs, mudanças recentes, CI/Gov, ambiente de destino. Criar checkpoint de reconciliação se divergirem.
2. Selecionar o **primeiro item elegível** abaixo cuja dependência técnica esteja satisfeita. Dentro da trilha, implementar sequencialmente; em paralelo, somente trabalhos verdadeiramente independentes. Proibido reconstruir função já integrada.
3. Antes de programar: confirmar autoridade canônica, contrato, arquivos impactados, fonte normativa com versão/vigência, escopo, perigos, aceites e testes. Se faltar fonte oficial para alíquota/regra, marcar BLOCKED_NORMATIVE e **não inventar** taxa, XML ou preenchimento.
4. Para cada microentrega: branch pequena → diff → Ruff, mypy, pytest direcionado + integrações pertinentes, frontend lint/typecheck/tests/build, E2E, PostgreSQL isolado, segurança tenant/RBAC/CSRF, scripts, Docker conforme impacto → PR → CI/Gov `SUCCESS` no HEAD exato → revisão → merge **somente com autorização aplicável** → CI/Gov pós-merge e checkpoint. Não eliminar testes para deixar verde.
5. Autonomia de merge BUILD-ONLY está descrita no AGENTS.md. **A autorização não se estende automaticamente a RTC, COG, site, production, migrações, segredos ou deploy.** Autorização de deploy declarada no chat em 31/10/2026 não é aprovação de migration produtiva, produção fiscal, real billing, credenciais ou promoção sem gates; verificar escopo novamente no ato.
6. Segurança: serviços determinísticos executam e validam; IA é consultiva. Sem segunda API, autenticação, tenant, unidade, motor tributário, persistência ou frontend. Toda evidência é segregada por tenant/unidade. Testes contra banco destrutivo **somente descartável e explicitamente isolado**; nunca rodar fixture `DROP SCHEMA public CASCADE` contra banco persistente.
7. Estado permitido: `ALREADY_INTEGRATED`, `IN_PROGRESS`, `PENDING`, `BLOCKED_NORMATIVE`, `BLOCKED_EXTERNAL`, `BLOCKED_HUMAN_ACTION`, `IMPLEMENTED_NOT_CERTIFIED`, `DONE_CERTIFIED_INTERNAL`, `DONE_CERTIFIED_OPERATIONAL`, `SUPERSEDED`. Nenhum `DONE` sem evidência; usar explicitamente `N/A` fundamentado.
8. Em **cada PR de entrega**, atualizar a linha correspondente **neste plano e no ledger canônico apropriado**, com data UTC, escopo, PR, HEAD, merge SHA, testes, CI pré/pós, evidência e próximo item. O próprio checkpoint é commit versionado. Não alterar checkpoints históricos retroativamente.
9. Preservar o uso único da linha DEV → HOMOLOGAÇÃO → PRODUÇÃO; não aplicar migrações de produção nem promover branch `production` como efeito de merge em `main`.
10. Se o agente perder acesso à ferramenta, parar alteração e informar estado: nada de alegar execução em background. A próxima execução retoma pela prova persistente, sem repetir fase.

## 2. Trilha RTC — Reformulação Tributária, prioridade de construção

| ID | WP canônico | Entrega mínima verificável | Dependências | Estado em 31/10 | Evidência / próximo gate |
|---|---|---|---|---|---|
| NFC-EXEC-01 | RTC-00/01 | Fechar lacunas do inventário e catálogo **oficial**: fonte, edição, vigência, SHA e revisão; identificar diferenças entre tabela piloto e produção sem ativação silenciosa | baseline em main | IMPLEMENTED_NOT_CERTIFIED | #267/#268/#270 merged; verificar cobertura normativa real e watcher versionado |
| NFC-EXEC-02 | RTC-02 | Completar matriz CRT × regime IRPJ/CSLL, histórico temporal, competência e estabelecimento, com autorização e PostgreSQL isolado | 01 quando afetar norma | IMPLEMENTED_NOT_CERTIFIED | #269/#271/#272; achar gaps em código, não refazer contrato já integrado |
| NFC-EXEC-03 | RTC-03 | Completar classificação nacional NCM/NBS, CST/cClassTrib, benefício, operação/destino/exceções, snapshots de decisão e falha fechada | 01/02 | IMPLEMENTED_NOT_CERTIFIED | #273/#274/#280; último merge `d1b8606` CI/Gov SUCCESS. Catálogo RTC precisa revisão normativa oficial |
| NFC-EXEC-04 | RTC-04 | Calculadora determinística IBS/CBS/IS usando Decimal, bases, reduções, créditos, arredondamento e totalização **somente** para células sustentadas por fontes normativas/golden cases verificáveis | 03 para célula em questão | PENDING | Primeiro bloco novo de **construção RTC**. Não inventar taxas; dividir por célula fiscal/versão |
| NFC-EXEC-05 | RTC-05 | Coexistência/temporalidade tributos legados + IBS/CBS/IS 2026–2033, snapshots e anti-regressão | 04 aplicável | PENDING | testes antes/depois por marco legal com vigência e prova |
| NFC-EXEC-06 | RTC-06 | NF-e/NFC-e: grupos XML, totais, conditionalidade, XSD vigente, assinatura/rejeição/contingência pelos adapters canônicos | 03–05 | PENDING | golden XML oficiais e validação XSD por versão; sem transmissão oficial fictícia |
| NFC-EXEC-07 | RTC-07 | NFS-e nacional/municípios homologáveis: DPS, NBS, IBS/CBS e eventos, sem alegar cobertura municipal universal | 03–05 | PENDING | testes por provedor/município/célula permitidos por fonte |
| NFC-EXEC-08 | RTC-08 | Casos diferenciados: importação, exportação, combustíveis, créditos, devoluções, regimes especiais; cobertura explícita e bloqueios para casos não suportados | 03–07 aplicáveis | PENDING | matriz suportado/não suportado com casos positivos/negativos |
| NFC-EXEC-09 | RTC-09 | Completar tela no Portal atual: classificação, cálculos, bloqueios, justificativas, fonte e vigência, com RBAC/CSRF/tenant/unidade e E2E | 02, 03 e cálculos suportados | IMPLEMENTED_NOT_CERTIFIED | #275/#278 primeira parte; restante PENDING |
| NFC-EXEC-10 | RTC-10 | Persistência canônica, trilhas, snapshots imutáveis, replay, idempotência e worker; avaliar necessidade de migration antes de criar | 04–09 afetados | PENDING | PostgreSQL descartável, concorrência, recuperação/rollback; migration produtiva requer autorização específica |
| NFC-EXEC-11 | RTC-11 | Certificação interna por regime × tributo × operação × documento × período × UF/município e CI/Gov verdes | 01–10 aplicáveis | PENDING | documento de cobertura com omissões explícitas; não igualar CI geral a conformidade |
| NFC-EXEC-12 | RTC-12 | Homologação fiscal real, credenciais, certificados, piloto, evidências oficiais e Go/No-Go | 11 + decisões externas | BLOCKED_EXTERNAL | requer escolha de provedor/UF/município e aprovação humana; sem transmissão real automática |

## 3. Trilha BUILD — pendências anteriores ao Core Cognitivo

| ID | WP canônico | Ação/aceite | Dependências | Estado em 31/10 | Evidência / próximo gate |
|---|---|---|---|---|---|
| NFC-EXEC-13 | BLD-00/01/02 | **Preservar** inventário, identidade/Portal e operações fiscais internas já certificados | nenhuma | DONE_CERTIFIED_INTERNAL | #226–#230; #253/#254/#255/#258; sem reconstrução |
| NFC-EXEC-14 | BLD-03 | Fechar teste Web cadastro trial→persistência→identidade→release e bloquear oferta se preço/duração/admin não aprovados | BLD-01 | IN_PROGRESS | #260/#279 merged; #237 SUPERSEDED; PR #292 na branch `fix/nfv1-bld03-public-trial-duplicate-json-20261031` rejeita JSON duplicado, valida Idempotency-Key conforme o serviço canônico (mínimo 16 caracteres), limita o body a 4 KiB durante streaming e bloqueia publicação de catálogo quando a leitura canônica falha (testes sem efeitos ou ofertas fictícias). Jornada completa e oferta pública ainda não aceitas; CI/merge pendentes |
| NFC-EXEC-15 | BLD-04 | Certificar HTTP Command assinado→inbox→dedupe→assinatura/provisioning→claim/activation/Worker, PostgreSQL descartável e falhas/replay | contratos BLD-03 | IN_PROGRESS | #281 integrado; CL11 já cobria ativação mas usava DROP SCHEMA public CASCADE. Branch `fix/nfv1-bld04-cl11-isolated-postgres-20261031` preserva casos existentes em schema PG descartável/local e evita destruição do public. CI e merge pendentes; BLD-04 completo ainda NÃO certificado |
| NFC-EXEC-16 | BLD-05 | Concluir gaps neutros de adapter fiscal e readiness por família, contrato real de integração sem fake em runtime | BLD-02 | PENDING | transmissão/homologação oficial permanece EXTERNAL |
| NFC-EXEC-17 | BLD-06 | E2E Web→API→PostgreSQL→Worker (outbox, retry, recuperação e isolamento) sem duplicar filas/serviços | BLD-04/05 contratos pertinentes | PENDING | provar ciclo por evento/tenant e health, sem afirmar operação externa sem teste |
| NFC-EXEC-18 | BLD-07 | Reconciliar site `fm-site-novo` PR #12, CORS/API Contabo, status da oferta e CTA; certificar e integrar apenas com autorização do outro repo | BLD-03/04 contratos | PENDING | site #12 Draft; não publicar trial sem liberação comercial |
| NFC-EXEC-19 | BLD-08 | Aceite por jornada autenticada cliente e operação fiscal em revisão publicada: login→ação→DB/Worker→UI; documentar blockers | BLD-03–07 | PENDING | `CONSTRUCTION_AND_WEB_INTEGRATION_COMPLETE` somente com provas reais por caminho |

## 4. Infraestrutura, operação e nova frente cognitiva

| ID | Frente | Ação/aceite | Dependência | Estado |
|---|---|---|---|---|
| NFC-EXEC-20 | Contabo, PR #284 | Auditar driver/cron e revisão atualmente implantada, backup/restauração, health/ready, rollback, Docker API/Portal/Worker, segredos e deploy sem migration implícita; corrigir com PR e CI | main verde + acesso operacional seguro | IN_PROGRESS: #284 MERGED em `1e1115cc2f3dee63d169edfca71a0644a7d540c6`, Gov e deploy-config pós-merge SUCCESS; CI completa pós-merge #41247712430 aguardava conclusão. PR #291 propõe gate de schema somente leitura/code-only; sem instalação/deploy/worker certificado |
| NFC-EXEC-21 | Promoção controlada | Reconciliar branch `production` vs `main`; conferir gates, migrations pendentes, backup e rollback; staging primeiro se disponível; promover somente revisão aprovada | 20 + gates e autorizações específicas | BLOCKED_HUMAN_ACTION para ações de schema/produção além da autorização de deploy |
| NFC-EXEC-22 | Fiscal externo | Homologação SEFAZ/NFS-e por célula e evidência; certificado/CSC/UF/município/provedor, habilitação real | RTC-11 + recursos externos | BLOCKED_EXTERNAL |
| NFC-EXEC-23 | Comercial externo | Definir oferta trial/preço/duração, prestador de cobrança, conta/segredos e transações reais, aprovar publicação | BUILD-03/04 internos | BLOCKED_HUMAN_ACTION |
| NFC-EXEC-24 | Operação comercial | Health/observabilidade, alertas, backup/RPO/RTO/runbooks, TLS/domínio, atendimento e Go/No-Go humano final | 19/21/22/23 | PENDING |
| NFC-EXEC-25 | COG-01 independente | Comparar patch do `cognitivo-nfcore-inteligencia-fiscal` com main; integrar sem segunda autoridade, hardening auditoria/limites/Portal, testes e aprovação própria; IA desligada por padrão | isolamento e CI; não bloquear RTC/BUILD | PENDING (não integrado) |

### Sequência operacional sem retrabalho

1. **Agora:** executar NFC-EXEC-04 (RTC-04) em microentregas normativas verificadas; NFC-EXEC-01/02/03 devem ser fechados **somente nos gaps comprovados** que condicionem a célula calculada. Em paralelo NFC-EXEC-14/15 se realmente independentes.
2. Depois RTC-05→06/07→08→09/10→11. Não pular dependência nem criar cálculo sem fonte.
3. Concluir BLD-03/04→05/06→07→08 conforme interfaces e decisões liberadas; fechar PR de infraestrutura #284 com seus próprios gates. Não assumir que a main já está implantada.
4. COG-01 pode ser integrado em branch própria sem bloquear fiscal; nunca declarar IA em produção a partir do patch.
5. RTC-12, pagamentos e Go/No-Go são gates externos: manter explícitos até teste real e autorização.

## 5. Template obrigatório de atualização por conclusão

Ao completar cada incremento, editar a linha acima **e** o ledger RTC/BUILD canônico pertinente, em **nova PR governada**:

```text
Data UTC:
Tarefa NFC-EXEC / WP canônico:
Current (main/production/conteiner Contabo e respectivas provas):
Objetivo e delta implementado:
Fonte normativa (URL oficial + versão + vigência + hash) / N/A justificado:
Branch / HEAD / PR:
Diff (componentes canônicos afetados):
Testes dirigidos (comandos + quantidade PASS/FAIL/SKIP):
Testes PostgreSQL/frontend/E2E/security conforme impacto:
CI e Governança pré-merge (run + HEAD + resultado):
Aprovação de merge aplicável:
Merge SHA:
CI/Governança pós-merge (run + SHA + resultado):
Staging / Contabo: revisão efetiva, health/smoke, rollback ou NÃO_EXECUTADO:
Riscos residuais / blockers / responsável / próximo item:
Novo estado (somente com evidência):
```

**Regra de manutenção:** atualize a linha na **mesma entrega** que satisfaz seu critério de aceite ou na PR imediatamente vinculada; não deixe o progresso só no chat. Se falhar CI, tarefa permanece `IN_PROGRESS`. Se não houver trabalho ativo entre conversas, este plano continua sendo um snapshot versionado, não um monitor automático.

### Checkpoint da implantação segura — 31/10/2026

- PR #284 (configuração Contabo, incluindo hardening da PR #290) MERGED em `main=1e1115cc2f3dee63d169edfca71a0644a7d540c6`. Governança e workflow de teste do deploy pós-merge: SUCCESS. CI completa #41247712430 ainda em execução no último levantamento da PR #291.
- PR #291, branch `fix/nfcore-contabo-codeonly-schema-gate-20261031`: amplia `migration_guard.py` com `--assert-current-production` exclusivamente SELECT-only; deploy automático passa a executar apenas quando versões fiscal e Cakto estão integralmente atuais, sem `--apply` ou aprovação embutida de migration; falha fechada com schema pendente/ilegível. Testes de build e compose-up falhos preservam rollback seguro de código.
- Esta atualização documental é **IN_PROGRESS**, não fecha NFC-EXEC-20 ou 21. CI/Gov e validação deploy da PR #291 precisam terminar SUCCESS no HEAD final; comparar scripts realmente instalados na Contabo e validar o SHA publicado antes de qualquer operação no servidor.
- `production=a3a2b3c97d26780b1e2b7581b4c93b6f07e86a70` no último auditado (reconsultar antes de promover); nenhuma migration/deploy/credencial/alteração de DB executada aqui. Worker continua fora do compose Contabo versionado; cobertura operacional BLD-06/08 ainda pendente.
