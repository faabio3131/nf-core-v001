## CURRENT reconciliado — continuidade 05/11/2026

Este registro prevalece sobre o snapshot de planejamento abaixo, sem promover estados globais.

- Repositório atual: faabio3131/nf-core-v001; main 3f56084041fc9cd441af9a61dcc9532ba6090a85.
- PRs #355/#356/#359 MERGED; #358 OPEN, destino production, sem merge nesta execução.
- PR #360 OPEN/DRAFT, base deste incremento feedf8b41085914b831c9585bec1b34675742008:
  inventário prioritário, bindings negativos e catálogo MG 55/65; Governança #1120 SUCCESS;
  CI #1689 ainda em execução na consulta inicial. Não presumir certificação.
- Branch deste incremento: feat/nfcore-nat03-mg-provenance, baseada no HEAD da #360.
- NAT-00 AUDITED (reconciliação interna; production não promovida).
- NAT-01 IMPLEMENTING: pesquisa/inventário em #360; contrato/ADRs globais ainda pendentes.
- NAT-03/04 IMPLEMENTING: autorização MG NF-e 55 reutiliza transporte SOAP e Vault;
  requer validador XSD confiável. Não registra provider/binding nem modifica runtime.
- NAT-UF-MG IMPLEMENTING/PARTIAL; RJ/PR/MT/MS sem módulos internos completos.
- Detalhes, mapa de impacto e critérios:
  docs/NFV1_NAT03_MG_AUTHORIZATION_CONTINUITY_2026-11-05.md.
- Ruff global PASS; Mypy direcionado PASS. Mypy global Windows encontrou 8 erros
  em 5 arquivos fora desta mudança: APIs POSIX ausentes no Windows e dependência
  brazilfiscalreport.danfe ausente. Não desabilitar verificações; CI Linux é gate obrigatório.
- Nenhuma transmissão fiscal real, credencial nova, migration, deploy ou homologação.
- Próxima ação: certificar CI desta candidata; congelar XSD/WSDL reais e composição
  com autoridade XmlSchemaValidator; depois demais operações MG, NFC-e e NFS-e BH.
- Merge main e promoção production aguardam autorização específica.

---

# NFCore National Expansion — Ledger de Estado e Continuidade

**Documento:** NFV1-NAT-LEDGER-001  
**Data:** 2026-11-05  
**Status:** planejamento documental, NÃO certificação técnica.  
**Fonte superior:** GitHub current, código, CI e evidência.  
**Escopo:** `docs/NFV1_NATIONAL_EXPANSION_MASTER_ARCHITECTURE_2026-11-05.md` + `docs/NFV1_NATIONAL_EXPANSION_MASTER_EXECUTION_SCHEDULE_2026-11-05.md`.

## Checkpoint atual

- Repositório: `faabio3131/nf-core-v001`.
- Branch deste planejamento: `docs/nfcore-national-fiscal-expansion-architecture-20261105`; baseada na `main` e sem alterações de runtime.
- PR #355: roteamento municipal SP em branch separada, em Draft na última checagem; **não absorvida neste planejamento**.
- Production/Contabo: nenhuma modificação por esta entrega.
- Cuidado: prontidão multi-tenant, modelos/UF na arquitetura **não** são homologação externa.
- Próximo bloco: **NAT-00**, reconciliação PR #355 + contratos canônicos + bootstrap de fontes oficiais MG.
- Go/No-Go: aprovação de arquitetura e cronograma pelo Diretor antes de implementação definitiva; aprovação específica para deploy/migrations/credenciais e homologação oficial.

## Ledger plataforma

| ID | CURRENT | TARGET | Status | Dependência | Evidência exigida |
| --- | --- | --- | --- | --- | --- |
| NAT-00 | PR #355 não integrada no momento da leitura | conciliar PR, main, production, CI | NOT_STARTED | CI + revisão | SHA e diff atuais, CI, decisões |
| NAT-01 | ProviderBinding/Resolver canônicos | contrato nacional versionado e governado | NOT_STARTED | NAT-00 | ADR+tests sem dupla autoridade |
| NAT-02 | tenant/unidade e perfil fiscal | vínculo escritório↔clientes e matriz/filial | NOT_STARTED | NAT-00 | RBAC, revogação, testes isolamento |
| NAT-03 | routing persistente por jurisdição | catálogo oficial versionado de endpoints | NOT_STARTED | NAT-01 | fontes/proveniência/approval |
| NAT-04 | gateway NF-e SP / modelos canônicos | adaptadores reutilizáveis UF/modelo/operação | NOT_STARTED | NAT-03 | XSD/SOAP/assinatura/ops |
| NAT-05 | Vault A1/CSC parcialmente existente | CSC/QR NFC-e governados por UF | NOT_STARTED | NAT-03/04 | QR oficial, sem logs de segredo |
| NAT-06 | NFS-e nacional + SP em construção | competências e famílias municipais | NOT_STARTED | NAT-01/03 | contratos municipais/nacionais |
| NAT-07 | Portal fiscal parcial | jornadas Web completas 55/65/serviço | NOT_STARTED | NAT-02/04/06 | Chromium+RBAC+download |
| NAT-08 | CI e idempotência existentes | stress PostgreSQL/recovery/observabilidade | NOT_STARTED | NAT-04/05/06 | 50/100, locks, métricas |
| NAT-09 | governança e CI existentes | certificação/gates por UF/doc/ambiente | NOT_STARTED | NAT-00..08 | ledger e gates completos |

## Ledger UF — todas as 27 unidades federativas

`NOT_STARTED` indica que **a nova expansão nacional** ainda não foi executada, não nega componentes anteriores ou trabalho da PR #355.

