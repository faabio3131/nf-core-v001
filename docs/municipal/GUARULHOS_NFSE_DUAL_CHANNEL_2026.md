# Guarulhos/SP — NFS-e 2026 — dois canais fiscais, um único NFCore

**Bloco:** SP-22 / Grupo GissOnline V2. **IBGE:** 3518800. **Data:** 15/11/2026.
**PR incremental:** #508 (`feat/nfcore-web-louveira-sp22-nacional-20261115`) conforme autorização posterior do proprietário para avançar municípios na **mesma PR** e fechar tudo depois. As decisões anteriores de bloco isolado continuam históricas e NÃO significam que este incremento já esteja certificado ou mergeado.
**Autoridade:** o Integrador/Release Manager é responsável pela revisão e merge na candidata #468; não alterar `main` nem Contabo nesta frente.

## Fontes primárias e atualidade

1. **Receita Federal, 14/08/2026 — Resolução CGSN 191/2026:** https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/agosto/simples-nacional-nfs-e-nacional-sera-obrigatoria-para-me-e-epp-a-partir-de-1o-de-novembro-de-2026
2. **CGNFS-e, 29/10/2026 — obrigatoriedade nacional por competência desde 01/11/2026:** https://www.gov.br/nfse/pt-br/noticias/nfs-e-informa-diretrizes-sobre-a-obrigatoriedade-da-emissao-da-nfs-e-nacional-para-optantes-do-simples-nacional
3. **Prefeitura/Secretaria da Receita — migração do GissOnline V2 desde 01/07/2026:** https://www.guarulhosdigital.com.br/noticia/guarulhos/nova-versao-do-gissonline-v2-entrou-em-operacao-em-1-de-julho
4. **Guarulhos — comunicado novembro/2026:** https://www.guarulhosdigital.com.br/noticia/guarulhos/nfs-e-do-simples-nacional-passa-a-ser-emitida-exclusivamente-no-emissor-nacional
5. **GissOnline Guarulhos, portal técnico vigente:** https://guarulhos.giss.com.br/giss-ajuda/desenvolvedores.html — manual técnico **Serviços Prestados V1.8** (2026), manual de retorno V1.0 e XSD atual. O material indica SOAP, ABRASF 2.04 + novos campos RTC, assinatura A1/A3 com ICP-Brasil e mTLS.
6. **WSDL informado no manual V1.8:** `https://ws-MEUMUNICIPIO.giss.com.br/service-ws/nf/nfse-ws?wsdl` e homologação `https://v2-ws-homologacao.giss.com.br/service-ws/nf/nfse-ws?wsdl`. O WSDL exige certificado cliente ICP-Brasil; a URL de produção *específica de Guarulhos* e as ações reais precisam ser validadas por hash e identificação municipal, sem inferir somente pelo nome.

## CURRENT → TARGET, disciplina fiscal

- `TaxRegimeCode.MEI`, competência desde 01/09/2023: **Emissor Nacional**.
- `TaxRegimeCode.SIMPLES_NACIONAL` e `SIMPLES_NACIONAL_EXCESS_SUBLIMIT`, competência desde **01/11/2026**: **Emissor Nacional**. Para competências de 01/07 até 31/10/2026, o GissOnline V2 pode receber emissão retroativa conforme as regras oficiais e credenciamento. A observância do sublimite exige decisão tributária canônica efetiva; não assumir.
- `TaxRegimeCode.NORMAL` na competência de 01/07/2026 em diante: **GissOnline V2**. Competências anteriores a 01/07 exigem contrato legado independente, não são autorizadas só por essa regra.
- `classify_sp_national_nfse_eligibility` continua a autoridade federal compartilhada. `require_guarulhos_nfse_channel` é uma verificação negativa da jurisdição/competência/regime sobre a **mesma** seleção de provedor persistida no Control Plane. Não registra binding, não escolhe certificado, não transmite nem modifica ISS.
- Emissor Nacional: o mesmo gateway DPS/SEFIN e eventos do NFCore utilizados por Louveira e Salto, sem cópias.
- GissOnline V2 municipal: opt-in do **mesmo SP4 Canonical RPS UoW** e `JundiaiGissHomologationTransport` reutilizado para a família GISS. Exige portas de XSD, assinatura, WSDL/SOAPAction, identidade A1 e prova oficial injectadas e revisadas; não permite aprovação por HTTP 200 ou apenas protocolo de lote. Não usar GINFES antigo como provedor vigente.
- A versão 1.8 exige adaptação dos campos RTC. **Não presumir que o pacote XSD Jundiaí seja idêntico**: pin de XSD/WSDL de Guarulhos é dependência documental para ativar transporte real, e sem ele o bootstrap não injeta as portas operacionais.

## Critérios de aceite (não marcar como certificados antes da CI do HEAD final)

1. Checagem do regime e competência pelo Portal e também pelo gateway canônico; nacional não aceita normal, municipal não aceita MEI/Simples após cutoff. Estabilidade dos outros municípios.
2. Cadastro de provedor por tenant/unidade/IBGE/operação `GUARULHOS_GISS_V2_PROVIDER_ID` e `NACIONAL_HOMOLOGATION_PROVIDER_ID`, sem spoof via browser; mesma sessão/RBAC e mesmos estados.
3. RPS municipal com identidade persistente, lote não rePOSTado em retorno incerto, consulta original por RPS e prova autorizada correlacionada. Cancelamento, substituição e retorno IBSCBS ainda exigem XSD/WSDL oficial completo para serem declarados concluídos.
4. Testes separados de transição 31/10→01/11, situação NORMAL, MEI, Simples/MEI, regra de 01/07, isolamento city/tenant, violação de binding e validação XSD, além de E2E HTTP da preparação.
5. Ruff/Mypy/Pytest/frontend/E2E/containers e CI remota integral no HEAD exato, seguidos de revisão do Integrador.

**Estado desta entrega incremental:** implementação do encaminhamento duplo e reutilização tipada do transport GissOnline V2. **Não declarar cobertura total de Guarulhos, certificação do bloco nem homologação externa** enquanto os contratos e operações municipais não estiverem comprovados e a CI final não passar.

**Louveira PF:** pendência anterior independente rastreada na issue #509. Não confundir avanço para Guarulhos com o fechamento de PF.
