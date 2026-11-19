# RTC-RFB — Calculadoras oficiais da Receita Federal no NFCore

Estado em 19/11/2026. O NFCore continua sendo a única autoridade fiscal. As calculadoras oficiais rodam como serviços internos, primeiro em modo sombra.

## Componentes oficiais

São 3 repositórios públicos da organização ReceitaFederal, todos MIT e atualizados em 27/10/2026.

| Componente | Repositório | Commit fixado | Estado |
|---|---|---|---|
| Simples Nacional | calculadora-rtc-simples-nacional | `c5b0f01c8351c3f0d0795cc617b29d233e9f98df` (app 0.0.6, Release 15) | Código lido e compilado (Java 21, Spring Boot 3.5.16, JAR de 90 MB). Banco ainda não gerado |
| Regime Regular | calculadora-rtc-regime-regular | — | Só o ROADMAP foi lido. A página principal, o README, `docs/exemplos.md` e `flyway/` não abriram (erro do GitHub ou permissão expirada). Não foi baixado por outro meio |
| Gerador DANFSe | calculadora-rtc-gerador-danfse (Go) | — | Ainda não lido |

## Fatos confirmados no código fixado do Simples

- `POST /api/calculadora/observabilidade/simples-nacional` sempre responde HTTP 200 (`ResponseEntity.ok()`), mesmo quando algum item falha.
- Cada item traz `estadoItem`, que pode ser `CALCULADO`, `NAO_CALCULADO`, `NAO_IMPLEMENTADO`, `INCONSISTENCIA_ENTRADA` ou `FALHA_TECNICA`.
- `GET /api/versao` devolve `versaoApp` e `versaoDb`. As respostas também trazem os headers `X-CALC-APP-VERSION` e `X-CALC-DB-VERSION`.
- O perfil `offline` abre o SQLite `./calculadora/db/calculadora-pro.db` só para leitura. Na inicialização ele consulta o piloto público (`VERSAO_URL`), mas segue funcionando se a consulta falhar.
- **Bloqueio:** os scripts Flyway que geram o banco ficam no repositório do Regime Regular (ADR009 do Simples), que ainda não foi lido.
- O Simples não calcula a alíquota efetiva (PGDAS-D); isso está previsto para a Release 16.

## O que já existe no NFCore (PR RTC-RFB-01..04)

- **Adaptador:** `src/kordena_fiscal/tax/rfb_simples_calculator.py`.
  - Aceita só URL interna (loopback ou nome de container) e confere a versão fixada antes de calcular.
  - Exige que cada item pedido volte uma única vez.
  - Converte valores para `Decimal`.
  - `require_all_calculated()` bloqueia qualquer item que não esteja `CALCULADO`.
  - `compare_shadow()` só registra divergências.
- **Container:** `deploy/rfb/simples/Dockerfile` compila o commit exato e confere o hash. Roda sem root, e `VERSAO_URL` é anulado para não sair para a internet.
- **Compose opt-in:** `deploy/contabo/compose.rtc-simples.opt-in.yml` não publica porta, monta o banco só para leitura e limita memória a 768m e CPU a 1. Não entra no deploy padrão.

## Próximos passos

1. **RFB-05:** gerar o banco e comparar os resultados.
   - Depende de ler o repositório do Regime Regular, ou seja, dos scripts Flyway.
   - Depois, rodar em sombra em casos reais e investigar as divergências.
2. **RFB-06:** integrar o Regime Regular (ler o código, fixar o commit, montar o adaptador).
3. **RFB-07:** ligar o Simples ao fluxo de NFS-e e NF-e, ainda em modo sombra.
4. **RFB-08:** adaptar o XML (NF-e, NFC-e e DPS da NFS-e) para os grupos IBS/CBS oficiais.
5. **RFB-09:** avaliar o gerador oficial de DANFSe frente ao `danfse_pdf.py`.
6. **RFB-10:** a Sentinela Normativa passa a observar os releases, com troca de pin só após testes e aprovação humana.
7. **RFB-11:** certificar e substituir seletivamente, regime a regime, com aprovação do Fábio.
8. **Medir o Contabo:** medir memória e CPU antes de subir os serviços (estimativa de 768m por serviço Java).