| Ordem | ID | Status nacional | Bloqueio ou próxima ação |
| ---: | --- | --- | --- |
| 0 (reconciliar) | NAT-UF-SP-RECONCILE | NOT_STARTED | revisar PR #355, não duplicar código |
| 1 | NAT-UF-MG | NOT_STARTED | contratos oficiais MG NF-e/NFC-e e Belo Horizonte NFS-e |
| 2 | NAT-UF-RJ | NOT_STARTED | SVRS NF-e e NFC-e RJ independente; NFS-e Rio |
| 3 | NAT-UF-PR | NOT_STARTED | PR NF-e/NFC-e, CSC/credenciamento, Curitiba |
| 4 | NAT-UF-MT | NOT_STARTED | MT NF-e/NFC-e, CSC/QR, Cuiabá |
| 5 | NAT-UF-MS | NOT_STARTED | MS NF-e/NFC-e, Campo Grande |
| 6 | NAT-UF-RS | NOT_STARTED | Porto Alegre, autorizador próprio |
| 7 | NAT-UF-SC | NOT_STARTED | Florianópolis; SVRS/contratos atuais |
| 8 | NAT-UF-ES | NOT_STARTED | Vitória; SVRS/contratos atuais |
| 9 | NAT-UF-GO | NOT_STARTED | Goiânia |
| 10 | NAT-UF-DF | NOT_STARTED | Brasília |
| 11 | NAT-UF-BA | NOT_STARTED | Salvador |
| 12 | NAT-UF-PE | NOT_STARTED | Recife |
| 13 | NAT-UF-CE | NOT_STARTED | Fortaleza |
| 14 | NAT-UF-PA | NOT_STARTED | Belém |
| 15 | NAT-UF-AM | NOT_STARTED | Manaus |
| 16 | NAT-UF-MA | NOT_STARTED | São Luís; SVAN NF-e |
| 17 | NAT-UF-PB | NOT_STARTED | João Pessoa |
| 18 | NAT-UF-RN | NOT_STARTED | Natal |
| 19 | NAT-UF-PI | NOT_STARTED | Teresina |
| 20 | NAT-UF-AL | NOT_STARTED | Maceió |
| 21 | NAT-UF-SE | NOT_STARTED | Aracaju |
| 22 | NAT-UF-TO | NOT_STARTED | Palmas |
| 23 | NAT-UF-RO | NOT_STARTED | Porto Velho |
| 24 | NAT-UF-AC | NOT_STARTED | Rio Branco |
| 25 | NAT-UF-AP | NOT_STARTED | Macapá |
| 26 | NAT-UF-RR | NOT_STARTED | Boa Vista |

## Registro obrigatoriamente preenchido a cada bloco

```
Data:
ID:
CURRENT branch + SHA:
TARGET:
Fontes oficiais + URL + data + versão/hash:
Escopo congelado:
Dependências e áreas protegidas:
Alterações de domínio/application/infra/DB/API/Web:
Testes Ruff/Mypy/pytest/postgres/frontend/Chromium/Docker/security:
CI/Governança (run e conclusion):
PR:
Merge (quando autorizado):
Smoke/homologação externa (se aplicável):
Riscos/blockers:
Próximo bloco:
```

**Nunca marcar CHECKED/CONCLUÍDO apenas por documentação, PR aberta, health 200 ou teste sintético.**

## NAT-03/04 — evidência incremental na PR #361

- Branch: feat/nfcore-nat03-mg-provenance. Primeiro commit a027b967c26af6869f3cb21f3be97df055653628.
- PR base #360: CI #1689 SUCCESS e Governança #1120 SUCCESS confirmadas.
- PR #361: Governança #1121 SUCCESS no primeiro commit; CI #1690 iniciada no SHA.
- Regressão local do primeiro incremento: 178 PASS; 18 testes MG PASS; Ruff global e Mypy direcionado PASS.
- Segundo incremento: download oficial PL_010g v1.03, cinco XSD NFe exatos, manifesto com hash,
  loader offline via SchemaResource/SchemaSet/XmlSchemaValidator, composição explícita MG com
  validação real da NFe assinada e negativa de XML incompleto antes de transporte.
- Testes XML + transporte MG após o incremento: 34 PASS; Ruff global PASS; Mypy dos dois módulos PASS.
- Zip original: b329ecbe7e4c05a41bfbc1527f105defb7047328acfeada7c77e1666da485eaf.
- Limite: não contém schema completo de envelope/eventos/WSDL; não representa vigência homologada,
  golden case autorizado, provider ativado, tributação/RTC certificada ou integração estadual completa.
- Evidência final de SHA/CI e packaging: registrar na PR #361; estados globais permanecem IMPLEMENTING.
- Próximo bloco: pacote completo enviNFe e operações, vigência por tpAmb e golden cases oficiais MG;
  em seguida NFC-e MG e NFS-e BH, depois RJ → PR → MT → MS.

### NAT-04 — incompatibilidade de assinatura identificada e correção MG

O XMLDSig do pacote oficial exige RSA-SHA1/SHA1; default anterior gera SHA256.
Perfil explícito NFE4_OFFICIAL_RSA_SHA1 adicionado ao assinador existente e
selecionado apenas no alvo MG homologação. Signature validada contra XSD real
e verificada criptograficamente em teste. Default SP e eventos não foram alterados;
sua compatibilidade oficial permanece PENDÊNCIA, sem homologação declarada.
Wheel e hashes exatos dos cinco XSD no índice/distribuição PASS.
Mypy dirigido de três módulos PASS. Não promover estados globais.

Regressão final do segundo incremento: **196 PASS em 60,31s**, zero falhas,
abrangendo XML, gateways, control_plane e A1 sintético. Ruff global PASS,
Mypy dirigido PASS, plano 59 IDs PASS. CI Linux no SHA final continua gate pendente.

