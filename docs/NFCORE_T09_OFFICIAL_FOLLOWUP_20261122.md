# T09 — Cotejo adicional de fontes primárias e revisão adversarial (22/11/2026)

**Classificação:** pesquisa normativa parcial, **não** revisão adversarial por agente independente, certificação de 27 benefícios ou autorização fiscal. HEAD de entrada `3d2fa6c3a47d0cf487ae54b87a7f87fec3065c2e`; PR #592 em Draft. 5 novas análises documentadas: AC/PB/MS/TO/PR. As outras 22 UFs conservam a fila anterior sem reclassificação artificial.

## AC — Decreto AC 11.852/2026 sobre RICMS Decreto 008/1998
- **Fonte estadual:** https://legis.ac.gov.br/detalhar/6757
- **Fonte complementar:** https://legis.ac.gov.br/detalhar/4788
- **Achado do texto/consulta:** Regras de entradas interestaduais/DIFAL e regime especial de industrial beneficiado; não criam automaticamente crédito presumido da Lei 1.358/2000.
- **Risco de falso positivo:** Separar mercadorias usadas no processo industrial das demais; não deduzir dispensa de DIFAL ou da antecipação como regime fiscal universal.
- **Condições a demonstrar por modalidade:** industrial_process_destination; special_regime_terms_and_difal; state_normative_eligibility_as_of_competence
- **Cadeia pendente:** Lei 1.358 financiamento é juridicamente distinta de crédito outorgado. Ato integral do DOE, alterações posteriores, LC160/CONFAZ exatos, competência, CNAE/NCM/CFOP, ST/DIFAL, testes jurídicos concretos e revisão externa independente de engenharia não foram certificados nesta rodada.

## PB — Decreto PB 48.405/2026 e Portaria 00080/2026/SEFAZ
- **Fonte estadual:** https://sefaz.pb.gov.br/legislacao/397-decretos-estaduais/icms/icms-2026/17811-decreto-n-48-405-de-03-de-julho-de-2026
- **Fonte complementar:** https://www.sefaz.pb.gov.br/legislacao/400-portarias/portarias-2026/17560-portaria-n-00080-2026-sefaz
- **Achado do texto/consulta:** CRF/FGTS válido na data do protocolo para concessão/renovação, Decreto 48.405 arts.1-5; Portaria 80 exige certidão de não similaridade para hipótese específica do FAIN.
- **Risco de falso positivo:** Não impor CRF por nota fiscal mensal sem previsão legal; nem presumir que quatro dígitos de NCM comprovam não similaridade sem certidão quando necessária.
- **Condições a demonstrar por modalidade:** fgts_valid_on_grant_or_renewal_request; fain_geief_non_similarity_certificate_when_relevant; distinct_new_product_ncm_four_digits
- **Cadeia pendente:** FGTS é requisito de pedido/renovação, não um benefício aplicável automaticamente em operações. Ato integral do DOE, alterações posteriores, LC160/CONFAZ exatos, competência, CNAE/NCM/CFOP, ST/DIFAL, testes jurídicos concretos e revisão externa independente de engenharia não foram certificados nesta rodada.

## MS — LC MS 93/2001 consolidada, LC 347/2025 e ADI 3794
- **Fonte estadual:** https://aacpdappls.net.ms.gov.br/appls/legislacao/secoge/govato.nsf/66ecc3cfb53d53ff04256b140049444b/3a836f159c1b161904256c000058e57a
- **Fonte complementar:** https://www.ms.gov.br/financas-e-impostos/requerimento-de-incentivos-fiscais-com-compromisso-de-obrigacoes-reciprocas63
- **Achado do texto/consulta:** Versão consolidada registra declaração STF ADI 3794 sobre dispositivos da LC 93; normas posteriores LC160/LC241 e LC347 requerem cotejo; LC347 art24-F define contribuição 13% no período 01/09/2025–31/08/2026 para grupo específico.
- **Risco de falso positivo:** Não usar arts.6-8 históricos declarados inconstitucionais como autorização isolada, nem aplicar 13% a todo MS-Empreendedor sem enquadramento no art.24-F.
- **Condições a demonstrar por modalidade:** ms_adi3794_constitutionality_chain; ms_eligible_individual_terms; ms_24f_contribution_period_when_applicable
- **Cadeia pendente:** Portal de serviço oficial confirma pedidos sujeitos a contrapartidas e instrumento bilateral, não modalidade automática de crédito. Ato integral do DOE, alterações posteriores, LC160/CONFAZ exatos, competência, CNAE/NCM/CFOP, ST/DIFAL, testes jurídicos concretos e revisão externa independente de engenharia não foram certificados nesta rodada.

