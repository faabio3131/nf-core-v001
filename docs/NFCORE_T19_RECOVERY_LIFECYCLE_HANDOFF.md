# T19 — Restituições e compensações: certificação e continuidade

## CURRENT — 26/11/2026

**CERTIFICADA TECNICAMENTE NO ESCOPO INTERNO / SANDBOX.** [PR #624](https://github.com/faabio3131/nf-core-v001/pull/624) integrada em 26/11/2026 às 00:02:26 (America/Sao_Paulo), por autorização expressa do proprietário no HEAD auditado `970701f600574a86e143ef01ebede8e7cc611488`.

| Evidência | Valor confirmado |
|---|---|
| Branch de implementação | `feat/nfcore-economy-t19-recovery-lifecycle` |
| Base anterior | `ea9349539c14c51b1efb26a95548b1d2ab316a65` |
| HEAD auditado/autorizado | `970701f600574a86e143ef01ebede8e7cc611488` |
| Merge em main | `75542dd18d7a1521a33017f80395e24285c39fe4` |
| Árvore auditada e integrada | `a78100476b06dc44192773eab9f73cb55f244290` — idêntica |
| CI pré-merge | [#45739710170](https://github.com/faabio3131/nf-core-v001/actions/runs/45739710170) SUCCESS |
| Governança pré-merge | [#45739710243](https://github.com/faabio3131/nf-core-v001/actions/runs/45739710243) SUCCESS |
| T2 efetiva fora de Draft | [#45745759948](https://github.com/faabio3131/nf-core-v001/actions/runs/45745759948) SUCCESS; log: `Bloco completo: descrição e checklist conferem.` |
| CI pós-merge push/main | [#45746332104](https://github.com/faabio3131/nf-core-v001/actions/runs/45746332104), tentativa 1, SUCCESS no merge exato |
| Governança pós-merge | [#45746332101](https://github.com/faabio3131/nf-core-v001/actions/runs/45746332101) SUCCESS |
| Production observada | `a5989e523c871c288bc2388c9508c1738082bb9a`; nenhuma promoção nesta entrega |

[Reauditoria independente Gemini R2](https://drive.google.com/file/d/1E6fY0omdULKjb6qsNWceFjvtYP9TlfLj/view) registrada na PR no mesmo HEAD: P0/P1/P2=0; achados R1 bloqueantes corrigidos. O parecer relata leitura 9/9 TXT, análise estática e simulações independentes; não relata reexecução própria de Pytest/PostgreSQL/Playwright nem recálculo de hashes binários. As execuções reais são comprovadas pelos logs GitHub acima, não inferidas do parecer.

A CI pós-merge concluiu **44/44 etapas**: **7.245 testes Python PASS, 1 SKIP, 30 testes frontend PASS, 87 Playwright E2E PASS, zero falhas**. Ruff, Mypy (489 arquivos), PostgreSQL 16.16, migrations, build, auditorias de dependências, containers, SBOM, readiness e ensaios isolados de backup/restore/transição aprovados. Skip explícito: `tests/runtime/test_p02_t02_fiscal_surfaces.py:389`, `runtime production composition requires PostgreSQL`; variante fora T19. A suíte principal usa PostgreSQL real. Não transformar esse skip em certificação da composição produtiva nem os ensaios isolados em prova de operação na Contabo.

## Fechamento documental e próxima tarefa

Branch de reconciliação: `docs/nfcore-t19-postmerge-closeout`. Escopo: somente documentação e estado das issues. O proprietário autorizou expressamente certificação pós-merge, atualização documental e liberação T20 na mesma decisão que autorizou o SHA da #624. Esta autorização não cobre implementação/merge futuro T20, deploy ou efeito fiscal real.

A reconciliação deve passar revisão do diff, validadores do plano/BUILD, CI integral e governança no HEAD exato, T2 efetiva fora de Draft, integração por PR e CI/governança pós-merge próprias. Não reutilizar a CI de `75542dd1` como CI de um novo commit documental. A PR documental e a [issue #626](https://github.com/faabio3131/nf-core-v001/issues/626) registram os SHAs finais e os runs desta etapa sem criar um ciclo de commits somente para citar o próprio hash.

Após esse gate: encerrar #622 e #623 com evidência, manter #625 aberta e marcar **T20 READY_TO_START / NOT_STARTED** na #626. [Handoff T20](NFCORE_T20_ACCOUNTING_DOSSIER_HANDOFF.md). A liberação é para iniciar a tarefa seguinte; nenhum gerador T20 está implementado por esta entrega. T21 continua bloqueada pela certificação T20 e pelos cinco refinamentos #625. Preservar #613/#616, Master v4.1, 18 etapas ERP e 59 IDs históricos.

### Reconciliação #622 e riscos preservados em #625

| Item #622 | Evidência integrada | Limite preservado |
|---|---|---|
| T18-R2-P3-01 | `EconomyStore.append_credit_entry` usa `strip().casefold()` nos dois identificadores; `test_postgres_legacy_reserved_prefixes_normalized` cobre seis combinações | Formato completo e vínculo único de movimentos T19 continuam no novo item #625 |
| T18-R2-P3-02 | `test_postgres_reconciliation_independently_rejects_cross_tax_receipt` testa diretamente Cofins→PIS/competências por recibo e hash; regressões T18 cobrem estorno parcial/integral | Não representa reconhecimento real de crédito |
| T18-R2-P3-03 | `RecoveryCaseService` revalida sessão/CSRF/RBAC/contador/MFA e identidade por operação; lock canônico mantido até commit; testes de concorrência, ambiguidade e leitura histórica | Contenção global e escala exigem solução/benchmark #625 antes da T21/Portal |

A [#625](https://github.com/faabio3131/nf-core-v001/issues/625) permanece OPEN com cinco P3 internos: formato/vínculo de movimentos; capacidade prospectiva também na escrita avulsa T18; política de resíduo/SELIC; revaloração mensal e saída revisada de restituição deferida; contenção entre tenants e limites de varredura. Não são dependências externas nem motivos para ocultar bloqueios. Não bloqueiam a T20 documental após fechamento certificado da T19, mas todos devem estar resolvidos e testados antes da exposição HTTP/Portal T21 ou operação comercial/fiscal real.

### Auditoria da continuidade histórica

O nome histórico `kordena-fiscal-engine-v2` resolve ao mesmo repositório `nf-core-v001`, ID `1366374504`. CL-01 (#46) e CL-02–CL-07 (#47–#53, checkpoints #54/#56–#61) estão integradas; #55 consolidou a cadeia em `57812960ae09013a4540cfb01730facf47c37235`, ancestral da main T19. A PR #53 não está mais aberta. Não repetir esses blocos por causa de textos antigos que ainda dizem Draft; não confundir sua integração com homologação externa.

## Escopo funcional certificado

DoD Master: gestão de PER/DCOMP, compensação administrativa e restituição em sandbox/mock, estados solicitado/transmitido/homologado ou indeferido, reservas, baixas, liberações, estornos, reconciliação, rejeições, prazos e alertas. Testar duplicados, fora de ordem, falhas e reprocessamentos.

## Autoridade e arquitetura

O diário T18/T01 é a única autoridade de valores; T19 persiste apenas estado e links de eventos exatos no mesmo PostgreSQL/RLS. A transação tem lock T14/T18 e savepoint por caso. Lotes geridos pelo T19 não podem ser movimentados pela CLI T18. Extensão compatível: novo saldo restituído aparece após primeiro evento de pagamento; projeções históricas anteriores permanecem byte-equivalentes. Não há novo banco, migration, fila ou motor de tributos. Sem API HTTP pública (T21 integra as operações do serviço). Todos os resultados têm simulation_only=true, crédito não reconhecido e realized_cents=null.

Estados: solicitado reserva; rejeição de transporte mantém solicitado e reserva, permite reprocessamento; transmissão da compensação baixa para compensado simulado (condicional), restituição mantém reserva; homologação da compensação não duplica baixa; deferimento de restituição NÃO é pagamento; pagamento simulado baixa para restituído; indeferimento reverte compensação para reserva ou mantém reserva da restituição, sem disponibilizar automaticamente; cancelamento anterior à transmissão libera; reversão de compensação homologada ou restituição paga retorna à reserva; decisão revisada posterior libera mediante revalidação atual T17 ou invalida (liberação e estorno atômicos). Novo caso exige saldo e evidência próprios; alvo ativo e referências de evidência não são duplicados. Eventos imutáveis, versão otimista e idempotência retornam status histórico e atual. Alertas explícitos por prazo revisado, inclusive vencido, sem presumir homologação tácita ou contagem legal automática.

Proveniência T17/T16/T15 é recomposta no pedido, transmissão e liberação posterior a indeferimento. Para PIS/Cofins por indébito em DARF, principal e SELIC da parcela são calculados pelo federal_interest da T17; não aceitar SELIC isolada ou estimativa arbitrária. Se valor do lote ou identidade fiscal mudar, novo compromisso falha fechado. No pagamento simulado, valor recalculado no mês de pagamento deve corresponder à reserva; diferença exige revisão/revaloração explícita, nunca baixa silenciosa de valor divergente. ICMS de escrituração só em roteiro administrativo simulado, sem SELIC, não prova crédito restituível. Rotas, débito alvo e fundamento são dados revisados; a rota PER/DCOMP só aceita PIS/Cofins suportados no recorte T17. Não inferir elegibilidade real, integralidade de tributos/UFs, autoridade de fornecedor ou acesso a serviço externo. Limites de lote/evento, replays, hashes e reconciliação rejeitam adulteração e órfãos.

Fontes oficiais consultadas em 25/11/2026: Lei 9.430/1996 art. 74 §§ 2,5,7 (https://www.planalto.gov.br/ccivil_03/leis/l9430compilada.htm); IN RFB 2.055/2021 arts. 64–67, 148–149 (https://normas.receita.fazenda.gov.br/sijut2consulta/link.action?idAto=122002); RFB consulta processamento e comunicações (https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/restituicao-ressarcimento-reembolso-e-compensacao/consulta-processamento); RFB pagamento indevido DARF (https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/restituicao-ressarcimento-reembolso-e-compensacao/creditos/pagamento/darf/como-solicitar-ou-compensar-o-credito). Homologação de DCOMP, deferimento PER e pagamento têm efeitos distintos. O prazo de 5 anos de homologação da DCOMP e ciência/prazos administrativos exigem revisão de eventos, calendário e hipóteses concretas; não geram efeito automaticamente. A construção interna não depende de credencial externa.

## Fronteira humana e #622

RecoveryCaseService recebe token de sessão/CSRF, deriva tenant e escopo, exige AUDIT_READ, contador designado por unidade e step-up MFA recente para escrita. Resolve CNPJ/perfil/regime históricos pelo control plane e valida perfil ativo/ambiente. Guard SHARE NOWAIT sobre unidades, perfis e configurações canônicas mantém predicados (inclusive inserção de segunda unidade) estáveis até commit da transação econômica; runtime econômico continua com RLS e menor privilégio. Esta solução conservadora é para sandbox: lock de tabela tem custo de contenção, deve ser medido e refinado antes de operação real/Portal em escala. Leitura histórica permite unidade ainda registrada, mesmo com ambiente desabilitado, com permissão e histórico estável, sem autorizar escrita. Autenticação é reconfirmada antes do serviço; nenhuma prova VerifiedCreditUnit é aceita de JSON. CLI usa serviços de identidade e MFA existentes. Testes usam sessões sintéticas, relógio e step-up controlados, não falsificam autorização fiscal real. #622: prefixos legado normalizados e testes diretos de guarda de recibos e reconciliação cruzada. Os três itens foram verificados no escopo interno integrado; fechar #622 após o gate documental acima. Autoridade/concorrência produtiva e volumetria continuam gates #625 antes de expor T21.

## Uso interno

python scripts/nfcore_recovery_lifecycle.py --unit UNIDADE --post evento.json
ou --report --competence AAAA-MM-01. Exige NFCORE_ENVIRONMENT development/test/staging, NFCORE_ECONOMY_ENABLED=true, sessão e CSRF legítimos em NFCORE_T19_SESSION_TOKEN / NFCORE_T19_CSRF_TOKEN, MFA configurado; não registrar tokens. JSON ReviewedEvent: event (Terms, action, expected_version, request_id, opinion_reference, professional_reference, evidence_reference, due_on, source_version/source_digest para request/transmit/release), evidence SHA256 e base64 do JSON exatamente {scope, issuer_cnpj, simulation_only:true, event}. Limite envelope 64 KiB, evidência 16 KiB. A data do evento deriva do relógio de servidor São Paulo. Resultados simulados, nunca chamar e-CAC ou banco. Não expor o serviço diretamente a clientes sem composição de API segura.

## Gates

Gates técnicos da T19 aprovados no SHA integrado conforme CURRENT acima. O fechamento documental tem CI própria; T20 é liberada somente quando essa reconciliação estiver integrada e certificada. T21 requer T20 certificada e #625 resolvida. Nenhuma transmissão, compensação, restituição ou deploy real foi autorizado.

Regressões adicionais: roteiro administrativo ICMS sem SELIC (sandbox), parcela federal com juros recalculados e limite de saldo, ambiguidade de CNPJ dentro do serviço e tentativa de encadear evento falso a lançamento já utilizado. A soma de parcelas sujeita a arredondamento nunca pode exceder cada componente do lote; divergência de saldo/valoração exige revisão, sem inventar ajuste tributário.

## HISTÓRICO — correção das regressões T19 (25/11/2026)

PR #624 Draft, issue #623. CI integral #45728411909 no HEAD `3e1472ff0f1d848922b2094830b8271f0618a0d5`: FAILURE no Pytest, 7.234 PASS, 2 FAIL (sessão expirada no teste de corte T17 e exceção de integridade encapsulada), 1 SKIP fora T19. Ruff/Mypy e governança #45728411891 SUCCESS; frontend, E2E, Docker e gates seguintes não executados. A correção preserva a expiração canônica (novo assert negativo e emissão de sessão/CSRF válida pelo mesmo serviço de identidade sintético), preserva FiscalValidationError específica na reconciliação e continua convertendo erros estruturais em falha fechada. Nenhuma supressão de teste, mudança de TTL, migration ou workflow. Revalidar os dois testes PostgreSQL na nova CI integral do HEAD da PR; não há execução local PostgreSQL comprovada. Gemini somente após CI integral verde no SHA exato; T2 efetiva, autorização específica, certificação pós-merge e fechamento continuam obrigatórios. T19 IMPLEMENTED_NOT_CERTIFIED; T20 bloqueada. Master v4.1 e produção preservados.

## HISTÓRICO — correção pós-auditoria Gemini (25/11/2026)

Parecer independente do HEAD 93bb2d9e180d4e0cbebe16b2951208e502ec7408, árvore aacc5c5b1e36627467c63f8d662ef13226a0cfd8: REPROVADO, P0=0/P1=1/P2=3/P3=4. CI #45730534528 SUCCESS (44/44, 7236 Python PASS, 1 SKIP fora T19, 87 Playwright), governança #45730534536 SUCCESS; não substituem auditoria. [Parecer original](https://drive.google.com/file/d/1c6frBHtAurD8dcEbylAoMtDd5ooroYtP/view). Auditor relatou leitura integral e simulações independentes, não execução Pytest/PostgreSQL ou recálculo binário independente.

Correções candidatas: P1-01 restringe ICMS escritural à compensação administrativa simulada sem SELIC, restituição somente indébito federal PIS/Cofins suportado, validação no domínio/serviço/replay; P2-01 valida capacidade prospectiva de casos/eventos e lançamentos antes de postar, sob lock e savepoint existentes, preservando replay e leitura; P2-02 homologação de compensação sem prazo/alerta, deferimento de restituição mantém acompanhamento; P2-03 acrescenta regressões de fronteiras e CLI subprocess com sessão PostgreSQL e MFA real sintético (sem mock do gate). P3-03 normaliza detecção de prefixo e rejeita variante não canônica. Nenhuma regra nova de crédito real, migration, workflow ou segunda autoridade.

P3-01 resíduo de centavos e P3-02 revaloração mensal/encerramento de restituição deferida exigem decisão contábil/fiscal explícita e testes de conservação; não ajustar artificialmente centavos nem simular indeferimento para contornar revaloração. P3-04 contenção global SHARE NOWAIT requer benchmark e solução governada antes de T21/Portal e operação real. Registrar/acompanhar os três riscos residuais na issue #623, com gate obrigatório antes da exposição comercial; não declarar cobertura externa. Limites finitos protegem integridade e leitura, mas exigem estratégia de escala antes de Portal. Correções implementadas, ainda NÃO CERTIFICADAS: execução focal local/PostgreSQL não comprovada; exigir CI integral no novo HEAD, rodada 02 Gemini, completude T2 efetiva, autorização de merge específica, CI pós-merge e fechamento. T20 bloqueada até certificação da T19. Master v4.1, #613/#616/#622, main e production preservados.
