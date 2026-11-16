> **REGISTRO HISTÓRICO RECUPERADO EM 16/11/2026 — PR #453, origem `e04005ad7a8c82ab016c167c90f5404e9e83c43d`.**
> O conteúdo original abaixo foi preservado integralmente. Afirmações de CURRENT, lacunas, prioridades, responsáveis, autorizações e estado de CI referem-se à data do documento. Para o estado vigente, consulte `docs/audit/NFCORE_PR_RECONCILIATION_LEDGER_CURRENT.md`, o GitHub e as decisões posteriores em `AGENTS.md`.
> A recuperação não reabre etapas integradas, não altera a prioridade de 13/11 ou a responsabilidade do Integrador de 15/11, não implementa travas e não certifica cobertura. T2 já possui implementação parcial posterior; esta especificação não prova T1/T3–T6 nem enforcement administrativo.

# NFCore — Cronograma de Execução do Motor Fiscal e da Cobertura (SP-22 primeiro)

**Documento:** NFV1-ENGINE-SCHEDULE-001 (identificador proposto; confirmar no ledger)
**Data:** 2026-11-12
**Status:** cronograma de ordem e governança. **NÃO é certificação técnica, homologação, merge nem deploy.**
**Autoridade:** decisão expressa do proprietário em 12/11/2026 (prioridade SP-22) — **ainda não registrada em `AGENTS.md`**; registrar após aprovação desta PR.
**Fonte superior:** GitHub CURRENT, código, CI e runtime. Este documento rege a **ordem**; não substitui os critérios técnicos de `docs/NFCORE_NATIONAL_COVERAGE_MASTER_SCHEDULE_2026-11-07.md`, `docs/checkpoints/NFCORE_MOTOR_FISCAL_GAP_AUDIT_2026-11-12.md` (#448) e `docs/checkpoints/NFCORE_FISCAL_ENGINE_RECONCILIATION_V2_2026-11-12.md` (#452).
**Origem:** auditoria do motor em `production@ea4bdd3`, reconciliação com `main@ef7ebe7` e PRs abertas, comparação com a arquitetura de referência de mercado e decisões do proprietário de 12/11/2026.

## 0. O que mudou nesta revisão

1. **Prioridade de cobertura.** A ordem anterior (MG-W1 ativa, depois DF → GO → MT → MS) foi montada com a premissa de que os 22 municípios de SP estavam prontos. Não estavam: a PR #446 mostra **0/22** com prova do contrato WebService atual e do ciclo real de autorização, consulta, cancelamento e substituição, e 21/22 com apenas fonte municipal localizada. **A prioridade passa a ser SP-22**, começando por Cajamar, Osasco, Barueri e Jundiaí, e depois os demais municípios.
2. **Centro-Oeste (DF → GO → MT → MS)** passa para depois de SP-22. Nenhuma implementação existente é perdida.
3. **MG-W1** não é descartada: fica no checkpoint registrado (PRs #423 e #440), conforme a pausa já declarada na #446, até o proprietário reordenar.
4. **B17 dividido** em B17a (porta do provedor, roteador e catálogo) e B17b (drivers individuais).
5. **Blocos B13 a B19** acrescentados a partir da comparação com a arquitetura de referência.
6. **Nomes.** A fase externa passa a se chamar **X1 a X4**, para não colidir com os blocos E0 a E5 do relatório #448.

## 1. Regras de execução

1. **Ausência de evidência é bloqueio, nunca autorização implícita.** Nenhum município é declarado homologado sem resposta oficial documentada por operação, ambiente, regime e competência.
2. **Um dono por regra fiscal.** #427 é a única autoridade de serial DPS. #446 é o dono de SP e dos municípios paulistas. #449 e #450 são o dono do emissor nativo. A frente nacional é dona de operações, canais e envelopes por UF. Esta frente de auditoria não escreve código.
3. **Fronteiras compartilhadas protegidas:** `gateway/nfse_nacional_homologation.py`, `issuance/nfse_dps_builder.py`, `runtime/canonical_fiscal_composition.py` e `tests/runtime/test_nfv1_nfse_preparation_recovery.py` são tocados por #446, #449 e #450. Reconciliar por função, sem checkout de arquivo inteiro e sem merge cego.
4. **Sem merge, deploy, DDL, migração v22 ou emissão real sem gate autorizado.** Nenhum selo antes do HEAD final com CI completa; aprovação de SHA anterior não é herdada.
5. **Preparação, fila, aceite HTTP e status sintético não equivalem a autorização fiscal.**
6. **Roteamento por regra determinística e versionada, nunca por disponibilidade.** Se o provedor cair, enfileira e tenta de novo, sem trocar de sistema. Exceção: contingência regulada (por exemplo SVC da NF-e).
7. **Segurança da evidência.** PFX, senha e chave mestra nunca entram em issue, PR ou chat. Checkpoints públicos só com identificadores mascarados.

## 2. Ordem de prioridade

| Prioridade | Frente | Conteúdo | Condição para começar |
|---|---|---|---|
| **P0** | Núcleo NFS-e comum | Fechar as 9 falhas de XSD 1.01 da #451 (campo `serie`); serial durável na #427; integração seletiva #450 incluindo os commits posteriores da #446; regras tributárias por regime e competência (G5); tomador completo (G2); rejeição estruturada e cancelamento (G9, G10) | Imediata. Pré-requisito de qualquer município. |
| **P1** | **SP-22** | Cajamar, depois Osasco, Barueri e Jundiaí, depois os demais municípios do catálogo SP-22 e a capital | Núcleo P0 reconciliado. Dono: executor da #446. |
| **P2** | Fundações de arquitetura | B17a, B13 e B14 (desenho), B15 (desenho), B16, B10, B9 | Em paralelo, por donos distintos, sem tocar fronteiras protegidas. |
| **P3** | Cobertura de documentos | B7 (NF-e completa) e B8 (NFC-e) | Depois de P0 e do desenho de B13/B14. |
| **P4** | Cobertura territorial seguinte | Retomada de MG-W1; depois DF → GO → MT → MS; B17b e B18 conforme o cronograma nacional (uma UF por vez) | SP-22 fechado no gate interno e decisão do proprietário. |
| **P5** | Fase externa X1 a X4 | A1 real em homologação, prova na SEFIN, piloto com o escritório contábil, Go/No-Go de produção | `INTERNAL_CERTIFICATION` completa. |

**Ordem dentro de SP-22 (decisão do proprietário, 12/11/2026):**

1. **Cajamar** — piloto, **fora do catálogo dos 22**. Emissor Nacional para ME/EPP do Simples, competência desde 01/11/2026 (Resolução CGSN 191/2026 e portal NFS-e Nacional; comunicado da Prefeitura de 15/07/2026). Isso não comprova CNPJ habilitado, A1 nem aceite da SEFIN via NFCore.
2. **Osasco**
3. **Barueri**
4. **Jundiaí**
5. **Demais municípios do SP-22**, na ordem definida pelo dono da #446 e confirmada pelo proprietário.

São Bernardo do Campo é o outro município piloto e também está fora do catálogo dos 22. A capital está dentro do catálogo e segue a regra da Prefeitura desde 01/11/2026 (competência do serviço, não o relógio do pedido).

**Gate por município (não negociável, herdado do cronograma nacional):** norma municipal vigente; competência, ISS e inscrição municipal; schema XSD com hash; XMLDSig; envelope correto; endpoint e autenticação oficiais; autorização, consulta, cancelamento e substituição conforme a capacidade; arquivos XML e PDF; pré-auditoria; isolamento por tenant e unidade; idempotência; E2E de Web; CI no SHA exato. Cada município passa pelos estados DESCONHECIDO → CANDIDATO → CONFIRMADO (com fonte) → HOMOLOGADO (com evidência) → PRODUÇÃO.

## 3. Blocos de trabalho

| Bloco | Escopo | Dono / frente | Condição | Aceite |
|---|---|---|---|---|
| B0 | Fatos e fontes: registro de cada afirmação com origem | Auditoria | Contínuo | Cada status com fonte e data |
| B1 | Domínio e builder NFS-e: tomador, regime, ISS, schema 1.01 | #449 / #450 | P0 | XSD, XMLDSig, casos de tomador |
| B2 | Resultado, arquivo, consulta e cancelamento NFS-e | #450 / #446 | P0 | XML oficial arquivado, consulta sem segundo POST |
| B3 | Numeração durável do DPS | #427 | P0 | Concorrência, replay, rollback |
| B4 | Entrada pelo Portal | #449 / #450 | P0 | E2E de navegador |
| B5 | Sentinela v2: pré-auditoria com catálogos oficiais | Motor fiscal | Depois de B1 | Catálogo versionado, regime e competência |
| B6 | Reforma tributária nos documentos | Motor fiscal | Depende de fonte normativa (NT 004 e NT 009) | Regras com vigência por data de emissão |
| B7 | NF-e 55 completa (entrada, eventos, costura de eventos `procEventoNFe`) | Motor fiscal | P3 | E2E de NF-e |
| B8 | NFC-e 65 (QR Code, CSC, DANFCE térmica, QR offline) | Motor fiscal | P3 | E2E de NFC-e |
| B9 | Core cognitivo: sinalizadores, cota, catálogos revisados | Cognitivo | Contínuo | Revisão do contador |
| B10 | Operação interna: backup e restauração do cofre A1, retenção, ruleset | Operação | Contínuo | Restore controlado |
| B11 | Certificação interna: gate mestre que atravessa todos os limites | Motor fiscal | Depois de P0 a P3 | Todos os gates verdes no HEAD exato |
| B12 | Escopo expandido por tipo e canal (decisão do proprietário) | Proprietário | — | Planilha de escopo aprovado |
| B13 | Emissão assíncrona reaproveitando o `DurableFiscalOutboxWorker` | Motor fiscal | P2 (desenho), P3 | Zero perda e zero duplicidade em falha |
| B14 | Contingência e status: NFC-e offline, SVC-AN e SVC-RS, conciliação | Motor fiscal | Depois do B13 | Consulta de chave antes de retransmitir |
| B15 | Custódia do A1, cadeia ICP-Brasil, revogação, política TLS | Operação / segurança | P2 (desenho) | Decisão de custódia aprovada |
| B16 | Pós-processamento contábil: ZIP mensal, DANFSE, alerta de quebra de sequência | Motor fiscal | P2 | Exportação por competência |
| **B17a** | **Porta do provedor, roteador e catálogo de municípios** | Frente de SP | Depois de #450, #427 e #446 reconciliadas | Primeiro passo: Nacional atrás da porta, sem mudar comportamento |
| **B17b** | **Drivers individuais por família de layout** | Frente de SP / nacional | Um por vez, por demanda da carteira | WSDL oficial e homologação com certificado real |
| B18 | Mapa de autorizadores por UF, de fonte oficial | Frente nacional | P4 | Teste que compara cada UF |
| B19 | Robustez e desempenho: limite por tenant, retry, circuit breaker, carga | Motor fiscal | Depois do B13 | Meta de capacidade definida pelo proprietário |

### B17a — porta do provedor (especificação)

- Contrato do driver: preparar, assinar, transmitir, consultar, cancelar e interpretar resultado. Cada driver declara o que suporta (operações e ambientes) e seu estado (NÃO_VERIFICADO, HOMOLOGADO, PRODUÇÃO). O que não estiver provado fica bloqueado.
- Resultado normalizado igual para todos: status, protocolo, número, código de verificação, XML autorizado e rejeições estruturadas (código, origem, mensagem crua).
- O contrato canônico de NFS-e fica acima da porta e nunca recebe campo de layout.
- Catálogo de municípios como **dado**: IBGE, layout, endpoints, perfil de assinatura (SHA-1 ou SHA-256), regras de código de serviço e alíquota, regimes, competência de vigência, fonte oficial e estado.
- Roteador determinístico e versionado. Sem rota verificada, recusa com motivo.
- O driver Nacional se separa em dois papéis: **SEFIN Nacional** para emissão e **ADN** para distribuição e consulta.
- Drivers por **família de layout**; cada provedor com **perfil de particularidades como dado** no catálogo.

## 4. Mapa-alvo do motor e o que já existe

A estrutura `engine/` proposta pelo proprietário vale como **mapa-alvo de capacidades**, não como reorganização de pastas. O equivalente já existe em `src/kordena_fiscal/`.

| Capacidade | O que já existe (production ea4bdd3) | Bloco |
|---|---|---|
| Certificados e assinatura | XMLDSig com SHA-256 e SHA-1 legado; conferência do CNPJ do certificado contra o emitente em `vault/a1_preflight.py`, que declara **não** validar cadeia ICP-Brasil nem revogação; cofre em arquivo AES-GCM, Secret Manager só para segredos de webhook | B15, B11 |
| Cálculo tributário | Prévia de reforma tributária; ISS, retenções e ICMS completos não existem | B5, B6 |
| Schemas XSD | XSDs com hash fixado | B1, B6 |
| Estadual (NF-e e NFC-e) | Chave de 44 dígitos e DV; costura `nfeProc` no gateway SP e no DANFE; mTLS; catálogo só de MG, MS, MT, PR, RJ e SP; sem QR Code e CSC no XML da NFC-e | B7, B8, B18 |
| NFS-e | Driver Nacional real; envelopes Paulistana e ABRASF 2.03 sem transporte | B17a, B17b |
| PDF | DANFE 55; DANFSE na #450; existe `presentation/danfe_nfce.py`, ainda não conferido quanto ao QR | B16, B8 |

## 5. Absorvido da arquitetura de referência, e o que não foi

**Absorvido:** regras tributárias como dado versionado com vigência (B5, B6); costura de eventos (B7); QR Code, CSC, DANFCE e QR offline (B8); retenção do cofre e teste de restauração do cofre A1 (B10); emissão assíncrona reaproveitando o outbox existente (B13); contingência e conciliação por consulta de chave (B14); custódia do A1, cadeia ICP-Brasil e revogação (B15); ZIP contábil e alerta de quebra de sequência (B16); porta do provedor, catálogo e drivers por família (B17a, B17b); mapa de autorizadores de fonte oficial (B18); limite de taxa, retry e circuit breaker (B19).

**Não absorvido:**

- A pasta `engine/` como reorganização, por gerar conflito com as PRs abertas sem ganho.
- A lista de UFs do SVRS do material de referência: diz 19 UFs e lista 17, e trata autorizadores próprios como se só mudasse a URL. O mapa vem de fonte oficial (B18).
- Driver ABRASF que "só troca URL e namespace": substituído por driver por família mais perfil por provedor.
- "Zero dependência externa" como regra: usamos bibliotecas e o Secret Manager; ERPs seguem como conectores opcionais, nunca como autoridade de emissão.
- Auto-healing por disponibilidade (ver regra 6).
- Detalhes sem fonte oficial confirmada (assinatura posicional da Paulistana; quais cidades usam DSF ou Ginfes): só entram com manual oficial.

## 6. Correspondência de numerações (aproximada)

O diagnóstico usa duas numerações do mesmo problema: G1 a G16 (auditoria do motor) e MF-01 a MF-18 (#448). Correspondência aproximada: MF-01 = G1; MF-02 = G2; MF-03 = G8; MF-04 = G5; MF-05 = G3; MF-06 e MF-10 = G9; MF-07 = G7; MF-12 = G4 e G10. Os blocos E0 a E5 do #448 correspondem às ondas internas deste cronograma; a fase externa daqui (X1 a X4) corresponde ao E4 e ao E5 de lá.

## 7. Fase externa (X1 a X4)

Só começa com a certificação interna completa e exige autorização humana específica para cada item.

- **X1** — A1 real de contribuinte autorizado, enviado ao cofre, nunca pelo chat ou GitHub.
- **X2** — Prova na SEFIN em homologação (`tpAmb=2`): emissão, consulta e eventos, com protocolo e XML oficiais.
- **X3** — Piloto com o escritório contábil, um município e uma competência por vez.
- **X4** — Go/No-Go de produção (`PRODUCTION_APPROVED`, `tpAmb=1`), em processo separado.

## 8. Decisões pendentes do proprietário

1. Ordem dos demais municípios do SP-22 depois de Cajamar, Osasco, Barueri e Jundiaí.
2. Quando retomar MG-W1 e o Centro-Oeste depois do gate interno de SP-22.
3. Municípios onde estão os clientes do escritório contábil, para escolher o segundo driver (B17b).
4. Cauda longa de municípios: cobrir por driver delegado a agregador terceirizado? Implica dependência e decisão sobre custódia do certificado.
5. Meta de capacidade do B19.
6. Escopo de CT-e, MDF-e, energia e telecom (B12).
7. Autorização para registrar esta prioridade em `AGENTS.md`.

## 9. Estado de evidência

- **Nenhuma** emissão com A1 real, resposta oficial autorizada e XML verificado foi comprovada.
- **Nenhum** município está homologado por evidência atual. 0/22 do SP-22 têm prova do contrato WebService atual.
- A #451 está com CI vermelha (9 falhas de XSD no campo `serie`); a #427 é Draft e conflitante; a #446 tem commits posteriores ao snapshot da #450.
- A implantação efetiva no servidor Contabo não foi verificada por este documento.
- Status global: `PARTIAL_IMPLEMENTATION / INTERNAL_CERTIFICATION_PENDING / EXTERNAL_HOMOLOGATION_PENDING`.

## 10. Registro de mudanças

- **2026-11-12:** criação. Prioridade de cobertura alterada de MG-W1 → DF → GO → MT → MS para SP-22 primeiro (Cajamar, Osasco, Barueri, Jundiaí, demais). B17 dividido em B17a e B17b. Blocos B13 a B19 acrescentados. Fase externa renomeada para X1 a X4.
