# NFCore — Cronograma Mestre da Cobertura Nacional (NF-e/NFC-e/NFS-e por UF)

**Documento:** NFV1-NATCOV-MASTER-001
**Data:** 2026-11-07
**Status:** cronograma de governança/ordem de execução. NÃO é certificação técnica nem homologação.
**Autoridade:** decisão expressa do proprietário em 07/11/2026, registrada em `AGENTS.md`.
**Fonte superior:** GitHub CURRENT, código, CI e runtime. Este documento rege ORDEM; não substitui `docs/NFV1_NATIONAL_EXPANSION_EXECUTION_LEDGER_2026-11-05.md`, `docs/NFV1_NATIONAL_EXPANSION_MASTER_ARCHITECTURE_2026-11-05.md` nem `docs/NFV1_NATIONAL_EXPANSION_MASTER_EXECUTION_SCHEDULE_2026-11-05.md`, que continuam regendo escopo/critério técnico de cada bloco NAT-xx.

## Regra obrigatória de sequenciamento

1. **Uma UF por vez.** Nenhuma UF nova pode ser iniciada (pesquisa normativa, contrato, envelope, transporte, assinatura ou homologação) enquanto a UF ATIVA não estiver marcada `UF_100_COMPLETA` nesta tabela.
2. **UF completa inclui seus municípios em escopo.** Uma UF só é `UF_100_COMPLETA` quando: (a) NF-e 55 e NFC-e 65 estaduais estão com transporte mTLS/A1 comprovado, autorização, consulta, cancelamento e inutilização homologados; e (b) **todos os municípios daquela UF que estão no escopo comercial atual** (não todos os ~5.570 municípios do Brasil — ver critério de escopo abaixo) têm NFS-e (Nacional ou municipal/ABRASF, conforme o contrato do município) com envelope, assinatura, transmissão e consulta homologados.
3. **Escopo municipal por UF:** por padrão, escopo = capital da UF + municípios onde já existe evidência de demanda/piloto registrada em ledger. Qualquer município fora desse escopo entra como `FORA_DE_ESCOPO_ATUAL`, não bloqueia a UF, mas também não pode ser trabalhado antes da UF ativa fechar.
4. **Não é retrabalho interromper para corrigir regressão da UF ativa** — isso continua dentro da mesma UF. É proibido, sim, abrir pesquisa/código de outra UF antes da ativa fechar.
5. **Pré-condição para esta trilha começar/retomar:** por decisão do proprietário de 07/11/2026, a Expansão Nacional só é retomada depois que (a) o piloto com o escritório contábil de segunda-feira estiver destravado, e (b) tudo que já está em construção/funcionando no NFCore (RTC-04 interno, blocos BLD-03 a BLD-08) estiver 100% pronto. Ver banner `AGENTS.md` de 07/11/2026.
6. Nenhuma homologação externa real, certificado real de cliente, migration produtiva ou deploy é autorizado por este cronograma; cada UF exige autorização específica para esses itens quando chegar sua vez.

## Critério de aceite "UF_100_COMPLETA" (checklist por UF)

- [ ] Transporte estadual mTLS com A1 elegível comprovado (não apenas GET WSDL sem credencial).
- [ ] NF-e 55: emissão, autorização, consulta, cancelamento, inutilização — com SHA/PR/CI no HEAD exato.
- [ ] NFC-e 65 (quando aplicável na UF): idem + CSC/QR code quando exigível.
- [ ] Para cada município em escopo: contrato de envelope identificado (Nacional vs ABRASF 1.x/2.03/2.04/layout próprio) com fonte oficial citada.
- [ ] Para cada município em escopo: envelope implementado, assinado (A1 do escopo), transmitido e consultável em ambiente de homologação do provedor.
- [ ] Testes dirigidos + CI verde no SHA exato para toda a UF (estadual + municipal).
- [ ] Checkpoint de fechamento registrado no ledger NAT com evidência, sem pendência aberta.
- Só então a UF muda de estado e a próxima pode ser iniciada.

## Ordem de execução das UFs

> A ordem abaixo é uma PROPOSTA baseada no estado real de evidência em 07/11/2026 (não em preferência arbitrária). O proprietário pode reordenar a qualquer momento; até reordenar, esta é a sequência vigente.

