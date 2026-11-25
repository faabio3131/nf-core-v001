# T17 — Motor de recuperação tributária

## Fechamento da T16

A PR #612 foi integrada com autorização expressa na main 6f138449e0e8c51e51fcbde896618614721c78b1. O HEAD auditado 267b0b0306fde9dabd1750694b084d62cd86d66c e o merge têm árvore 062ca0f5b6e0c82cb08e4f969c5fd5546c93589d. CI pós-merge #45527493411, tentativa 2, SUCCESS em 44/44 etapas (7.151 Python aprovados, 1 skip, 87 Playwright aprovados). A primeira tentativa recebeu HTTP 429 do Maven Central. Governança #45527493836 e completude efetiva #45527067399 aprovadas. Refinamentos abertos na #613.

## Abertura da T17

Issue #614. O DoD exige seleção de marcos prescricionais por modalidade, cálculo determinístico com SELIC oficial versionada por competência, exclusão de períodos prescritos e memória auditável com precisão de centavos. A implementação deve revalidar as evidências e o saldo candidato da T16 antes de atribuir qualquer valor. T18 aguarda a certificação da T17.


## Checkpoint de implementação — PR #615 Draft

Motor puro em `tax/tax_recovery.py` e serviço restrito em `application/tax_recovery.py`. Importador canônico: `python scripts/nfcore_historical_audit_import.py pacote.json --tenant EMPRESA --unit FILIAL --recovery`. O envelope segue T16; facts contém competence, t16_version, t16_digest e claims. Claim vincula o CNPJ, item/tributo, digest do snapshot vigente, marco e prazo ordinário revisados, evidência de não aproveitamento/pedido anterior e revisão causal. Projeção JSON é comparada aos bytes originais do parecer e a fonte legal ao SHA da citação.

A T17 reconstrói o lote T16 dos chunks e páginas imutáveis, reexecuta o detector com o mesmo perfil/data e compara todo o relatório. O snapshot T15 atual precisa ser aquele vinculado na T16, sem sobreposição de indébito T15. Para PIS/Cofins pagos diretamente, exige componente único de recibo conciliado e retificação revisada vinculada ao pagamento e à apuração, com diferença exata igual à soma atribuída. Não presume indébito apenas de crédito escritural. ICMS escritural no regime normal utiliza emissão do documento, sem SELIC automática (LC 87/1996 art. 23). Indébito federal ordinário utiliza pagamento e CTN art. 168 I; IN RFB 2055/2021 arts. 148, 149 e 151. O mês final é uma **projeção**, não uma restituição/compensação realizada. Prazo ordinário inclui o aniversário de cinco anos; feriado/expediente excepcional exige revisão do calendário; aniversários em fim de semana e casos bissextos falham fechados. Sem revisão suficiente, modalidade, vigência, marcos ou tabela, valor nulo. Demais modalidades, pagamentos múltiplos por tributo, Simples/DAS, decisões judiciais, situações especiais e períodos futuros sem tabela permanecem fora deste recorte; não se afirma cobertura fiscal nacional.

### Conferência da SELIC

Fonte primária: Sicalc RFB emitido em 01/11/2026, páginas 3 e 4, [espelho oficial SEFAZ-MT](https://www5.sefaz.mt.gov.br/documents/d/sefaz/selic-acumulada-11-2026-pdf). Comparação de segunda leitura visual das 61 células outubro/2021–outubro/2026: 61/61 iguais à transcrição. Diferenças adjacentes produzem 60 taxas fechadas novembro/2021–outubro/2026; total 6036 pontos-base. Outubro/2026 = 107 pb, e o 1% de novembro é exclusivamente o mês final projetado. Exemplo R$100,00 pagos em janeiro/2026, projeção novembro: R$10,95 de atualização. Mesma competência sem juros, precisão inteira com frações e arredondamento em centavos. O hash registra a normalização, não os bytes do PDF. A conferência não equivale à auditoria independente Gemini. Fonte alternativa SGS 4390 do BCB identificada, consulta API não confirmada nesta rodada.

### Gates

Testes novos em `tests/test_t17_tax_recovery.py`: tabela integral, limites, centavos, prazo, revisão/recibo, idempotência, rollback, isolamento por tenant/unidade/host/ambiente, CLI e bloqueio produtivo. O HEAD inicial 30f3416b falhou no Mypy #45533080608; correção da variável opcional publicada nesta revisão. Não declarar testes aprovados antes de CI do HEAD novo. Auditoria Gemini e autorização de merge específicas do SHA final obrigatórias. Nenhum ledger, deploy, reconhecimento de crédito ou operação fiscal real. T18 bloqueada.
