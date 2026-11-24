> **RECONCILIAÇÃO SUPERVENIENTE 13/11/2026 — Ler antes do histórico abaixo.**
> O estado IMPLEMENTING/NOT CERTIFIED registrado originalmente neste arquivo é um checkpoint histórico da PR #466, anterior às entregas das PRs #469 e #472 e à recuperação de WSDL/XSD municipais reais.
> A fonte atual de engenharia é o checkpoint [NFCORE_OSASCO_OFFICIAL_WCF_RTC_V22_FINAL_2026-11-13.md](NFCORE_OSASCO_OFFICIAL_WCF_RTC_V22_FINAL_2026-11-13.md), com contratos públicos e testes da fábrica executável api:app.
> O aceite final depende de CI integral SUCCESS no SHA de integração final da PR #468. Homologação municipal de contribuinte permanece uma evidência externa distinta.

---
# Osasco — engenharia isolada de NFS-e WCF RTC (13/11/2026)

**Status: IMPLEMENTING / NOT CERTIFIED.** PR sucessora de Cajamar #463@72f7ed5df2d57f77c2de72b00b9ccf19672b8337; a base nuclear #454 continua em Draft. Não há homologação oficial nem merge/deploy.

**Fontes municipais oficiais:**
- [Osasco — Manual Web Service v2.1, abril/2026](https://nfe.osasco.sp.gov.br/EissnfeWebApp/Portal/Manual/Geracao%20de%20NFS-e%20Via%20Web%20Service%202.1.pdf). RTC_EmitirNFE, RTC_EmitirNFELote, RTC_ConsultarNFE, RTC_ConsultarLote, ConsultarNotaCompleta e Cancelar; autenticação por chave específica de inscrição municipal.
- [Endpoint de homologação divulgado pela prefeitura](https://nfe.osasco.sp.gov.br/EissnfeWebApp/Portal/NfEletronica.aspx): https://homolog-nfe.osasco.sp.gov.br/EissnfeWebServices/NotaFiscalEletronica.svc?wsdl.
- [Orientação nacional de 29/10/2026](https://www.gov.br/nfse/pt-br/noticias/nfs-e-informa-diretrizes-sobre-a-obrigatoriedade-da-emissao-da-nfs-e-nacional-para-optantes-do-simples-nacional/) — ME/EPP Simples a partir de competência 01/11/2026 via NFS-e nacional; MEI desde 2023.

**Escopo planejado:** reaproveitamento seletivo dos cinco módulos e testes de Osasco originados na PR #461, sem importar Osasco/Barueri/Jundiaí por tabela ou copiar o núcleo B. Completar preparação no mesmo Portal e FiscalApplicationService/UoW, recibo original durável, dados RTC validados, credencial por tenant/unidade/CNPJ/IM, consulta do XML completo sem segundo POST, cancelamento de nota com aprovação e correlação, testes HTTP/E2E, mapeamento dos resultados, escopo e CI completa no HEAD exato.

**Dependências externas:** WSDL/schema vigente verificável, chave de autenticação municipal de contribuinte, resposta real de homologação e layout de impressão oficial. Não inserir segredos nem declarar 100% por artefatos sintéticos. Alterações às fronteiras protegidas do B exigem revisão e autorização de integração.


## Matriz viva — execução nesta branch (não é homologação)

| Capacidade | Código/contrato | Evidência | Estado |
| --- | --- | --- | --- |
| Web Service WCF v2.1, SOAP 1.1, homologação | `gateway/osasco_rtc_homologation.py` e builders | testes de gateway extraídos de #461 | IMPLEMENTED_NOT_CERTIFIED |
| Fiscal RTC / regime / competência | `gateway/osasco_rtc_issue_builder.py` | testes de tax fields e guarda NFS-e nacional | IMPLEMENTED_NOT_CERTIFIED |
| Fonte única, RPS e contador | `application/service.py`, `issuance/sp4_original_rps_archive.py` | mesma UoW, reserva, fingerprint, replay; teste HTTP novo | IMPLEMENTED_NOT_CERTIFIED |
| Preparação via mesmo Portal | `web/native_nfse_preparation.py` | teste HTTP Osasco, emissão municipal e bloqueio Simples ≥ 01/11/2026 | IMPLEMENTED_NOT_CERTIFIED |
| Ponte de emissão e consulta sem segundo POST | `runtime/sp4_municipal_provider_bridges.py` e `runtime/osasco_operational_composition.py` | E2E sintético com `Sp4ReviewedMunicipalPorts`; não é resposta oficial | IMPLEMENTED_NOT_CERTIFIED |
| Proteção da chave municipal | `runtime/osasco_credentials.py` | `SecretResolutionService` / `FiscalSecretVault`; conferência tenant/unidade/CNPJ/IM; testes sem credencial real | IMPLEMENTED_NOT_CERTIFIED |
| Contrato WSDL/XSD verificado de Osasco | WSDL 2026 citado, hash/schema e operação por método devem ser pinados | manual municipal v2.1 não inclui pacote de schema consumível aqui | EXTERNAL_CONTRACT_PENDING |
| Dados RTC reais por perfil fiscal | `OsascoRtcTaxFields` exigido pelo builder | classificação NBS, cClassTrib, cidade/incidência e tributos precisam de regra proveniente do motor fiscal | INTERNAL_PENDING |
| XML oficial completo e integridade | `ConsultarNotaCompleta` pelo recibo original; parser estrito `osasco_rtc_invoice_interpreter.py` | modelo de resposta da Prefeitura v10.6/2024 e regressões sintéticas de RPS/CNPJ/valor/nota única; XSD vigente e retorno oficial não verificados | IMPLEMENTED_SYNTHETIC / EXTERNAL_CONTRACT_PENDING |
| Cancelamento/substituição integrados no lifecycle | `osasco_rtc_cancellation_builder.py` cobre envelope; composição de comando/jornada ainda pendente | sem teste E2E de cancelamento no Portal em HEAD | INTERNAL_PENDING |
| Provisionamento real no entrypoint API | `build_osasco_trusted_transport` compõe contrato/secret por portas; não habilita automaticamente no `api:app` | depende da fonte governada de segredos e contrato de provedor | INTERNAL_PENDING / EXTERNAL_INPUT |
| CI do HEAD exato, PostgreSQL, frontend/E2E, containers | `feat/nfcore-web-osasco-ci-20261113` como branch de CI | conferir sucesso completo do SHA de #466, nunca herdar selo de #463 | PENDING |

**Não declarar Osasco 100% nesta fase.** O código é de engenharia, sem habilitação fiscal real. O retorno `RTC_EmitirNFE` com `Erro=false` não basta para arquivar nota autorizada; somente a consulta do XML completo, correlação do recibo e verificador oficial podem fazê-lo. O Portal permanece com autoridade canônica; não construir segundo motor nem autenticação paralela.

### Contrato oficial: pontos relevantes de operação

- A Prefeitura orienta uma **chave específica por inscrição municipal**; o segredo não é A1 e não deve ser colocado em manifesto versionado, Portal ou logs. A referência de credencial usa os contratos `SecretReferenceKind.CREDENTIALS`, `SecretUsagePurpose.PROVIDER_AUTHENTICATION` e o mesmo `SecretResolutionService`.
- O método `ConsultarNotaCompleta` filtra por `NumeroReciboUnico`. O manual diz que retorna dados completos em XML, mas não fornece naquele trecho um XML suficiente para mapear com segurança todos os campos fiscais. **Não inventar XML de prefeitura**.
- Os contratos oficiais distinguem RTC e emissão legada; o routing de competência é aplicado antes de abrir o transporte.

### Gatilho para fechamento

Concluir as pendências internas, demonstrar teste sintético real do `api:app` com WSDL/XSD fixture e chave sintética, revisão independente A/B e CI verde no HEAD da própria #466. Artefatos externos oficiais e credenciais reais permanecem fase distinta e não podem ser forjados. Não fazer merge/deploy sem autorização.


## Evidência adicional da Prefeitura — formato histórico da consulta (13/11/2026)

Fonte **oficial, porém histórica**: [Manual Web Service de Osasco v10.6, set/2024, páginas 18–20](https://nfe.osasco.sp.gov.br/EissnfeWebApp/Portal/Manual/Gera%C3%A7%C3%A3o%20de%20NF-E%20via%20Web%20Service%20V10.6.pdf). Descreve `ConsultarNotaCompletaResponse/ConsultarNotaCompletaResult` e `NotasGeradas/NotaFiscalRelatorioDTO`, com `NumeroRecibo`, `Numero`, `CodigoAutenticidade`, `Prestador/CNPJ`, `Valor`, `QtdeNotas`. O manual v2.1 de abril/2026 confirma que `ConsultarNotaCompleta` permanece disponível para qualquer competência.

Foi criado `gateway/osasco_rtc_invoice_interpreter.py`: uma nota, recibo, CNPJ e valor precisam coincidir com o `Sp4OriginalRps` durável; erro SOAP, múltiplas notas, cancelamento, DTD ou divergência não autorizam automaticamente. Os testes passam XML sintético baseado no **modelo documental** histórico e não substituem validação por WSDL/XSD oficial vigente, resposta real ou inspeção independente de autorização fiscal. O `Sp4MunicipalCanonicalGateway` continua exigindo o `verify_official_invoice_xml` injetado para promover o status a autorizado.

Ainda faltam integração do cancelamento no Portal, mapeamento RTC completo por política tributária validada, provisionamento real do entrypoint com os contratos de provedor e execução da matriz final no HEAD combinado.
