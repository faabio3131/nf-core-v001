# Santana de Parnaíba/SP — Simpliss 2026, implantação municipal

**IBGE 3547304.** Documentação pública aponta Simpliss, NÃO SMARAPD
previsto na nota de planejamento SP-22 de 13/11/2026.

**Fontes municipais primárias**
- https://santanadeparnaiba.simplissweb.com.br/contrib/Home/NotificacaoNovoLayout
- https://santanadeparnaiba.simplissweb.com.br/contrib/app/nfse/DocumentoIntegracaoNotaNacional/Index
- https://santanadeparnaiba.simplissweb.com.br/contrib/app/nfse/DocumentoIntegracaoNotaNacional/DownloadArquivo?nomeDocumento=manual_integracao_nota_nacional_-_simpliss_v1.00
- Swagger produção restrita: https://producaorestrita.simplissweb.com.br/swagger/index.html

**Contrato do Manual Simpliss V1.00 (outubro/2025):** JSON com XML
assinado XMLDSig, compactado GZip/Base64, A1/A3 mTLS. POST /nfse emite
DPS; GET /nfse/{chaveAcesso} consulta; POST /nfse/{chaveAcesso}/eventos
registra cancelamento 101101 e GET do mesmo caminho consulta eventos.
Substituição é outra DPS contendo chave substituída, resultando no evento
de cancelamento automático; não inventar SOAP SubstituirNfse.

**Autoridade do NFCore:** novo provider municipal explícito, reutiliza
a numeração DPS durável, builder nacional, A1 do cofre, verificador XMLDSig
do recibo e a UoW fiscal existente. Sem segundo contador, ledger, API ou
canal de emissão sem autorização. O certificado oficial da assinatura
municipal e seu trust-chain exigem prova externa separada.

**Não inventar rota do provedor:** o manual remete ao Swagger para URL base,
e seu acesso não autenticado retornou 403 na auditoria. URL exata de
produção restrita somente pode ser informada em configuração revisada
e restrita à origem HTTPS do provedor, sem token real no repositório.
Não assumir que o domínio da Swagger é o caminho HTTP final.

**Contratos oficiais capturados, versionados e executáveis:** o download
público municipal foi adquirido em auditoria GitHub Actions, e seu pacote
XSD 2025-12-10 contém **18 arquivos originais** em
`contracts/official/santana/simpliss_2026/xsd/`. O `manifest.json`
preserva URLs e SHA-256 do ZIP, manual e das planilhas de DPS, eventos e
RTC, assim como o hash e o tamanho de cada XSD. Os conjuntos municipais
DPS, NFS-e, pedido e registro de evento v1.01 são compilados offline
com integridade verificada. O código utiliza as cópias municipais pinadas,
preservando bytes oficiais e tratando explicitamente as derivações XSD
auditadas. Os artefatos de classificação NBS 2.0 e correlação RTC
também possuem inventário de origem e hashes verificáveis. Conferir
`tests/runtime/test_santana_official_contracts.py`,
`src/kordena_fiscal/xml/santana_simpliss_schema.py` e o fluxo
`santana-official-contracts.yml`. A captura de documentos públicos
não equivale a assinatura ou aceite fiscal pelo município.

**Implementação canônica existente na PR #496 (sem merge):**
- Preparação HTTP autenticada: NBS 2.0 revisada, numeração DPS reservada
  em persistência canônica, A1 do cofre e XSD Simpliss de emissão;
  `issueFiscalDocument` envia a DPS exatamente uma vez.
- Consulta: `GET /nfse/{chaveAcesso}` somente após chave oficial conhecida,
  XML autorizado verificado, arquivo fiscal e ciclo idempotente existentes.
- Cancelamento: `cancelSantanaNfse` exige aprovação humana, prova de NFS-e
  previamente autorizada, evento 101101 assinado, reivindicação durável
  anterior ao POST e arquivamento da resposta oficial validada.
- Substituição: `substituteSantanaNfse` usa **nova DPS**, com `subst`,
  motivação legal, revisão do original e mesmo emitente/tenant/unidade;
  reivindica os dois documentos na UoW e confirma a mudança por resposta
  assinada, sem simular um endpoint de substituição inexistente.
- Recuperação de POST incerto: `reconcileSantanaNfseCancellation` e
  `reconcileSantanaNfseSubstitution` utilizam a rota oficial
  `GET /nfse/{chaveAcesso}/eventos`, XMLDSig e XSD municipais;
  para substituição, a nova NFS-e é buscada por chave oficial e vinculada
  à DPS numerada e ao `chSubstda` originais. Ausência de confirmação
  mantém o estado pendente, sem novo POST.
- Uma única cadeia de RBAC, sessão e permissões do Portal, identidade de
  tenant/unidade e persistência; nenhuma segunda API, regra fiscal ou ledger.
- Testes dirigidos: `tests/gateway/test_santana_simpliss_*.py`,
  `tests/runtime/test_santana_*.py` e
  `tests/web/test_native_nfse_preparation_http.py` validam contratos reais,
  assinatura sintética RSA, HTTP/SQLite, replay, escopo, rejeições,
  timeout/recuperação e aprovação. O workflow
  `santana-internal-gates.yml` executa Ruff, Mypy e regressões focadas.

**Limites separados de engenharia interna e homologação externa:**
1. A URL REST exata da produção restrita deve ser revisada a partir do
   Swagger autorizado pelo operador; o Swagger anônimo retornou HTTP 403.
2. O mTLS com A1 real, a cadeia de confiança do emissor oficial e a
   confirmação do município em sua infraestrutura exigem credenciais e
   ambiente externos. Teste sintético não é homologação externa.
3. O manual não informa GET de DPS apenas por IdDPS; caso haja timeout de
   emissão antes da chave, fica aberto um estado incerto para investigação
   assistida, jamais um reenvio automático.
4. Sem autorização humana específica não realizar merge, deploy, migration
   produtiva, publicação em produção ou envio fiscal real.

**Evidências e fechamento:** o código só será certificado internamente
quando `Santana Internal Engineering Gates` e **toda a matriz de
`FM NFCORE V1 CI`** terminarem em SUCCESS no **HEAD exato** desta PR.
Os IDs das execuções aprovadas devem constar no registro do PR; CI de
commit anterior não certifica novos commits. A PR #496 permanece em Draft
até esse gate e o encaminhamento autorizado para a candidata cumulativa.
**Situação de homologação externa:** não comprovada, separada da engenharia.
