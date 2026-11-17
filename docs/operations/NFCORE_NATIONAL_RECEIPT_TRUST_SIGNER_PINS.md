# FIS-03 — pinning de certificados signatários de recibos nacionais

**Status:** proteção de pinagem + validação offline de caminho/CRL para transporte real; **não encerra FIS-03 nem autoriza deploy/emissão real**.

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

**Validação adicional de cadeia e revogação (incremento interno).** Os
transportes HTTP nacionais padrão exigem, além dos pins de signatário, os
três parâmetros a seguir **antes de TLS ou rede**:

```text
NFCORE_NFSE_RECEIPT_CA_BUNDLE=/caminho-absoluto/protegido/acs-autorizadas.pem
NFCORE_NFSE_RECEIPT_CRL_BUNDLE=/caminho-absoluto/protegido/lcrs-assinadas.pem
NFCORE_NFSE_RECEIPT_ROOT_SHA256=<fingerprint-64-hex-da-raiz-oficial>
```

O conteúdo deve vir de fontes oficiais autenticadas, verificadas fora do
XML recebido. O bundle de AC contém certificados PEM de raízes e
intermediárias autorizadas (sem segredo); o bundle de LCR contém PEM
assinado pela AC emissora de cada certificado não raiz. Ambos devem
ter permissões de leitura restritas ao runtime e substituição atômica.
A aplicação verifica: integridade criptográfica de cada ligação da
cadeia, raiz exata SHA-256, BasicConstraints/KeyUsage de AC, validade
temporal dos certificados, LCR emitida pela AC correta, assinatura
e frescor da LCR, e serial revogado em qualquer ligação não raiz.
Material ausente, corrompido, expirado, sem raiz pinada ou com revogação
fecha a emissão/consulta; não existe fallback para apenas XMLDSig.
O preflight antes de rede exige **uma LCR verificável e vigente por AC**
do bundle, raiz assinada por si própria e certificados intermediários
assinados pela AC superior sem revogação. LCR de emissora ausente
não pode disparar POST e ser descoberta só depois da resposta.

**Limites de certificação pendentes:** não há ainda validação completa
RFC 5280 (name constraints, políticas/OIDs e pathLen), consulta OCSP
alternativa, identificação formal do signatário SEFIN em todas as
competências, validação histórica no instante de autorização e pacote
de evidências da situação de revogação no momento do registro.
Não afirmar FIS-03 100% encerrado sem esses requisitos e testes externos.
O mecanismo atual aplica verificação de LCR vigente no relógio atual;
revalidação histórica pode precisar LTV e provas imutáveis adicionais.

Referências oficiais para instalação e atualização de raízes e regras de
revogação: [ITI — certificados das ACs ICP-Brasil](https://www.gov.br/iti/pt-br/assuntos/repositorio/certificados-das-acs-da-icp-brasil-arquivo-unico-compactado)
e [DOC-ICP-15.03](https://www.gov.br/iti/pt-br/assuntos/legislacao/documentos-principais/v9.1_IN2021_03_DOCICP15.03_compilada.pdf).

**Aceite deste incremento:** testes de pin correto, signer de outro
certificado, configuração malformada/ausente e prova de zero envio
na ausência de pins; Ruff/Mypy/Pytest/PostgreSQL/Browser/container em CI
do HEAD exato; revisão EGM independente. Sem dados, certificações,
ambiente ou credenciais reais incluídos. Não promover production antes
dos demais gates de FIS-03 e de infraestrutura.
