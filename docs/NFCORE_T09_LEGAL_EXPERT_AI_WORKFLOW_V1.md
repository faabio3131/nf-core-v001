# T09 — Agente IA especialista em Direito Tributário Estadual (consolidação normativa)

**Decisão do proprietário em 21/11/2026:** a **consolidação jurídica integral por benefício e competência** é uma tarefa de pesquisa e engenharia jurídica **interna executável por IA especializada**, com prova documental. O **parecer independente assinado** do contador foi classificado como **PENDÊNCIA EXTERNA**; isso não elimina seu gate antes da aplicação fiscal real.

## Escopo congelado e CURRENT

- Produto FM NFCORE V1. Branch candidata `feat/nfcore-economy-t09-state-catalog-27ufs-20261121`, PR #592.
- **CURRENT** na inspeção: HEAD `917cf3ac428b682c6d575aba3e8f18d4f316d4d5`; main e production são autoridades separadas, sem merge.
- 27 UFs têm uma candidata de pesquisa `draft` cada. São **27 recortes representativos**, NÃO o universo dos incentivos estaduais.
- Na matriz do dossiê, 24/27 UFs possuem algum trecho de fonte governamental examinado. Isso **não** é consolidação integral de um ato. Novos apontamentos de AL, RR e TO na issue #593 devem ser reconciliados antes de ampliar a contagem.
- 0 políticas aprovadas, 0 atos plenamente consolidados por competência, 0 pareceres independentes recebidos e 0 regras aptas a creditamento.

## Papel do agente e limites

**Responsável interno proposto:** `AI_LEGAL_TAX_RESEARCH_SPECIALIST`, agente de curadoria com especialização operacional em legislação tributária estadual. O presente arquivo define seu procedimento; **não comprova um processo de IA autônomo já implantado, rodando ou concluindo as pesquisas**.

O agente pode localizar, recuperar, organizar, confrontar, resumir e interpretar **para fins de triagem** leis, RICMS, decretos, portarias, convênios CONFAZ, Diário Oficial, respostas a consultas e atos concessivos; produzir propostas de condições de elegibilidade e casos de teste. **Não pode** assinar parecer profissional, declarar homologação, alterar cadastro fiscal, emitir documentos, aprovar créditos, conferir consentimento/adesão inexistente, promover sozinho `reviewed`, fazer merge ou deploy.

O Core coordena; serviços determinísticos aplicam os guardas existentes de `state_benefits`, `EconomyStore`, `FiscalProfile`, session/RBAC, escopo de tenant/unidade. **Não criar um segundo motor ICMS, API, persistência ou autoridade fiscal.**

## Método de trabalho por ato e competência