## Continuidade MG — branch feat/nfcore-mg-lifecycle-20261105

Base 7739fd1587f2cb59f07032523b282c218da6a210, PR #361, CI #1691 e Governança #1122 SUCCESS.
CURRENT main permanece 3f56084041fc9cd441af9a61dcc9532ba6090a85.
Escopo NAT-03/04 / NAT-UF-MG-T03/T04 parcial:
consulta, cancelamento e inutilização MG55 no transporte compartilhado, XSD
offline completo de operações/envelope e verificação criptográfica após SOAP.
Snapshot interno composto MG_LIFECYCLE_20261105 possui fontes e hashes por arquivo;
não representa homologação oficial ou vigência aprovada por contribuinte.
44 testes dirigidos de operações/schema passaram antes da regressão ampliada.
Teste positivo: NF-e sintética completa → assinatura → XSD enviNFe → SOAP com
digest/assinatura verificados → resposta local → nfeProc validado por XSD.
Bugs de causa raiz corrigidos: literal CONSULTAR, SOAPAction e namespaces SOAP
que alteravam a canonicalização. Detalhes e gaps internos:
docs/NFV1_MG_LIFECYCLE_CONTINUITY_2026-11-05.md.
Estados globais NAT-UF-MG e transversais continuam IMPLEMENTING.
Próximo bloco: runtime governado e preparação/recuperação Web; resolver ano explícito
de inutilização, seguir NFC-e MG e NFS-e BH antes de promover MG como completa.
PR/SHA/CI final devem constar na PR deste incremento. Sem merge/deploy nesta execução.

Gate local da continuidade MG: **265 PASS em 97,55s**; Ruff global, Mypy dirigido
(cinco módulos), plano de 59 tarefas e validação BUILD PASS. Wheel construída.
Cenário positivo de NF-e completa assinada e nfeProc validado é sintético e
comprova contrato estrutural/criptográfico; não comprova tributação ou homologação.


## NFS-e Nacional — validação do município emissor na DPS (06/11/2026)

