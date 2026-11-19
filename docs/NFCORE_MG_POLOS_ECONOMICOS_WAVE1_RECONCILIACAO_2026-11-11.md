# NFCore V1 — Reconciliação de precedência MG polos econômicos → Centro-Oeste

**Decisão:** 11/11/2026, proprietário. **Status:** escopo e inventário de PESQUISA/CONSTRUÇÃO, nunca emissão/homologação comprovada.
**Trilha:** NAT-MG-W1, branch isolada da trilha Bling/release/Contabo.
**Registro de conflito anterior:** NAT-GOV-2026-11-10-02 na PR #413 (Draft); esta decisão substitui a precedência que colocava DF antes de concluir o escopo relevante de MG.
**Documentos a reconciliar após a PR #413:** `AGENTS.md`, `docs/NFCORE_NATIONAL_COVERAGE_MASTER_SCHEDULE_2026-11-07.md`, `docs/NFV1_NATIONAL_EXPANSION_MASTER_EXECUTION_SCHEDULE_2026-11-05.md` e ledger nacional. Nenhum deles deve perder seu histórico.

## Ordem executiva aprovada e fronteiras

1. **MG — primeira onda de polos econômicos:** trabalhar a construção interna para NF-e 55, NFC-e 65 e NFS-e dos 20 municípios abaixo, com Belo Horizonte como primeiro município NFS-e e os outros 19 por contrato fiscal comprovado individualmente. Preservar o código MG já incorporado; corrigir só deltas reais. A seleção municipal é econômica, **não habilitação automática de NFS-e**.
2. **Centro-Oeste, depois do gate interno MG-W1:** DF → GO → MT → MS, respeitando as fases e as tarefas DF-01..DF-05, GO-01..GO-07, MT-01..MT-06, MS-01..MS-07 do `AGENTS.md`. Não trabalhar as quatro UFs como um único adaptador genérico.
3. **MG — municípios de menor relevância comercial:** ficam como `DEFERRED_WAVE_2` (não abandonados), a retomar após a sequência acordada. Para uma prefeitura fora da primeira onda, responder `FORA_DO_ESCOPO_ATUAL`, sem expor prontidão fictícia.
4. **Demais UFs fora da decisão:** preservar backlog nacional antigo (SP, RJ, PR, RS e restantes), sem cancelar funcionalidades já existentes nem afirmar alteração automática de contratos/emissores. Repriorização posterior exige registro expresso.
5. **Trabalho paralelo:** o outro agente mantém Bling, release, runtime, deploy, Contabo e integrações externas. Esta trilha modifica somente cobertura municipal MG, testes e seu registro. Cada agente usa branch/PR próprios; nenhum merge/deploy em nome do outro.

**Gate de passagem:** `MG_W1_INTERNAL_COMPLETE` requer T01..T09 do módulo aplicáveis, contrato vigente por município, XSD/XMLDSig, operações, bindings explícitos e separados por ambiente/tenant/unidade, jornada Web, idempotência, testes e CI no SHA exato. Certificado real, CNPJ autorizado e retorno de serviço público são dependências externas `EXTERNAL_BLOCKED`, registradas separadamente. Não rebatizar o gate interno como `UF_100_COMPLETA` nem `EXTERNAL_HOMOLOGATED`. Ativação em produção depende de autorização humana independente. Esta distinção permite construção interna no Centro-Oeste mesmo sem clientes/certificados reais, **desde que MG-W1 esteja internamente completo**.

## Seleção objetiva: 20 maiores PIBs municipais mineiros

