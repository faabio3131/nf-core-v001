# T09 — Inspeções de dispositivos oficiais (22/11/2026)

Checkpoint de entrada PR #592 HEAD aa349689a2ea670ce955861de37ccf175cdb2e3c; a CI anterior cobre esse SHA, não o commit novo. Sem mudanças de regras fiscais executáveis. Esta pesquisa NÃO é aceite de curadoria.

## SP
Fonte: https://legislacao.fazenda.sp.gov.br/Paginas/an3art041.aspx
Complemento: https://legislacao.fazenda.sp.gov.br/Paginas/an2art052.aspx
Dispositivos: Anexo III art.41; Anexo II art.52 §§4-5
Achados: Crédito outorgado de 12% da saída interna tributada sob redução de base art.52; substitui outros créditos e exclui retorno. Art.52 §4 exclui consumidor/usuário final, mas NÃO reutilizar exclusão histórica do Simples; vigência textual até 31/12/2026.
Pendências: NCM completa, CAT 35/2017, depósito 190/17 e períodos das alterações
Controles de evidência a validar: sp_art52_product_review, sp_nonreturn_credit_substitution, sp_final_consumer_and_manufacturer_review, sp_option_term_review.

## MG
Fonte: https://www.fazenda.mg.gov.br/empresas/legislacao_tributaria/ricms_2023_seco/anexoii2023_3.html
Dispositivos: Anexo II item 26 e 26.1-26.2
Achados: Saída interna de materiais especificados para Cohab MG: redução base 61,11% quando alíquota 18% ou 41,66% quando 12% (carga aproximada 7%). Exige desconto repassado ao preço e anotação na nota. Termo textual 31/12/2026, Convênio 136/97.
Pendências: Resolução conjunta 01/1998, comprovação concreta e prorrogações CONFAZ
Controles de evidência a validar: mg_cohab_material_project, mg_discount_invoice_note, mg_convention_136_97.

## RN
Fonte: https://www.diariooficial.rn.gov.br/dei/dorn3/documentos/00000001/20220819/783139.htm
Complemento: https://webdisk.diariooficial.rn.gov.br/Jornal/12025-03-08.pdf
Dispositivos: Anexo 003 art.1 I a, arts.5-6; Decreto 34.390/2025
Achados: Art.1 original: 60% do ICMS incidente sobre peixe em saída interna originário RN, depois 64% segundo alteração 2025 ainda sujeita a verificação da competência. Exige termo de opção, PJ contribuinte normal, ajuste EFD e restrições de créditos. Não é benefício de aves.
Pendências: Competência intramensal 20/03/2025, opção, CONFAZ e cadeia intermediária
Controles de evidência a validar: rn_fish_origin, rn_option_term, rn_efd_credit_adjustment, rn_competence_amendment.

## PB
Fonte: https://sefaz.pb.gov.br/legislacao/397-decretos-estaduais/icms/icms-2026/17297-decreto-n-47-898-de-18-de-fevereiro-de-2026
Dispositivos: Decreto 47.898/2026 arts.1-5; Decreto 17.252/1994 arts.3 §§9 e 15-17 e art.31 §§3-4
Achados: DOE 19/02/2026. Novo produto: NCM diferente em pelo menos um dos quatro primeiros dígitos; novos produtos exigem novo projeto; excesso de produção dos mesmos produtos e mesmas condições segue regra diversa. Certidão SEFAZ para bem sem similar. Industrialização por encomenda possui regras próprias.
Pendências: Regulamento completo, efeitos interpretativos, requisito de projeto e CONFAZ
Controles de evidência a validar: pb_fain_project_approval, pb_ncm_first_four_digits, pb_new_product_project, pb_grant_review.

## PE
Fonte: https://www.sefaz.pe.gov.br/Legislacao/Tributaria/Documents/Legislacao/Decretos/2026/Dec61000_2026.htm
Complemento: https://www.sefaz.pe.gov.br/Legislacao/Tributaria/Documents/legislacao/decretos/1999/Dec21959_99.htm
Dispositivos: Decreto 61.000/2026 ementa; Lei 11.675/1999 e Decreto 21.959/1999
Achados: Decreto 61.000/2026 altera EFD-ICMS/IPI e conformidade Programa Coopera, NÃO altera materialmente benefício PRODEPE. Não usar como ato concessivo nem modificador de percentual.
Pendências: Localizar alterações realmente pertinentes ao PRODEPE e validar produto, prazo, EFD, concessão
Controles de evidência a validar: pe_prodepe_material_act, pe_prodepe_product_grant, pe_actual_amendments, pe_confaz_route.

## PI
Fonte: https://portaldalegislacao.sefaz.pi.gov.br/Arquivos/ARQUIVOS_CHRONUS/ARQUIVO_PRINCIPAL_LEGISLACAO/1396/Decreto_n_21.866_2023_-_ANEXO_IV.pdf
Dispositivos: Anexo IV art.25-A, Decreto 23.672/2025
Achados: Isenção das saídas INTERNAS do rol de alimentos no art.25-A com efeitos desde 01/04/2025; não abrange qualquer alimento ou saídas interestaduais, depende do Convênio 224/2017 e atos supervenientes.
Pendências: Confrontar DOE 23.672 data, Convênios 21/26 e 131/26, ST, créditos e estornos
Controles de evidência a validar: pi_internal_operation, pi_art25a_product_list, pi_confaz_224_17, pi_validity_by_competence.

## Decisões

Não aproveitar fontes secundárias como original. Os 50 arquivos recebidos foram vinculados aos 27 dossiês sem confundir captura com vigência. PE Decreto 61.000/2026 deixa de figurar como modificador material PRODEPE; PB Decreto 47.898/2026 é confirmado. Sem inventar CNAE, NCM, CFOP, atos individuais, CONFAZ, data de competência ou percentual. Todos os 27 status de aceite permanecem negativos. Não confundir uma guarda testada com o benefício integral homologado. A revisão independente e o aceite humano permanecem pendentes.