- O gateway canônico de produção restrita passou a exigir o código IBGE do endereço do perfil fiscal do emitente e conferir o campo `infDPS/cLocEmi` antes do POST. O município de prestação é um dado distinto. A regra não habilita emissor nem substitui o vínculo durável.
- A regressão exercita São Paulo, Belo Horizonte, Rio de Janeiro, Curitiba e Cuiabá contra um XML assinado com município emissor divergente. O builder confiável, a jornada Web por unidade e a homologação contábil continuam como dependências.
- Campo Grande: em nova checagem, o portal municipal de homologação respondeu, mas o hostname de lotes do WSDL oficial ABRASF 2.03 retornou NXDOMAIN. O adaptador continua sem ativação. Fonte: [comunicado da prefeitura](https://cdn.campogrande.ms.gov.br/portal/prod/uploads/sites/29/2026/03/Comunicado-RPS-Integracao-Web-Service-2.pdf).
- Jundiaí: a prefeitura confirma o uso do emissor nacional pelas empresas do Simples a partir de 01/11/2026. Evidência de canal e vigência, sem aprovação automática do provider. Fonte: [comunicado municipal](https://jundiai.sp.gov.br/noticias/2026/10/29/nota-fiscal-de-servicos-empresas-do-simples-nacional-devem-usar-emissor-nacional-a-partir-de-1o-de-novembro/).

## NAT-UF-MG-T04 — consulta NF-e 55 na composição canônica

Em 05/11/2026, `main` estava em `b1769429d651ca58c94745904ea7378693b55652` e
`production` em `a2efbe3242be1e0569fa6513020458e920badff5`, com #362 e #358
integradas em suas respectivas bases. A última promoção tinha CI e Governança verdes.
Branch do incremento `feat/nfcore-mg-runtime-pilot`. SHA e checks na PR da branch.

A consulta direta e o cliente de consulta usado na recuperação de transmissão incerta
passam pelo gateway MG somente para NF-e 55 de homologação com vínculo persistente
habilitado para tenant, unidade, ambiente, UF e operação `query`, com provider
`sefaz-mg-homologacao-nfe4`. A fronteira usa o resolvedor durável, o Vault por escopo
e emitente e o adaptador MG com os XSD oficiais já congelados. O incremento cobre
consulta interna, com o caminho legado de SP e a injeção de gateways preservados.

Gates locais com 140 testes direcionados, Ruff global, Mypy dos módulos de aplicação
e composição e os dois validadores de governança. O teste novo usa SQLite migrado,
certificado A1 sintético, XSD real e resposta SOAP local. Exercita bloqueios antes
do Vault e transporte e uma consulta aceita com o vínculo correto.
A prova ponta a ponta autenticada em ambiente publicado e a homologação oficial
permanecem pendentes.

Próximo bloco interno de MG inclui seleção governada para autorização e cancelamento,
preparação Web, emissor e ano explícitos na inutilização, NFC-e MG e NFS-e de Belo
Horizonte. Em seguida, RJ, PR, MT e MS com seus municípios-piloto e expansão pelas
demais UFs e municípios. NAT-UF-MG permanece em implementação.


### NAT-UF-MG-T04 — autorização de NF-e 55 preparada

A PR #364 registrou CI e Governança verdes em a25e0d7 antes deste incremento.
A composição canônica seleciona MG para autorização somente com o vínculo
persistente da operação authorize. A seleção ocorre antes de iniciar a
transmissão durável. O gateway confere XSD, referência, algoritmos,
digest, assinatura e correspondência com o certificado A1 do Vault antes do
transporte. A preparação arquivada permanece no formato existente e a
recuperação consulta o autorizador com seu próprio vínculo.

A prova interna usa documento previamente assinado, SQLite migrado e
resposta SOAP local. A jornada de criação e preparação pelo Portal, o
teste autenticado em ambiente publicado e a homologação oficial permanecem
pendentes. As evidências de CI para o novo SHA estão na PR #364.


### NAT-03/04 — envelopes e referências Multi-UF (06/11/2026)

Base auditada main 851efe0ddcf7372f532cbcba33b323f0e0f11ed6 e production
9e966e7e50fc0a9b33eb2f751cce60ab21686be5. Escopo do incremento limitado ao
catálogo versionado, resolução exata, consumo pelas rotas existentes e
proteção de transporte. Vínculos persistentes e gates de ativação continuam
sendo as autoridades de execução.

- 144 referências de NF-e e NFC-e para SP, MG, RJ, PR, MT e MS nos dois
  ambientes. Operações de autorização, recibo, consulta, evento, inutilização
  e status. RJ usa SVRS. A busca compara cUF, família, ambiente e operação,
  verifica coerência do prefixo IBGE quando informado e recusa lacunas.
- Adaptadores NF-e já compostos de SP e MG continuam usando os mesmos
  destinos de homologação, agora a partir do catálogo. O transporte atual
  trata 103/105 como pendência mesmo se houver protocolo contraditório.
  A consulta por chave segue como recuperação existente. A rota de recibo
  descoberta ainda precisa de cliente operacional ligado à persistência.
- Os dois caminhos de transporte da NFS-e Nacional recusam redirects.
  Material A1 permanece no contexto mTLS por emitente e escopo do Vault.
  A NFS-e municipal segue no roteamento existente por vínculo/município.
- Os XSD oficiais já fixados continuam sendo a referência de validação.
  NCM, CFOP e regras jurisdicionais ainda requerem dados normativos
  governados e uma jornada de pré-auditoria. O Core Cognitivo permanece
  consultivo. Uso do Gemini 3.8 Flash antes da assinatura em runtime
  requer integração e prova específicas.
- 48 GETs WSDL sem credencial, em homologação, com TLS verificado e sem
  redirects, falharam na verificação TLS no cliente Python/Windows.
  A amostra MG NF-e na Contabo também falhou no handshake sem A1.
  O resultado é inconclusivo para mTLS autenticado. Ativação e
  homologar operações exigem emitente elegível, A1 e prova do autorizador.

Fontes consultadas em 06/11/2026:
- https://dfe-portal.svrs.rs.gov.br/Nfe/Servicos
- https://dfe-portal.svrs.rs.gov.br/Nfce/Servicos
- https://portalsped.fazenda.mg.gov.br/spedmg/nfce/web-services/
- https://www.nfe.fazenda.gov.br/portal/webServices.aspx
- https://portal.fazenda.rj.gov.br/dfe/wp-content/uploads/sites/17/2023/01/DF-e_NFC-e.pdf
- https://www.ibge.gov.br/explica/codigos-dos-municipios.php
- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash

Próxima entrega: cliente de recibo com correlação persistente e teste mTLS
de homologação, seguido de adaptação comprovada por modelo/UF e contratos
municipais. Gates de CI e SHA na PR.


### NAT-04 — envelopes municipais em homologação (06/11/2026)

A malha estadual e o roteamento municipal usam contratos distintos. O gateway
Nacional envia DPS XML assinada dentro de JSON compactado via POST REST SEFIN.
A preparação ABRASF 2.03 produz SOAP 1.1 com partes string de cabeçalho e
dados, XML no namespace ABRASF, ação WSDL e assinaturas RPS antes do lote.
A consulta de lote valida o prestador e o protocolo sem assinar a consulta.
A assinatura usa o A1 do escopo; a chave privada e a senha ficam fora dos
envelopes. O cliente mTLS verifica o servidor e recusa redirects.

| Município | IBGE | Contrato identificado |
|---|---|---|
| São Paulo | 3550308 | Nota Paulistana tem layout próprio. Emissor Nacional conforme competência e regime, incluindo ME/EPP do Simples desde 01/11/2026. |
| Belo Horizonte | 3106200 | Emissor Nacional conforme orientações BHISS. |
| Rio de Janeiro | 3304557 | Emissor Nacional para novas emissões conforme orientação municipal. |
| Curitiba | 4106902 | Emissor Nacional conforme cronograma oficial por grupo. |
| Cuiabá | 5103403 | Emissor Nacional a partir de 01/11/2026 conforme Prefeitura. |
| Campo Grande | 5002704 | ABRASF 2.03 via webservice municipal onde aplicável; regime e competência exigem checagem antes de escolher o canal. |

Os demais polos do catálogo paulista continuam como candidatos por município.
O mapeamento acima é evidência de contrato, sem autorizar fallback, ativar
bindings ou tratar ABRASF 1.x, 2.03, 2.04 e Nota Paulistana como equivalentes.
O WSDL municipal de Campo Grande indicado no comunicado não resolveu por DNS
nesta execução. O envelope implementado segue o WSDL-base da ABRASF, ainda
sem registro em runtime para transmissão municipal.

O ZIP ABRASF tem SHA-256
638f7f9a0dfb76898357e4335270424a5123c2cc2ab040bdb0b2de08da58a941.
O arquivo .txt de schema não era XML bem formado. Foi corrigida a falta
de um caractere de abertura na restrição de tsNif e normalizado o whitespace
de fim de linha para o repositório. O schema derivado e o import estão pinados.
O ZIP Nacional de 09/02/2026 tem SHA-256
e7935cbd9470527c6cc32984c1b2263e614183bf0139ce2733eaaed2de9a8072.
As duas versões DPS compilam offline a partir de arquivos pinados.

A pré-auditoria da preparação ABRASF recebe apenas campos de tributação
e pode vetar antes de acessar o Vault. As taxas e retenções por município
precisam de autoridade normativa versionada. Gemini 3.8 Flash/Sentinela
em runtime, assinatura Nacional aceita pelo autorizador e mTLS municipal
com A1 elegível continuam pendentes de prova.

Fontes conferidas:
- https://abrasf.org.br/biblioteca/arquivos-publicos/nfs-e/versao-2-03
- https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual
- https://notadomilhao.sf.prefeitura.sp.gov.br/manuais-reforma-tributaria/
- https://notadomilhao.sf.prefeitura.sp.gov.br/noticias/migracao-de-contribuintes-do-simples-nacional-para-o-ambiente-nacional/
- https://prefeitura.pbh.gov.br/fazenda/bhiss/avisos
- https://www.1746.rio/hc/pt-br/articles/10674193247771-ISS-Emiss%C3%A3o-de-nota-fiscal-eletr%C3%B4nica-Nota-Carioca
- https://lp.curitiba.pr.gov.br/notanacional/
- https://cuiaba.mt.gov.br/noticias/cuiaba-prorroga-prazo-para-emissao-de-nfs-e-pelo-emissor-nacional
- https://cdn.campogrande.ms.gov.br/portal/prod/uploads/sites/29/2026/03/Comunicado-RPS-Integracao-Web-Service-2.pdf


## Nota Paulistana — preparação interna do teste de lote (06/11/2026)

- Base de execução: `main@c4f8023fca5174199afa1b4af132d6d710fe2d14`. Produção observada antes da alteração: `e1ee6f0ea4c9206029441175f945e5807057c5e5`.
- Entrega: `prepare_paulistana_test_batch` prepara somente a operação municipal `TesteEnvioLoteRPS`, que não gera nota. Recebe lote versão 2, valida remetente e CCM, oferece fatos fiscais à pré-auditoria e exige A1 resolvido pelo escopo. Aplica a assinatura RSA/SHA-1 de cada RPS e depois XMLDSig no pedido inteiro. O algoritmo legado segue o manual municipal e fica restrito a esse contrato e aos contratos legados preexistentes.
- XSDs oficiais imutáveis do pacote 02-7, ZIP SHA-256 `b38ea1361c76f49f848de2b4840a6ee7b2b929d063744afbf0bbb11e46ed4ad5`, usados offline. Os testes extraem a mensagem do SOAP e verificam digest e as duas assinaturas com chave sintética. O manual exemplifica SOAP 1.1 nas mensagens síncronas e menciona SOAP 1.2 no resumo técnico. A forma SOAP 1.1 segue o exemplo síncrono e permanece candidata até confirmar o binding no WSDL oficial. O GET público de WSDL respondeu HTTP 403 sem certificado.
- A prefeitura avisa que o pacote 02-7 publicado ainda não reflete o ambiente produtivo. O preparador não registra provider, não faz POST, não ativa emissão, não escolhe automaticamente emissor por regime e não afirma homologação.
- Integração seguinte: confirmar WSDL com credencial de homologação e compor o cliente municipal com A1/mTLS, Sentinela, vínculo durável por unidade e jornada Web. Para os pilotos do Ambiente Nacional, conectar o builder confiável de DPS à composição canônica antes dos testes da contabilidade. Para Campo Grande, confirmar a publicação atual do WSDL municipal antes de compor o adaptador.
- Evidência paulista adicional: Campinas confirma Ambiente Nacional para ME/EPP do Simples a partir da competência de 01/11/2026 e canal municipal para competências anteriores, com regras específicas para os demais grupos. Barueri documenta o canal nacional para o Simples desde 01/11 e layouts próprios PMB para os casos municipais. A página de Barueri apresenta data de transição inválida (31/11/2026), portanto nenhum cutoff do PMB 003 foi codificado. O catálogo paulista continua consultivo.
- Fontes oficiais: [manual 3.4](https://notadomilhao.sf.prefeitura.sp.gov.br/nfe_web_service-12/), [comunicado XSD 02-7](https://notadomilhao.sf.prefeitura.sp.gov.br/noticias/nova-versao-do-manual-de-utilizacao-do-webservice-de-nfs-e/), [migração paulistana](https://notadomilhao.sf.prefeitura.sp.gov.br/noticias/migracao-de-contribuintes-do-simples-nacional-para-o-ambiente-nacional/), [Campinas](https://campinas.sp.gov.br/noticia/151237), [Barueri](https://portal.barueri.sp.gov.br/secretarias/secretaria-de-financas/nota-fiscal).

## NFS-e na jornada Web ? v?nculo e pr?-auditoria antes do cofre (06/11/2026)

- Base: `main@0cb93a337e360d991206a502db781e4b5bfb07ad`. PR #369 integrada em `8a987ff47a039782f7fd69d4d263bab8407d7d8d`. Ambas as PRs passaram em CI e Governan?a antes da integra??o.
- A composi??o Portal/Bridge exige uma pr?-auditoria expl?cita ao configurar o builder confi?vel de DPS. Antes de acessar o cofre, confere o v?nculo dur?vel do emitente por tenant, unidade, namespace, ambiente, IBGE e opera??o. Um v?nculo municipal incompat?vel n?o pode cair no gateway nacional.
- Testes cobrem composi??o sem auditor, v?nculo ausente, provedor divergente, veto da auditoria e ordem de execu??o do caminho aprovado. A porta de pr?-auditoria ainda depende da composi??o com o Sentinela real no entrypoint.
- Pend?ncias internas: gerar DPS a partir dos dados fiscais confi?veis e da numera??o persistente; ligar o Sentinela real ? porta de pr?-auditoria; conectar o teste paulistano ? jornada Web de homologa??o sem reaproveitar o handler de emiss?o.
- Pend?ncias externas: confirma??o do contrato SOAP municipal, valida??o com A1 da contabilidade e homologa??o. Este bloco n?o ativa provider, n?o modifica a Contabo e n?o transmite documentos.

---

## Checkpoint incremental MG-W1 — 11/11/2026 — PR #423 (não mergeada)

**CURRENT remoto consultado:** `faabio3131/nf-core-v001`, `main@545b7606208eedf77b3fd6b852ccb82b4716f6b8`, `production@61015a837be8b2e5e3b0f1cdb5fb14c5c875fb91`. **Branch:** `feat/nfcore-mg-polos-economicos-wave1-20261111`. **Outro agente:** Bling/release/Contabo; nenhum artefato seu foi sobrescrito. **PR documental concorrente:** #413 aberta, preservar a reconciliação dos três arquivos.

**DECISÃO aprovada:** MG 20 polos econômicos → Centro-Oeste DF → GO → MT → MS → MG municípios de menor prioridade em onda posterior. As demais UFs ficam no backlog. O gate para avançar no trabalho interno é `MG_W1_INTERNAL_COMPLETE`, não homologação externa imaginada.

**Achados de arquitetura reais, aproveitamento:**
- Catálogo MG 55/65 e NF-e 55 autorizacao/consulta/cancelamento/inutilização com gateway, A1 e XMLDSig existentes; não reescrever.
- `nfse_dps_builder.py` + `nfse_nacional_homologation.py` + `nfse_national_homologation.py` formam pipeline DPS → XSD → XMLDSig → JSON `dpsXmlGZipB64` → mTLS/SEFIN. **Não equivale** a contrato municipal aprovado.
- Defeito do catálogo MG-W1: IBGE de outra UF era aceito. CI do commit `b669804a5bf4034eef5651432100e564b08dd740` terminou **FAILURE**: 1 teste novo falhou, 3798 passaram, 3 skip. A correção verifica explicitamente IBGE de MG antes do construtor.
- **Proteção implementada e reconciliada com regra federal de 29/10/2026:** Contagem (3118601) publica ISS Digital próprio; o gateway recusa SEFIN antes do A1/assinatura/transporte somente para regimes e competências que exigem emissor municipal (ex.: regime NORMAL atual e Simples retroativo de outubro/2026). Para ME/EPP Simples com competência desde 01/11/2026, SEFIN Nacional é o canal exigido pela regra federal, sujeito ainda a binding/autenticação/XSD/assinatura e homologação. Fonte: https://www.gov.br/nfse/pt-br/noticias/nfs-e-informa-diretrizes-sobre-a-obrigatoriedade-da-emissao-da-nfs-e-nacional-para-optantes-do-simples-nacional. Municipal próprio demanda contrato Swagger verificável e autenticação específica, não presumidos.
- **Proteção implementada:** retorno SEFIN contendo apenas `chaveAcesso` não produz autorização; requer NFSe XML zipado válido e `tipoAmbiente` numérico 2 explícito. Novos testes exercitam negativos e casos sintéticos.
- **Envelope implementado/testado em laboratório:** XML DPS assinada e XSD v1.00, JSON gzip/base64 para BH 3106200, Betim 3106705 e Uberlândia 3170206; **prova sintética, não transmissão oficial**. A vigência de v1.01 e o leiaute RTC devem ser revalidados antes de certificação final.
- **Pendência interna crítica já identificada no código:** `_derive_dps_numbering` usa hash como número provisório. Fonte federal exige numeração sequencial crescente (https://www.gov.br/nfse/pt-br/saiba-mais/como-a-nfs-e-e-gerada/o-que-e-dps). Deve convergir com reserva durável/fiscal oficial e retry idempotente, sem `MAX+1`, antes de liberar qualquer emissão operacional.
- **Matriz por município:** `docs/coverage/NFCORE_MG_W1_MUNICIPAL_CELLS_2026-11-11.json` mantém 20 linhas com `nfse_envelope_contract_version`, `nfse_envelope_xsd_sha256`, SHAs de assinatura/transporte/Web, operações e homologação por contribuinte. Nenhuma cidade está `INTERNAL_COMPLETE`, `EXTERNAL_HOMOLOGATED` ou `PRODUCTION_LIVE`. Teste de gate falha quando há declaração de conclusão sem evidência.

**Fontes públicas específicas**: BHISS Prefeitura BH; comunicados Prefeitura Betim; aviso Prefeitura Uberlândia; Receita Contagem `https://receita.contagem.mg.gov.br/nfe/`; NFS-e Nacional documentação atual em 04/11/2026 `https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual` e pacote de produção restrita atualizado em 20/10/2026 `https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/producao-restrita`. Fonte de ranking PIB: IBGE/SIDRA 2023, link no plano MG-W1.

**Gates:** Governança PR #423 aprovada em commits anteriores. CI final é **PENDENTE DE CONFIRMAÇÃO NO HEAD FINAL**; Ruff/Mypy/Pytest/E2E e demais checks **não devem ser herdados** de commits anteriores ou das 265 PASS locais de 05/11. EGM original sete skills **não executado** nesta PR; não inventar revisão Goldfish. Nenhum merge, deploy, migration produtiva, A1 real ou emissão fiscal realizado.

**Próxima sequência mandatória:** corrigir qualquer falha da CI neste HEAD → certificar e registrar SHA/CI → completar numeração DPS durável, MG NF-e/NFC-e e NFS-e BH com contrato XSD vigente → seguir Betim, Uberlândia e Contagem conforme os envelopes e transportes oficiais, depois os outros 16, sempre com matriz por célula e sem falsa homologação.

---

## Checkpoint MG-W1 — revisão de contratos fiscais e EGM, 11/11/2026

**Trilha de cobertura:** PR #423 Draft; sem merge, sem alteração na Contabo e sem criar segundo motor fiscal. Esta entrega avança proteção fiscal e testes, **não conclui os 20 municípios**. Revisar os checks no SHA exato da PR antes de qualquer mudança de estado.

**Deltas de construção:** `src/kordena_fiscal/gateway/mg_nfse_channel_guard.py` recusa envio NFS-e ao ambiente nacional antes de abrir A1 para município MG-W1 sem elegibilidade comprovada pela competência/regime. Para ME/EPP Simples, a regra federal de 29/10/2026 exige ambiente nacional desde competência 01/11/2026. MEI segue sua regra anterior. Para os sete canais nacionais exclusivos com fonte municipal, os cortes anteriores continuam documentados. Sem município/regime/competência elegível, falha fechada; o guard **não** autoriza emissor e não substitui o binding durável por tenant/unidade. Testes cobrem toda a matriz dos 20 polos e casos negativos.

**Envelope/retorno nacional:** o parser de resposta agora exige a chave NFS-e de 50 dígitos e identidade `infNFSe/@Id='NFS'+chave`; rejeita XML de outro documento, DOCTYPE e inconsistências em testes sintéticos. Essa verificação **não** equivale a assinatura oficial do XML de resposta, recibo real ou homologação do contribuinte. O transporte Nacional continua separado dos envelopes municipais e dos SOAP NF-e/NFC-e.

**Alerta regulatório XSD obrigatório:** o governo publicou em 20/10/2026 a Nota Técnica 009 release 1 para o ambiente de **produção restrita** (reposicionamento CST/cClassTrib, serviços 99.02–99.04, grupo vAjusteBC), com migração planejada de releases à produção a partir de 01/12/2026. O builder canônico `nfse_dps_builder.py` ainda gera `DPS_v1.00` do pacote histórico; **não** declarar aderência integral ao XSD corrente de produção restrita nem enviar em ambiente real antes de reconciliar versões por ambiente, vigência e serviço. Fontes: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/producao-restrita ; https://www.gov.br/nfse/pt-br/noticias/cgnfs-e-informa-disponibilizadas-no-ambiente-de-testes-o-release-1-das-evolucoes-da-nota-tecnica-009 ; https://www.gov.br/nfse/pt-br/noticias/nfs-e-nacional-confira-oas-rientacoes-sobre-leiaute-em-producao-regras-de-preenchimento-de-ibs-cbs-e-status-da-nota-tecnica-009/ . **O leiaute de produção difere do leiaute de testes em 11/11.**

**Bloqueios internos identificados e não escondidos:** numeração `nDPS` ainda é hash sintético e não reserva sequencial legal por CNPJ/ambiente/série; reutilizar tabela estadual 55/65 seria incorreto. Falta contrato/migration atômica e recuperação idempotente antes de ativar NFS-e. NF-e MG55 tem caminho de autorização e consulta/cancelamento por vínculo, mas o ciclo integral não está certificado; NFC-e MG65 ainda exige assinatura, QR Code por versão, contingência, eventos e autorização própria. A NT 2025.001 v1.03 de QR versão 3 dispensa CSC nessa **versão**; CSC continua relevante para versões legadas: não aplicar regra única às duas versões. Referência: https://portalsped.fazenda.mg.gov.br/spedmg/nfce/web-services/ (validar checksum e versão do arquivo oficial no ato da implementação).

**Matriz de 20 municípios:** `docs/coverage/NFCORE_MG_W1_MUNICIPAL_CELLS_2026-11-11.json` diferencia fonte normativa, XSD do envelope, XMLDSig, transporte, UI, numeração fiscal e CI por cidade. Fontes municipais identificadas em 16/20; outros quatro requerem contrato primário completo; **0/20 INTERNAL_COMPLETE, 0/20 homologados externamente**. A adoção federal não supre regras de ISS municipais nem prova endpoint próprio.

**EGM:** leitura da auditoria independente `AUDITORIA_INDEPENDENTE_EGM_NFCORE_2026-11-10.md` confirma 36 achados e etapa 9 não executada no laboratório. Nenhum agente EGM original nem sete skills foi executado neste incremento; revisão por CI/GitHub não deve receber carimbo EGM.

**Gates para próxima certificação:** A) versão XSD correta em homologação e produção, schemas/hash/RTC, B) DPS sequencial durável por CNPJ sem novo provedor de autoridade, C) NF-e 55 e NFC-e 65 ciclos completos, D) contrato municipal/envelope/eventos/ISS para cada cidade, E) API+Web+PG+RBAC/E2E+CI+EGM auditável, F) externa A1/credenciamento e prova oficial, G) autorização humana para produção. Atualizar a PR/cronograma a cada marco; sem mover DF à frente de MG-W1.

 **Regra local BH adicional:** aviso BHISS de 11/08/2026 confirma que ME/EPP Simples em Belo Horizonte já utilizam Emissor Nacional desde a competência novembro/2025; a regra federal nacional de novembro/2026 não substitui o corte municipal anterior. Fonte: https://prefeitura.pbh.gov.br/fazenda/bhiss/avisos?page=1 .


