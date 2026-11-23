# NFCore — reconciliação Git de perda zero (7 PRs) — 23/11/2026

**Finalidade:** integrar somente trabalho existente até T09, sem T10–T22, sem novas pesquisas SE/AP/PA/RR, sem alteração de autoridade fiscal e sem deploy.

## GRAFO CURRENT antes do candidato

- `main = 549ab3c005d7183ff6c7940236414412ea004b9d` — ancestral do #592, 1293 ahead / 0 behind.
- `production = a5989e523c871c288bc2388c9508c1738082bb9a` — ancestral do #592, 1329 ahead / 0 behind. Diverge da `main` (17 commits próprios de produção / 53 próprios de main desde merge-base `cd0dc4d80fff0b5cc90d64695c863e065b84f052`); ambos já entram na árvore #592.
- `work/nfcore-closeout-20261119 = 39e64ea3772595691a1f50bbd8389f7b95f80709` — ancestral do #592 (163 ahead / 0 behind). DESTINO: referência histórica preservada, sem integração isolada.
- `#592 = c083595b57a6222bbd8fc34f66d3e6fedf3b9364` — [CI #45273717614](https://github.com/faabio3131/nf-core-v001/actions/runs/45273717614) SUCCESS.

| PR | Base anterior | HEAD | Commits exclusivos FORA da #592 (DAG) | Destino |
|---|---|---|---|---|
| #468 | main | 5cb2f4e9b73af3f7d9402e8b87c6cd2ff763f29f | 3 | Preservar ancestralidade na PR única, integrar teste S2S |
| #498 | production | 4cbbe7c3b222cc2abdf8c1a791203474072e8e5a | 0 | Já ancestral, evitar merge com conflito histórico `production` |
| #556 | branch Web #498 | 5cb2f4e9b73af3f7d9402e8b87c6cd2ff763f29f | MESMOS 3 DE #468, não somar duas vezes | PR redundante após integração na main |
| #560 | branch fiscal #468 | 96fdfbede1b2109c44a4f2847268525f588cc594 | 0 | Já ancestral da #592 |
| #563 | branch fiscal #468 | 1da651e2e70f526ff290aea2421ea3a8215ac947 | 0 | Já ancestral da #592 |
| #591 | #563 | 30b9d1e9d71c606f83a9274bd652af6829db57d3 | 2 | Preservar ancestralidade na PR única, integrar teste FIS03 |
| #592 | work/nfcore-closeout-20261119 | c083595b57a6222bbd8fc34f66d3e6fedf3b9364 | 0 | Origem cumulativa da única PR Draft → main |

**Cinco commits não ancestrais incluídos pelos pais do novo commit:** `14c430e5cdf1cac61dbd03b491052c29ea257429`, `e12d18b9795b9e231f44b52012a31e37be2cc73e`, `5cb2f4e9b73af3f7d9402e8b87c6cd2ff763f29f`, `d09295523fe2da419df2d75674dca21960d4b62b`, `30b9d1e9d71c606f83a9274bd652af6829db57d3`. O mesmo HEAD cobre #468/#556 sem duplicar objeto.

## Prova de arquivos e equivalência

- Git trees completos (`truncated=false`): arquivos regulares na #592 = 1765; #468 = 1535, #498 = 1537, #560 = 1535, #563 = 1535, #591 = 1535, main = 1220, production = 1163.
- **0 arquivos de qualquer uma dessas árvores ausentes** da #592. Não significa que arquivos modificados sejam byte-idênticos (mudanças posteriores legítimas foram preservadas da candidata cumulativa).
- O mapeamento de 59 tarefas tem **149 referências a arquivos**; **149/149 presentes** no HEAD #592. Manifesto JSON anexo lista os caminhos e SHA Git de cada blob-base.
- Correção A1 dos três commits: a API de retirada, `withdrawIronA1`, `CERTIFICATE_WITHDRAWAL_REQUESTED`, lease de escopo, bloqueio de replay e Vault já existem no código da #592. A suíte da #592 **não continha** o teste S2S específico da #468, por isso foi reintegrado sem substituir código runtime.
- Correção FIS03 dos dois commits: `_dps_id` no HEAD #592 já usa `national_dps_id` sem reconstruir o XML fiscal; faltava o teste antirregressão específico da #591, que foi reintegrado.
- Novo commit candidato: pais ordenados [#592, #468/#556, #591]. Tree-base é o HEAD #592, com **somente os dois testes faltantes e documentos/manifesto de reconciliação**. As PRs antigas permanecem OPEN até aprovação do merge da PR única e prova pós-merge (fechá-las agora não adiciona segurança).
- O conflito da #498 é na base **production** (compare `production...#498`: 928 ahead, 2 behind). `production` e #498 são ambos ancestrais do novo candidato, evitando replay daquele merge conflituoso. Nenhum deploy provocado.

## Critérios de aceite e restrições

1. Revalidar SHA da `main`, HEAD das sete PRs, ancestry completa (behind=0 para cada tip no novo HEAD) e 149 blobs preservados; a branch só recebe push após essa validação do commit criado.
2. Exigir uma única CI integral no HEAD novo (Ruff, Mypy, Pytest, E2E, PostgreSQL, Docker, security, governança); registrar run na PR. CI histórica #45273717614 apenas baseline, **não é aprovação do novo SHA**.
3. Permitir `INTEGRATED_MAIN` e liberação para T10 somente após revisão técnica, merge humano autorizado, CI pós-merge e reconciliação documental de aceites T01–T09. Não promover 27 UFs legalmente nem a matriz municipal.
4. SE/AP/PA/RR seguem `BLOCK_ICMS_BENEFIT_CALCULATION_AND_FISCAL_IMPORT`. Benefícios legais: 0/27 curadorias aprovadas/importadas; documentação futura isolada. Não executar novas pesquisas legais neste bloco.
5. `PRODUCTION_APPROVED=NO`, sem merge nesta entrega, sem DNS, deploy, migrations produtivas, credenciais ou emissão fiscal.
