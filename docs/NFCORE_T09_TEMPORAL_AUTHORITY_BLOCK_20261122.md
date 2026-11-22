# T09 — Autoridade temporal e prorrogações por competência (22/11/2026)

**CURRENT base:** PR #592 `66456984ec6838935e3935dd92cb7a30081156b6`, Draft, sem merge, CI integral desse SHA ainda em execução. Esta matriz de seis casos não equivale a seis curadorias estaduais concluídas.

## Decisão arquitetural

O único motor determinístico de ICMS estadual continua sendo `src/kordena_fiscal/tax/state_benefits.py`, com `valid_from`, `valid_until` **exclusivo**, `legal_valid_until_inclusive` e bloqueio de competência não integral. Este bloco NÃO criou segunda regra executável, nem autorizou cálculo fiscal. Acrescentou artefato de pesquisa rastreável `NFCORE_T09_TEMPORAL_AUTHORITY_20261122.json` e testes automatizados `tests/tax/test_t09_primary_provision_guards.py`.

**Regra de segurança:** uma prorrogação do CONFAZ, por si só, não comprova vigência estadual, adoção, enquadramento ou concessão individual. Devem-se conciliar instrumentos, competência e especificidade do benefício. A data estadual de término prevalece como **limite conservador documental** até existir ato estadual posterior comprovado; isso não é julgamento jurídico definitivo.

## Casos de auditoria e evidências

| UF | Achado e controle do teste | Fonte primária ou ressalva |
|---|---|---|
| MG | Item 26 do Anexo II estadual vigora textualmente até **31/12/2026**; a comunicação do COMSEFAZ sobre prorrogação de convênios até 2028 não confirma sozinha adoção estadual nem o enquadramento do Convênio 136/97. Janeiro/2027 bloqueado enquanto não houver alteração estadual comprovada. | https://www.fazenda.mg.gov.br/empresas/legislacao_tributaria/ricms_2023_seco/anexoii2023_3.html ; https://www.confaz.fazenda.gov.br/legislacao/convenios/1997/CV136_97 ; https://comsefaz.org.br/novo/confaz-prorroga-ate-2028-convenios-de-icms-sobre-beneficios-fiscais/ |
| SP | Art. 41/Portaria CAT 35: **9,7%** (15/01–31/03/2021), **9%** (01/04/2021–14/01/2023) e **12%** desde 15/01/2023 no art. 41, até 31/12/2026 no texto consultado. A vigência a partir de 15/01/2023 não autoriza automaticamente o mês de janeiro integral. | https://legislacao.fazenda.sp.gov.br/Paginas/an3art041.aspx ; https://legislacao.fazenda.sp.gov.br/Paginas/pcat352017.aspx ; https://legislacao.fazenda.sp.gov.br/Paginas/RC33644_2026.aspx |
| RN | Peixe interno: texto original 60% do ICMS incidente e alteração para 64% em 2025 com efeitos reportados em 20/03; competência de março não pode ser automaticamente inteira, nem taxa nova retroagir sem norma. | https://www.diariooficial.rn.gov.br/dei/dorn3/documentos/00000001/20220819/783139.htm ; https://webdisk.diariooficial.rn.gov.br/Jornal/12025-03-08.pdf |
| AP | Decreto 2.349/2026 de 07/04 revogado pelo 2.656 de 17/04; bloquear generalização para abril inteiro e separação de modalidade art. 415. | https://diofe.portal.ap.gov.br/portal/edicoes/visualizar_pdf/9915/ |
| RR | Redação estadual localizada do Anexo I, art. 1 LXVII, indicava 31/12/2025; prorrogação federal do Convênio 100/97 até 2027 NÃO demonstra prorrogação estadual em 2026. | https://www.sefaz.rr.gov.br/downloads?catid=1404&id=25395&m=0&task=download.send |
| MT | Informação estadual 124/2026 vincula art.31-A/§6 ao Decreto 1.802/2025 e Convênio 79/2025, indicando 31/12/2027; janeiro/2028 não pode usar data antiga como autorização. | https://app1.sefaz.mt.gov.br/sistema/legislacao/respostaconsulta.nsf/766feae0478e62780325673c0049468e/dfdffa903c8253dd03258e28005313b4 |

## Escopo e próximos gates

Os testes demonstram apenas **guardas negativas necessárias** com dados e CNAE/NCM sintéticos, que retornam `not_applicable` após os limites; `potential` é apenas triagem consultiva, nunca direito a benefício. **0/27 aceites/importações**, hashes de DOE originais não arquivados, falta cadeia legal integral, CONFAZ exato, requisitos materiais e concessões, teste jurídico positivo realmente revisado, auditoria independente e aceite humano. A CI do **novo** HEAD deve ser comprovada após este commit. T10 bloqueada, sem merge/deploy.
