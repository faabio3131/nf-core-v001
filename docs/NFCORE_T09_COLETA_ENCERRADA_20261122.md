# NFCore T09 — Recebimento encerrado por declaração do proprietário (22/11/2026)

## Ação realizada
Coleta **ENCERRADA**, sem novas solicitações documentais ao usuário. Inventário dos **50 arquivos efetivamente recebidos** em cinco lotes de dez (40 conforme quatro manifestos prévios + últimos 10). Arquivos abrangem **22 UFs** nos lotes recentes; as outras 5 UFs continuam representadas na fila canônica de 27 candidatas e nas pesquisas anteriores. Não somar 50 capturas a 29 capturas históricas como se fossem 79 normas exclusivas, nem somar os dois ZIPs históricos como novos benefícios.

**Arquivo consolidado criado e ZIP CRC verificado:** `NFCORE_T09_COLETA_CONSOLIDADA_50_ARQUIVOS_20261122.zip`, 20785123 bytes, SHA-256 `584a0cd1458619b7033d39e95a7ee4cbe31558cba90cf0ee1cdab00e1f4cd547`, **59 entradas**: 50 documentos, quatro manifestos anteriores, dois ZIPs históricos, memorial de terceiro, relatório de fechamento e manifesto completo. O arquivo está disponível como artefato do chat, **não foi persistido como binário no GitHub**, armazenamento governado/INT-01 permanece pendente. Manifesto compactado rastreável em `docs/NFCORE_T09_RECEBIMENTO_FINAL_50_DOCUMENTOS_20261122.json`; manifesto local completo sha256 `4059c5c5b6f53e2fd62cc299e22dc2c881d358d35a1f430f9a6ae0cfa6bee8a7`.

**Integridade:** 50/50 SHA-256 calculados sobre os bytes; os primeiros 40 também conferem com os manifestos previamente emitidos. Integridade local NÃO comprova editor, texto vigente, autenticação, abrangência, CONFAZ, concessão, homologação ou aptidão para cálculo.

## Achados de risco que corrigem a triagem de terceiros

| UF | Documento/pista | Decisão |
|---|---|---|
| PB | Decreto 47.898/2026 | **EXISTE no portal oficial SEFAZ/PB** e altera o Decreto 17.252/1994, FAIN; o memorando que negava sua existência estava incorreto. https://sefaz.pb.gov.br/legislacao/397-decretos-estaduais/icms/icms-2026/17297-decreto-n-47-898-de-18-de-fevereiro-de-2026 |
| PB | Anexo Decreto 38.179/2018 | O PDF de 23 páginas inventaria benefícios de 08/08/2017 sob LC160; não é prova de aprovação/efeitos em 2026 ou NCM automática. |
| PE | Decreto 61.000/2026 | Texto da SEFAZ/PE trata EFD, regularidade e Programa Coopera, **não alteração específica do PRODEPE**. https://www.sefaz.pe.gov.br/Legislacao/Tributaria/Documents/Legislacao/Decretos/2026/Dec61000_2026.htm |
| PA | ADI 3779 | **EXISTE** no STF; não aceitar alerta de inexistência nem substituir por ADI 3246 ou ADI 3796. Acórdão, efeitos e reinstituição seguem em estudo. https://noticias.stf.jus.br/postsnoticias/adi-pede-interpretacao-conforme-a-constituicao-para-lei-paraense-de-incentivo-fiscal/ |
| GO | Certificado de depósito | Arquivo intitulado adesão611 contém Certificado SE/CONFAZ **20/2021** (duas páginas). Depósito de planilhas e menção à adesão Lei 20.787/2020 a MS; não comprova automaticamente cada benefício atual. |
| CE | Decreto 29.183/2008 / CEDIN 131/2019 | Decreto de 2008 aparece revogado pelo 32.438/2017; resolução 131/2019 dispõe do PROAPI. Ambos são auxiliares históricos, não substituem Decreto 34.508/2022 do FDI. |
| RO | Decreto 28.385/2023 | Não confundir com referência histórica **28.386/2023** da candidata CONDER. Captura de outro ato é rejeitada como substituto. |
| SP | CAT 35/2010 / CAT 35/2017 | Atos diferentes: o de 2010 cassa inscrições de substitutos; **não** orienta opção pelo crédito têxtil do ato de 2017. |
| RS | CXCIII/CXCIV | Páginas são de outras modalidades, **não** do inciso CLXXXVI das estruturas metálicas. |
| RN | Decreto 33.005/2023 | Altera outros anexos e assuntos (remessas, ICMS sobre combustíveis, remessas postais), sem comprovar regra de pescado Anexo 003; Decreto 34.390/2025 localizado separadamente. https://www.legisweb.com.br/legislacao/?id=474825 |
| AC | Convênio 190/2017 | Texto federal genérico não prova depósito específico da Lei 1.358/2000. Disputa de 2032/2035 permanece em aberto. |
| MG | Convênio 131/2026 | Convênio federal é diferente de decreto/resolução numerada pela SEF/MG; conferir prorrogação material e implementação estadual, não descartar pelo padrão de numeração estadual. |
| AP | Decreto 2.766/2007 | Fundamenta parte do regime; não resolve automaticamente suspensão do selo em 2024. |
| RR | Notícia 2025 | Não substitui prorrogação estadual do benefício Anexo I LXVII nem comprova vigência em 2026. |
| MS | LC 304/2022 | Altera LC 93/2001 e fortalece cadeia histórica; identificar modalidade/regra de concessão e efeitos. |
| PA | Lei 7.485/2010 | Altera Lei 6.913/2006; não mitiga sem análise a questão constitucional/ADI 3779. |