### Incremento fiscal MG65 — preflight separado, sem ativação (11/11/2026)

- `SefazHomologationAuthorizationGateway` mantém a mesma implementação e agora reconhece `MG_NFCE` (modelo 65) com provedor e endpoint próprios da SEFAZ/MG; **não reutiliza o endereço de NF-e 55**. Fonte oficial: https://portalsped.fazenda.mg.gov.br/spedmg/nfce/web-services/ . O alvo é configurável em código de homologação mas não foi conectado ao runtime canônico para clientes.
- Guarda antecipada valida chave MG/65, tpAmb=2, `infNFeSupl` com QR Code apontando ao host/path oficial e `urlChave` ao portal de homologação; bloqueia QR spoofed e modelo 55 antes de Vault A1, assinatura ou HTTP. Sem prova de montagem criptográfica final do QR v3, CSC onde cabível, contingência e eventos: **NFC-e 65 permanece PREFLIGHT_IMPLEMENTED_NOT_CERTIFIED**.
- Adaptador de operações do modelo 55/SP recusa explicitamente alvo MG65, impedindo roteamento por fallback. Testes negativos dedicados `tests/gateway/test_mg_nfce_model65_preflight.py` e matriz `docs/coverage/NFCORE_MG_W1_MUNICIPAL_CELLS_2026-11-11.json` preservam o bloqueio.
- Estado atual do PR: Draft, sem merge e sem deploy; **a CI deve ser verificada no HEAD exato após estes commits**, sucesso anterior não serve de certificado deste incremento. Issue canônica de fechamento MG-W1: https://github.com/faabio3131/nf-core-v001/issues/426 . EGM original não foi executado. Próximo delta exige QR v3 assinado, composição exata no Control Plane, consulta/cancelamento/inutilização, teste XML completo e Web/E2E.


