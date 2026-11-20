# RTC-RFB — Calculadoras oficiais da Receita Federal no NFCore

Estado em 20/11/2026. O NFCore continua sendo a única autoridade fiscal. As calculadoras oficiais rodam como serviços internos, em modo sombra: conferem e registram divergências, nunca alteram nem bloqueiam uma nota.

## Componentes fixados

| Componente | Repositório (MIT) | Commit fixado | Versão | Estado |
|---|---|---|---|---|
| Banco SQLite | calculadora-rtc-regime-regular (`flyway/`) | `f1eebd7ce3157423b1a6aaca7dc1d6c3395452c4` | V0073 (cClassTrib de 30/10/2026) | Gerado com Flyway e conferido (0 migrações com falha). As duas calculadoras usam o mesmo arquivo |
| Simples Nacional | calculadora-rtc-simples-nacional | `a926d5a76095ac0295a6612a9a54db7ffead2396` | 1.0.2 (18/11/2026) | Compilado (Java 25) e executado contra o banco V0073 |
| Regime Regular | calculadora-rtc-regime-regular | `f1eebd7ce3157423b1a6aaca7dc1d6c3395452c4` | 1.7.2 (18/11/2026) | Compilado (Java 25) e executado contra o banco V0073 |
| Gerador DANFSe | calculadora-rtc-gerador-danfse (Go) | — | — | Não integrado |

A cópia do repositório do Regime Regular veio do ZIP enviado pelo Fábio em 20/11. O commit do ZIP (`f1eebd7c`) é igual ao HEAD público consultado com `git ls-remote`.

## Prova de ponta a ponta feita em 20/11/2026

- Banco gerado com `flyway:migrate` a partir do commit fixado: 73 versões aplicadas, nenhuma com falha.
- Simples 1.0.2: `GET /api/versao` respondeu `versaoApp 1.0.2` e `versaoDb V0073`. Uma NF-e com CRT 1 e `cAtivSN 01` deu `CALCULADO` (vCBSSN 11,61, vIBSSN 0,13 sobre R$ 1.000). Um item sem `cAtivSN` deu `NAO_CALCULADO`, com o motivo `CATIVSN_AUSENTE`.
- Regime Regular 1.7.2: `GET /api/calculadora/dados-abertos/versao` respondeu 1.7.2 e V0073. Uma NF-e de MG em 2026 deu `CALCULADO`, com CBS de 0,9% (R$ 9,00) e IBS UF de 0,1% (R$ 1,00). Um item com NCM não vinculada deu `INCONSISTENCIA_ENTRADA`, com o código `REG-011`.
- As respostas reais estão gravadas em `tests/tax/fixtures/rfb/` e os testes as usam.

## Contratos (mudanças em relação ao pin anterior 0.0.6)

- **Simples 1.x:**
  - exige `versao` na operação e `valorImpostoSeletivo` em todo item;
  - devolve os valores como texto (`"11.61"`);
  - responde 422 quando a operação inteira é inválida;
  - inclui `motivoEstado` quando o item não foi calculado.
  - O endpoint usado agora é marcado como obsoleto. O novo, `/nao-assistido`, cobre NF-e, NFC-e e **NFS-e (tpDoc 91)**, e a migração para ele é o próximo passo.
- **Regime Regular:**
  - exige `versao`, `municipio` e `uf`;
  - os valores vêm em `tribCalc.IBSCBS.gIBSCBS`;
  - os estados possíveis incluem `CALCULO_SIMULADO`;
  - `aliquotasNominais` são obrigatórias a partir de 01/01/2027 e proibidas antes. O adaptador recusa 2027 enquanto o NFCore não envia essas alíquotas.

## O que existe no NFCore

- **Adaptadores:** `tax/rfb_simples_calculator.py` e `tax/rfb_regime_regular_calculator.py`.
  - Aceitam só URL interna.
  - Conferem a versão do aplicativo e, no Regime Regular, também a do banco.
  - Exigem que cada item pedido volte exatamente uma vez.
  - Trabalham com valores em Decimal.
- **Sombra (`tax/rtc_shadow.py`):** CRT 1/2 vão para o Simples; CRT 3 (Lucro Presumido ou Real) vai para o Regime Regular. A função nunca levanta exceção e devolve um registro arquivável.
- **Containers:**
  - `deploy/rfb/database` gera o banco;
  - `deploy/rfb/simples` e `deploy/rfb/regime-regular` compilam os commits fixados e conferem o hash;
  - rodam sem root e não acessam o piloto público.
- **Compose opt-in:** `deploy/contabo/compose.rtc-calculators.opt-in.yml` sobe as duas calculadoras.
  - Não publica porta e monta o banco só para leitura.
  - Limita cada uma a 768m de memória e 1 CPU.
  - Não entra no deploy padrão.

## Pendências

1. ~~Ligar a sombra depois da emissão~~ **Feito:** `prepare_nfe_sale` chama `record_rtc_shadow` depois do commit, ativado por `NFCORE_RTC_SIMPLES_URL` e `NFCORE_RTC_REGIME_REGULAR_URL` (o overlay do compose já define as duas). O registro fica arquivado junto da nota, e qualquer falha é engolida.
2. ~~`/nao-assistido`~~ **Feito no adaptador:** `build_nfse_request` e `calculate_unassisted` montam a NFS-e (tpDoc 91, um item, `opSimpNac`, `regApIBSCBSSN`, `regApTribSN`, `aliquotasEfetivas` por anexo, com o par sem redistribuição do ISS nos anexos III/IV/V), conferidos contra resposta real (`sn_nfse_calc.json`). **Ainda não ligado à emissão da NFS-e:** depende das alíquotas efetivas do PGDAS de cada empresa no período, dado externo que o contador informa. Observação: o NBS do exemplo oficial (114051000) não existe no banco V0073 (VSN-050); usamos 114051100.
3. ~~cAtivSN~~ **Feito:** `simples_activity_code` na regra fiscal (códigos oficiais 01–14 e 90), enviado à calculadora como `cAtivSN`.
4. ~~Indicadores da CLASSIFICACAO_TRIBUTARIA~~ **Feito para o que o NFCore emite:** `tax/rtc_group_indicators.py` traz, do V0073, quais CST exigem `gIBSCBS` e as seis classificações (000003, 000004, 200054, 410016, 410026, 410030) que exigem grupos que o NFCore não gera (gCredPresOper, gEstornoCred); essas são recusadas antes do XML. CST 400 (isenção) passou a ser emitido como o 410, validado no XSD oficial. Um teste opcional (`NFCORE_RFB_CALCULATOR_DB`) confere a tabela contra o banco. **Fora do escopo atual, recusados de forma explícita:** 010/011 (setor financeiro), 220/221/222, 510/515 (diferimento), 550, 620 (monofásico de combustíveis), 800/810/811/820/830 — exigem grupos próprios e não fazem parte do público do NFCore hoje.
5. **Subir no Contabo.** O primeiro passo é medir memória e CPU; a estimativa é de cerca de 768m por serviço Java.
6. **Sentinela Normativa:** observar os releases e trocar o pin só depois dos testes e da aprovação humana.

## Reconciliação RTC-RFB × Economia Fiscal T07 — 20/11/2026

A reconciliação tem uma única autoridade documental: [cronograma central da Economia Fiscal — T07](../NFCORE_CENTRAL_ECONOMIA_FISCAL_EXECUTION_SCHEDULE.md#reconciliação-rtc-rfb--economia-fiscal-t07--20112026). Consultar ali o estado e as evidências; este documento não replica o checkpoint.
