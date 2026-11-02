# FM NFCORE V1 — DOCUMENTO MESTRE DE ADEQUAÇÃO À REFORMA TRIBUTÁRIA DO CONSUMO (RTC)

**Criado:** 30/10/2026 · **Estado:** EM CONSTRUÇÃO / NÃO HOMOLOGADO · **Branch:** `feat/nfcore-rtc-reforma-tributaria-foundation-20261030`  
**Base auditada:** `main@c2d29a45d8a6c0458f49d963936bad9f5dfc534b`. Esta referência é checkpoint, nunca CURRENT permanente.  
**Produto:** FM NFCORE V1, repositório atual `faabio3131/nf-core-v001` (redirect histórico de `kordena-fiscal-engine-v2`).  
**Continuidade:** anexo independente RTC ao cronograma BUILD-ONLY e ao cronograma comercial de 59 tarefas; não altera seus estados, WPs, gates nem a autoridade de `main`.

## 1. Objetivo e definição verificável de "100% apto"

Fazer o NFCore suportar corretamente, **por jurisdição, documento, operação, regime fiscal e data de vigência**, a transição legal/técnica da RTC nos regimes Simples Nacional, Lucro Presumido e Lucro Real, **dentro das autoridades canônicas existentes**, sem duplicar motor, API, autenticação, persistência ou Portal.

**100% CONSTRUCTION** exige contratos, schemas, regras de classificação/cálculo quando exigidas e normativamente fundamentadas, validadores, XML, adapters, API/Portal e testes internos cobrindo todos os casos da matriz aprovada. **100% HOMOLOGAÇÃO** exige respostas oficiais por célula (documento × operação × UF/município × provedor × ambiente × regime quando aplicável), XML/retorno e evidência versionada. **100% PRODUÇÃO** exige ainda segredos reais em vault, certificação de segurança, staging, observabilidade, backup/restore, deploy/go-no-go humano e operação real. Nenhum percentual deve ser inferido do número de PRs.

**Escopo de produto:** motor de classificação, cálculo tributário transacional e emissão/document lifecycle. Apuração contábil integral (IRPJ, CSLL, ECD/ECF, PGDAS-D, EFD etc.) é **outro escopo**; mapear integração/exportação e decidir formalmente se integrar ou desenvolver depois. Jamais dizer que o NFCore faz apuração integral só por emitir documento.

## 2. Fontes normativas verificadas em 30/10/2026

- Emenda Constitucional 132/2023, LC 214/2025, LC 227/2026 e regulamentação vigente: https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria-do-consumo/legislacao/
- Cronograma oficial de documentos da RTC atualizado em 28/10/2026: https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria-do-consumo/orientacoes-da-reforma-tributaria/cronograma
- Portal da NF-e: NT 2025.002 **v1.52**, publicada 01/10/2026, e demais NTs relevantes: https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=04BIflQt1aY%3D
- Flexibilização anunciada das regras técnicas de rejeição para campos CBS/IBS (não equivale à revogação da obrigação legal): https://www.gov.br/fazenda/pt-br/assuntos/noticias/2026/agosto/receita-federal-e-cgibs-flexibilizarao-obrigatoriedade-de-informacoes-em-documentos-fiscais

**Governança da atualização:** confirmar publicação oficial e vigência por documento, baixando leiaute/XSD/tabelas/IT com hash SHA-256 e data. Fonte normativa, schema oficial, tabela de classificação e comportamento de autorizador são eixos distintos. **Sem tabela/artefato técnico oficial revisado e teste de conformidade, não inventar alíquota, cClassTrib, CST-IBS/CBS, crédito ou regra.** A referência em `config/rtc/official-baseline-2026-10-30.json` é informativa e não ativa cálculo ou emissão.

**Marcos:** observar diferenças entre publicação, vigência, obrigatoriedade, período de transição e validação técnica; o cronograma oficial informa marco de **01/01/2027 para documentos de contribuintes Simples Nacional**, sem autorizar extrapolar a outros contribuintes. Verificar regras de 2026/2027 e alterações posteriores por família e jurisdição.

## 3. CURRENT confirmado por código, não homologação

