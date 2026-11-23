# T09 — parecer de reauditoria jurídica final do lote (23/11/2026)

**CI pré-requisito:** [45256835394](https://github.com/faabio3131/nf-core-v001/actions/runs/45256835394), **SUCCESS**, HEAD `161743ce577c3d7f99bc51441af53e66cdcd0721`, verificado antes deste commit. **Sem alteração do motor fiscal; importação/cálculo bloqueados 4/4.**

## Deliberações legais que podem ser concluídas sem inventar prova

| UF | Prova documental | Veredito juridicamente suportado | Limite lógico |
|---|---|---|---|
| **PA** | [STF ADI 3779](https://portal.stf.jus.br/peticaoInicial/verPeticaoInicial.asp?base=ADI&numProcesso=3779) arquivo HTML SHA `aede1b1a62bca6bdf677a8c0a54313a61785cd538a1b05ce6a91a96e2c0b5ac5`, [DOE 33.584/2018](https://www.ioepa.com.br/pages/2018/2018.03.23.DOE.pdf) SHA `6dbf8fdb313e6673ce6105b9c6e74714070adaa220e39cbd2187840ef4abf0a0` e [Decreto 2.490/2006](https://bancodeleis.alepa.pa.gov.br/arquivos/lei2490_2006_53513.pdf) SHA `313fe0b074d55dedbff71ba148b7e703a96da1611341aee0ae074ceaa5278ad3` | **NAO_APLICAVEL_CERTIFICADO** exclusivamente para invocação **isolada** da Lei 6.913/2006 invalidada no STF | Não declarar que a Lei 8.930/2019 nunca reinstituiu modalidades: arts. 3º–6º tratam de sucessão condicionada e depósitos; atos individuais continuam requeridos para uso real |
| **RR** | [Consulta oficial 24/2024](https://www.sefaz.rr.gov.br/downloads?catid=1404&id=25395&m=0&task=download.send) cita texto do Anexo I art. 1º LXVII, prazo até 31/12/2025, Decreto 30.363-E/2021. [Diretório 2026](https://www.sefaz.rr.gov.br/downloads/legislacao?dir=02+-+LEGISLACAO+ESTADUAL%2F07+-+DECRETOS%2F2026) | **NÃO IMPORTAR** a redação de 2021 no ano 2026; aquele prazo expirou | O índice de downloads da SEFAZ não é acervo necessariamente exaustivo, e o PDF oficial da Consulta não tem hash arquivado: certidão negativa da inexistência de todo decreto superveniente não foi obtida. **Não declarar NAO_APLICAVEL_CERTIFICADO 2026 de toda modalidade sem essa prova** |
| **AP** | [DOE 8.631/2026](https://diofe.portal.ap.gov.br/portal/edicoes/download/9901) SHA `8db2b8901a3774739846444691b8caced5bd549759537e28182fc19782bcf9c5`, pp. 20 e 29–33; [DOE 8.639/2026](https://diofe.portal.ap.gov.br/portal/edicoes/download/9915) fonte oficial para Decreto 2.656/2026 | **Impede certificação negativa geral**: Decreto 2.349/2026 art. 27 menciona expressamente indústria do pescado; art. 29 prevê diferimento e outras modalidades; Decreto 2.656 art. 3º também contempla pescado e art. 9º revoga 2.349 | Ausência do Decreto 3.599/2001 no Anexo da Lei 3.490/2026 não prova extinção; Lei 3.395/2025 menciona 3.599. Precisam-se CRD 14/2018, texto integral 3.599 e atos de concessão para liberar modalidade material em 2026 |
| **SE** | [Lei 8.490/2018 ALESE, art.1º e Anexo Único item1](https://aleselegis.al.se.leg.br/Arquivo/Documents/legislacao/html/l84902018.html) indica reinstituição da Lei 3.140/1991 e certificado CONFAZ 13/2018; SHA ALESE Lei 3.140 `520b1a1f93b9a1c6c8ec5d315d5d885ec436df4236f7c46dfbdc9a21b9c080a5`; decreto histórico PGE `ca18358fccdfd93259819b1ab1d2fe7347b7084cde54d9660b3c8d0ffc67b3b8` | **6/6 modalidades com base legal identificada, 0/6 certificadas para importação**; não há prova de inexistência do PSDI | Faltam certificado CONFAZ 13/2018/planilha e originais dos decretos 820 e 868/2024 com vínculo por modalidade, revisão de alterações até 2026 e ato CDI para contribuinte real |

## Seis modalidades de SE — avaliadas separadamente

| Código | Modalidade e risco de confusão | Resultado |
|---|---|---|
| `SE_PSDI_NEW_INDUSTRY_8` | Percentual 8% sobre ICMS devido, **não alíquota nominal** | **BLOCKED**, norma identificada; vínculo modal CONFAZ/alterações e ato CDI não comprovados |
| `SE_PSDI_NEW_INDUSTRY_6_2` | Percentual 6.2% sobre ICMS devido, **não alíquota nominal** | **BLOCKED**, norma identificada; vínculo modal CONFAZ/alterações e ato CDI não comprovados |
| `SE_PSDI_DOMESTIC_RAW_DEFERRAL` | Benefício condicionado/sem percentual único | **BLOCKED**, norma identificada; vínculo modal CONFAZ/alterações e ato CDI não comprovados |
| `SE_PSDI_CAPITAL_GOODS_DEFERRAL` | Benefício condicionado/sem percentual único | **BLOCKED**, norma identificada; vínculo modal CONFAZ/alterações e ato CDI não comprovados |
| `SE_PSDI_IMPORTED_RAW_DEFERRAL` | Benefício condicionado/sem percentual único | **BLOCKED**, norma identificada; vínculo modal CONFAZ/alterações e ato CDI não comprovados |
| `SE_PSDI_EXISTING_INDUSTRY_GROWTH` | Benefício condicionado/sem percentual único | **BLOCKED**, norma identificada; vínculo modal CONFAZ/alterações e ato CDI não comprovados |

## Critérios de certificação

`APLICAVEL_CERTIFICADO`: fonte original oficial íntegra com SHA por ato e por alteração, efeito temporal competente, fundamento CONFAZ efetivo e testes positivos/negativos. `NAO_APLICAVEL_CERTIFICADO`: prova afirmativa de expiração, revogação, inconstitucionalidade ou ausência de internalização suficientemente exaustiva **para o instrumento rigorosamente delimitado**. **Não equiparar “não consegui baixar” a “não existe”**. Para todos: `tax_calculation_authorized=false`, `import_authorized=false`, sem deploy nem merge.

## Artefatos e lacunas exatas

- AP: Decreto 2.656/2026 download oficial PDF `https://diofe.portal.ap.gov.br/portal/edicoes/download/9915` agora acrescentado à fila de captura; fonte jurídica válida mesmo sem novo SHA nesta revisão. Certificado de registro e depósito **AP/CONFAZ 14/2018, Anexo I item 11**, republicação do Decreto 3.599/2001 no **DOE AP nº 2.751 de 25/03/2002**.
- SE: **SE/CONFAZ nº 13/2018 + planilha**, DOE-SE **16/10/2024** (Decreto 820) e **26/11/2024** (Decreto 868). O **certificado 126/2024** não é substituto do 13/2018.
- PA: arquivo integral da **Lei 8.930/2019** com hash, depósito PNTT específico dos atos reinstituídos, prova sobre efeitos após ADI 3779 e concessões; permanece negativa a utilização **isolada** do texto invalidado.
- RR: DOE/compilação RR que alcance competência novembro de 2026 para o inciso LXVII, decreto expresso posterior se houver e original Consulta 24/2024 com SHA. Índice recente não constitui prova negativa exaustiva.

**Resultado técnico do motor:** 4/4 bloqueios implementados e preservados. **Resultado jurídico amplo:** 0/4 vereditos binários irrestritos demonstrados; **1 veredito negativo estritamente delimitado (PA, lei original isolada)**. O exame de fatos novos afasta conscientemente qualquer declaração de “4/4 jurídico” inventada.