**Revisão adicional do QR v3 (NT 2025.001 v1.03):** o preflight de NFC-e 65 verifica o formato **online exato** `p=<chNFe>|3|2`, não aceita campos sintéticos extras nem QR v2 neste alvo; contingência `tpEmis=9` fica bloqueada até haver geração/verificação de assinatura digital específica de seus oito campos. A origem e `urlChave` devem coincidir com os endereços oficiais de homologação MG. Referência primária: https://hom.nfe.fazenda.gov.br/portal/exibirArquivo.aspx?AspxAutoDetectCookieSupport=1&conteudo=uthum2eC3is%3D (NT v1.03, seção 04). **Status:** QR v3 ONLINE PREFLIGHT ONLY, não autorização, DANFE ou contingência certificados.


**Gate MG65 síncrono adicional:** NF-e/NFC-e Nacional NT 2025.001 v1.03 exige autorização síncrona para lote com uma única NFC-e; o preflight MG65 agora rejeita `indSinc!=1` antes de A1/transporte, com teste de regressão. Isto não ativa consulta, cancelamento, inutilização ou contingência NFC-e. Evidence: `tests/gateway/test_mg_nfce_model65_preflight.py`, PR #423, CI do HEAD a comprovar.

## Checkpoint da pesquisa Web MG-W1 — 11/11/2026 — reconciliação superveniente

