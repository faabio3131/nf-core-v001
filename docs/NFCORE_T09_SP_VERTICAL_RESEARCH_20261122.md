# T09 — SP: dossiê vertical de ICMS têxtil (checkpoint não certificado)

## Escopo exato
**Candidata:** SP-RICMS2000-AN3-ART41-TEXTILE-V1. **Estado:** SP. **Autoridade operacional:** motor único `kordena_fiscal.tax.state_benefits`; documento é pesquisa. Nenhuma regra ativada nem curadoria aceite; T09-EXT (aprovação do proprietário/contador/concessões reais) não impede a investigação técnica.

## Atos estaduais, efeitos e histórico
- **Decreto 62.560/2017**: a partir de 2017-05-06, Art.41 introduced with 12%; base: state official art41 and RC33644/2026.
- **Decreto 65.255/2020**: a partir de 2021-01-15, 9.7% for 15/01–31/03/2021; base: state official art41 and CAT35/2017.
- **Decreto 65.452/2020**: a partir de 2021-04-01, 9% through 14/01/2023; base: state official art41 and RC33644/2026.
- **Decreto 67.524/2023**: a partir de 2023-01-15, 12% thereafter, based on taxpayer eligible sale value; base: state official art41 and RC33644/2026.
- **Decreto 69.292/2025**: a partir de 2025-01-01, Art41 and Art52 current statutory end extended to 31/12/2026; base: state official art41 and art52.
- **Portaria CAT 35/2017**: a partir de 2017-05-27, RUDFTO formal optional election + 12-month minimum + apportioned credit reversal; later CAT126/2017 and CAT27/2021; base: state official CAT35/2017.

**Conflito de redação resolvido:** a Portaria CAT 35/2017 mantém menção a 9% na redação de 2021, mas o decreto estadual prevalente (67.524/2023) restabeleceu 12% a partir de 15/01/2023, confirmado pela consulta tributária 33644/2026. Essa consulta é sobre crédito extemporâneo de um caso particular e **não comprova que outros contribuintes preencham os requisitos**.

## Fontes primárias e preservação por hash
- [RICMS/SP Anexo II art.52](https://legislacao.fazenda.sp.gov.br/Paginas/an2art052.aspx), arquivo recebido `SP_RICMS_AnexoII_art52.html`, **171572 bytes**, SHA-256 **0b8102e052b75146a61636c5cbbfaf3b82120b11c5ef1aafe33ac80e9a3b901d**. O hash atesta exclusivamente os bytes da captura HTML no portal estadual; **não certifica o arquivo originário do DOE nem a cadeia integral**.
- [Portaria CAT 35/2017](https://legislacao.fazenda.sp.gov.br/Paginas/pcat352017.aspx), arquivo recebido `SP_PortariaCAT_35_2017.html`, **158040 bytes**, SHA-256 **fbbb5fdbce095d7fe439d06ec4b3f0af5071b1f02080d1ae18146d51423d6d04**. O hash atesta exclusivamente os bytes da captura HTML no portal estadual; **não certifica o arquivo originário do DOE nem a cadeia integral**.
- [Art41 Anexo III](https://legislacao.fazenda.sp.gov.br/Paginas/an3art041.aspx): texto oficial consultado (sem hash dos bytes originais publicados neste pacote).
- [RC 33644/2026](https://legislacao.fazenda.sp.gov.br/Paginas/RC33644_2026.aspx): consulta publicada em 04/11/2026, com ressalva explícita de não confirmação do direito material.
- [Portaria CAT35/2010](https://legislacao.fazenda.sp.gov.br/): arquivo indevidamente confundível com a Portaria CAT35/2017; **não usar** como evidência do crédito têxtil.

## Critérios materiais com base no dispositivo
- Internal taxable sales of listed textile NCM manufactured by eligible SP establishment (Art41 c/c Art52) — Art41 caput; Art52 caput.
- Art52 item I: NCM 5402–5406, 5501–5507, 5902.20.00 (12% ICMS burden); item II textile chapters with exclusions including 5601 and 6309, plus specified accessories, subject to current version — Art52 I, II(a-i).
- Art52 §1: own manufacturer, same owner transfer or qualifying in-state outsourced manufacturing with material/brand/credential condition — Art52 §1.
- Art52 §2: tax regularity and permitted sureties or active installments where expressly allowed — Art52 §2.
- Art52 §4: no consumer or final user (current post-2021 text); historical separate Simples restriction NOT current by inference — Art52 §4.
- Art41 §§1-4: taxable, book as Outros Créditos, no real/symbolic return, substitutes other credits — Art41 §§1-4.
- Portaria CAT35/2017 art2: RUDFTO election for all establishments, subsequent-month effectiveness, minimum 12 months — CAT35 art2.
- Portaria CAT35 art5: apportioned reversal E=(B/T)xC using 12-month mean and memory/RAICMS records — CAT35 art5.
- CFOP 5.101; CNAE 14.21-5/00; NCM 6115.95.00 are example facts in RC33644/2026, NOT complete statute-wide white lists — RC33644/2026 items1–3.

### Cenários negativos obrigatórios
- Out-of-state sale CFOP 6.101 → not_applicable; Art41 caput, Art52 caput.
- Final consumer → insufficient_basis without nonfinal-consumer proof; Art52 §4.
- NCM 6309.00.00 in excluded position 6309 → not_applicable; Art52 II(a).
- No RUDFTO option or within incomplete first month → insufficient_basis/not_applicable; CAT35 art2.
- Actual/symbolic return, accumulation of input credits → insufficient_basis; Art41 §§3-4, CAT35 art5.
- Competence 01/2027 without demonstrated extension → not_applicable; Art41 §5 and Art52 §5.
- Unresolved ST or DIFAL for a concrete operation → insufficient_basis; canonical mandatory operation evidence, not general statutory waiver.

## Gates ainda faltantes
- Obtain original publication bytes for Art41 and binding amendment acts, archived and SHA-256 matched
- Verify full chain including later 2026 publications and exact historical time boundaries
- Validate explicit LC160/CONFAZ190 deposit/certificate and art41/52 reinstitution effects
- Resolve entire NCM eligibility by exact context, ST/DIFAL and outsourced manufacturing exceptions
- Run and archive end-to-end positive/negative cases as state-specific source-backed tests
- Independent third-party technical/legal counterreview with auditable review identity

**Proveniência legal:** o art.41 e o art.52 citam o Convênio 190/2017, mas isso **não comprova sozinho** a planilha depositada/registro da modalidade. O campo `source_publication_and_original_bytes_digest` da fila permanece **NULL** por falta do original completo da publicação-base. Os seis gates restantes e o aceite continuam false, e a pesquisa não muda `review_status=draft`.

## Testes
O módulo `tests/tax/test_t09_sp_textile_vertical.py` executa hipóteses de fábrica, NCM e CFOP baseadas na consulta de 2026 **com dados sintéticos e sem declaração de entitlement**. Resultado `potential` do motor é exclusivamente triagem: `issuance_authorized=false`, `tax_calculation_authorized=false`, `eligibility_certified=false`. O teste não prova a integralidade da classificação NCM nem a regularidade da opção de um contribuinte verdadeiro. Submeter execução CI e análise contraditória independente.
