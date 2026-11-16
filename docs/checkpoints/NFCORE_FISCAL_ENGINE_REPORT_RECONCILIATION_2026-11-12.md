> **REGISTRO HISTÓRICO RECUPERADO EM 16/11/2026 — PR #448, origem `aa7ce1553d260a13fc105e3b1b324af964e72cca`.**
> O conteúdo original abaixo foi preservado integralmente. Afirmações de CURRENT, lacunas, prioridades, responsáveis, autorizações e estado de CI referem-se à data do documento. Para o estado vigente, consulte `docs/audit/NFCORE_PR_RECONCILIATION_LEDGER_CURRENT.md`, o GitHub e as decisões posteriores em `AGENTS.md`.
> A recuperação não reabre etapas integradas, não altera a prioridade de 13/11 ou a responsabilidade do Integrador de 15/11, não implementa travas e não certifica cobertura. T2 já possui implementação parcial posterior; esta especificação não prova T1/T3–T6 nem enforcement administrativo.

# NFCore V1 — Reconciliação técnica da auditoria do motor fiscal
**Data:** 12/11/2026. **Status:** diagnóstico técnico; não é certificação de emissão. **Owner:** issue #447.

**Fonte recebida:** “Auditoria do motor fiscal NFCore — prontidão por tipo de nota e plano de execução”, 12/11/2026, 361 linhas, 25.922 bytes, SHA-256 9aa9ef90db973d420959c0066fb418db0e86c5a2eb2c9f6252e0b3b1a6dd408b. A fonte íntegra foi preservada no anexo da conversa; este checkpoint é uma análise reconciliada, e não a transcrição do relatório.

**Baseline auditado pela fonte:** production @ ea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599. **Comparação atual:** main @ ef7ebe7e104f0e49897075cd961d51a052948b43. PR #427 DRAFT com conflitos; PR #441 MERGED; PR #446 DRAFT (SP4, outro executor); PR #448 DRAFT (documentos); PR #449 DRAFT no SHA d6f8f1c37377e5dcb4077410ee035cb5b7ede0a4 (emissor nativo). Na consulta, governança da #449 SUCCESS e CI geral #2399 IN_PROGRESS. A implantação efetiva na Contabo não foi verificada neste checkpoint.

## 1. Veredito
1. O motor fiscal é próprio e já inclui domínio, serviços, assinatura XML, cofre A1, gateway de homologação, arquivo, segurança e rotas. Nenhum ERP externo é autoridade ou pré-requisito constitucional de emissão.
2. Não há prova fornecida de uma emissão fiscal oficial completa em homologação com CNPJ autorizado, A1 real, resposta da SEFIN/SEFAZ, protocolo e XML verificável. Não declarar homologação.
3. A fonte descreve **production** em um commit específico. Ausência em production não é ausência absoluta no produto, na main ou em branches candidatas. Branch não é release.
4. Nenhuma das 22 cidades paulistas deve ser chamada CERTIFIED por catálogo, seleção de canal ou CI sintética.
5. A frase “nunca houve A1 real” é **relato histórico não revalidado no servidor**, não uma prova negativa de todo o histórico. Realizar E2E com evidência oficial.

## 2. Matriz reconciliada de G1 a G16
**Legenda:** SNAPSHOT = válido para production ea4bdd3; MAIN = código atual da main difere; CANDIDATO = PR não certificada/mesclada; EXTERNO = depende do ambiente oficial; PENDENTE = engenharia interna.

