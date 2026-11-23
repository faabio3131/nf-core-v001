# NFCore T09 — PSDI Sergipe, dossiê por modalidade (23/11/2026)

**Status: pesquisa material substancial, SEM certificação normativa final.** Os arquivos de usuário e da coleta antiga foram preservados. Não exigimos concessão concreta de cliente nem parecer contábil externo para a pesquisa. Candidata `SE-PSDI-LEI3140-DEC29935-V1` segue `draft`.

## Proveniência confirmada

- **ALESE:** [Lei 3.140/1991 compilada até Lei 9.943/2026](https://aleselegis.al.se.leg.br/Arquivo/Documents/legislacao/html/l31401991.HTML); HTML do usuário em Biblioteca SHA256 `520b1a1f93b9a1c6c8ec5d315d5d885ec436df4236f7c46dfbdc9a21b9c080a5`; compilado legislativo, não DOE original.
- **PGE:** [Decreto 29.935/2014 histórico, 37 páginas](https://pge.se.gov.br/wp-content/uploads/2025/02/DECRETO-29-935-1.pdf); PDF no acervo já entregue em `/NFCore Commercial Launch/T09 Legal Evidence/SE_Decreto_29935_2014_PGE_Original_Historico.pdf`, bytes reais **171106**, SHA256 `ca18358fccdfd93259819b1ab1d2fe7347b7084cde54d9660b3c8d0ffc67b3b8`. **É versão histórica, sem alterações 820/868 de 2024; não foi comparado byte a byte com URL PGE em tempo real.**
- **Decreto 820/2024**, DOE 16/10/2024, efeitos declarados de **23/07/2024**: art5 IV-e, §5-B, §28. Texto consultado na [reprodução](https://www.legisweb.com.br/legislacao/?id=466606). Publicação original não arquivada; **julho de 2024 é intramensal**.
- **Decreto 868/2024**, DOE 26/11/2024, eficácia desde a publicação: art5 §§5-C..5-G, Anexo III e §22 revogado. Texto consultado na [reprodução](https://www.legisweb.com.br/legislacao/?id=469405). Publicação original não arquivada; **novembro de 2024 é intramensal**.
- **Leis 9.494/2024, 9.812/2025 e 9.943/2026**: disposições indicadas no HTML oficial ALESE; datas/atos originais e eventuais mudanças subsequentes ainda requerem verificação.
- **[Certificado SE/CONFAZ 126/2024](https://www.confaz.fazenda.gov.br/legislacao/certificado-registro-deposito-cv-icms-190-17-1/sergipe/2024/126-certificado-de-registro-e-deposito-se-an-e-ac-alteracao-e-extensao.pdf)**: depósito registrado **125/2024**, atos de **outubro de 2022**, LC160/Convênio 190. **Não é aprovação modal automática**. Sem planilha e ato que vinculem uma modalidade específica, todas permanecem `CONFAZ_PENDING`.

## Matriz jurídica por modalidade

| Modalidade | Dispositivo | Condição positiva | Exclusão/vedação | Fundamento CONFAZ | Situação |
|---|---|---|---|---|---|
| SE_PSDI_NEW_INDUSTRY_8 | Lei 3.140/1991 art3 §5 I; Decreto 29.935/2014 art5 §3 I | nova indústria industrial/agroindustrial/pecuária aquícola em modalidade apta, resolução CDI individual eficaz, receita/ICMS da atividade-fim e demais provas | empresa no Simples atual; ausência de resolução CDI; operação fora da atividade-fim; ICMS-ST retido; consumidor final sem exceção comprovada | PENDING_ACT_SPECIFIC_MATCH | Não certificada |
| SE_PSDI_NEW_INDUSTRY_6_2 | Lei 3.140/1991 art3 §5 II; Decreto 29.935/2014 art5 §3 II | novo empreendimento na localização semiárida ou de fronteira / projeto de relevante interesse conforme hipótese normativamente prevista, CDI e requisitos comprovados | localização genérica; projeto relevante sem deliberação CDI; resolução sem percentual de 6,2%; empresa no Simples atual | PENDING_ACT_SPECIFIC_MATCH | Não certificada |
| SE_PSDI_DOMESTIC_RAW_DEFERRAL | Lei 3.140/1991 art3 IV d, §31, §5-B; Decreto 820/2024 art1; Decreto 868/2024 art1 §§5-C..G | operação interna de matéria-prima efetivamente industrializada, sem cumulação vedada, estorno aplicável, obrigação de recolher na saída de produto resultante; condições CDI | crédito acumulado sem exceção exportação; produto já incentivado; matéria-prima de químico/plástico fora do Anexo III; benefício aplicado ao mês integral de julho/2024; competência novembro/2024 sem divisão de vigência | LC160_CONVENIO190_CLAUSE13_MENTIONED_ACT_SPECIFIC_DEPOSIT_NOT_PROVEN | Não certificada |
| SE_PSDI_CAPITAL_GOODS_DEFERRAL | Lei 3.140/1991 art3 IV a; Decreto 29.935/2014 art5 IV a e §2 | bens de capital novos/diferencial em hipótese individual enquadrada e regime de prazo aplicável | bens usados; bem desincorporado sem análise de pagamento; sem resolução CDI | PENDING_ACT_SPECIFIC_MATCH | Não certificada |
| SE_PSDI_IMPORTED_RAW_DEFERRAL | Lei 3.140/1991 art3 IV c; Decreto 29.935/2014 art5 IV c e §11 | importação de insumo e crédito fiscal com operação legal individualmente enquadrada | produto excluído por alteração 2021; prazo 6º mês não aferido; sem ato CDI | PENDING_ACT_SPECIFIC_MATCH | Não certificada |
| SE_PSDI_EXISTING_INDUSTRY_GROWTH | Lei 3.140/1991 art3 §5 III; Decreto 29.935/2014 art5 §3 III | empreendimento já instalado com crescimento apurado, média ICMS 12 meses e fórmula de excedente com ato CDI | usar indiscriminadamente taxa 8/6,2 do empreendimento novo; crescimento insuficiente; média 110% não atingida | PENDING_ACT_SPECIFIC_MATCH | Não certificada |

**8% e 6,2%:** são parcelas do **ICMS devido**, não alíquotas de saída/faturamento. A regra 8% alcança indústria nova nos termos art3 §5º I e Dec29935 art5 §3º I. A regra 6,2% exige hipótese diferenciada semiarido/fronteira/projeto relevante, requisitos do CDI, resolução e exame do §5º II, não decorre apenas de CNAE. Para indústria existente, não aplicar indiscriminadamente esses percentuais; verificar critério de crescimento e 110%.

**Lei 9.494/2024:** o diferimento é de entradas **internas de matéria-prima para industrialização**, não imunidade permanente; obrigação na saída do produto industrializado. Restringe créditos de insumos, com exceção de exportação e estorno, e o Decreto 868 proíbe cumulação e exige estornos periódicos/Anexo III para químico-plástico.

**Lei 9.812/2025:** optante atual Simples ≠ empreendimento **desenquadrado**, que pode ser classificado novo somente se os demais requisitos e data do desenquadramento forem provados. A concessão permanece individual.

**Lei 9.943/2026:** SEDETEC administra, CDI delibera, CODISE e DESENVOLVE-SE são executoras; a unidade captadora instrui o processo, com exceção locacional; obrigações de manutenção, fiscalização e perda devem ser cotejadas.

**Prazo:** 10 anos ordinários; extensão excepcional até 25 anos exige deliberação CDI; incentivos eficazes conforme resolução individual, não por inscrição isolada; em caso de descumprimento, suspender análise sem permitir crédito.

**Operação:** consumidor final e ICMS-ST retido excluídos conforme Dec29935 art5 §20, ressalvadas exceções normativamente previstas (órgãos públicos, fertilizantes rurais e dispositivos LED vendidos a PJ na redação Dec30428/2016), que sempre exigem revisão específica da operação.

## Integração técnica

`src/kordena_fiscal/tax/se_psdi_advisory.py` e integração em `state_benefits.py`. Retorno **potential somente informativo**, sempre `tax_calculation_authorized=false`, sem aprovação monetária. Testes de concessão ativa/revogada/suspensa, pós-Simples, 8%/6,2%, data intramensal 2024, ST, consumidor final, vedação créditos e Anexo III.

## Bloqueios INTRÍNSECOS à certificação jurídica

1. Localizar/arquivar DOE oficial de 820/2024 e 868/2024 com SHA + qualquer alteração 2025/2026 do decreto, e reconciliar competência.
2. Vincular a **planilha CONFAZ/LC160 específica e ato de reinstituição/admissão por modalidade**; certificado 126/2024 isolado insuficiente.
3. Documentar íntegro enquadramento setorial/produtivo e hipóteses NCM/CFOP/CNAE relevantes, inclusive exceções.
4. Revisão contraditória independente e resultado da CI do HEAD final.

**Resultado:** texto legal-base e regulamento histórico com SHA, análise de dispositivos e motor de triagem implementados; **SE não certificada, não importada e não aplicável fiscalmente**.