- `tax/engine.py`, `tax/models.py`: `TaxRuleEngine` único, `TaxRuleContext` inclui regime, escopo, instante, jurisdição, documento, operação, destinatário e produto; `TaxRuleOutcome` já possui `ibs_cbs_classification_code`.
- `compliance/rtc.py`: `RegulatoryBaseline`, `RegulatoryArtifactPin`, `ReformTaxSnapshot`, CBS, IBS estadual/municipal, IS, `RtcEmissionPolicyResolver` para separar obrigação legal de comportamento técnico de rejeição.
- `tests/compliance/test_rtc_multiuf.py`: contratos e cenários sintéticos; cobertura das 27 UFs em nível **CONTRACT_ONLY**, não homologação de 27 UFs.
- `AGENTS.md`, `docs/NFCORE_V1_BUILD_INTEGRATION_EXECUTION_2026-10-18.md`: autoridade do motor fiscal, operações seguras, continuidade BUILD-ONLY, proibição de fake em runtime e deploy sem autorização.
- **Não confirmado:** catálogo oficial de alíquotas/classificações atual, leiautes RTC efetivamente serializados em NF-e/NFC-e/NFS-e, cobertura de XML/XSD e integração autorizadora conforme NT 1.52; regras de benefícios/creditamento/monofásico, modelo completo por regime e homologação externa.

## 4. Arquitetura única e mapa de autoridade

`Official normative artifacts + versions` → curadoria/review humano → `RegulatoryBaseline` / versionamento da norma → `TaxRuleEngine` com contexto e regra vigente → `ReformTaxSnapshot` → application/intent/UoW/documento canônico → serializers de cada família/adapter externo → API/Portal existente. Persistência deve manter **snapshot imutável, prova da regra e da versão de schema**, sem recalcular histórico retroativamente.

Condições invariantes:
1. Uma única fonte autoritativa de regime por empresa/estabelecimento, com histórico de vigência e segurança tenant/unidade; não inferir Lucro Real/Presumido a partir do CRT da NF-e: regime de IRPJ/CSLL e CRT de ICMS/documento têm semânticas distintas.
2. Compatibilidade progressiva em coexistência dos tributos tradicionais e IBS/CBS/IS conforme vigência, sem remover ICMS, ISS, PIS/Cofins e IPI antes da norma.
3. Resultado determinístico e `Decimal` com arredondamento por campo/tributo conforme especificação oficial; regras exatas versionadas.
4. Ausência/contradição de classificação, NCM/NBS, município, destino, alíquota, tratamento de crédito, vigência ou perfil fiscal falha fechada; sem suposição por IA.
5. Separar obrigação de informar, validade do schema, rejeição efetiva e autoridade para produção. A flexibilização de rejeição não autoriza omitir o campo por regra de negócio.
6. Sem XML ou evidência sintética confundida com autorização; sem segredo/CSC/certificado em banco, Git, browser ou logs.
7. Estado da emissão, cancelamento, eventos, consulta e reconciliação continuam nas autoridades atuais de lifecycle; replay/timeout idempotentes.

## 5. Matriz de cobertura mínima de regimes e operações

**Regimes:** Simples Nacional (incluindo particularidades e transição), Lucro Presumido, Lucro Real; regimes especiais e tratamentos diferenciados ficam explicitamente descobertos antes de alegar cobertura. O lucro tributário (Presumido/Real) não equivale ao código de regime da NF-e; modelar duas dimensões somente se a auditoria demonstrar que falta essa informação na autoridade canônica.

**Famílias:** NF-e 55, NFC-e 65, NFS-e nacional/municipal suportada; CT-e, NFCom, NF3e, BP-e, NFAg, DeRE, NF-e importação, operações específicas de combustíveis e documentos de novos leiautes **são cobertura adicional a inventariar**, não afirmar implementados sem produto/adapter acordado.

**Cenários críticos por família:** venda/prestação, devolução/cancelamento, bonificação/brinde, transferência, interestadual, consumidor final, exportação, importação, isenção, suspensão, redução de base, regimes especiais, cesta básica, seletivo, combustíveis, créditos presumidos, retenções, operações mistas, splits e valores de ajuste **quando previstos e pertinentes**. Classes cClassTrib/CST e exceções dependem da tabela oficial vigente.