| ID | Achado do relatório | Reconciliado com CURRENT | Gate correto |
|---|---|---|---|
| G1 | Portal não prepara NFS-e | SNAPSHOT correto; CANDIDATO #449 acrescenta prepareNativeNfse, formulário, sessão, CSRF, RBAC, binding e preparação canônica. Prepara, **não transmite**. | CI + HTTP/PostgreSQL/E2E navegador + integração posterior |
| G2 | DPS sem tomador | SNAPSHOT correto; CANDIDATO #449 acrescenta NfseServiceTaker, CPF/CNPJ, grupo toma, codec e fingerprint. **UI atual não coleta endereço/IM**, embora o modelo permita. | XSD vigente, casos de tomador e PII, compatibilidade v1 |
| G3 | XML autorizado NFS-e não arquivado | SNAPSHOT correto. MAIN já tem campo NfseAuthorizationResult.authorized_xml e arquivamento no serviço canônico, mas gateway Nacional main faz parse e não entrega os bytes ao resultado. CANDIDATO #449 liga XML validado ao resultado; #446 toca mesmo arquivo. | Banco/arquivo auditável, chave e XML oficial vinculados, CI, integração sem conflito |
| G4 | Consulta Nacional ausente | SNAPSHOT correto. MAIN injeta prepared_nfse_query_client apenas para WebISS Extrema; o router de NFS-e só consulta Extrema e nega consulta Nacional. CANDIDATO #446 implementa rota nacional de recuperação GET, sem merge. | Query Nacional por binding próprio; reconciliação sem reenvio POST, timeout e replay |
| G5 | ISS/regime hardcoded/provisório | Confirmado em MAIN: regEspTrib=0; tribISSQN=1; regApTribSN=3 provisório em subcaso de Simples; pAliq derivado do ISS informado. #449 apenas bloqueia certos casos não suportados, não fecha regra. | **P0 interno:** regime, competência, retenção, isenção, exceções, tabela oficial de cTribNac, testes e XSD |
| G6 | Canal Nacional de Cajamar não confirmado | **CORRIGIDO POR FONTES OFICIAIS:** Prefeitura de Cajamar de 15/07/2026 orienta uso do Nacional e integração API. Resolução CGSN 191/2026 e notícia Nacional de 29/10/2026 confirmam obrigação nacional para ME/EPP do Simples com competência desde **01/11/2026**. A data municipal anterior de setembro foi superada. | Canal normativo confirmado; NÃO comprova A1, credenciamento, CNPJ piloto ou aceite da SEFIN |
| G7 | Sem prova de A1 real | EXTERNO não demonstrado na fonte nem nesta revisão; health/CI/mock não substituem transmissão oficial. | A1 e autorização do contribuinte; homologação com protocolo e XML oficial |
| G8 | Numeração DPS por hash | Confirmado MAIN/production: método marcado PROVISIONAL. #427: DRAFT, 51 arquivos e conflito. | **P0 interno:** sequenciador transacional, escopo/série, replay e concorrência; reconciliar #427 sem duplicação |
| G9 | Rejeição pouco clara e sem DANFSe | SNAPSHOT correto; CANDIDATO #449 registra status/código/motivo saneados e adiciona renderer DANFSe local do XML autorizado, além de rota de PDF autenticada. | Regressões de UI/segurança, PDF correto, motivo real e recuperação sem falso sucesso |
| G10 | NFS-e sem cancelamento | SNAPSHOT Nacional correto; CANDIDATO #446 cria fronteira de evento Nacional, mas o dossiê da própria #446 admite que não está integrado ao Portal/lifecycle. MAIN tem operações municipais específicas para Extrema; não generalizar. | Evento/XSD, aprovação humana, protocolo, consulta posterior e estado persistente |
| G11 | Sentinela restrito | Validação nfse_preaudit é estrutural e determinística; normative_sentinel verifica pin hash, não autenticidade; main também possui preaudit específico de Extrema. Não é auditor fiscal normativo completo. | Catálogo oficial/versionado, regime, competência, jurisdição e proveniência; IA não valida domínio |
| G12 | Risco operacional do cofre, backup e regras | A fonte cita riscos do backup A1/chave e ruleset. Não foram revalidados no host; **restore PostgreSQL não testa restore do cofre**. GSM Worker não é worker fiscal. | Auditoria somente leitura de backups A1/keys, proteção e restore controlado sem expor segredos |
| G13 | NF-e 55 só entra via Bling; MG sem cancelamento | Emissão manual NF-e via Portal continua não demonstrada. Porém MAIN tem _GovernedMgQueryGateway.cancel e binding MG, então “MG sempre usa cancelamento SP” é desatualizado. | Formular NF-e direta; E2E NF-e 55, revisão de evento MG e numeração |
| G14 | Produção fiscal tpAmb=1 ausente | Gateway Nacional auditado é de homologação. Portal Web já publicado **não** significa emissão fiscal em produção. | Gate PRODUCTION_APPROVED separado, prova externa e autorização humana |
| G15 | NFC-e, municipal, CT-e/MDF-e ausentes | **QUALIFICAR:** MAIN tem gateway MG NFC-e 65 e seletor com modelo 65, mas QR/CSC e jornada ponta a ponta não estão fechados; MAIN tem gateway NFS-e municipal WebISS Extrema. PR #446 oferece fronteiras SP4 que o próprio dossiê classifica incompletas. CT-e e MDF-e não fazem parte do enum FiscalDocumentKind auditado; só incluir com aprovação explícita do escopo V1. | Matriz por canal/documento/município, não declarar ausência universal nem prontidão |
| G16 | Vigilância normativa não agendada | Apenas artefato de exemplo foi apontado; sem leitura do host não comprovar presença/ausência de cron/systemd. | Prova de job real, alerta, owner humano e zero promoção automática de regra |