Critério da onda inicial: ranking por PIB municipal de **2023** do IBGE (853 municípios em MG). Selecionados os 20 primeiros, abrangendo polos metropolitanos, logísticos, industriais, de comércio, serviços, mineração e cidades regionais. Referência estatística: [IBGE — PIB dos Municípios](https://www.ibge.gov.br/estatisticas/economicas/industria/9088-produto-interno-bruto-dos-municipios.html); ordenação de 2023 [base derivada identificável e auditável](https://dadobruto.com/rankings/pib/mg). Cada código municipal abaixo aponta à ficha oficial do IBGE.

| Ranking PIB 2023 | Município | IBGE | Fonte código | Estado NFS-e por município |
|---:|---|---|---|---|
| 1 | Belo Horizonte | 3106200 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/belo-horizonte.html) | PESQUISA_CONTRATO_PENDENTE |
| 2 | Betim | 3106705 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/betim.html) | PESQUISA_CONTRATO_PENDENTE |
| 3 | Uberlândia | 3170206 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/uberlandia.html) | PESQUISA_CONTRATO_PENDENTE |
| 4 | Contagem | 3118601 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/contagem.html) | PESQUISA_CONTRATO_PENDENTE |
| 5 | Uberaba | 3170107 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/uberaba.html) | PESQUISA_CONTRATO_PENDENTE |
| 6 | Juiz de Fora | 3136702 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/juiz-de-fora.html) | PESQUISA_CONTRATO_PENDENTE |
| 7 | Extrema | 3125101 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/extrema.html) | PESQUISA_CONTRATO_PENDENTE |
| 8 | Ipatinga | 3131307 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/ipatinga.html) | PESQUISA_CONTRATO_PENDENTE |
| 9 | Sete Lagoas | 3167202 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/sete-lagoas.html) | PESQUISA_CONTRATO_PENDENTE |
| 10 | Pouso Alegre | 3152501 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/pouso-alegre.html) | PESQUISA_CONTRATO_PENDENTE |
| 11 | Montes Claros | 3143302 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/montes-claros.html) | PESQUISA_CONTRATO_PENDENTE |
| 12 | Nova Lima | 3144805 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/nova-lima.html) | PESQUISA_CONTRATO_PENDENTE |
| 13 | Poços de Caldas | 3151800 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/pocos-de-caldas.html) | PESQUISA_CONTRATO_PENDENTE |
| 14 | Varginha | 3170701 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/varginha.html) | PESQUISA_CONTRATO_PENDENTE |
| 15 | Divinópolis | 3122306 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/divinopolis.html) | PESQUISA_CONTRATO_PENDENTE |
| 16 | Araxá | 3104007 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/araxa.html) | PESQUISA_CONTRATO_PENDENTE |
| 17 | Governador Valadares | 3127701 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/governador-valadares.html) | PESQUISA_CONTRATO_PENDENTE |
| 18 | Patos de Minas | 3148004 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/patos-de-minas.html) | PESQUISA_CONTRATO_PENDENTE |
| 19 | Congonhas | 3118007 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/congonhas.html) | PESQUISA_CONTRATO_PENDENTE |
| 20 | Itabira | 3131703 | [IBGE](https://www.ibge.gov.br/cidades-e-estados/mg/itabira.html) | PESQUISA_CONTRATO_PENDENTE |

**Limitação fiscal:** aderir à NFS-e Nacional ou integrar o ADN **não** prova que um contribuinte naquele município possa emitir pelo mesmo endpoint. Resolver individualmente emissor oficial, prefeitura/SEFIN, modelo DPS/RPS, vigência, serviço, inscrição municipal, ISS, competência, eventos e credenciamento antes de criar binding de transmissão. No catálogo de código estes 20 itens permanecem `RESEARCH_ONLY` e não têm URL de transporte, credencial, autorização nem alíquota.

## Tarefas executáveis do bloco NAT-MG-W1

| ID | Trabalho | Critério de saída |
|---|---|---|
| MG-W1-00 | Reconciliar `main`, PRs de cobertura, NAT-03/04/06 e bindings reais; preservar MG55 existente | matriz CURRENT por operação/documento/município, sem reprogramação redundante |
| MG-W1-01 | Concluir NF-e 55 MG: autorizar, consultar, cancelar, inutilizar, status/recibo, XSD e assinatura conforme fonte vigente | casos válidos/negativos, idempotência, A1 sintético e CI |
| MG-W1-02 | Concluir NFC-e 65 MG: autorizador próprio, CSC/QR, contingência permitida, consulta, cancelamento, inutilização quando cabível | Golden Cases 65 e negativa de fallback 55→65 |
| MG-W1-03 | Concluir NFS-e Belo Horizonte, usando o contrato municipal/nacional vigente sem extrapolar disponibilidade | DPS/RPS, XMLDSig, consulta/eventos, competência ISS, pré-auditoria e binder governado |
| MG-W1-04 | Apurar contratos oficiais para os 19 polos restantes, por prioridade da tabela, e reutilizar adaptador somente quando compatibilidade documentada for comprovada | matriz municipal versionada por modelo/operação/ambiente, sem endpoints presumidos |
| MG-W1-05 | Construir/travar fluxo Web, arquivos XML/PDF, recuperação, RBAC, isolamento tenant/unidade e concorrência | regressão API/Web/PG, carga e sem falso positivo de cobertura |
| MG-W1-06 | Certificar code+CI no HEAD e revisão independente EGM quando runner compatível estiver disponível | gates determinísticos, review-loop/drift-report com manifest real ou bloqueio explícito |
| MG-W1-07 | Gate humano para homologação oficial por contribuinte (externo, posterior) | `EXTERNAL_HOMOLOGATED` apenas por prova oficial; nunca bloqueio arbitrário de construção interna |

**Estado em 11/11/2026 no início da frente:** inventário e reconciliação de escopo em construção; MG 55 com implementações parciais existentes, MG 65 e municípios de NFS-e sem certificado final de cobertura auditado; zero das 20 cidades nesta tabela declarado externamente homologado. A próxima alteração de código deve atacar `MG-W1-00` e os deltas `MG-W1-01`, sempre verificando o SHA real antes de afirmar conclusão.

## EGM, rastreabilidade e coordenação

A referência `PLANO_FM_EGM_CICLO_COMPLETO_SAAS.md` de 10/11/2026 é **proposta, não orquestrador implantado**. O laboratório EGM NFCore tem revisão arquitetural ainda não certificada (36 achados; etapa 9 não executada). Esta PR não afirma execução de subagentes ou das sete skills. Aplicar conceito de `draft→review→resolve` ao plano e `review-loop/drift-report` quando infraestrutura real estiver habilitada; manter testes e revisão por SHA independentemente disso. Não usar output de EGM como substituto de homologação de prefeitura.

**Controle de conflito:** PR #413 modifica os documentos canônicos de governança; reconciliar seu diff com esta decisão no momento da integração, sem sobrescrever a contribuição do outro agente. Esta PR não altera produção, migrations, certificados reais, segredos nem configurações comerciais.
