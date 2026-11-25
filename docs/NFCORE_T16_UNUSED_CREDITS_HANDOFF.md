# T16 — Detector de créditos não aproveitados

Issue #611, PR #612. Base T15 integrada c4026bb0b4a5e47c523a674bc70408ecd602698a. A planilha mestre exige identificar automaticamente notas de entrada elegíveis sem crédito escriturado e separar os valores por tributo e competência. A integração depende de CI, revisão independente e autorização para o SHA final.

## Operação interna

O importador existente aceita um lote mensal de compras com a opção `--unused-credits`. O operador informa o tenant, unidade e um pacote revisado. O ambiente homologation usa os mesmos controles de acesso PostgreSQL T01 e o perfil/regime histórico do emitente. O lote de saída T15, se existente, tem os arquivos reconstruídos e reprocessados antes de vincular o digest. Indícios T15 não participam da fórmula de crédito.

```sh
python scripts/nfcore_historical_audit_import.py compras.json --tenant EMPRESA --unit FILIAL --unused-credits
```

O envelope é o mesmo da T15. O campo facts segue Batch em tax/unused_credits.py. Cada compra contém os bytes originais da NF-e de fornecedor, o digest, situação documental revisada e evidências de destinação por item e tributo. Cada regra revisada especifica UF, regime, CNAE, NCM, CFOP, condições materiais, modalidade de cálculo, fração exata, ato, dispositivo, vigência e bytes da fonte legal. Os fatos observados são comparados com as condições da regra. Múltiplas regras aplicáveis impedem atribuir valor. O extrato de escrituração revisado identifica CNPJ, competência, data de corte, abrangência e alocações por chave, item e tributo. O importador compara o conteúdo integral do extrato original com a projeção.

Para cada item, a memória preserva base, fração, escrituração anterior, fonte legal, digests e valor candidato em centavos. Os totais são parciais. Falta de extrato, alcance incompleto, divergências, situação documental pendente ou falta de regra aplicável produzem valor nulo. A comparação utiliza frações exatas e o arredondamento do motor T04. O valor candidato não movimenta o ledger.

## Limites da candidata

A entrada XML implementada cobre NF-e modelo 55 doméstica emitida pelo fornecedor no mês selecionado, com CNPJ destinatário da unidade. A verificação estrutural do protocolo não autentica assinatura nem eventos posteriores. A origem e o status dependem da revisão dos documentos. O recorte admite componentes documentados de insumo, frete, energia e ativo, com ICMS, IPI, PIS, Cofins e presumidos IBS/CBS sujeitos ao catálogo revisado. As regras e taxas das fixtures são sintéticas. Ausência de catálogo aplicável deixa a oportunidade sem valor.

Esta versão não importa diretamente CT-e, NF3e ou EFD bruta. Exige extrato normalizado revisado. Uma mesma chave não entra duas vezes no lote, a competência deriva do XML e novas versões substituem a visão do período. O importador recusa CNPJ vinculado a duas unidades do mesmo tenant enquanto houver ambiguidade de titularidade. Evidências são armazenadas em snapshots imutáveis de fontes e páginas, com rollback transacional. A T17 continua bloqueada até a certificação da T16.

## Verificação

A suíte focal em PostgreSQL 16.2 isolado aprovou 93 casos T15/T16, sem skips. Inclui variações de protocolo, numeração de itens, reprocessamento após mudança de perfil/regime, seis tributos, quatro destinações, três resultados de escrituração, insuficiência documental, expiração, isolamento, conflito, replay e rollback. Resultados da CI do HEAD e parecer Gemini devem ser vinculados na PR antes de solicitar integração.
