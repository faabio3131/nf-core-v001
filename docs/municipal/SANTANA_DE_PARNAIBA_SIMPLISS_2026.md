# Santana de Parnaíba/SP — Simpliss 2026, implantação municipal

**IBGE 3547304.** Documentação pública aponta Simpliss, NÃO SMARAPD
previsto na nota de planejamento SP-22 de 13/11/2026.

**Fontes municipais primárias**
- https://santanadeparnaiba.simplissweb.com.br/contrib/Home/NotificacaoNovoLayout
- https://santanadeparnaiba.simplissweb.com.br/contrib/app/nfse/DocumentoIntegracaoNotaNacional/Index
- https://santanadeparnaiba.simplissweb.com.br/contrib/app/nfse/DocumentoIntegracaoNotaNacional/DownloadArquivo?nomeDocumento=Manual+Integra%C3%A7%C3%A3o+Nota+Nacional+-+Simpliss+V1.00
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

**Documentos adicionais:** portal oferece XSD ZIP nacional e layouts
RTC; confirmar hashes, versões, correspondência 1.01 e regras vigentes
antes de marcar contrato oficial Simpliss como certificado. Os XSD
nacionais 1.01 já existem no NFCore, hash-pinned separadamente.

**Recuperação:** a versão pública do manual não publica GET por IdDPS.
Consulta por chave confirmada é read-only. Timeout de POST sem chave
não habilita replay, nem significa autorização comprovada.

**Estado:** em engenharia; não é homologação externa ou produção.