1. **Congelar o objeto de estudo:** identificador de candidata, UF, benefício exato, natureza, operações e competências. Se uma UF tiver benefícios distintos, cada dispositivo adicional exige linha separada, não pressupor aprovação da UF inteira.
2. **Recuperar original oficial:** texto do DOE/SEFAZ/assembleia legislativa, versões consolidadas e atos modificadores. Capturar bytes originais, URL, data da publicação e hash SHA-256 real. Links/trechos e hashes calculados de textos gerados por IA não são evidência primária.
3. **Construir cadeia temporal:** vigência original, efeitos e alterações até a competência mensal, revogações, prorrogações, disposições transitórias e regimes concorrentes. Uma regra vencida gera `not_applicable`; lacuna documental gera `insufficient_basis`. **Contrato T09:** `legal_valid_until_inclusive` reproduz o último dia legal da norma; `valid_until` é o primeiro dia excluído calculado determinísticamente (ex.: ato até 30/11/2026 => `2026-11-30` e `2026-12-01`, respectivamente). Se a norma não tiver termo final, ambos devem ser `null`. Não interpretar `valid_until` como data legal inclusiva.
4. **Conciliar competência constitucional/CONFAZ:** identificar se precisa Convênio de ICMS, adoção, reinstituição, registro/depósito e certificado da LC 160/2017 e Convênio 190/2017; não aplicar essas rotas a todos os programas indistintamente.
5. **Extrair condições materiais:** CNAE primário e, se exigido, secundário da fonte canônica, NCM/CEST/CFOP, origem/destino, tipo de operação, regime ICMS e federal, ST, DIFAL, consumidor final, classificação da empresa, limites, estorno, obrigação acessória, valores, opção/deferimento/contrato e prazos.
6. **Diferenciar lei geral de concessão individual:** protocolo, notícia, programa, isenção condicionada, despacho, decisão de conselho e ato para outro CNPJ não comprovam fruição por cliente real. Solicitar documentos de habilitação sem registrar dados pessoais/segredos no Git.
7. **Criar matriz positiva e negativa reproduzível:** provas de enquadramento e de exclusão para cada hipótese, base legal por item/parágrafo, cenários de mudança temporal e conflito de normas. Os testes de engenharia nunca equivalem à autorização jurídica.
8. **Revisão contraditória independente por outra IA/agente:** verificar falsos positivos, fonte revogada, erro de porcentagem efetiva versus percentual de crédito, ato/empresa errados, efeito retroativo e hipóteses não descritas. A revisão por IA também **não substitui** parecer profissional.
9. **Certificação interna:** cada artefato é auditado pelo humano responsável e passa em testes e CI do HEAD. Só marcar `internal_curatorial_accepted` depois de **todos** os gates verificáveis. Não alterar `review_status=reviewed` sem aprovação jurídica humana externa para benefício executável.
10. **Entrega ao contador:** enviar pacote por ato/competência, documento original e hash, conflitos, requisitos e casos; manter `EXTERNAL_DEPENDENCY/PENDING_NOT_RECEIVED` até parecer verificável e datado. Um parecer específico não aprova todos os estados.

## Ordem de investigação

Priorizar as lacunas **AL, RR e TO** (incluindo alerta de vigência 2025 dos insumos RR), depois consolidar as outras 24 candidatas integralmente, do ato original à última alteração. Respeitar a classificação específica de AC (financiamento, não crédito universal), RJ (carga efetiva não percentual de crédito), DF (percentual máximo sujeito à aprovação), PI (isenção/redução distintas), SP (art.41 + art.52, exclusões) e demais notas da issue #593.

## Estados e gates

Ver `docs/NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json` (27 filas). `AWAITING_COMPLETE_NORMATIVE_CONSOLIDATION` é **pendência de execução interna**; não significa falta de software de triagem. O campo `PENDING_NOT_RECEIVED` do contador é **dependência externa**, separada.

**Definition of Done — curadoria IA interna:** 27/27 objetos normativos selecionados com fontes originais capturadas e hashes reais, cadeia temporal/competências, condições, exceções, conferência CONFAZ quando cabível, casos positivos/negativos reais, revisão contraditória de agente e aceite do responsável técnico. Esse marco **não** implica cobertura exaustiva de todos os benefícios existentes em cada estado.

**Definition of Done — prontidão fiscal e comercial:** parecer do contador e autoridade humana específica, validação do direito por contribuinte e testes de integração/homologação aplicáveis, gates técnicos e operacionais e Go/No-Go de produção. A falta do parecer **não impede continuar a pesquisa, o código e os testes internos**, mas impede declarar benefício juridicamente aprovado e aplicá-lo no mundo real.

**Normas nacionais referenciais:** [LC 160/2017](https://www2.camara.leg.br/legin/fed/leicom/2017/leicomplementar-160-7-agosto-2017-785276-normaatualizada-pl.html) e [repositório de certificados CONFAZ](https://www.confaz.fazenda.gov.br/legislacao/certificado-registro-deposito-cv-icms-190-17-1). Sempre priorizar norma estadual aplicável a cada hipótese e suas alterações.
