> **CURRENT 02/11/2026 — CONSULTA GITHUB:** `main@bc3fae72c8f4d5b18a4a2bdaa63c3f3d137582bd`, RTC-04 B8-H #326, B9 #325 e reconciliação #327 MERGED. CI pós-merge #1503 SUCCESS; Governança #934 SUCCESS. RTC-04 B10, PR #328 DRAFT, acrescenta verificação fail-closed de artefatos de alíquotas e política candidata de arredondamento publicados após a captura do `RegulatoryBaseline`, com dois testes sintéticos de regressão. CI #1504 e Gov #935 ainda exigem resultado terminal no HEAD final da PR. Não certificar B10 nem RTC-04 global antes dos gates; não autoriza XML, cálculo fiscal emitível, homologação, produção ou Contabo.

> **CHECKPOINT CURRENT 02/11/2026 (supera o cabeçalho histórico abaixo):** RTC-04 B7 #322 e B8 #324 integradas; `main@c765146cb2a7e7bb788de1b05e6f4303ab8e40eb`. Governança pós-merge #926 SUCCESS, CI pós-merge #1495 IN_PROGRESS na verificação, portanto B8 IMPLEMENTED_MERGED_AWAITING_POSTMERGE_CI. B8 exige mesmo pin de catálogo/alíquota e guarda temporal da prévia; seus testes são sintéticos, NÃO homologação. B8-H PR #326 DRAFT busca vincular source_reference; B9 tributária 2027–2028 PR #325 DRAFT em frente paralela ao witness, ainda sem merge. RTC-04 permanece IMPLEMENTED_PARTIAL, cálculo non-authoritative; RTC-05..08/10/11 pendentes, RTC-12 BLOCKED_EXTERNAL. Fontes IT 2025.002 v1.71/NT 2026.005 v1.00 ainda REFERENCE_ONLY até PDF/tabelas/XSD/hash/fonte/vigência e golden cases originais auditados. Não alterar produção/Contabo.

# FM NFCORE V1 — CRONOGRAMA MESTRE RTC 2026→TRANSIÇÃO

**Abertura:** 30/10/2026 · **CURRENT confirmado em 02/11/2026:** `main@2e388071af68c63d63cdbf258b58c7fe4113f7d5`; CI #1466 e Governança #897 pós-merge SUCCESS. RTC-00/01/02/03 e RTC-09 parcialmente integrados; RTC-04 PRs #289/#307/#308/#309/#310/#311/#312 **MERGED**, ainda **IMPLEMENTED_PARTIAL / NON_AUTHORITATIVE**, sem emissão fiscal RTC autorizada. RTC-05..08/10/11 pendentes, RTC-12 bloqueada externamente. Para continuidade, **RTC-04 (Reforma Tributária, inclusive aplicabilidade por regime e Simples Nacional) é a frente prioritária**, não recomeçar BLD-03..08. `production` e revisão realmente implantada na Contabo não foram auditadas nesta reconciliação; nenhuma operação produtiva autorizada.
**Norma:** `AGENTS.md` + `docs/NFCORE_RTC_REFORMA_TRIBUTARIA_MASTER_2026-10-30.md`; esta é uma frente *independente*, não altera checkboxes do cronograma das 59 tarefas nem o ledger BUILD.

## Regras gerais de execução

Cada WP: auditar CURRENT e fonte oficial → mapear autoridade/camadas → congelar recorte → desenvolver no módulo atual → fixtures oficiais verificadas + cenários negativos → Ruff/mypy/pytest → CI/Governança do HEAD → documentação de evidência → PR/merge apenas com autorização aplicável → pós-merge. **Sem segunda API, segundo Tax Rule Engine, schema paralelo ou frontend novo.** Não avançar a etapa dependente se o predecessor falhar; outras frentes independentes podem continuar em branch isolada. Não presumir homologação real nem deploy. Toda regra fiscal requer fonte, versão, publicação, vigência e teste.

