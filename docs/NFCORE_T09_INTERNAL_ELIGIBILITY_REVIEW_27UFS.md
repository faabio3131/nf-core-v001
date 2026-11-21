# T09 — Revisão interna de elegibilidade estadual, 27 UFs

**CURRENT validado:** PR #592, código canônico de benefícios ICMS. Este artefato
é uma **matriz de triagem técnica de evidências necessárias** por UF, não
um parecer jurídico e **não é a lista exaustiva dos benefícios fiscais existentes**.

O arquivo `NFCORE_T09_ICMS_ELIGIBILITY_SCREENING_27UFS_V1.json` estabelece,
para **cada uma das 27 UFs**, uma linha de pesquisa com benefício/programa
ou regulamento estadual, âncora legal, URL governamental, hipóteses de
enquadramento a conferir, principal cenário negativo e os gates transversais
por competência, CNPJ/IE/regime ICMS, produto, operação/CFOP/NCM/CNAE, ST/DIFAL,
efeitos, concessão individual, CONFAZ/LC 160 quando aplicável, contrapartidas,
acumulação/estorno e proveniência documental.

## Situação demonstrável

| Indicador | Resultado |
|---|---|
| UFs com linha de estudo interna e critérios de verificação registrados | 27/27 |
| Benefícios/atos estaduais integralmente consolidados por competência | NÃO COMPROVADO |
| Benefícios importados como `reviewed` | 0 |
| Revisões jurídico-fiscais independentes aprovadas | 0 |
| Casos positivos com benefício real certificado | 0 |
| Direitos fiscais autorizados automaticamente | 0 |
| Prontidão para análise do contador | Matriz e perguntas prontas, documentos completos por ato ainda pendentes |

**Diferença fundamental:** `internal_screening_status =
risks_and_required_evidence_mapped` indica critérios de investigação
estruturados, **não** que esses critérios foram juridicamente comprovados ou
que o contribuinte pode usar o benefício.

## Critérios de elegibilidade a validar antes de marcar um caso como positivo

1. Normas vigentes e dispositivos **exatos**, incluídas alterações posteriores,
   revogações, data inicial/final e aplicação à competência mensal analisada.
2. Concessão, contrato, opção, regime especial, adesão, deferimento e
   publicidade do ato individual quando previstos; sempre conferir abrangência
   por CNPJ/estabelecimento e eventual prazo mínimo de opção.
3. CNAE/NCM/CFOP/tributação corretos, natureza da operação, localização de
   origem/destino, consumidor final, ICMS-ST, importação, DIFAL e exceções.
4. Obrigações acessórias, condição de regularidade fiscal/FGTS, metas,
   contrapartidas e requisitos de manutenção; verificar acumulações e estornos.
5. Revisão de CONFAZ, LC 160/2017, Convênio 190/2017 e outros convênios
   **apenas quando aplicáveis ao benefício específico**; não presumir cobertura.
6. Evidência de fonte oficial **capturada** com SHA-256 dos bytes examinados,
   fonte editorial, vigência e identificação do revisor independente.
7. Um caso positivo e negativos reais por benefício/competência; a triagem
   computacional continua consultiva até autoridade fiscal específica.

**Engenharia adicionada:** CFOP incompatível com direção da operação (venda
interna 5xxx, venda interestadual 6xxx, entrada interna 1xxx, entrada
interestadual 2xxx, importação-entrada 3xxx e aquisição de ativo 1/2/3)
agora produz `insufficient_basis/cfop_operation_mismatch`, nunca
`potential`, mesmo que um catálogo indevido inclua esse CFOP.
Transporte requer avaliação documental individual, pois o prefixo depende
da direção registrada. Alinhado ao [Guia EFD-ICMS/IPI do CONFAZ](
https://www.confaz.fazenda.gov.br/legislacao/arquivo-manuais/06___anexoguia_pratico_da_escrituracao_fiscal_digital___efd.pdf).

## Entrega ao contador

Utilizar a matriz por UF como roteiro para selecionar o **conjunto de atos
que será efetivamente comercializado na V1**. Para cada ato, fornecer os bytes
originais completos, texto consolidado e alterações, resolução individual,
dados do contribuinte/operação de teste e minuta do contrato normativo.
O profissional emite um parecer identificando UF, ato, artigos, vigência,
operações, empresa, limites, condições, fontes e evidências positivas/negativas.
Somente após esse parecer e os testes reais o time poderá promover uma política
de `draft` a `reviewed` por fluxo governado.

**Não confundir:** 27 linhas de elegibilidade investigadas ≠ cobertura completa
de todos os incentivos estaduais. A primeira é uma entrega de engenharia
sobre como verificar; a segunda é curadoria jurídica extensiva ainda pendente.

**Autoridade de revisão independente definida pelo proprietário:** contador
da organização; issue #593. Sem aprovação escrita não há elegibilidade
certificada. Sem autorização separada não há merge/deploy/ativação fiscal.