**CURRENT da pesquisa:** 20/20 municípios com canal/emissor NFS-e publicamente **identificado**, substituindo os saldos históricos de 16/20 acima. Quatro municípios antes sem fonte: Uberaba (3170107) → portal oficial da prefeitura encaminha ao WebISS; Extrema (3125101) → Fazenda Digital + WebISS, manuais/XSD RTC 2026 anunciados; Governador Valadares (3127701) → NOBE/ISS Integra notifica migração de emissão para API SEFIN Nacional em 2026, mas Decreto 12.443/2026 precisa de original conferido; Itabira (3131703) → portal ISS Digital Cidade360 e link municipal Swagger (resposta 502 na consulta). A matriz oficial deste **checkpoint de pesquisa** é `docs/coverage/NFCORE_MG_W1_MUNICIPAL_CELLS_2026-11-11.json`, 20 `CHANNEL_RESEARCHED`, **nenhum `INTERNAL_COMPLETE`**.

**Fontes verificáveis:** https://portal.uberaba.mg.gov.br/pesquisa/nota%20fiscal ; https://uberabamg.webiss.com.br/ ; https://www.extrema.mg.gov.br/servicos/fazenda-digital ; https://extremamg.webiss.com.br/ ; https://governadorvaladares-mg.issintegra.com.br/ ; https://www.valadares.mg.gov.br/abrir_arquivo.aspx?arquivo=%7BB6ADE82C-8CCD-1B8A-BE1E-BDB4DCC70260%7D.pdf&cdLocal=12 ; https://webapp1-itabira.cidade360.cloud/nfse.portal/ ; https://www.itabira.mg.gov.br/ . Resumo detalhado: `docs/NFCORE_MG_NFSE_OFFICIAL_CHANNEL_EVIDENCE_2026-11-11.md`.

**Risco técnico identificado:** biblioteca NFS-e Nacional atualizada em 04/11/2026 publica `NFSe-ESQUEMAS_XSD-v1.01-20260209` e `ANEXO_I-SEFIN_ADN-DPS_NFSe-SNNFSe-v1.01-20260209`, enquanto builder atual utiliza esquema v1.00. Fonte oficial: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual . Conciliar versão conforme produção/produção restrita, competência e NT009/RTC; **não** atualizar campo de versão sem instalar/validar schemas completos e fixtures. A regra federal de competência >= 01/11/2026 para ME/EPP Simples permite SEFIN nos quatro municípios e preserva o canal municipal aplicável em históricos/outros regimes.

**Gate:** pesquisa normativa de canal `RESEARCHED_20_OF_20`; engenharia de contrato `PENDING_20_OF_20`, homologação externa `PENDING_20_OF_20`. Nenhum endpoint de transmissão ou binding municipal foi criado por este checkpoint, e nenhum deploy/merge autorizado. A numeração durável DPS está em PR #427 (Draft, CI própria); esta PR #423 mantém a cobertura MG-W1. Não promover Centro-Oeste antes do gate interno completo de MG.