## 3. Principais riscos adicionais da comparação

### R1 — Divergência main × production
Os dois HEADs diferem materialmente: main já suporta contrato de XML NFS-e, WebISS Extrema e rotas MG adicionais. O diagnóstico original não deve ser usado para pedir reconstrução desses módulos.

### R2 — Sobreposição de PRs e executores
#446 e #449 modificam em comum: gateway/nfse_nacional_homologation.py, issuance/nfse_dps_builder.py e tests/runtime/test_nfv1_nfse_preparation_recovery.py. A #427 altera a numeração/contratos. Necessário inventário por função, integração controlada e CI no novo SHA. **Não fazer merge/cherry-pick cegamente**, não dividir uma regra fiscal entre dois owners.

### R3 — Preparação não é transmissão
Na #449, prepareNativeNfse grava documento interno e devolve document_id. Para emitir, a interface precisa acionar posteriormente issueFiscalDocument. Teste de HTTP 200 na preparação não prova envio, aceite nem XML autorizado.

### R4 — Campos livres não são regra normativa
Na UI candidata, valores tributários, source_normative e rule_version são digitados e declarados revisados. Uma declaração do usuário não equivale a catálogo oficial, competência e regime efetivos; a validação fiscal deve permanecer no backend. A UI exige endereço/IM adicional conforme cenário autorizado.

### R5 — Schema nacional
MAIN ainda usa _SCHEMA_VERSION 1.00 no builder. A documentação técnica nacional, atualizada 04/11/2026, lista XSD **v1.01**. Verificar a versão efetiva também em homologação e os anexos fiscais/RTC antes de promover; não alterar versão às cegas.

### R6 — “Primeira nota” não é “conclusão interna total”
A auditoria ordena o caminho crítico do piloto de Cajamar e posterga NF-e manual, NFC-e, integrações municipais e demais eventos. Isso **não cumpre sozinho** a ordem do proprietário para concluir toda a engenharia interna aplicável da V1. Manter planilha de escopo aprovado por tipo/canal e trilha do piloto separada. CT-e/MDF-e/nota de energia e telecom não se tornam escopo automaticamente.

### R7 — CI e testes sintéticos não são selo fiscal
A fonte informou aproximadamente 1.445 PASS e 262 SKIP em ambiente próprio sem PostgreSQL, e não anexou saída integral nesta revisão. **Resultado relatado pelo auditor, não executado novamente aqui**. A #449 teve falha anterior de Pytest e correções; o novo commit deve concluir CI, frontend, E2E, PostgreSQL, segurança e Docker. Não promover o último estado verde de um SHA diferente.

