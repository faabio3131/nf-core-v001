# Central de Economia Fiscal — execução T01–T22
Fonte: NFCore_Cronograma_Master_v3_Trilhas_Com_Trava.xlsx, Trilha 1, linhas 6–27.
A folha T23–T33, a Trilha 2 H01–H06 e a reformulação Enterprise não integram esta rodada. A futura oitava tela é a Central de Economia Fiscal; T21 exige interface funcional antes do redesign. Nenhuma tarefa é ENTREGUE sem DoD, data e evidência.

| ID | Entrega | Estado |
|---|---|---|
| T01 | Modelagem de dados, oportunidades, benefícios, ledger, dossiês, RLS | Em construção |
| T02 | Contrato Core Cognitivo | Bloqueado por T01 |
| T03 | Sentinela Normativa e anistias/REFIS | Bloqueado |
| T04 | Motor Simples e Fator R | Bloqueado |
| T05 | Diagnóstico e otimizador Fator R | Bloqueado |
| T06 | Classificador de receitas segregáveis | Bloqueado |
| T07 | Apuração/PGDAS segregada | Bloqueado |
| T08 | Catálogo federal | Bloqueado |
| T09 | Catálogo estadual 27 UFs | Bloqueado |
| T10 | Benefícios municipais e radar unificado | Bloqueado |
| T11 | Simulação Presumido/Real e IVA | Bloqueado |
| T12 | Comparador multi-regime | Bloqueado |
| T13 | Aprovação contábil auditável | Bloqueado; referência anterior preservada |
| T14 | Aplicação autorizada emissão | Bloqueado; protótipo de engenharia preservado |
| T15 | Auditoria histórica 60 meses | Bloqueado |
| T16 | Créditos não aproveitados | Bloqueado |
| T17 | Recuperação/prescrição/SELIC | Bloqueado |
| T18 | Ledger partidas dobradas | Bloqueado |
| T19 | Restituição/compensação | Bloqueado |
| T20 | Dossiê PDF/Excel/XML | Bloqueado |
| T21 | Interface Central vinculada a APIs reais | Bloqueado |
| T22 | E2E interno seis blocos | Bloqueado |

## T01 — incremento 20/11/2026
Base 52568a3df46dc6cf608a22c7b9971266ce71cbef; migração MFA v24 está em PR #586 concorrente. Construído esquema aditivo de cinco tabelas com chaves e FKs completas por host/tenant/unidade/ambiente, RLS FORCE, políticas de SELECT/INSERT, índices, montantes em centavos e versões imutáveis. Acrescentado repositório PostgreSQL inicial para snapshots e teste de migração isolada, papel sem BYPASSRLS, isolamento, imutabilidade e rollback. A numeração/integração na autoridade canônica de migrations e configuração do papel runtime restrito ainda precisam ser feitas após conciliação da v24; não existe execução DDL de produção. Ledger é somente estrutura inicial, não motor de partidas dobradas T18. T01 permanece EM CONSTRUÇÃO, não certificado. T13/T14 preservados na branch feat/nfcore-fiscal-benefits-20261120 (1a839b3bf51f9920c79b3d1f4ef7e099e10c24c5), sem merge antecipado.

Persistência de inserção e leitura escopada acrescentada para as cinco entidades, com validação de referências, centavos e digest. Teste PostgreSQL ampliado para toda a cadeia e para referência cruzada impossível entre empresas. Execução não comprovada.

Repositório endurecido: leitura e gravação exigem transação escopada ativa, reuso após encerramento e chamada direta recusados; projeções conferem digest, entradas passam pelas mesmas primitivas SQL e teste de rollback explícito adicionado. Estado continua EM EXECUÇÃO; teste PostgreSQL não executado.
