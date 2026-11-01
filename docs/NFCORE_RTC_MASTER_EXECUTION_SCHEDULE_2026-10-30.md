# FM NFCORE V1 — CRONOGRAMA MESTRE RTC 2026→TRANSIÇÃO

**Abertura:** 30/10/2026 · **Status CURRENT (reconciliado em 01/11/2026):** EM EXECUÇÃO, entregas RTC-00/01/02/03 e RTC-09 parciais integradas; RTC-04 em PR #289 ainda não integrada; RTC-05..08/10/11 pendentes, RTC-12 bloqueada externamente. **Base de auditoria:** `main@d3d1002a54b7`, `production@d7cf5e4d58cc`. Histórico de abertura preservado no checkpoint, não usar como CURRENT.  
**Norma:** `AGENTS.md` + `docs/NFCORE_RTC_REFORMA_TRIBUTARIA_MASTER_2026-10-30.md`; esta é uma frente *independente*, não altera checkboxes do cronograma das 59 tarefas nem o ledger BUILD.

## Regras gerais de execução

Cada WP: auditar CURRENT e fonte oficial → mapear autoridade/camadas → congelar recorte → desenvolver no módulo atual → fixtures oficiais verificadas + cenários negativos → Ruff/mypy/pytest → CI/Governança do HEAD → documentação de evidência → PR/merge apenas com autorização aplicável → pós-merge. **Sem segunda API, segundo Tax Rule Engine, schema paralelo ou frontend novo.** Não avançar a etapa dependente se o predecessor falhar; outras frentes independentes podem continuar em branch isolada. Não presumir homologação real nem deploy. Toda regra fiscal requer fonte, versão, publicação, vigência e teste.

| WP | Escopo/entrega | Dependência | Critério objetivo de aceite | Estado |
|---|---|---|---|---|
| **RTC-00** | Inventário completo de domínios/migrations/APIs/XML/Portal; catálogo de fontes, versões e baseline datada | `main` real, normas | Relatório Current→Target e pins oficiais sem ativação; testes de baseline | IMPLEMENTED_PARTIAL — #267 MERGED; inventário/gate de aceite global pendente |
| **RTC-01** | Governança normativa: NTs/ITs tabelas CST, cClassTrib, alíquotas, XSD, dados oficiais, SHA/versionamento e watcher governado | RTC-00 | Artefatos originais verificáveis, comparação de versões, change review, rollback; nenhuma mudança autoativa | IMPLEMENTED_PARTIAL — #268/#270 MERGED; catálogo/watcher/rollback normativo completos não certificados |
| **RTC-02** | Modelo fiscal do estabelecimento: CRT × regime IRPJ/CSLL, opção Simples, histórico temporal, competências, jurisdição/atividade | RTC-00 | Autoridade de dados única; validade temporal; tenant/unidade/RBAC e anti-spoofing; migração só se justificada | IMPLEMENTED_PARTIAL — #269/#271/#272 MERGED; matriz integral e PG/RBAC por todas células não certificada |
| **RTC-03** | Matriz nacional de incidência e classificação: NCM/NBS, CST IBS/CBS, cClassTrib, benefício, operação, destino, exceções | RTC-01/02 | Resolução determinística pelo `TaxRuleEngine`, ausência/empate fail-closed, fonte e versão por decisão | IMPLEMENTED_PARTIAL — #273/#274/#280 MERGED; NCM/NBS, benefícios e exceções ainda incompletos |
| **RTC-04** | Calculadora transacional IBS UF/município + CBS + IS, reduções, créditos, regimes e eventos de ajuste aplicáveis | RTC-03 | Cálculos Decimal/rounding oficiais, Golden Cases verificáveis, sem taxas fictícias ou IA como autoridade | IMPLEMENTED_NOT_MERGED — PR #289 OPEN; CI/Gov SUCCESS no HEAD 61f8bdf; prévia sintética, não cálculo oficial |
| **RTC-05** | Coexistência e transição: ICMS/ISS/IPI/PIS/Cofins com IBS/CBS/IS e vigências 2026–2033 conforme legislação atualizada | RTC-03/04 | Casos de antes/depois vigência, preservação de snapshots e histórico, sem desativar tributos legados antecipadamente | PENDING |
| **RTC-06** | NF-e 55 e NFC-e 65: serializadores, leiaute NT 2025.002 versão vigente, XSD, assinatura, totais, rejeições, contingência | RTC-03/04/05 | XML golden oficial, schemas oficiais, assinatura e fluxo canônico de emissão/consulta/cancelamento; rollback no teste | PENDING |
| **RTC-07** | NFS-e nacional e municipais pertinentes: DPS/NFS-e, NBS/códigos, IBS/CBS, serviços, eventos e regras municipal/nacional | RTC-03/04/05 | Leiaute nacional vigente e adapters suportados testados por município/célula; sem declarar universalidade | PENDING |
| **RTC-08** | Casos especiais: export/import, combustíveis/monofásico, créditos, devoluções, regime especial, operações não padronizadas | RTC-03..07 | Matriz de operações cobertas/não cobertas, sem fallback silencioso, provas legais e técnicas por célula | PENDING |
| **RTC-09** | API/application/Portal: cadastro e revisão de regime, visualização de cálculos/classificação e motivo de bloqueio | RTC-02..08 | Mesmo Portal/API, sessão/RBAC/CSRF, escopo, sem cálculo autoritativo no browser; E2E Web real interno | IMPLEMENTED_PARTIAL — #275/#278 MERGED; classificação/cálculos/erros/E2E completos pendentes |
| **RTC-10** | Persistência, ledger, auditoria, replay, idempotência, workers, performance, migrações, DR | RTC-03..09 | Teste PostgreSQL descartável, concorrência, rollback, schema convergence, snapshots imutáveis | PENDING |
| **RTC-11** | Certificação interna ponta a ponta, matrix regimes × operações × documentos × período × UF/município | RTC-01..10 | Todos os casos obrigatórios aplicáveis evidenciados + CI/Gov verde sem gaps ocultos | PENDING |
| **RTC-12** | Homologação oficial por provedor/jurisdição/operação, pilotos limitados, observabilidade, certificação de produção e Go/No-Go | RTC-11 + ações externas/humanas | Request/response oficiais + vault + ambiente + performance + runbooks + rollback e GO humano explícito | BLOCKED_EXTERNAL |

