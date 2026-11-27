# T19-R2-P3-01 — identidade canônica de movimentos gerenciados

## CURRENT / TARGET
- Base main `e33d889f3a23daed24713339ed3daa6391ab6a12` (PR #629 certificada; #626 CLOSED).
- Issue #625, subbloco 1. Escopo congelado: identidade T19, referências, vínculo exato movimento/evento/lote/digest e regressão; sem alterações de autoridade monetária, DB schema, migrations, API, UI, RBAC, RLS, MFA ou configuração.
- Causa: writer aceitava qualquer prefixo casefold t19-; report identificava case pelo segundo componente, sem validação completa do formato. Replay validava valores e histórico mas não o namespace.
- TARGET: parser/gerador único, digest lowercase, versão 1..100 e índice 1..2; referências do mesmo caso e evento anterior; validação na escrita e replay; report compara bijetivamente movimento com lote/versão/digest do vínculo validado em _case_history. O writer interno continua dentro da transação lifecycle; não vira autoridade pública.
- Histórico append-only preservado; IDs válidos existentes continuam válidos. Dados adulterados falham fechado, não são corrigidos automaticamente.

## CURRENT — remediação da regressão de integração T20 (26/11/2026)

CI [#45927550166](https://github.com/faabio3131/nf-core-v001/actions/runs/45927550166), HEAD histórico `e5c483bf9506874240be1f6d02c1c5a845d3eb36`: FAILURE em Pytest; 7.291 PASS, 1 FAIL, 1 SKIP fora do escopo. Ruff, Mypy (491 fontes) e governança #45927550163 PASS; gates posteriores ao Pytest não executados. O teste T20 `test_postgres_orphan_managed_ledger_blocks_dossier` injetava um ID maiúsculo pelo writer antes da exportação; o novo controle corretamente o rejeitou na escrita. Correção exclusiva do teste e deste handoff: preservar cenário de órfão canônico e adicionar cenário de corrupção histórica com ID maiúsculo, injetado diretamente no store de testes com evidência, postings, balanços e digest consistentes. Comprovar rejeição pelo writer, ausência de mutação na rejeição, falha de exportação nos dois cenários e ausência de artefatos T20. Nenhum relaxamento do runtime, nenhuma supressão de teste, migration ou workflow. Candidata ainda não certificada; exigir nova CI integral no HEAD exato, revisão de vínculo e evidências de PostgreSQL.

## Aceite / gates
- Testes de formato completo, limites, referência cruzada, escritor rejeitando antes de mutar, histórico adulterado com digest válido, órfão canônico, regressões existentes de replay, cancelamento, estorno, vínculo falso e concorrência. Completar/avaliar casos de lote divergente e versão/digest divergentes na revisão.
- Estado: candidata não certificada. Execução local indisponível (DNS GitHub no container); CI PostgreSQL e integral no HEAD exato obrigatórias, revisão de segurança e Gemini, T2 efetiva e autorização específica de merge; certificação pós-merge.
- #625 permanece aberta: capacidade prospectiva, política de resíduo SELIC, revaloração revisada, contenção cross-tenant, exclusão do dossiê documental. T21 bloqueada. Nenhuma operação fiscal real ou deploy.