| WP | Escopo/entrega | Dependência | Critério objetivo de aceite | Estado |
|---|---|---|---|---|
| **RTC-00** | Inventário completo de domínios/migrations/APIs/XML/Portal; catálogo de fontes, versões e baseline datada | `main` real, normas | Relatório Current→Target e pins oficiais sem ativação; testes de baseline | IMPLEMENTED_PARTIAL — #267 MERGED; inventário/gate de aceite global pendente |
| **RTC-01** | Governança normativa: NTs/ITs tabelas CST, cClassTrib, alíquotas, XSD, dados oficiais, SHA/versionamento e watcher governado | RTC-00 | Artefatos originais verificáveis, comparação de versões, change review, rollback; nenhuma mudança autoativa | IMPLEMENTED_PARTIAL — #268/#270 MERGED; catálogo/watcher/rollback normativo completos não certificados |
| **RTC-02** | Modelo fiscal do estabelecimento: CRT × regime IRPJ/CSLL, opção Simples, histórico temporal, competências, jurisdição/atividade | RTC-00 | Autoridade de dados única; validade temporal; tenant/unidade/RBAC e anti-spoofing; migração só se justificada | IMPLEMENTED_PARTIAL — #269/#271/#272 MERGED; matriz integral e PG/RBAC por todas células não certificada |
| **RTC-03** | Matriz nacional de incidência e classificação: NCM/NBS, CST IBS/CBS, cClassTrib, benefício, operação, destino, exceções | RTC-01/02 | Resolução determinística pelo `TaxRuleEngine`, ausência/empate fail-closed, fonte e versão por decisão | IMPLEMENTED_PARTIAL — #273/#274/#280 MERGED; NCM/NBS, benefícios e exceções ainda incompletos |
| **RTC-04** | Calculadora transacional IBS UF/município + CBS + IS, reduções, créditos, regimes e eventos de ajuste aplicáveis | RTC-03 | Cálculos Decimal/rounding oficiais, Golden Cases verificáveis, sem taxas fictícias ou IA como autoridade | IMPLEMENTED_PARTIAL — PRs #289/#307/#308/#309/#310/#311/#312 MERGED; composição B1+B2+B3 final em main `2e388071` com CI #1466/Gov #897 SUCCESS. Prévia `authoritative=False`: incidência estrita, base art. 12, referência nominal 2026 e candidato de arredondamento pinado; ainda sem fórmulas, golden XML/XSD e elegibilidade oficial suficiente para emissão. |
| **RTC-05** | Coexistência e transição: ICMS/ISS/IPI/PIS/Cofins com IBS/CBS/IS e vigências 2026–2033 conforme legislação atualizada | RTC-03/04 | Casos de antes/depois vigência, preservação de snapshots e histórico, sem desativar tributos legados antecipadamente | PENDING |
| **RTC-06** | NF-e 55 e NFC-e 65: serializadores, leiaute NT 2025.002 versão vigente, XSD, assinatura, totais, rejeições, contingência | RTC-03/04/05 | XML golden oficial, schemas oficiais, assinatura e fluxo canônico de emissão/consulta/cancelamento; rollback no teste | PENDING |
| **RTC-07** | NFS-e nacional e municipais pertinentes: DPS/NFS-e, NBS/códigos, IBS/CBS, serviços, eventos e regras municipal/nacional | RTC-03/04/05 | Leiaute nacional vigente e adapters suportados testados por município/célula; sem declarar universalidade | PENDING |
| **RTC-08** | Casos especiais: export/import, combustíveis/monofásico, créditos, devoluções, regime especial, operações não padronizadas | RTC-03..07 | Matriz de operações cobertas/não cobertas, sem fallback silencioso, provas legais e técnicas por célula | PENDING |
| **RTC-09** | API/application/Portal: cadastro e revisão de regime, visualização de cálculos/classificação e motivo de bloqueio | RTC-02..08 | Mesmo Portal/API, sessão/RBAC/CSRF, escopo, sem cálculo autoritativo no browser; E2E Web real interno | IMPLEMENTED_PARTIAL — #275/#278 MERGED; classificação/cálculos/erros/E2E completos pendentes |
| **RTC-10** | Persistência, ledger, auditoria, replay, idempotência, workers, performance, migrações, DR | RTC-03..09 | Teste PostgreSQL descartável, concorrência, rollback, schema convergence, snapshots imutáveis | PENDING |
| **RTC-11** | Certificação interna ponta a ponta, matrix regimes × operações × documentos × período × UF/município | RTC-01..10 | Todos os casos obrigatórios aplicáveis evidenciados + CI/Gov verde sem gaps ocultos | PENDING |
| **RTC-12** | Homologação oficial por provedor/jurisdição/operação, pilotos limitados, observabilidade, certificação de produção e Go/No-Go | RTC-11 + ações externas/humanas | Request/response oficiais + vault + ambiente + performance + runbooks + rollback e GO humano explícito | BLOCKED_EXTERNAL |