## Resultado formal
- **ENCERRADO:** recebimento de todos os arquivos disponíveis e manifesto por SHA-256.
- **PARCIAL:** arquivamento governado de originais (ZIP em artefato do chat, não no repositório), cotejo primário e cronologia por benefício.
- **PENDENTE:** INT-03/04/05, casos jurídicos executados INT-06, revisão contraditória independente INT-08, aceite por candidata INT-09, CI do novo HEAD INT-10 e fechamento normativo INT-11.
- **REFERÊNCIA TÉCNICA ANTERIOR:** seis workflows do HEAD `8155a7de268fb3d37d5a07c07de7a13eb244f004` foram SUCCESS, incluindo CI integral #45015043804. Nova CI obrigatória para commits deste bloco.
- **STATUS IMUTÁVEL:** 0/27 curadorias aceitas, 0/27 políticas importadas, zero homologações externas. As dependências externas não justificam parar a pesquisa/engenharia interna.
- **DECISÃO:** nenhuma promoção, merge, deploy ou ativação fiscal por este recebimento; T10 bloqueada até completar os gates definidos.

## Próxima ação sem depender de novos envios
O agente de engenharia deve continuar pesquisando fontes oficiais para lacunas específicas por UF, separar atos distintos, reconciliar CONFAZ/LC160/efeitos temporais e executar os casos legais sobre o motor único. O proprietário declarou que não possui outros documentos; **não abrir pendências artificiais de coleta com o cliente**.


## Arquivo persistente pessoal — 22/11/2026

O ZIP consolidado e seu manifesto detalhado foram copiados para a **Biblioteca pessoal privada do ChatGPT**, pasta `/NFCore Commercial Launch/T09 Legal Evidence/` e conferidos por listagem. ZIP com **20.785.123 bytes**, SHA-256 da cópia local de origem `584a0cd1458619b7033d39e95a7ee4cbe31558cba90cf0ee1cdab00e1f4cd547`, CRC íntegro e 50/50 capturas verificadas. Manifesto separado `NFCORE_T09_RECEBIMENTO_FINAL_50_DOCUMENTOS_20261122.json`, SHA-256 `4059c5c5b6f53e2fd62cc299e22dc2c881d358d35a1f430f9a6ae0cfa6bee8a7`. **Persistência de cópia pessoal confirmada**, não substitui arquivamento jurídico WORM, autenticidade de DOE ou disponibilização de bytes na CI. Arquivamento governado permanece **PARCIAL**, não marcar INT-01 como integralmente certificado.