**Dimensões de teste combináveis:** data 2026/2027/anos de transição; UFs e municípios pertinentes; origem/destino; contribuinte/não contribuinte/consumidor final; NCM/NBS; atividade; produto/serviço; CRT e tributação corporativa; política de benefício; provider; schema; cancelamento/retorno; tenant/unidade e sessão; diferenças entre regra de cálculo e exigência de campo.

## 6. Segurança, migrações e evidências

- Nenhuma migration produtiva implícita; modelo aditivo e forward-only somente após mapear schema/rollback, fresh install vs upgrade e idempotência.
- Motor fiscal não recebe campo calculado pela UI como autoridade; testes contra spoofing de tenant, enquadramento, CST/classificação, alíquota e provider.
- As mudanças na Web devem preservar Portal existente, RBAC e autenticação; estados bloqueados claros.
- Controle de drift: regra aprovada, versão, hash de artefato, vigência, responsável, testes golden XML, schema e comparação; mudança legal produz PR, nunca alteração automática de produção.
- Homologação sempre por célula com request/response oficial, correlation ID, ambiente, data e aprovação; dados sintéticos não homologam autorização fiscal.

## 7. Decisões, riscos e gates

**Decisões aprovadas preexistentes:** arquitetura única evolutiva, CORE coordena e serviços determinísticos validam/executam, single authority, fail-closed, versionamento da norma, configurações externas, isolamento de tenant/unidade, separação BUILD de homologação/deploy.

**Decisões ainda requeridas:** escopo de CT-e/outros documentos, abrangência de apuração tributária contábil, escolha e contrato de provedores oficiais, fontes de tabelas normativas com licenciamento/atualização, e critérios comerciais de UFs/municípios prioritários.

**Riscos principais:** versão obsoleta do leiaute, divergência norma versus tolerância técnica, confusão CRT versus IRPJ, alíquota incorreta, regra sem prova de vigência, alteração retroativa de XML, efeitos em workers, baixa cobertura de NFS-e e homologação geográfica não generalizável.

**Gates:** Ruff, mypy strict, pytest dirigido/global, schema/XSD oficial, round-trip XML, API contrato, PostgreSQL/migration, RBAC/tenant/unit, concurrency/idempotência, Worker, frontend lint/typecheck/test/build, E2E sintético, artifact scan, CI/Governança do SHA da PR, CI pós-merge quando autorizado. Produção exige ainda homologação real + decisão humana.

## 8. Registro de estado e continuidade

**CURRENT reconciliado em 01/11/2026:** RTC-00 (#267), RTC-01 (#268/#270), RTC-02 (#269/#271/#272), RTC-03 (#273/#274/#280) e RTC-09 inicial (#275/#278) possuem código integrado à `main` e preservado em `production`, mas **não** aceitação integral. RTC-04 contém prévia Decimal pinada **não fiscal** da PR #289 MERGED em `main@5bb3b2f` (CI/Gov pré-merge verdes); PR #307 MERGED em `main@c36d363`, CI/Gov pós-merge SUCCESS; PR #308 OPEN propõe apenas referência nominal legal 2026 CBS 0,9% e IBS estadual 0,1% com Decimal sem arredondamento, sem cálculo fiscal emitível. RTC-05..08/10/11 permanecem sem entrega completa certificada; RTC-12 exige homologação externa. O baseline JSON **não** autoriza cálculo ou emissão. Consultar o checkpoint canônico `docs/checkpoints/NFCORE_RTC_CURRENT_RECONCILIATION_2026-11-01.md` e a tabela revisada do cronograma.

Ao retomar: ler estes dois docs + `AGENTS.md` + ledger BUILD canônico; verificar main/HEAD/PRs/CI, comparar branch, identificar primeiro WP RTC aberto; não fazer merge/deploy sem gates e autorização apropriada. O trabalho RTC pode prosseguir em branch isolada paralela a BLD-03; não deve alterar nem sobrescrever o trabalho BLD-03.