## RTC-04 — incremento após B3: opção IBS/CBS do Simples Nacional (02/11/2026)

- **Current de código:** CRT=1/2/3/4 permanece no `FiscalProfile`; regimes federais são declarações explícitas em `tax/regimes.py`; o preview nominal do regime normal 2026 segue recusando Simples Nacional.
- **Delta desta entrega:** `SimplesIbsCbsElection` e `resolve_simples_ibs_cbs_mode` no módulo canônico de declarações, com vínculo a tenant/unidade/host, ID+versão do perfil, fonte, vigência, períodos sem sobreposição e distinção entre recolhimento unificado e apuração regular do IBS/CBS, sem criar TaxRuleEngine paralelo.
- **Base normativa:** LC 214/2025 art. 41 §§2–4, https://normas.leg.br/?urn=urn:lex:br:federal:lei.complementar:2025-01-16;214!art41 ; Receita Federal 11/08/2026 https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/agosto/cgsn-atualiza-regras-do-simples-nacional-para-adequacao-a-reforma-tributaria-do-consumo ; Receita Federal 14/08/2026 https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/agosto/simples-nacional-nfs-e-nacional-sera-obrigatoria-para-me-e-epp-a-partir-de-1o-de-novembro-de-2026 .
- **Temporalidade:** a resolução dos modos IBS/CBS do Simples **não** autoriza cálculo RTC em 2026; a partir de 01/01/2027 exige evidência explícita revisada do enquadramento/opção no escopo e período. A inexistência de opção formal pode levar ao regime simplificado conforme norma, mas este contrato exige evidência de enquadramento/não-opção; **não cria opção formal perante o CGSN**. A NFS-e nacional obrigatória para ME/EPP abrangidas a partir de 01/11/2026 é obrigação **separada** e não fica dispensada por esse resultado.
- **Gate restante:** conexão persistente da declaração à fonte autorizada, revisão de opções/competências específicas, regras de cálculo por células normativas e golden cases; `authoritative=False` na prévia fiscal; nenhum imposto/aliquota/valor, XML, transmissão, migration, deploy ou homologação criados aqui.
- **Relação com BLD:** não retomar onboarding/trial/site/checkout antes da conclusão do produto; integrações comerciais externas seguem pendentes por decisão.

### RTC-02/04 — coerência CRT × regime federal (02/11/2026)

- **Causa concreta:** `FederalRegimeDeclaration` exigia as duas dimensões, mas permitia pares contraditórios (ex.: CRT=3 normal + regime federal Simples Nacional), mesmo após validar escopo/perfil. Não confundir a identidade do CRT com a escolha independente Lucro Real/Presumido dentro do regime normal.
- **Implementação incremental:** validação no **mesmo** `tax/regimes.py`, preservando o `FederalRegimeDeclaration` canônico. CRT=1/2/4 exige classificação federal Simples; CRT=3 admite Lucro Real ou Presumido explicitamente declarado. O CRT=2/4 continua distinto para cálculo ICMS/ISS/MEI e **não** recebe regras fiscais de CRT=1 automaticamente.
- **Fonte técnica oficial:** NT 2024.001 CRT MEI, https://www.nfe.fazenda.gov.br/Portal/exibirArquivo.aspx?conteudo=kIiniiSkpKc%3D, e leiaute CRT=1/2/3/4; não cria alíquotas ou habilita XML RTC.
- **Evidência de código:** testes preservam os três regimes federais com CRT coerente e acrescentam rejeição de combinações contraditórias. O resultado não é homologação oficial nem fechamento do RTC-02/04 integral.

