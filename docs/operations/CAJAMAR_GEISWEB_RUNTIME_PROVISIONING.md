# NFCore · Cajamar GeisWeb · Composição operacional canônica

**STATUS:** construção de código sob certificação. **Não significa emissão real, homologação, merge ou deploy.**

## Problema corrigido

O adaptador de Cajamar já existia como ports injetáveis, mas o
`kordena_fiscal.runtime.api:app` (entrypoint real do contêiner) não os
ativava. Agora o entrypoint verifica uma configuração *opt-in* e chama
`build_cajamar_port_builder_from_environ` no mesmo
`build_runtime_fiscal_handler_factory` que já compõe NFS-e Nacional,
Extrema e operações fiscais genéricas. O builder recebe o
**mesmo `FiscalApplicationService`**, nunca abre outra persistência.

O default sem configuração conserva o município **não provisionado**.
A construção do Portal e da análise municipal de substituição não concede
por si só permissão de transmissão fiscal.

## Configuração externa posterior à conclusão da engenharia

Não inserir no Git credenciais, A1, certificados, chaves ou dados reais de
clientes. Quando autorizado em homologação, montar um arquivo JSON revisado
de contratos fiscais e definir:

`NFCORE_CAJAMAR_GEISWEB_CONFIG_PATH=/caminho/absoluto/reviewed.json`

O JSON contém EXATAMENTE os seguintes campos:

| Campo | Obrigatoriedade |
| --- | --- |
| `mode` | `reviewed-homologation` |
| `endpoint` | URL HTTPS oficial, terminada em `GeisWebServiceImpl.php`, host permitido |
| `namespace` | Namespace SOAP aprovado no WSDL |
| `wsdl_file`, `wsdl_sha256` | Arquivo local e digest SHA-256 real |
| `xsd_package_sha256` | Digest do pacote `SchemaSet` inteiro |
| `method_actions` | SOAPAction WSDL exata para `EnviaLoteRps`, `ConsultaLoteRps`, `ConsultaNfse`, `CancelaNfse` |
| `xsd_resources` | Dicionário `nome-relativo.xsd`: `sha256` de cada recurso oficial |
| `xsd_roots` | Root XSD para `EnviaLoteRps`, `ConsultaLoteRps`, `CancelaNfse`, `ConsultaLoteRpsResposta`, `CancelaNfseResposta` |
| `signature_profile` | Perfil XMLDSig expressamente aprovado por contrato: `rsa-sha256-enveloped-document` ou, somente se oficial exigir, `rsa-sha1-enveloped-document` |
| `issuers` | Array de políticas fiscais revisadas, específico por tenant/unidade/CNPJ |

Cada política em `issuers` exige exatamente:
`tenant_id`, `unit_id`, `issuer_cnpj`, `fiscal_profile_id`,
`fiscal_profile_version`, `tax_regime`, `launch_type`,
`geisweb_regime` e `service_city`.

Esses parâmetros são **regras de serialização do contrato externo**, não
autoridades novas de usuário, tenant, unidade, numeração ou tributação.
O `FiscalProfile` canônico precisa coincidir com os dados revisados; um
`CNPJ` não listado jamais herda política de outro contribuinte. O Portal
não recebe nem pode sobrescrever esses parâmetros.

Os arquivos WSDL/XSD ficam no diretório do manifest. O carregador rejeita
caminhos fora da pasta, mudança de digest, schema incompleto, perfis de
assinatura desconhecidos, políticas de emitente duplicadas e configuração
sem cofre A1. A compilação do XSD não acessa a internet. A assinatura é
gerada no port criptográfico já existente (`append_nfse_signature`)
com certificado obtido somente do **A1 Vault existente**, resolvido pela
identidade e escopo do emitente. Validação independente de hash da assinatura,
algoritmo, referência, certificado e XSD ocorre antes de transmitir.