## Microentregas implementáveis com autonomia controlada

### Bloco A — foundations, sem alterar operação produtiva
- A1. Baseline oficial datada com provenance/versão (RTC-00; JSON apenas de referência).
- A2. Teste programático que carrega pins via `RegulatoryBaseline` já existente; detectar ausência, duplicata e fonte inválida antes de aceitar snapshot.
- A3. Inventário de classes existentes e casos antigos (CRT/regime, TaxRuleEngine, RTC policy resolver, emissão por família e mappings).
- A4. Descarregar/canonicalizar apenas os artefatos oficiais necessários, com hash e changelog, sem inventar tabela.
- A5. Criar fixtures de conformidade sob `tests/` para versões oficiais, sem ligação com produção.
- **Gate A:** modelo atual preservado; CI dos candidatos verde; nenhuma migração, provider, cobrança, produção ou deploy.

### Bloco B — regra e documentação eletrônica
- B1. Tax regime dimension audit — não colapsar Simples/Presumido/Real em CRT; decidir dimensionamento de IRPJ só após inspeção de contratos.
- B2. cClassTrib/CST e códigos vigentes por tabela oficial, regra de vigência e classificação context-aware.
- B3. IBS/CBS/IS calculators somente com fórmulas normativas exatas, efeitos de créditos e cálculos componíveis.
- B4. Adequar NF-e/NFC-e ao leiaute vigente com XSD, totais e campos condicionais.
- B5. Adequar NFS-e nacional aos layouts públicos aplicáveis e municípios selecionados.
- **Gate B:** casos oficiais de exemplo e contraprova; conservar XML histórico; snapshot auditável.

### Bloco C — integração funcional
- C1. Composição segura de aplicação e persistência/Worker já existentes.
- C2. Portal Web: regime fiscal validado, detalhes de tributação, erros, ajustes e períodos.
- C3. E2E de fluxos reais internos por regime em PostgreSQL descartável + navegador.
- C4. Regressão total de segurança e isolamentos.
- **Gate C:** sem botão morto, nenhum sistema paralelo, CI completa e evidência reproduzível.

