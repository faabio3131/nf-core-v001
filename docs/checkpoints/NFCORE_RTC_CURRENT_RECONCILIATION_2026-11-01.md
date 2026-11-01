# NFCore RTC — Reconciliação CURRENT / anti-retrabalho — 2026-11-01

**Natureza:** checkpoint de auditoria documental; NÃO equivale à homologação, cálculo oficial ou autorização de merge/deploy. Fonte de verdade superior: código GitHub CURRENT + CI + ambiente.

## Baselines auditadas

- Repositório canônico: `faabio3131/nf-core-v001` (nome histórico `kordena-fiscal-engine-v2`).
- `main`: `d3d1002a54b78b0c7df7f77f28aeac181bc2c40d` (auditado 01/11/2026); `production`: `d7cf5e4d58cce8ab43105b17e13b2237edc551fb` após PR #305, com API/Portal/DB healthy e HTTP 200 na Contabo, **sem homologação tributária**.
- O cronograma RTC de 30/10 permanecia congelado no RTC-00 e marcava RTC-01..09 como PENDING apesar de merges posteriores. Este checkpoint reconcilia os estados **sem mudar o escopo nem inventar conclusão**.
- PR #289: `OPEN` / `mergeable`, HEAD CURRENT `576a0e165c926a1527ab87f20cc1ec28913b56b6` (reconciliado com `main@d3d1002a54b7`), CI `41357578346` em execução nesta auditoria (verificar resultado final), governança `41357578344` SUCCESS; revisão anterior `61f8bdf` teve CI `41253932330` e Gov `41253932304` SUCCESS, mas esses gates não certificam novo HEAD. Merge sujeito a revisão e autorização RTC. A candidata traz prévia Decimal sintética pinada, não emissão, não cálculo oficial amplo.

## Matriz de implementação RTC (CURRENT → TARGET)

| WP | Código integrado comprovado | Aceite ainda ausente / TARGET | Estado conservador |
|---|---|---|---|
| RTC-00 | PR #267, baseline e cronograma | inventário completo com reconciliação de fontes atualizadas e gates | IMPLEMENTED_PARTIAL |
| RTC-01 | PRs #268 e #270, integridade/pins e versão IT 2025.002 v1.70 | artefatos oficiais efetivamente coletados, hash/licença/proveniência/version diff/review, watcher e rollback testados por família | IMPLEMENTED_PARTIAL |
| RTC-02 | PRs #269/#271/#272, separação CRT x regime federal, verificação FiscalProfile e histórico | matriz completa estabelecimento/tempo/atividade, PostgreSQL, RBAC e anti-spoofing por célula | IMPLEMENTED_PARTIAL |
| RTC-03 | PRs #273/#274/#280, catálogo CST/cClassTrib, fail-closed, integração com TaxRuleEngine | NCM/NBS, operações/destino, benefícios/créditos/exceções e cobertura normativa nacional | IMPLEMENTED_PARTIAL |
| RTC-04 | PR #289 OPEN, preview Decimal por artefato pinado, bloqueio de publicação/vigência futura, instante com fuso e testes sintéticos (NÃO integrado à main) | cálculo IBS UF/município, CBS e IS com bases, reduções, créditos, regras de arredondamento/totais oficiais por célula | IMPLEMENTED_NOT_MERGED |
| RTC-05 | nenhum WP fechado | transição 2026–2033 e coexistência com tributos legados, casos de vigência | PENDING |
| RTC-06 | nenhum WP fechado | XML NF-e/NFC-e RTC, XSD oficiais, assinatura, eventos, totals e autorização por ambiente | PENDING |
| RTC-07 | nenhum WP fechado | DPS/NFS-e RTC por provedor/município, layout e casos autorizados | PENDING |
| RTC-08 | nenhum WP fechado | exceções/créditos/devoluções/import-export/regimes especiais e bloqueios explícitos | PENDING |
| RTC-09 | PRs #275/#278, primeira UI e cadastro fiscal do emitente no Portal canônico | cálculo/classificação/motivo de bloqueio em tela, autorização e jornada E2E completa | IMPLEMENTED_PARTIAL |
| RTC-10 | nenhuma certificação RTC integral; primitivas de DB/Worker preexistentes | snapshots/auditoria idempotência/replay e PG descartável para cenários RTC | PENDING |
| RTC-11 | CI global NFCore é distinta de certificação RTC | matriz regime × operação × documento × período × UF/município e golden oficial | PENDING |
| RTC-12 | sem prova oficial por célula | provedor/credencial/certificado, homologação oficial, piloto e Go/No-Go | BLOCKED_EXTERNAL |

## Fontes oficiais confirmadas para a PR de continuidade

- Legislação/alterações: https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria-do-consumo/legislacao/ (inclui EC132/2023, LC214/2025, LC227/2026).
- Portal Nacional NF-e: NT 2025.002 v1.52, publicada 01/10/2026: https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=04BIflQt1aY%3D ; comunicado de alteração de datas de implantação (26/10 homologação, 16/11 produção): https://www.nfe.fazenda.gov.br/portal/informe.aspx?Id=1&ehCTG=false . Distinguir versão publicada, entrada em homologação e implantação produtiva.
- IT 2025.002 v1.70 e tabelas cClassTrib/cCredPres publicadas 01/10/2026: https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=B%2F6oigHgyAw%3D e https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=%2FNJarYc9nus%3D . A listagem oficial NÃO substitui download/hash/validação da tabela para cálculo.
- Cronograma RFB/CGIBS atualizado 28/10/2026: https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria-do-consumo/orientacoes-da-reforma-tributaria/cronograma . Marcos por documento/empresa distintos; não aplicar generalização do Simples Nacional aos demais regimes.

## Ordem retomada e gates

1. Resolver **somente** faltas normativas necessárias à célula RTC-04; verificar se os hashes/edições de material oficial e seu período efetivo correspondem à classificação CST/cClassTrib antes de qualquer fórmula.
2. Revisar PR #289 versus `main` CURRENT; preview permanece em módulo isolado, sem integração à emissão, sem taxas sintéticas em runtime; concluir teste/documentação e, depois de gates e autorização de merge RTC, preservar como ferramenta de cálculo de referência não fiscal.
3. Construir RTC-04 por células oficiais, classes específicas CBS/IBS UF/município/IS, arredondamento e totalização oficiais + golden cases, mantendo TaxRuleEngine como autoridade de regra. Não criar alíquotas, bases, crédito ou XSD na ausência de prova.
4. RTC-05 → RTC-06 e 07 → RTC-08 → RTC-09/10 → RTC-11. RTC-12 externo bloqueado até request/response oficial e autorização humana. Não reexecutar migração produtiva #19 nem criar segunda API/Portal/TaxRuleEngine.
5. Antes de qualquer merge RTC: diff, Ruff, mypy, pytest, CI/Gov no SHA, revisão normativa e autorização de merge aplicável. Promoção a `production` e homologação fiscal exigem autorização separada.

**Pendências de continuidade:** este checkpoint não corrige lacunas de implementação por mera edição documental; PR de reconciliação deve receber CI e revisão. Nenhuma alteração produtiva ou emissão fiscal nesta tarefa.