### RTC-04 B4 — bloqueio de regra genérica e baseline SVRS (candidato 02/11/2026)

**Código construído nesta PR:** a função `calculate_2026_nominal_reference_preview` passa a usar `resolve_strict_rtc_2026_incidence_candidate` do mesmo `TaxRuleEngine` já utilizado em B3. A consequência funcional é que a prévia isolada, inclusive quando usada pela base art. 12, não aceita mais regras `wildcard` sem UF, CRT, modelo, operação, destinatário e NCM explícitos. Não altera fórmula, alíquota, serializador ou emissão. Os testes têm casos de bloqueio e os cenários existentes são atualizados para usar seletor específico.

**Fontes oficiais consultadas em 02/11/2026:** [SVRS NF-e/Documentos](https://dfe-portal.svrs.rs.gov.br/NFe/Documentos) registra **NT 2026.005 v1.00 (Simples Nacional)** e **IT 2025.002 v1.71** publicadas em **30/10/2026**; o catálogo CST/cClassTrib da RT foi atualizado na mesma data. O arquivo `config/rtc/official-baseline-2026-10-30.json` registra apenas esses metadados, **sem baixar/adotar tabelas, PDF, XSD, SHA originais ou ativar regras**. A tabela de créditos presumidos mantém referência histórica 1.70 até verificação documental própria. `REFERENCE_ONLY_NOT_PRODUCTION_APPROVED` e `authoritative=False` permanecem.

**Aceite do delta:** CI/Gov desta PR + pós-merge; ausência de cálculo baseado em wildcard; nenhuma mudança produtiva. **Ainda pendente:** obtenção/revisão de PDFs/XSD e tabela cClassTrib 1.71 com hashes e matriz de vigência/validações, golden cases por célula do Simples, regras especiais, reduções, créditos, IS e demais etapas RTC-04/05. Nunca interpretar metadado de publicação como vigência operacional da SEFAZ.

### RTC-04 B5 — CRT=2 na escolha IBS/CBS com anti-replay (candidato 02/11/2026)

**Lacuna de implementação:** o resolvedor de modo IBS/CBS criado em B3/B4 (PR #316) admitia apenas `TaxRegimeCode.SIMPLES_NACIONAL` (CRT=1), embora o perfil fiscal possua também `SIMPLES_NACIONAL_EXCESS_SUBLIMIT` (CRT=2). No mesmo contrato canônico `SimplesIbsCbsElection`, esta entrega permite resolver CRT=1 ou CRT=2 de forma explícita, com `crt` registrado na declaração e comparação obrigatória com o `FiscalProfile` para impedir replay entre estabelecimentos/perfis mesmo se ID e versão forem falsamente reutilizados.

**Limite:** CRT=2 continua com tratamento próprio de ICMS/ISS; o resolvedor de opção não calcula IBS/CBS, não transmite a opção ao CGSN e não aceita CRT=3/MEI. A partir de 2027 exige evidência vigente, com isolamento tenant/unidade/host e proibição de sobreposição de períodos; 2026 permanece sem cálculo RTC pelo Simples. Referência de publicação para revisão posterior: NT 2026.005 v1.00 Simples Nacional, SVRS 30/10/2026, https://dfe-portal.svrs.rs.gov.br/NFe/Documentos; **não há XML, regra de preenchimento, schema ou tributo habilitado sem artefatos oficiais verificados**.

**Aceite desta PR:** novos casos de CRT=2 com opções explícitas e testes negativos para cruzamento CRT=1↔2, ausência de declaração, vigência e separação CRT=3/4, mais gates CI/Gov. RTC-04 global mantém `IMPLEMENTED_PARTIAL`.

### RTC-04 B6 — recibo de opção regular IBS/CBS do Simples em 2027/H1 (02/11/2026)

**Construção funcional:** em `tax/regimes.py`, `SimplesRegularOptionReceipt2027H1` representa a evidência de opção CGSN confirmada, com protocolo, datas, escopo canônico, perfil fiscal versionado e CRT. `resolve_simples_ibs_cbs_mode` exige esse recibo **somente quando o modo for `REGULAR_SEPARATE` no 1º semestre de 2027**; mantém o Simples unificado sem inferir que houve opção regular. Recusa protocolização fora da janela, opções canceladas, confirmação futura, perfil/CRT/tenant divergentes e extrapolação do período 2027/H1 para H2. É a mesma autoridade do B5, sem API, motor ou persistência paralelos.

**Fonte primária:** Receita Federal, comunicado de 29/09/2026 sobre Resolução CGSN 194, <https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/setembro/simples-nacional-2027-entenda-os-novos-prazos-e-faca-sua-escolha-com-consciencia-e-tranquilidade/>. Jan–Jun/2027: formalização do regime regular IBS/CBS de 01/09 a 30/10/2026; cancelamento de 03/11 a 20/12/2026. **Os prazos de opção pelo Simples Nacional em si são diferentes** e não são reutilizados como janela IBS/CBS. A partir de julho/2027, exige nova prova normativa em vez de usar automaticamente o recibo de H1.

**Limites:** o objeto de protocolo não comprova autenticidade por si só; apenas camada confiável ou aprovação humana pode fornecer evidência verificada. Não registra opção/cancelamento na Receita, não calcula IBS/CBS/IS, não autoriza XML/transmissão e não prova conformidade ao XSD. Aceite interno: CI, governança, testes de períodos e isolamento, merge e gates pós-merge. RTC-04 total continua `IMPLEMENTED_PARTIAL`, RTC-05 não iniciado nesta entrega.

### RTC-04 B7 — guarda temporal do catálogo CST/cClassTrib (02/11/2026)

- **Gap funcional comprovado:** `resolve_rule_with_verified_rtc_catalog` validava par CST/cClassTrib e SHA do catálogo normalizado, mas não comparava a **data do fato gerador** com a publicação/vigência do artefato. Assim seria possível uma prévia retrospectiva usando uma versão de tabela publicada depois da operação.
- **Delta construído:** a `VerifiedRtcClassificationCatalog` passa a carregar `published_on` e `effective_from` herdados da `RegulatoryArtifactPin`, incluídos no witness de integridade. O loader rejeita publicação posterior à captura do baseline; o resolvedor canônico exige timestamp com timezone e recusa fatos anteriores à publicação ou à vigência explícita. Sem autoridade temporal alternativa e sem mudança de TaxRuleEngine.
- **Prova:** novos testes negativos contra versão publicada no futuro, vigência posterior ao fato, metadados adulterados, timestamp sem timezone e baseline capturado antes da publicação. Mantém `authoritative=False` e **não presume** que a publicação isolada certifique vigência legal: `effective_from` somente opera quando fonte/pin o declara explicitamente.
- **Fontes oficiais e limite:** SVRS `https://dfe-portal.svrs.rs.gov.br/NFe/Documentos` publica a NT 2026.005 v1.00 e a IT 2025.002 v1.71 (30/10/2026). O manifesto atual contém referência sem bytes/XSD/hash originais e não é adotado como catálogo produtivo nesta entrega. **Ainda faltam** obtenção do pacote original, verificação de autenticidade, vigência por operação/CRT, golden cases de bases, créditos, redução, CBS/IBS/IS e autorização/homologação de emissão. Nenhum código XML, alíquota ou produção foi alterado.
- **Aceite:** CI/Gov no exato HEAD da PR e pós-merge da `main`; B7 só fica `INTERNALLY_CERTIFIED` após ambos os gates. RTC-04 segue `IMPLEMENTED_PARTIAL`.

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

**Próxima construção CURRENT (02/11/2026; GitHub `main@b6ec499d4b2b2d92081c44c9f55cacb25c4a43a0`):** após B6 PR #320 **MERGED**, não reiniciar RTC-04 B1..B6 nem BLD. Conferir CI pós-merge #1485 e Governança #916 do mesmo SHA antes de declarar B6 certificada. **RTC-04 B7**: obter o PDF/XSD oficial NT 2026.005 v1.00 e tabela IT 2025.002 v1.71 com bytes e SHA verificáveis, mapear célula CBS/IBS/IS, vigência/CRT/documento/operação, compor golden cases e implementar somente o delta comprovado no motor existente. Se artefato não puder ser verificado, manter célula `BLOCKED_NORMATIVE` e avançar outra elegível sem criar regras por inferência; `authoritative=False` na prévia, sem emissão. Após o fechamento técnico elegível RTC-04, seguir RTC-05 → RTC-06/07 → RTC-08 → RTC-09/10 → RTC-11; RTC-12 externo. Oferta/trial/checkout não são prioritários até o produto ficar pronto; nenhuma alteração Contabo/`production` autorizada.

**Evidências e anti-retrabalho:** `docs/checkpoints/NFCORE_RTC_CURRENT_RECONCILIATION_2026-11-01.md` (PRs, HEADs, CI, riscos e critérios faltantes). Esta tabela substitui o estado operacional da abertura; se divergir, auditar GitHub atual, nunca a memória.

## Reconciliação RTC-RFB × Economia Fiscal T07 — 20/11/2026

Decisão do proprietário: reaproveitar integralmente a integração existente, completar lacunas sem duplicar autoridade. CURRENT auditado na PR #589, HEAD 9e334f3988fe94452f10230e11da1039667d2c69, main 549ab3c005d7183ff6c7940236414412ea004b9d. PRs #576, #584 e #585 integradas em work/nfcore-closeout-20261119 e presentes na árvore T07. Não reimportar ou reconstruir seus componentes.

| Entrega | Autoridade e destino | Estado |
|---|---|---|
| Simples RTC 1.0.2, Regular 1.7.2, banco V0073 | Adaptadores tax/rfb_* e deploy/rfb existentes | Integrados ao código, respostas registradas; operação Contabo não comprovada |
| Sombra NF-e/NFC-e | tax/rtc_shadow.py e application/rtc_shadow_recorder.py | Integrada, opt-in, sem autoridade de emissão |
| NFS-e /nao-assistido | build_nfse_request, SimplesEffectiveRates existentes | Adaptador testado por fixture real; falta composição com alíquotas PGDAS verificadas e jornada de emissão |
| Apuração mensal 2026 | tax/simples_nacional.py, segregação T06/T07, store T01 | Candidata; falta certificar caixa, excessos, histórico e comparações |
| Transição 2027 | RTC-04/05 e T07 compartilham regime temporal e evidências; reusar tax/regimes.py | Regra 2027 não pode ser deduzida das tabelas 2026; requer partilha vigente, evidência da opção e testes |
| Comparação PGDAS | T07 compare_assessment | Não confundir com comparação RTC por documento; referência real externa necessária para paridade oficial |
| Ativação Contabo e sentinela de releases | RTC/Release Manager | Gate operacional separado, não declarar ativado |

Contrato-alvo: apuração mensal revisada -> alíquotas efetivas por anexo vinculadas a emissor, competência, escopo, versão e evidência -> SimplesEffectiveRates -> adaptador oficial já existente. Nenhuma promoção automática de estimativas T07 a alíquota declarada, nenhum cálculo do browser/IA, nenhuma segunda persistência ou serviço fiscal. A opção IBS/CBS deve vir da autoridade temporal existente em tax/regimes.py, não de seleção livre no payload. Preservar modo sombra, evidências, pins, V0073 e controles de emissão. Critérios de aceite: comparação por tributo, casos de caixa/competência e excesso, vigência, isolamento, replay, testes PostgreSQL, integração dos adaptadores e CI cumulativa; revisão independente antes de promoção. T08 bloqueada até fechamento do escopo T07. Não autoriza deploy, DDL, transmissão ou merge main/production.