| Ordem | UF | Estado em 07/11/2026 | Município(s) em escopo inicial | Justificativa da posição |
|---|---|---|---|---|
| **1 (ATIVA)** | **MG — Minas Gerais** | `NAT-UF-MG IMPLEMENTING/PARTIAL` — autorização NF-e 55 em construção (NAT-03), reutiliza transporte SOAP/Vault existente; falta validador XSD confiável, NFC-e 65, e módulo NFS-e de Belo Horizonte | Belo Horizonte (BHISS, contrato "Emissor Nacional" já identificado) | É a UF com mais progresso real de autorização estadual já registrado no ledger (`docs/NFV1_NAT03_MG_AUTHORIZATION_CONTINUITY_2026-11-05.md`); terminar o que já está em andamento antes de abrir outra. |
| 2 | SP — São Paulo | Município capital com preparo de lote avançado (`prepare_paulistana_test_batch`, XSD 02-7 pinado, SHA conferido), mas SEM módulo estadual (NF-e/NFC-e) iniciado para SP e sem WSDL de homologação confirmado | São Paulo capital (Nota Paulistana) | Maior volume de trabalho municipal já investido de qualquer UF; mas como UF ainda não tem estadual iniciado, fica atrás de MG, que já tem os dois eixos em andamento. |
| 3 | RJ — Rio de Janeiro | Transporte SVRS pesquisado para NF-e/NFC-e (inconclusivo, falha de handshake sem A1); município Rio de Janeiro mapeado só como evidência de contrato ("Nota Carioca") | Rio de Janeiro capital | Pesquisa normativa existente, zero código. |
| 4 | RS — Rio Grande do Sul | Transporte SVRS pesquisado (mesmo transporte de RJ/MG via SVRS), zero módulo de autorização | A definir quando chegar a vez | Compartilha transporte SVRS já pesquisado; decisão de incluir/mesclar com MG/RJ fica para quando chegar a vez. |
| 5 | PR — Paraná | Município Curitiba mapeado só como evidência de contrato | Curitiba | Pesquisa normativa parcial, zero código. |
| 6 | MT — Mato Grosso | Município Cuiabá mapeado só como evidência de contrato | Cuiabá | Pesquisa normativa parcial, zero código. |
| 7 | MS — Mato Grosso do Sul | Município Campo Grande mapeado como evidência, mas WSDL municipal não resolveu por DNS na última tentativa | Campo Grande | Pesquisa normativa parcial, zero código, pendência técnica extra (DNS). |
| — | Demais 21 UFs + ~5.500 municípios restantes | `NOT_STARTED` | — | Fora de escopo até reavaliação do proprietário após a UF nº 7. |

## Próxima ação concreta (quando a trilha for retomada)

1. Confirmar GitHub CURRENT e reconciliar com `docs/NFV1_NAT03_MG_AUTHORIZATION_CONTINUITY_2026-11-05.md` antes de qualquer código.
2. Fechar NAT-03 para MG: validador XSD confiável + autorização NF-e 55 com CI no HEAD exato.
3. Implementar NFC-e 65 de MG (mesma UF, mesmo transporte).
4. Implementar módulo NFS-e de Belo Horizonte (município em escopo de MG).
5. Rodar o checklist `UF_100_COMPLETA` inteiro para MG antes de tocar em qualquer arquivo/pesquisa de SP, RJ ou qualquer outra UF.
6. Só depois disso, abrir a UF nº 2 (SP) por este mesmo cronograma.

## Registro de mudanças

- **2026-11-07:** criação do cronograma, com MG definida como UF ativa (proposta) por ser a que já tinha mais evidência de progresso real na reconciliação de 05/11/2026.

---

## Revisão formal do sequenciamento e do escopo comercial — 11/11/2026

**Decisão superveniente do proprietário:** este cronograma de 07/11 mantém valor histórico, mas a ordem após MG não é mais automaticamente SP. A **UF ativa continua MG**, com **escopo inicial alterado de apenas Belo Horizonte para 20 polos econômicos**. A segunda onda mineira pode ser executada depois. A sequência seguinte é **DF → GO → MT → MS** (fases de `AGENTS.md`). SP, RJ, RS, PR e demais UFs continuam no backlog e não perdem nenhuma implementação/contrato preexistente.

**Municípios W1 (ranking PIB municipal 2023):** Belo Horizonte, Betim, Uberlândia, Contagem, Uberaba, Juiz de Fora, Extrema, Ipatinga, Sete Lagoas, Pouso Alegre, Montes Claros, Nova Lima, Poços de Caldas, Varginha, Divinópolis, Araxá, Governador Valadares, Patos de Minas, Congonhas e Itabira. Códigos IBGE, fontes e prioridade executável: `docs/NFCORE_MG_POLOS_ECONOMICOS_WAVE1_RECONCILIACAO_2026-11-11.md` e `src/kordena_fiscal/control_plane/mg_economic_priority_inventory.py`.

**Duas certificações distintas:** `MG_W1_INTERNAL_COMPLETE` exige todas as células de engenharia implementadas e certificadas internamente com testes/CI, inclusive envelopes municipais; habilita estudo da próxima frente quando comprovado. `UF_100_COMPLETA` permanece sujeito ao checklist externo original (A1, contribuinte, homologação oficial) e **não é inferido** do primeiro gate. Ausência de credenciais externas é `EXTERNAL_BLOCKED`, não autorização para omitir construção. Nenhuma prefeitura sem envelope compatível confirmado pode ser declarada funcional.

**Gate per-city NFS-e não negociável:** norma municipal vigente + competência/ISS/IM + schema XSD/hash + XMLDSig + envelope correto + endpoint e autenticação oficial + autorização/consulta/cancelamento/substituição conforme capacidade + arquivos XML/PDF + pré-auditoria + isolamento tenant/unidade + idempotência + Web/E2E + CI no SHA. Sem transpor simplesmente envelopes estaduais NF-e/NFC-e para serviços municipais.

**Execução registrada na PR #423:** catálogo read-only dos 20 polos, matriz JSON de evidências, testes sintéticos de envelope DPS Nacional para BH/Betim/Uberlândia, negação de envio SEFIN para Contagem somente quando regime/competência exigem emissor municipal, preservando regra federal do Simples desde competência 01/11/2026, resposta SEFIN exigindo XML oficial e `tipoAmbiente=2` explícito. **Isso não conclui nenhuma cidade**; arquivos e CI específicos devem ser conferidos. Alteração deliberadamente separada da PR #413 (governança) e da trilha Bling. Estado geral MG-W1 = `IMPLEMENTING`. Próximo gate é finalizar e certificar o HEAD desta PR, depois avançar no ciclo fiscal completo MG e contratos municipais um a um.

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
