# FIS-03 — pinning de certificados signatários de recibos nacionais

**Status:** incremento defensivo interno; **não encerra FIS-03 nem autoriza deploy/emissão real**.

## Fronteira de segurança

O verificador já confere XMLDSig RSA-SHA256, XSD NFSe NT009, chave e DPS
canônica. Antes deste incremento, o certificado X509 incluído no próprio
XML poderia ser autoassinado: integridade criptográfica não prova a
autoridade do signatário. Um comprovante sintético assinado não deve ser
confundido com autorização da SEFIN.

A configuração `NFCORE_NFSE_RECEIPT_SIGNER_SHA256` aceita **1 a 8**
fingerprints SHA-256 (64 caracteres hexadecimais cada) separados por vírgula,
sem espaço. Os hashes representam o certificado **DER exato que assina
o elemento externo NFSe**, não o certificado A1 do emitente presente em
DPS aninhada. O conteúdo XML é verificado criptograficamente **antes**
de comparar o certificado.

Exemplo **fictício e inválido para operação real**:

```text
NFCORE_NFSE_RECEIPT_SIGNER_SHA256=0000000000000000000000000000000000000000000000000000000000000000
```

**Nunca instalar o exemplo acima.** O operador deve obter, por canal oficial
autenticado e independente da resposta recebida, os certificados de
assinatura realmente autorizados pela SEFIN, confirmar sua finalidade e
identidade, conferir os hashes e registrar evidência da fonte/versionamento.
Não pinçar como confiável o hash extraído de um XML não confiável.
O arquivo de configuração de produção permanece fora do repositório.

- POST nacional canônico e POST de baixo nível **com transporte real**
  recusam sem pins válidos antes de acessar a rede.
- GET nacional real recusa sem pins antes de resolver o A1/abrir rede.
- Com pins configurados, XML assinado por certificado diferente é recusado,
  inclusive em testes com transporte sintético injetado.
- Valor ausente não habilita automaticamente uma operação real; valor vazio,
  inválido, duplicado ou acima do limite falha fechado. A configuração
  é global à instância, não uma permissão para outro tenant/unidade.
- A configuração deve acompanhar o runtime API responsável pela emissão e
  pela recuperação. Rotação de certificado requer nova conferência oficial,
  publicação controlada e testes de aceitação/rejeição. Os pins antigos
  devem ser retirados apenas após o encerramento das pendências emitidas.

## Evidência e limitações obrigatórias

**Este mecanismo é uma pinagem de certificado de assinatura, não uma
validação PKI completa.** Ainda devem ser implementados, revisados e
comprovados separadamente: cadeia de confiança ICP-Brasil/SEFIN,
autorização do signatário no período, finalidade e políticas de certificado,
LCR/OCSP assinadas com estado de revogação fresco, vigência no instante
comprovado de autorização (não apenas no relógio atual), provas históricas
de revogação e trilha imutável de política/consulta para replay e auditoria.
Além disso, consultar o contrato SEFIN vigente e a fonte exata do certificado.

Referências oficiais para instalação e atualização de raízes e regras de
revogação: [ITI — certificados das ACs ICP-Brasil](https://www.gov.br/iti/pt-br/assuntos/repositorio/certificados-das-acs-da-icp-brasil-arquivo-unico-compactado)
e [DOC-ICP-15.03](https://www.gov.br/iti/pt-br/assuntos/legislacao/documentos-principais/v9.1_IN2021_03_DOCICP15.03_compilada.pdf).

**Aceite deste incremento:** testes de pin correto, signer de outro
certificado, configuração malformada/ausente e prova de zero envio
na ausência de pins; Ruff/Mypy/Pytest/PostgreSQL/Browser/container em CI
do HEAD exato; revisão EGM independente. Sem dados, certificações,
ambiente ou credenciais reais incluídos. Não promover production antes
dos demais gates de FIS-03 e de infraestrutura.
