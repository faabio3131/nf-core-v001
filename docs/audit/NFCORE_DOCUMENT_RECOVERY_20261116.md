# Recuperação documental das PRs #413, #448 e #453

Data: 16/11/2026. Base auditada: candidata #468 em `93534458a4f2e3d4879ead703bf407f346a1fa35`, com CI integral [43926134508](https://github.com/faabio3131/nf-core-v001/actions/runs/43926134508) SUCCESS. Main `549ab3c0` e production `ea4bdd3b` permanecem distintas. Este registro não certifica o produto.

## Current → Target e escopo

Quatro documentos de diagnóstico/especificação e os acréscimos do incidente de continuidade estavam somente nas branches de origem, apesar de referências a eles na candidata. Recuperar o material e sua proveniência sem substituir arquivos evoluídos por versões antigas. Somente documentação; nenhum código, workflow, regra fiscal ou autorização operacional muda.

| Origem | Achado confirmado | Tratamento |
| --- | --- | --- |
| #413 `6af3d020` | Acréscimos em AGENTS, cronograma nacional e ledger não estavam presentes literalmente | Patch original preservado em `history/PR413_historical_additions.patch`; incidente reconhecido nos três pontos de entrada atuais |
| #448 `aa7ce155` | Dois diagnósticos ausentes dos caminhos originais | Recuperados integralmente com aviso de data e precedência |
| #453 `e04005ad` | Especificação de travas e cronograma ausentes; banner antigo não corresponde à ordem posterior | Dois documentos recuperados integralmente; patch do cronograma preservado para consulta, sem aplicá-lo sobre a ordem vigente |

## Decisões e riscos

O incidente `NAT-GOV-2026-11-10-01` é falha reconhecida de acompanhamento técnico: o cronograma foi confundido com conclusão, sem atribuir a divergência ao proprietário. Recuperar seu registro não encerra a auditoria de cobertura. A reconciliação nacional por UF/município/documento/operação/ambiente continua pendente onde faltam provas.

A disputa de sequência `NAT-GOV-2026-11-10-02` tem decisões posteriores registradas em AGENTS: prioridade SP-22 de 12/11, agrupamento por engenharia de 13/11 e Integrador único de 15/11. Os cronogramas recuperados são históricos; nenhuma nova prioridade é aprovada aqui.

O texto de 12/11 de que nenhuma trava existe foi superado parcialmente pela implementação posterior de T2 (`scripts/ci/check_pr_block_completeness.py`). Não comprova T1/T3–T6, permissões ou rulesets. Também não revoga as autorizações atuais do proprietário registradas no ledger.

## Prova de preservação e aceite

`NFCORE_DOCUMENT_RECOVERY_MANIFEST_20261116.json` fixa commit, blob e SHA-256 de cada fonte. Nos quatro documentos recuperados, remover exatamente `prefix_bytes` deve reproduzir os bytes originais. Os dois patches devem coincidir com o diff Git dos commits indicados. Não executar esses patches: são evidência histórica.

Gates: comparar os bytes com as seis fontes; verificar que os arquivos ativos existentes apenas receberam aviso/link, sem perda de conteúdo; validar o plano canônico; revisão independente; CI do HEAD publicado. Nenhuma alegação normativa dos documentos antigos foi revalidada como lei vigente por esta recuperação.

As PRs de origem permanecem abertas até integração deste material e prova de preservação no destino. Fechá-las depois significará recuperação documental, não conclusão de MF-04, MG20, SP22, confiança fiscal ou lançamento comercial.

Próxima ação: concluir os gates e integrar sequencialmente na candidata, após o bloco MF-09. Preservar branches de origem e registrar o SHA de destino antes de encerrar as PRs antigas.