## TO — Lei TO 1.385/2003; Lei 3.577/2019; consulta tributária 034/2024
- **Fonte estadual:** https://dtri.sefaz.to.gov.br/legislacao/ntributaria/Leis/Lei1.385-03.htm
- **Fonte complementar:** https://dtri.sefaz.to.gov.br/legislacao/consultas/2024/Consulta034.2024.htm
- **Achado do texto/consulta:** Art.6º Lei 1.385 vincula benefício a carta-consulta aprovada; Lei 3.577/2019 trata remissão, anistia e reinstituição no Convênio 190/2017.
- **Risco de falso positivo:** Distinguir PROINDÚSTRIA e PROSPERAR, substituição tributária e operação; Lei de reinstituição não prova planilha depositada específica.
- **Condições a demonstrar por modalidade:** to_approved_consulta_and_instrument; to_lc160_reinstitution_and_confaz_deposit; to_st_incidence_by_operation
- **Cadeia pendente:** Lei 3.577/2019 identificada no índice de Leis da SEFAZ/TO; ainda falta cotejo de anexos/certificados por modalidade. Ato integral do DOE, alterações posteriores, LC160/CONFAZ exatos, competência, CNAE/NCM/CFOP, ST/DIFAL, testes jurídicos concretos e revisão externa independente de engenharia não foram certificados nesta rodada.

## PR — Decreto PR 7.721/2024 e Resolução SEFA 227/2026
- **Fonte estadual:** https://www.legislacao.pr.gov.br/legislacao/pesquisarAto.do?action=exibir&codAto=341992
- **Fonte complementar:** https://www.legislacao.pr.gov.br/legislacao/listarAtosAno.do?action=exibir&codAto=389398&codItemAto=2473441
- **Achado do texto/consulta:** Decreto Paraná Competitivo tem modalidades com contribuição de 0,4% sobre base de operação e relatórios de investimento, conforme artigo/benefício específico. Resolução 227/2026 versa transferência de créditos do art.12, não lista de NCM proibidas do art.14.
- **Risco de falso positivo:** Não aplicar contribuição de 0,4% a todas modalidades, nem converter resolução de transferência em lista de NCM elegível.
- **Condições a demonstrar por modalidade:** pr_modality_and_legal_item; pr_financial_contribution_if_required; pr_negative_ncm_list_current_by_act
- **Cadeia pendente:** Resolução 469/2026 alterou condições da 227; verificar redação vigente, prazo e contratos/termos do investidor. Ato integral do DOE, alterações posteriores, LC160/CONFAZ exatos, competência, CNAE/NCM/CFOP, ST/DIFAL, testes jurídicos concretos e revisão externa independente de engenharia não foram certificados nesta rodada.


## Testes e autoridade
`tests/tax/test_t09_official_2026_crosschecks.py` verifica cruzamento com as mesmas 27 identidades, fontes e riscos de falsos positivos; **não declara execução de concessão individual, nem simula que uma fonte isolada satisfaz todos os gates**. Os drafts permanecem em `review_status=draft`, `import_authorized=false`.

## Fonte primária vs original arquivado
Foram consultados textos públicos e índices oficiais, mas **nenhum hash de PDF/DOE foi inferido de uma página web**. Os 50 arquivos capturados anteriormente foram verificados byte a byte e estão em Biblioteca pessoal do ChatGPT. Esta Biblioteca privada não substitui arquivamento jurídico imutável, DOE autenticamente verificado, nem armazenamento acessível à CI. O arquivo consolidado original e o manifesto foram preservados separadamente no caminho privado `/NFCore Commercial Launch/T09 Legal Evidence/`. Não inserir URLs ou IDs privados como se fossem fontes oficiais.

## Certificação e pendências
T09-INT requer 27 cadeias normativas e CONFAZ vinculados por modalidade, evidências oficiais disponíveis, regra e competência exatas, condições legais, casos jurídicos negativos/positivos reproduzíveis, revisão técnica independente e CI do HEAD final. Nenhum dos cinco achados é aceito automaticamente. T09-EXT (aceite humano, parecer assinado e concessões reais) permanece fora do DoD de pesquisa, mas é obrigatório para fruição fiscal real.
