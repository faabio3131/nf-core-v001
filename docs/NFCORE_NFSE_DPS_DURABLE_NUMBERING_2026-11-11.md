# NFCore — DPS NFS-e: numeração fiscal durável, 11/11/2026

## Identidade e governança

**Produto:** FM NFCORE V1. **PR de implementação:** #427 (Draft). **PR de cobertura MG-W1:** #423 (Draft). **Issue de aceite final:** #426. **Branch:** `feat/nfcore-nfse-dps-durable-numbering-20261111`, base `main@545b7606208eedf77b3fd6b852ccb82b4716f6b8` no início da implementação.

**CURRENT auditado:** `src/kordena_fiscal/issuance/nfse_dps_builder.py` derivava `nDPS` do hash da requisição, sem contador fiscal. O preparo NFS-e `FiscalApplicationService.prepare_nfse_authorization` já persistia idempotência, lifecycle e arquivo numa mesma UoW. `fm_fiscal_sequences` possui identidade tenant/unidade/modelo55/65/série, insuficiente para sequência legal de NFS-e por **CNPJ emissor**. Reaproveitar o modelo 55/65 transformaria uma autoridade errada em fonte fiscal. Isso seria regressão de domínio.

**TARGET implementado como candidato (não homologado):**

1. `DpsNumberingStore` é um **port acoplado à mesma FiscalUnitOfWork** que já governa o produto, não um segundo banco, auth ou API.
2. Migration **aditiva versão 22** (`nfse_dps_numbering_schema.py`) cria `fm_nfse_dps_counters` e `fm_nfse_dps_reservations`, com UNIQUE por emitente/municipio/ambiente/série/número e replay por documento. A versão pode coexistir com ou sem as migrations opcionais Bling 20/21. Nunca aplicar automaticamente em staging/produção.
3. `SqliteDpsNumberingStore`: transação sob `BEGIN IMMEDIATE`; `PostgresDpsNumberingStore`: lock consultivo transacional por documento e por emitente/série, persistência na mesma transação, não `MAX+1`.
4. `NfseCanonicalDocument` preserva compatibilidade retroativa de snapshots ainda não numerados, mas o builder rejeita assinatura/transmissão sem o número reservado. `prepare_nfse_authorization` atribui série/número na transação canônica antes de construir fingerprint, arquivar e finalizar `READY_TO_TRANSMIT`; replay mantém a mesma reserva.
5. `nfse_archive` persiste e recupera a numeração. `build_signed_dps` usa o número governado em `nDPS` e `infDPS/@Id`, com zero padding somente no identificador fiscal; rejeita hash, número informado pelo cliente e concorrência insegura.
6. Gateway SEFIN Nacional recusa ausência de reserva antes de abrir A1, executar assinatura ou HTTP.
7. Os testes incluem conflitos, interleaving de tenants/unidades, séries, ambientes, rollback, replay, reinício, concorrência SQLite e PostgreSQL real de banco `_test`, e build XML assinado.

## Limites que permanecem

**PENDENTE:** testar e revisar o SHA exato da PR #427 com Ruff, Mypy, Pytest, PostgreSQL e demais gates. A aprovação de governança é independente de CI geral. **Nenhuma migration foi aplicada em base persistente externa**, nenhum A1 real foi tocado, nenhum município foi homologado e nenhum merge/deploy autorizado.

**BLOQUEIO FISCAL INDEPENDENTE:** o DPS ainda usa XSD histórico `DPS_v1.00` enquanto a NFS-e Nacional produção restrita possui evolução de NT009/RTC com versões e vigência próprias. Campos de ISS e configuração tributária especiais (`regApTribSN`, `regEspTrib`, `tribISSQN`) continuam sem modelo integralmente governado; número sequencial não certifica o envelope vigente. Não liberar produção só porque esta PR passou.

**RISCO DE INTEGRAÇÃO:** PR #422 modifica `scripts/ci/migration_guard.py`, e PR #423 mexe no gateway NFS-e. Antes de merge, reconciliação de diffs por código e testes é obrigatória; não sobrescrever as trilhas Bling/Contabo/EGM.

**Ordem subsequente:** certificação desta PR por SHA → reconciliação com #423/CI → versão oficial correta do XSD por ambiente e data → operações MG 55/65 restantes → contratos, envelopes e eventos fiscais específicos dos 20 municípios → testes Web/PG/E2E e revisão independente EGM real (quando disponível). **MG-W1 não muda de IMPLEMENTING sem 20/20 evidências completas.**
