# NFCore SP5 — auditoria de fechamento das pendências internas (15/11/2026)

> **Estado:** EXECUÇÃO / EVIDÊNCIA PARCIAL, não é certificado de fechamento. 
> **Base auditada:** `#468@f331da56a50b55157f08bffd8d7d4d38c26eaa31`, CI [#43754395916](https://github.com/faabio3131/nf-core-v001/actions/runs/43754395916) SUCCESS (42/42). 
> **Release Web:** `#498@798874e2f85c6b75b6eb995e2d6bbb6da7eaf628`, CIs #43754404745 e #43754410713 SUCCESS.
> **Linha protegida:** `main@f23d2a050a4c1555de1bdbe8620bb69b6d983cc8`, `production@ea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599`. Sem promoção/implantação.

## Convenção de evidência

Um *blob igual* prova equivalência literal do arquivo, mas um *blob diferente* **não** prova ausência funcional. CI verde da árvore não prova revisão independente nem operação no host. Reconciliação funcional depende de comparar funções, testes e contratos, não de copiar branches históricas.

## Matriz Current → Target

| Bloco | Achado CURRENT reproduzível | Critério de aceite ainda exigido |
|---|---|---|
| A/B ownership | `portal/app.js` chama `/v1/portal/fiscal-intents/*`; `portal_api.py` governa sessão/RBAC/escopo; `web/native_nfse_preparation.py` reutiliza UoW; `gateway/nfse_national_receipt.py` verifica XMLDSig; `issuance/nfse_dps_builder.py` reserva serial pelo UoW. | Revisão cruzada assinada por executor independente, por função, incluindo ausência de segundo login, tenant authority e persisted numbering |
| MF-04 | `NfseNationalTaxTreatment` exige fonte normativa, versão, período, código ISS 1..4 e de regime; `nfse_dps_builder.py` não mais aplica `regApTribSN=3` incondicionalmente; excesso do sublimite exige decisão revisada. `tests/issuance/test_nfse_dps_builder.py` cobre regimes, imune/exportação/sublimite e competência. | Validar que fallback para operação ordinária (`regEspTrib=0`, `tribISSQN=1`) é restrito a casos elegíveis e não encobre regimes desconhecidos |
| MF-09 | No Portal, `issueFiscalDocument` recebe `document_id` preparado; `appendNativeNfsePreparation` existe, mas não há `prepareNativeNfe`/`prepareNativeNfce` ou formulário manual de dados de mercadorias. | Jornada Web própria para preparar NF-e/NFC-e, persistir, emitir e consultar pelo mesmo core, com evidência E2E e autorização multi-tenant |
| NFS-e GET | `nfse_national_query.py` usa `validate_official_nfse_receipt`, que verifica chave/Id e XMLDSig RSA-SHA256, mas a documentação do próprio módulo exclui validação integral do XSD e cadeia ICP-Brasil/revogação. | Contrato XSD correto e pinado para ambiente/versão, validação do arquivo recebido e teste negativo; mecanismo explícito de confiança de cadeia, separado de fixtures sintéticos |
| Delta histórico #446/#449/#450 | #446 tem 82 paths alterados: 39 blobs idênticos em #468 e 43 divergentes/ausentes. #449: 21 paths (5 iguais/16 diferentes). #450: 56 paths (10 iguais/46 diferentes). As divergências incluem evolução posterior de código; **não fazer cherry-pick cego**. | Parecer por função com lista de funções realmente ausentes e testes substitutos; guardar proveniência |
| EGM independente | Nenhuma evidência de revisão independente isolada apareceu no HEAD auditado. | Auditor/revisor separado verifica contratos e antipadrões; o mesmo executor não declara sua própria revisão como independente |

## Conflito histórico identificado — SP inutilização

A branch #446 mantém o antigo `tests/gateway/test_sp_inutilization_direct_guard.py`, que exige negar **toda** inutilização SP antes do A1. A arquitetura CURRENT do `pilot_sp_jurisdiction.py` afirma que a dispensa de obrigatoriedade em novembro/2026 **não é proibição**: o serviço SEFAZ-SP continuaria operacional durante a transição até março/2027. O teste corrente `tests/gateway/test_pilot_sp_jurisdiction.py` preserva essa regra para NF-e 55/NFC-e 65. **Não reintegrar o teste histórico sem revalidar a norma**: seria regressão funcional e bloquearia operação legalmente possível.

## Autoridades canônicas a preservar

- Autenticação: cookie/sessão assinados e autorização no backend; UI é apenas superfície.
- Contexto: `AuthenticatedHuman`, unidade/tenant e `ExecutionScope`; não aceitar headers/browser como autoridade.
- Emissão: `FiscalApplicationService` + UoW durável; nenhum contador fiscal paralelo.
- Assinatura A1: cofre existente, nunca transportar PFX em log/Git.
- Provedor: composição fiscal única, bindings por operação e tenant; sem registry paralelo.
- Recuperação: `fiscal-intents` idempotente e arquivo oficial sem retransmissão no replay.

## Gates para declarar fechado

1. Todas as mudanças em branch isolada, testes negativos de RBAC/tenant/unidade/idempotência quando afetados.
2. Ruff/Mypy/Pytest, frontend lint/typecheck/tests/build, E2E, Docker, segurança, PostgreSQL/restore e CI integral no **HEAD final**.
3. Parecer de revisão independente e inventário por função/hunk para #446/#449/#450.
4. T2 `block-completeness` verde somente quando **zero pendências internas reais**. Dependências externas operacionais permanecem `EXTERNAL_BLOCKED`, não migram para `DONE` por conveniência.
5. Promoção em `main` e `production` apenas após gates; backup/offsite/A1, schema DPS v22, staging e Go/No-Go por release são verificados em separado.

**Decisão:** este documento é um checkpoint técnico e NÃO altera os estados de release. 

## DRIFT DE LEIAUTE NFS-e POR AMBIENTE — DESCOBERTA ADICIONAL EM 15/11/2026

**Fontes oficiais, não inferência do chat:**
- Produção: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual — seção `NFSe-ESQUEMAS_XSD-v1.01-20260209` (atualizada em 04/11/2026).
- Produção restrita/homologação: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/producao-restrita — pacote `NFSe-ESQUEMAS_XSD-PRODREST-v1.01-20261020` (atualizada em 20/10/2026).
- Comunicado oficial 20/10/2026: https://www.gov.br/nfse/pt-br/noticias/cgnfs-e-informa-disponibilizadas-no-ambiente-de-testes-o-release-1-das-evolucoes-da-nota-tecnica-009 — NT009 Release 1 exclusiva de produção restrita e cronograma de produção futura 01/12/2026. O atributo XML `versao=1.01` por si só **não identifica** qual dos dois pacotes é aplicável.

**CURRENT de engenharia:** `issuance/nfse_dps_builder.py` fixa `_SCHEMA_VERSION="1.01"` + `tpAmb=2`; `xml/nfse_nacional_schema.py` pinou exclusivamente o pacote nacional de **20260209**; `gateway/nfse_national_homologation.py` envia a `sefin.producaorestrita.nfse.gov.br`. Isto configura **risco concreto de incompatibilidade do XML em homologação NT009**, não uma emissão oficial comprovadamente rejeitada (nenhuma rede oficial foi acionada). É trabalho **interno**: adicionar pacote oficial 20261020 hash-pinned, roteamento por perfil/ambiente de layout independente do atributo `versao`, testes dual-XSD e regressão; jamais substituir silenciosamente os arquivos 20260209 que ainda servem a produção.

**Prova negativa de identidade:** comparação literal em 15/11 de `NFSe_v1.01.xsd`, `tiposComplexos_v1.01.xsd`, `tiposSimples_v1.01.xsd` e `xmldsig-core-schema.xsd` do mirror público `nfse-nacional/nfse-php` contra `NFSE_NACIONAL_1.01` e `SANTANA_SIMPLISS_2026`: root NFS-e e assinatura podem coincidir entre mirrors, **mas complexos/simples são diferentes entre as três árvores**. Não tratar root idêntico como pacote integral homologado. A origem espelhada pública também não substitui o pacote oficial zip por SHA.

**Critério novo de aceite:** manifest por **ambiente + revisão de pacote**, hash SHA256 de todos os XSD oficiais originais, teste de cenário que diferencia os campos NT009 entre 20260209/20261020, runtime que pinne o perfil correto e negativo que falhe se schema de homologação for tratado como produção, sem alterar regras de produção sem prova. Prova operacional com SEFIN oficial permanece EXTERNAL_BLOCKED, mas construção interna da compatibilidade é **pendência interna**.
