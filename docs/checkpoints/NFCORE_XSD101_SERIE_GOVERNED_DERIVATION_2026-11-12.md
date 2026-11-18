# NFCore — Exceção controlada de compatibilidade XSD NFS-e Nacional 1.01 (TSSerieDPS)

Data: 12/11/2026. Responsável: Agente B (motor fiscal). Escopo: serial DPS #427 e incidente #451.
Estado: CANDIDATO DE IMPLEMENTAÇÃO / CI NO HEAD PENDENTE / NÃO HOMOLOGADO.
Branch isolada: fix/nfcore-b-xsd101-serie-governed-20261112 (derivada de #451@334821b53).
Não é merge, migração v22, alteração no XSD oficial, emissão fiscal real ou homologação.

## Fato e causa

A cópia nacional em src/kordena_fiscal/xml/official/NFSE_NACIONAL_1.01/tiposSimples_v1.01.xsd
possui, em TSSerieDPS, a restrição:

    <xs:pattern value="^0{0,4}\d{1,5}$"/>

Expressões XSD são implicitamente ancoradas: ^ e $ não funcionam como âncoras PCRE.
A regra rejeita séries fiscais 1, 17, 00001 e aceita indevidamente texto com ^ e $.

Fontes verificadas:
- Catálogo oficial do Emissor Nacional, atualizado em 04/11/2026:
  https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/documentacao-atual
- URL do ZIP 1.01 vinculada pelo catálogo:
  https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/nfse-esquemas_xsd-v1-01-20260209.zip
- Definição W3C de regex XSD:
  https://www.w3.org/TR/xmlschema/#regexs

LIMITAÇÃO DE PROVENIÊNCIA: catálogo e URL foram conferidos, mas não foi possível
baixar o ZIP binário oficial e comparar seus arquivos byte a byte nesta execução.
Os SHA-256 abaixo são da cópia versionada no GitHub e de seu derivado em memória.
Antes da promoção, comparar obrigatoriamente com o ZIP oficial obtido independentemente.

## Regra da exceção

Nenhum arquivo sob xml/official/ foi modificado. O carregador verifica SHA-256
do recurso original com SchemaResource antes de toda derivação. Somente na
versão 1.01 para o nome exato tiposSimples_v1.01.xsd, confere que o padrão
ocorre exatamente uma vez, substitui somente esse trecho em memória e confere
SHA-256 independente fixado do derivado. Drift resulta em SchemaIntegrityError.

| Identidade | Valor |
|---|---|
| Arquivo fonte | NFSE_NACIONAL_1.01/tiposSimples_v1.01.xsd |
| SHA-256 da cópia original no repositório | 41df4fd084b80d86200e0edb1d7d8df4adbc7fb6d19b93f35014a9dcbb8a2fa9 |
| Padrão original | ^0{0,4}\d{1,5}$ |
| Padrão derivado | 0{0,4}\d{1,5} |
| SHA-256 do derivado determinístico | 42a3026812524f787c5157cb1d6411d4461151798a33569df069c3f35ef18773 |
| Arquivos oficiais alterados | 0 |
| Outros elementos do schema alterados | 0 |
| Schema 1.00 alterado | NÃO |

O hash de pacote do XmlSchemaValidator utiliza os recursos efetivamente
compilados e identifica o derivado; não o mascara como schema oficial intocado.

## Evidência independente executada

Ensaio isolado com Java JAXP javax.xml.validation.SchemaFactory (não utiliza
o validador lxml do NFCore). Um XSD mínimo com a restrição mostrou:

| Série | Original | Derivado |
|---|---|---|
| 1 | REJEITA | ACEITA |
| 17 | REJEITA | ACEITA |
| 00001 | REJEITA | ACEITA |
| ^1$ | ACEITA | REJEITA |
| 12A | REJEITA | REJEITA |

O ensaio prova semântica regex, NÃO a DPS completa assinada e válida conforme
todos os esquemas oficiais. Isso permanece gate obrigatório.

## Critérios de aceite

- [x] Arquivos oficiais versionados preservados.
- [x] SHA-256 do original versionado confrontado com o pin existente.
- [x] Diff de um só padrão, com hash próprio verificado.
- [x] Ensaio mínimo em validador independente.
- [x] Testes de regressão adicionados para digest, drift e valores de série.
- [ ] CI completa no HEAD final (Ruff, Mypy, Pytest, PostgreSQL real).
- [ ] Comparação contra pacote ZIP oficial baixado e verificado.
- [ ] Validação XSD e XMLDSig independente da DPS assinada completa.
- [ ] Integração #427 + #450 + delta de #446 certificada no mesmo HEAD.
- [ ] Migração v22 expressamente aprovada (não executada).
- [ ] Homologação externa com A1 real (não executada).

Não alterar arquivo oficial, não relaxar teste, não mesclar nem executar DDL
ou produção em consequência desta PR.
