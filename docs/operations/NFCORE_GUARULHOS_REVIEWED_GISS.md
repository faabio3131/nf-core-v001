# Guarulhos — contrato revisado GISS na API existente

O canal é exclusivamente de homologação. A variável `NFCORE_GUARULHOS_GISS_CONFIG_PATH`
aponta para um manifesto absoluto, fornecido pelo operador, com
`municipality_ibge: "3518800"` e `mode: "reviewed-homologation"`.
Sem a variável não há ativação; com configuração inválida o startup falha fechado.
O cofre A1 canônico deve estar configurado. Não inserir PKCS#12 ou senha no manifesto.

O formato e a validação são os mesmos de `JundiaiReviewedStartup.load`, com município
explícito. São obrigatórios WSDL, ações SOAP, 24 recursos XSD, hash do pacote,
entrypoints, certificado público do assinante municipal e políticas dos emitentes.
Cada arquivo é referenciado por nome simples e SHA256. O emitente é vinculado a
tenant/unidade, CNPJ, perfil/versão, regime e município. Não reutilizar uma política
fiscal de Jundiaí por mera igualdade dos schemas.

Os 24 schemas oficiais são compartilhados por identidade de bytes, conforme
`contracts/official/guarulhos/giss_v2_04/shared-schema-manifest.json`.
Copiar esses recursos para o diretório revisado; obter e revisar o WSDL e a identidade
municipal no processo oficial. Certificados/WSDL sintéticos de testes não podem
ser instalados como contrato homologado.

Para a composição Contabo existente, adicionar explicitamente
`deploy/contabo/compose.guarulhos-giss.api.yml` à lista de arquivos Compose e definir
`NFCORE_GUARULHOS_REVIEWED_HOST_DIR` com diretório já existente e legível pelo usuário
não root da API. O mount é somente leitura. Este documento não altera o host nem
autoriza migração, emissão ou cancelamento reais.

O Portal reutiliza sessão/RBAC, tenant/unidade, intenção durável e arquivo fiscal.
Cancelamento requer `document.cancel`; revisão de reemissão requer também
`document.issue`; conciliação requer `reconciliation.execute`.
O fluxo de reemissão cancela o original e emite o substituto separadamente. Não é
`SubstituirNfse` atômico. Resultado incerto exige consulta, nunca retransmissão cega.

Aceite operacional pendente: manifesto real revisado, A1 do emitente, transmissão e
consulta oficial, confirmação de cancelamento arquivada e prova na revisão implantada.


### Correction — 2026-11-19
The shared official ConsultarNfseRpsEnvio schema does not permit a root Id
attribute. The reviewed runtime signs the entire read-only request with an
empty URI and checks that exact root, a single direct enveloped signature,
digest and pinned A1. Mutating operations and municipal invoice/cancellation
proof retain Id-bound verification. The official XSD bytes are unchanged.
A regression test uses the 24 official schema resources and synthetic signing
material; it has not been executed in this construction round.