### R8 — Segurança da evidência
XML autorizado pode conter CPF, CNPJ, endereço e valores; certificado PFX, senha e chave mestra nunca devem entrar em issue, PR ou chat. Guardar resposta completa em repositório seguro tenant-scoped; checkpoint público contém somente identificadores mascarados, SHA, tpAmb, competência, IBGE, horário e status.

## 4. Plano de execução revisado — não bloquear engenharia interna pelo A1

| Gate | Trabalho | Critério de encerramento |
|---|---|---|
| A — reconciliar | main/production/#427/#446/#449 e baseline sem regressão | Mapa de conflitos, owner único e interface canônica preservados |
| B — domínio | Tomador completo, regimes e ISS, regra nacional vigente, nDPS durável | XSD/XMLDSig, concorrência, idempotência, tributação oficial e regressões |
| C — resultado | XML autorizado e protocolo, consulta Nacional sem segundo POST, cancelamento/eventos quando suportados, DANFSe e erros | Arquivo consistente, timeout seguro, query real e PDF tenant-scoped |
| D — Portal | Cadastro→preparar→emitir→consultar→XML/PDF no mesmo motor, sem Bling | RBAC, tenant/unit, CSRF, HTTP, PostgreSQL, Playwright E2E |
| E — abrangência interna | NF-e 55 nativa, NFC-e 65 com CSC/QR, eventos, municípios/regimes da V1 | Cada caso aplicável com contrato seguro e teste; #446 segue dono do SP4 |
| F — certificação interna | Ruff, mypy, Pytest, DB, frontend, build, E2E, security, container, smoke | Todos os gates verdes no commit exato; erros corrigidos, não mascarados |
| G — homologação externa | CNPJ autorizado, certificado A1 real via cofre, provider/canal governado | Resposta oficial, protocolo, XML, consulta e evidência segregada |
| H — ativação produtiva | Após G, segurança, DR e decisão humana | PRODUCTION_APPROVED, observabilidade, cutover governado e Go/No-Go |

A data 13/11/2026 às 09h BRT da frente contabilidade SP4 é **objetivo de piloto**, não evidência de aceite. As etapas A–F podem ser programadas e testadas sem certificado do cliente; G/H não podem ser inventadas nem realizadas sem suas autorizações.

## 5. Decisões e próxima ação
- Preservar o motor proprietário e as autoridades existentes. Não criar segundo motor, API fiscal nem frontend.
- Canal do Simples Nacional para Cajamar confirmado por normas; emitir pelo NFCore **ainda não comprovado**.
- P0 internos: CI #449, tax/regime/schema, numeração #427, recuperação Nacional da #446, Portal E2E e arquivo XML/DANFSe seguros.
- Frentes São Paulo (#445/#446) e numeração (#427) permanecem com owners próprios; este checkpoint **não altera o código deles**.
- Status global: PARTIAL_IMPLEMENTATION / INTERNAL_CERTIFICATION_PENDING / EXTERNAL_HOMOLOGATION_PENDING.
- Próxima ação: revisar CI do HEAD #449, reconciliar mudanças concorrentes sem conflito, fechar em lote todas as pendências internas do motor fiscal aprovadas, e certificar o percurso real por evidências. Nenhum merge, deploy, migration ou emissão real autorizado por este documento.

## 6. Fontes externas verificadas em 12/11/2026
- Prefeitura de Cajamar, comunicação inicial 15/07/2026: https://cajamar.sp.gov.br/noticias/2026/07/15/empresas-do-simples-nacional-deverao-emitir-nfs-e-exclusivamente-pelo-emissor-nacional-a-partir-de-setembro/
- Portal Nacional, regra e competência 01/11/2026: https://www.gov.br/nfse/pt-br/noticias/nfs-e-informa-diretrizes-sobre-a-obrigatoriedade-da-emissao-da-nfs-e-nacional-para-optantes-do-simples-nacional/
- Documentação NFS-e atual, XSD/anexos: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual
- Prefeitura de São Paulo, adiamento oficial: https://prefeitura.sp.gov.br/web/fazenda/w/usoemissornacional
- GitHub: issues #445 e #447, PRs #427, #446, #448, #449.
