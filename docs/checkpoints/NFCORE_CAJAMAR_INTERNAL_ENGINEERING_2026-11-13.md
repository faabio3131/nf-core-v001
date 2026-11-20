# NFCore — Cajamar / GeisWeb — recorte municipal isolado (13/11/2026)

**Classificação:** `IMPLEMENTED_NOT_CERTIFIED` (não é homologação municipal, nem conclusão comercial).

## Decisão N2 e dependências
- Aprovação do proprietário: [issue #447, comentário 6840103335](https://github.com/faabio3131/nf-core-v001/issues/447#issuecomment-6840103335).
- Fonte congelada de extração: #461 `b4d2eecc11d9a91fa2ab55891a5d77715e9ad916`. Essa PR NÃO foi modificada.
- Núcleo comum canônico candidato: PR #454, base desta branch, HEAD congelado para extração `fbe904dbdcf9f19eca94c090f99e7fd5f216e565`; a PR do núcleo permanece do Agente B e **não foi editada por esta frente**.
- Escopo: **apenas Cajamar** como primeira PR municipal. As interfaces SP4 genéricas nesta branch são contratos compartilhados, não adaptadores operacionais dos outros municípios.
- Fronteiras B protegidas NÃO modificadas: `gateway/nfse_nacional_homologation.py`, `issuance/nfse_dps_builder.py`, `runtime/canonical_fiscal_composition.py`, `tests/runtime/test_nfv1_nfse_preparation_recovery.py`.
- Não aplicar migration v22, A1, secrets, merge, deploy, `tpAmb=1` ou emissão real sem autorização N3.

## Marco normativo — correção obrigatória

**ME/EPP optantes pelo Simples Nacional:** NFS-e nacional obrigatória **por competência desde 01/11/2026**, não 01/09/2026; Resolução CGSN nº 191/2026 revogou a data anterior estabelecida pela nº 189/2026. A competência do serviço, não a data da requisição HTTP, define o corte de canal. Competências anteriores a 01/11/2026 continuam sujeitas ao fluxo municipal aplicável e à comprovação das permissões/contratos da prefeitura; não criar autorização por inferência.

**MEI:** corte nacional em 01/09/2023 (marco distinto). Regras de destaque IBS/CBS relativas ao Simples a partir de 01/01/2027 são outro marco normativo, não confundido com a escolha do emissor.

Fontes oficiais:
- Receita Federal (14/08/2026): https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/agosto/simples-nacional-nfs-e-nacional-sera-obrigatoria-para-me-e-epp-a-partir-de-1o-de-novembro-de-2026
- Portal NFS-e (29/10/2026), critério de competência e notas retroativas: https://www.gov.br/nfse/pt-br/noticias/nfs-e-informa-diretrizes-sobre-a-obrigatoriedade-da-emissao-da-nfs-e-nacional-para-optantes-do-simples-nacional
- Portal da Fazenda de Cajamar (existência de serviço municipal, **não prova WSDL para contribuinte**): https://cajamar.sp.gov.br/fazenda/servicos-online/

## Escopo de engenharia no commit candidato

### Construção interna (não herda CI de #461)
- [x] Extração dos **seis módulos GeisWeb de Cajamar**: transporte com WSDL/XSD injetado, emissão, consulta de lote/RPS original, interpretador, consulta original e cancelamento; origem preservada seletivamente.
- [x] Correção em `CajamarPreparedNfse` para o corte ME/EPP **01/11/2026**, preservado 01/09/2023 para MEI; testes de fronteira e retroatividade corrigidos.
- [x] `Sp4OriginalRps` / `Sp4ProviderOutcome` e composição de ports existentes; ponte e factory **somente Cajamar**, sem classes importadas de Osasco/Barueri/Jundiaí.
- [x] Prova sintética de batch original durável e request fingerprint, XML, tomador e valores, rejeição de adulteração, cancelamento revisado e reconciliação read-only sem segundo POST (componentes testáveis).
- [x] `sp4_original_rps_archive` usa a autoridade de sequência fiscal existente; incluídos testes locais de token/escopo/numeração, sem um segundo contador.
- [ ] CI do HEAD exato, Ruff, Mypy, Pytest/PostgreSQL, lint/frontend/E2E/browser, assinaturas e segurança (pendentes até comprovação remota).
- [ ] Resolver integração de persistência `prepare_nfse_authorization` + `load_sp4_original_rps` na linha combinada com o Agente B; a aplicação da #454 ainda não expõe esses métodos.
- [ ] Integrar `Sp4ReviewedMunicipalPorts` ao composition root/API/Portal por contrato pactuado com B; **não editar arquivo protegido por iniciativa unilateral**.
- [ ] E2E sintético completo Cajamar Portal → preparar → RPS/lote duráveis → envio → consulta → XML/resultado → PDF → cancelamento/substituição quando oficialmente suportados, sem assumir aceitação fiscal de HTTP 200.
- [ ] Testes de schema municipal com artefatos verificáveis e XMLDSig independente; manter falta de pacote oficial como dependência externa rastreável.

### EXTERNAL_BLOCKED (não impede engenharia interna)
- WSDL/XSD vigente da prefeitura/GeisWeb com origem, hashes e autorização de uso do contribuinte.
- A1 e credenciais do contribuinte, sujeitos à auditoria de volume e backup do cofre na Contabo (#462); o proprietário informou que o A1 já foi exportado em arquivo .pfx protegido por senha e armazenado fora do repositório e servidor ([issue #447, comentário 6840382267](https://github.com/faabio3131/nf-core-v001/issues/447#issuecomment-6840382267)). A reemissão à DigitalSign não é mais necessária. Cadastro/upload no cofre continua pendente de auditoria operacional e de autorização N3.
- Validação em ambiente oficial com contribuinte autorizado e resposta municipal real, protocolo/XML legítimo, regras de cancelamento/substituição conforme disponibilidade oficial.

## Critério de avanço
Esta PR permanece **DRAFT** até testes/CI no HEAD final, revisão A/B dos contratos de integração e resolução de todas as pendências internas. Nenhum sucesso da #454, da #450 ou da #461 certifica automaticamente este recorte. A ordem posterior é Osasco → Barueri → Jundiaí somente após Cajamar internamente encerrada ou bloqueada externamente com evidência.


## Execução integrada adicional — 13/11/2026 (candidato, não homologado)

**CURRENT → TARGET:** A PR #463 passou do recorte de adaptadores para implementar o fluxo
de preparação municipal no **mesmo** `FiscalApplicationService` e operação HTTP
`prepareNativeNfse`, sem outra autoridade. O arquivo
`src/kordena_fiscal/application/service.py` recebeu reserva `NFSE_RPS`, evidência
`SP4_ORIGINAL_RPS_MEDIA_TYPE`, replay e loader tipado no mesmo commit UoW.
A composição `runtime/canonical_fiscal_composition.py` recebeu port opt-in
para emissão/consulta Cajamar usando binding persistido e loader canônico;
a função HTTP de preparação e o formulário existente receberam ramo municipal
sem escolha livre de provider no browser e campos completos de endereço do tomador.

**Gates publicados:** testes de SQLite para transação/rollback/replay/tenant;
preparação HTTP municipal com competência anterior à obrigação nacional;
rejeição de competência Simples >= 01/11/2026; fluxo HTTP simulado de
preparação → emissão pendente → consulta original → XML em arquivo → GET
autenticado → replay sem segundo POST. São testes de arquitetura e payloads
sintéticos, **não** respostas oficiais GeisWeb ou homologação fiscal.
O nível de contrato dos providers revisados requer WSDL/XSD/XMLDSig oficiais
versionados e credenciais aprovadas por contribuinte antes de execução real.

**Código protegido/ownership:** a integração em arquivos do B está
proposta na mesma árvore **Draft** para revisão de função e de contrato;
não equivale a aprovação para merge/deploy nem substitui o pacto de ownership
na issue #447 e seu pedido N2 específico. Não foi alterada a branch #454
para incorporar código municipal; o bloco A/B deve ser reconciliado em um
HEAD combinado antes de certificação comercial.

**Download:** a PR nuclear #454 tem implementação do renderizador nacional
DANFSe + GET HTTP com CI completa verde no SHA `d2a71c1250c01afcd38b0a422cd841e6a7ebfb02`,
separado desta árvore. O XML municipal passa pela mesma camada de download
protegida; a representação PDF oficial municipal ainda depende do layout,
prova XML e/ou geração por provedor oficial: **não apresentar PDF inventado
como DANFSe municipal**.

**Certificação do HEAD:** as CI #2648/#2649/#2650 falharam em lint nas
revisões intermediárias, e os ajustes foram aplicados no HEAD candidato.
Não promover `INTERNAL_COMPLETE` nem `100%` sem CI completa do HEAD
integrado e todas as jornadas web, cancellation e PDF/print em contrato
do município. Não houve merge, deploy, A1 real, migration aplicada ou
transmissão fiscal.


## Reconciliador final de download e contrato de impressão GeisWeb (13/11/2026)

- O código da #463 agora inclui, no **mesmo Portal runtime canônico**, o
  renderizador nacional `render_authorized_national_danfse` já implementado
  e aprovado pela #454@`d2a71c1250c01afcd38b0a422cd841e6a7ebfb02`.
  Este hunk é **reaproveitamento**, não um segundo PDF engine, e ainda deve
  ser reconciliado formalmente no HEAD cumulativo com o owner B.
- A geração nacional depende de XML NFS-e nacional oficial arquivado,
  com `infNFSe/@Id` de chave nacional válida; não aceita XML municipal
  de Cajamar como NFS-e Nacional, não cria autorização em mock.
- **Fonte GeisWeb20 identificada, atualização 23/12/2025:**
  https://atendimento.tecnospeed.com.br/hc/pt-br/articles/1500006998382-Documenta%C3%A7%C3%A3o-T%C3%A9cnica-Padr%C3%A3o-GeisWeb20
  (CajamarSP e seção Impressão). O fornecedor diz expressamente:
  *impressão de NFS-e em homologação não disponível*. O comando auxiliar
  `ObterLinkImpressaoNFSe` é apresentado no contexto do SDK Tecnospeed,
  não equivale a um endpoint SOAP nativo conhecido, e não fornece PDF
  oficial de homologação. Não inventar link de cliente nem gerar impressão
  que não se pode verificar. Classificar como
  `EXTERNAL_PROVIDER_PRINT_HOMOLOGATION_UNAVAILABLE`.
- Aceite interno do município permanece dependente de tests positivos completos
  no HEAD final, revisão do B nas fronteiras compartilhadas, cancelamento
  municipal com resultado comprovável, contrato WSDL/XSD oficial pinado
  quando disponibilizado, XMLDA/XMLDSig, observabilidade e readiness real.
  Este checkpoint não certifica homologação externa nem lançamento.