**IMPORTANTE:** apenas preencher esse JSON não habilita uma prefeitura nem
prova a correspondência do padrão. O WSDL/XSD, a modalidade de XMLDSig e
os códigos GeisWeb precisam ser fornecidos/revistos pelo responsável fiscal
e confrontados com a prefeitura antes de habilitar o runtime.

## Checklist de aceitação de construção

1. Sem variável de ambiente → runtime anterior intacto; Cajamar sem transport.
2. Configuração incompleta/adulterada → startup fail-closed.
3. Configuração revisada com artefatos → mesma aplicação conecta ports de
   emissão, consulta e cancelamento sem segundo banco, auth ou signer.
4. Issuer/tenant/registro fiscal diverge → operação recusada antes do A1/HTTP.
5. Assinatura e validação XMLDSig/XSD → ports de código disponíveis e testáveis.
6. Estados de emissão, reconciliação, idempotência e arquivos oficiais seguem a
   mesma `FiscalApplicationService` e as mesmas migrations.
7. Auditoria de CI: Ruff, Mypy, Pytest/PostgreSQL, lint/build/frontend, Docker e
   políticas de segurança no **HEAD exato**.
8. Somente após certificação do HEAD, revisar a dependência da PR #454;
   manter a #463 em Draft até autorização explícita para merge.
9. Deploy, emissão fiscal, modificações no cofre e cadastro externo continuam
   processos futuros e separados.

**O que a engenharia NÃO inventa:** WSDL municipal oficial atual, resposta
fiscal real, certificado de cliente, link oficial de impressão ou operação
SOAP nativa de substituição. A análise de substituição do Decreto Municipal
7.311/2024 exige operação humana no sistema do município e prova externa.

## Reconciliation 19/11/2026 — embalagem Contabo e identidade da substituição

O entrypoint já estava composto. O overlay versionado `deploy/contabo/compose.cajamar-geisweb.api.yml` agora oferece montagem somente leitura, opt-in, no MESMO serviço API, sem criação automática de pasta ou segundo cofre. Exige `NFCORE_CAJAMAR_REVIEWED_HOST_DIR` apontando ao diretório oficial previamente revisado, com `manifest.json` e WSDL/XSD. Integrar esse overlay somente depois de gates, autorização e material revisado. Nenhuma alteração no host realizada. O teste de composição existente recebeu asserções da montagem, preservação do Vault e falha sem input; não foi executado nesta entrega.

A revisão de substituição agora exige que a jurisdição do emitente candidato seja a mesma do original, além do CNPJ, unidade e local do serviço, com regressão escrita. Não cria SOAP de substituição, não fecha CANCEL_REQUESTED após timeout, não fabrica PDF municipal; esses itens são distintos. A ausência de contrato/prova externa de substituição não constitui autorização para criar regra fiscal.

## Cancelamento incerto — correção de segurança 19/11/2026

O manual GeisWeb20 §13.4 (https://atendimento.tecnospeed.com.br/hc/pt-br/article_attachments/1500009353402/Manual_GeisWeb20.pdf) distingue código 11 (nota já cancelada), 10, 12 e 14. Esses códigos e desconhecidos não comprovam nota ativa. A aplicação grava o intent original em arquivo fiscal na mesma transação do claim CANCEL_REQUESTED, antes do I/O; guarda a resposta correlacionada quando recebida e mantém CANCEL_REQUESTED para resultados incertos. Apenas resposta de cancelamento vinculada confirma CANCELLED; rejeição explícita da solicitação (allowlist) pode restaurar AUTHORIZED. Portal informa investigação, sem rePOST. Testes de código 11, códigos desconhecidos, timeout, intent durável e replay escritos, não executados. A consulta §13.2 não estabelece status de cancelamento inequívoco, portanto consulta bem-sucedida e ausência de nota não permitem finalizar o evento. O fechamento automático ainda depende de contrato/prova externa verificável; não inventar campo de situação.