### Bloco D — externo/homologação
- D1. Escolha/aprovação humana de provider/UF/municípios, credenciais/certificados, contas e ambientes.
- D2. Homologação por célula real, matriz de retorno oficial, XML assinado, rejeição e eventos.
- D3. Staging/produção, DNS/TLS/segredos, runbook, backup/restore, DR, piloto controlado.
- D4. Go/No-Go humano. **Sempre BLOCKED_EXTERNAL até evidência**, sem promoção automática.

## Matriz detalhada de testes obrigatórios

1. **Identidade:** test-tax-regime mismatch, CRT inválido, mudança retroativa, estabelecimento divergente, regime desconhecido.
2. **Regras:** inexistente, empate, benefício incompatível, classificação sem tabela, tabela vencida, NCM/NBS incompatível, mudança de versão, fuso/competência.
3. **Cálculo:** bases/tributos/arredondamento exatos, redução, crédito, imposto seletivo, totalização e conciliação, regras com alíquotas zero ou não aplicáveis quando oficiais.
4. **Documentos:** NF-e, NFC-e, NFS-e, XML/XSD por versão, campos condicionais, DANFE/representação quando necessário, assinatura, contingência e consulta.
5. **Operações:** venda, devolução, cancelamento, retificação/eventos, prestação, retorno, operações diferenciadas aplicáveis.
6. **Temporalidade:** 2026, entrada de obrigatoriedade Simples em 2027, cada marco legal de transição subsequente.
7. **Segurança:** forged tenant/unit/provider/aliquota, cross-tenant, RBAC, CSRF, replay/nonce, PII/segredos e audit trail.
8. **Integração:** Portal→API→Application→TaxRuleEngine→UoW/DB→Worker→Adapter sob bloqueio externo governado.
9. **Resiliência:** timeout/unknown, recuperação, concorrência, idempotência, rollback, fresh migration vs upgrade, backup/restore governados.
10. **Conformidade:** golden files vinculados a artefato oficial SHA e versão; rejeição real somente homologação externa.

## Tracker operacional de abertura (HISTÓRICO; supersedido pelo CURRENT abaixo)

| Entrega | Código/artefato | Estado | Evidência |
|---|---|---|---|
| Branch isolada | `feat/nfcore-rtc-reforma-tributaria-foundation-20261030` | CREATED | GitHub branch criada a partir de `c2d29a45` |
| Pin normativo | `config/rtc/official-baseline-2026-10-30.json` | IMPLEMENTED_NOT_CI_CERTIFIED | metadata fontes oficiais, não ativa cálculo |
| Testes de baseline | `tests/compliance/test_rtc_official_baseline_20261030.py` | IMPLEMENTED_NOT_CI_CERTIFIED | testes adicionados; aguardar CI do HEAD |
| Documento mestre | `docs/NFCORE_RTC_REFORMA_TRIBUTARIA_MASTER_2026-10-30.md` | DRAFTED | fonte e decisões explicitadas |
| Cronograma | este arquivo | DRAFTED | WPs RTC-00..12; sem gates externos fictícios |
| Alteração de TaxRuleEngine/RTC runtime | Nenhuma | NOT_STARTED | preservar atual até mapear delta |
| Merge/main/deploy/migration | Nenhum | NOT_AUTHORIZED | não executar por reflexo da branch |

**Próximo passo CURRENT (01/11/2026):** preservar RTC-00..03 e RTC-09 já integrados; resolver somente lacunas normativas comprovadas que bloqueiem uma célula RTC-04, concluir a revisão da PR #289 sem promover prévia sintética à emissão, e desenvolver o cálculo oficial por célula validada. Em seguida RTC-05 → RTC-06/07 → RTC-08 → complemento RTC-09/RTC-10 → RTC-11 → RTC-12 externo. A autorização BUILD não autoriza merge RTC, nem produção.

**Evidências e anti-retrabalho:** `docs/checkpoints/NFCORE_RTC_CURRENT_RECONCILIATION_2026-11-01.md` (PRs, HEADs, CI, riscos e critérios faltantes). Esta tabela substitui o estado operacional da abertura; se divergir, auditar GitHub atual, nunca a memória.
