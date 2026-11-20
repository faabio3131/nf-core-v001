> **REGISTRO HISTÓRICO RECUPERADO EM 16/11/2026 — PR #453, origem `e04005ad7a8c82ab016c167c90f5404e9e83c43d`.**
> O conteúdo original abaixo foi preservado integralmente. Afirmações de CURRENT, lacunas, prioridades, responsáveis, autorizações e estado de CI referem-se à data do documento. Para o estado vigente, consulte `docs/audit/NFCORE_PR_RECONCILIATION_LEDGER_CURRENT.md`, o GitHub e as decisões posteriores em `AGENTS.md`.
> A recuperação não reabre etapas integradas, não altera a prioridade de 13/11 ou a responsabilidade do Integrador de 15/11, não implementa travas e não certifica cobertura. T2 já possui implementação parcial posterior; esta especificação não prova T1/T3–T6 nem enforcement administrativo.

# NFCore — Regra de fechamento de bloco e especificação do pacote de travas

**Documento:** NFV1-CLOSING-RULES-001 (identificador proposto; confirmar no ledger)
**Data:** 2026-11-12
**Status:** **ESPECIFICAÇÃO. Nada deste documento está implementado.** Não altera CI, ruleset, `CODEOWNERS`, permissões, código, migração, merge nem deploy. Qualquer implementação exige autorização expressa do proprietário.
**Complementa:** `docs/NFCORE_FISCAL_ENGINE_EXECUTION_SCHEDULE_2026-11-12.md`.

## 1. Por que existe

Regras em texto (`AGENTS.md`, skills, cronogramas) são lidas pelo agente como contexto e podem ser ignoradas, esquecidas entre sessões ou "cumpridas" por escrita. Resultado observado: blocos iniciados e não completados, status "pronto" declarado por existência de código ou CI verde, PRs com escopo sem fim (#446: mais de 100 commits e 45 arquivos), três PRs no mesmo arquivo (#446, #449, #450), PRs em draft conflitantes (#427) ou vermelhas (#451). Só é lei o que roda fora do agente e bloqueia.

## 2. Divisão de responsabilidades

| Camada | Responsável | O que garante |
|---|---|---|
| Processo | Travas mecânicas (permissão e CI) e, como camada de planejamento, EGM | Quem pode fazer o quê; o que precisa estar provado para declarar pronto; quantas frentes ficam abertas; plano completo antes de construir |
| Implementação fiscal | Agentes construtores (A e B) | Regra fiscal implementada, fonte oficial lida, testes escritos, caminho de ponta a ponta percorrido |
| Verificação fiscal externa ao construtor | Norma oficial, validador independente, resposta real de homologação, revisão do contador | Correção fiscal. O construtor não é o único juiz de que sua entrega está correta |

Travas e EGM **não** verificam se uma alíquota, um campo ou uma regra municipal está certo. Para isso valem a norma citada com data e versão, o teste e o contador.

## 3. Regra de fechamento de bloco

1. **Um bloco, uma PR.** Cada bloco do cronograma (B0 a B19) tem uma PR própria. Não se abre PR nova para o mesmo bloco nem se fecha a PR para "testar".
2. **A PR do bloco permanece em draft** até que o checklist de aceite do bloco (coluna "Aceite" do cronograma) esteja 100% marcado e a CI do **HEAD exato** esteja verde. Aprovação de SHA anterior não é herdada.
3. **Uma frente por vez para cada agente (WIP = 1).** Não se abre bloco novo enquanto o anterior não estiver FECHADO ou `EXTERNAL_BLOCKED`, com o motivo escrito na PR.
4. **Definição de pronto:** o caminho real percorrido por teste de ponta a ponta (por exemplo, Portal → motor → gateway sintético → arquivo), além de testes unitários e CI. Código existente, CI verde, health e catálogo não equivalem a pronto.
5. **Vocabulário travado:** "certificado" e "homologado" só com a lista de evidências anexa. Sem ela, o status é `IMPLEMENTED_NOT_CERTIFIED`.
6. **Nada incompleto à vista.** Funcionalidade não completa fica desligada ou explicitamente `NÃO IMPLEMENTADO`, sem botão ou endpoint que prometa o que não existe.
7. **Dimensionar antes de começar.** Bloco grande demais para fechar sem virar monólito é dividido de antemão em sub-blocos independentes, cada um com PR e checklist próprios. Não se divide no meio do caminho.
8. **Testes sem fechar.** Durante o bloco roda-se o teste dirigido a cada passo; a suíte completa roda no fim do bloco e sob demanda. Parar para testar não é motivo para fechar ou trocar de PR.
9. **Integrar a main na branch com frequência** (merge do base no head, nunca reescrita de histórico em branch alheia), para o conflito aparecer cedo.
10. **Tamanho como alerta.** Passou de um limite a definir (sugestão inicial: 400 linhas alteradas fora de testes e fixtures, ou 20 arquivos), o agente justifica ou divide.
11. **Auditoria independente no fechamento.** Antes de abrir o bloco seguinte, outro agente ou pessoa, que não o construiu, confere o diff contra o checklist. Resultado INCOMPLETE conta como reprovado.
12. **Matriz viva** (requisito, código, teste, CI, ambiente, lacuna) como única fonte do que está pronto. O status de uma capacidade só sobe se o teste de ponta a ponta correspondente passar.

## 4. Pacote de travas (especificação; nada implementado)

| Trava | O que bloqueia | Como é verificada | Dono |
|---|---|---|---|
| T1 Permissões | Agente fazendo merge ou push em `main` e `production`; alterar CI ou ruleset | Ruleset exigindo checks e aprovação humana; token do agente com menor privilégio; `CODEOWNERS` com aprovação do proprietário para as quatro fronteiras protegidas, para `.github/workflows/**` e para os cronogramas | Proprietário |
| T2 Check de evidência | PR que usa "certificado", "homologado" ou "22/22" sem arquivo de evidência anexo e SHA conferido | Workflow que lê o corpo da PR e os documentos alterados | A definir |
| T3 Limite de frentes | Autor com mais de N PRs draft abertas, ou PR de bloco novo com o anterior não fechado | Workflow que consulta a API do GitHub | A definir |
| T4 Matriz ligada a testes | Subir o status de uma capacidade sem o teste de ponta a ponta correspondente | Comparação entre a matriz em arquivo e os resultados de teste | A definir |
| T5 Anti-stub | Marcadores `PROVISIONAL`, `NotImplemented`, `TODO` em caminho declarado pronto | Teste ou varredura estática | A definir |
| T6 Fronteira protegida | PR que altera `gateway/nfse_nacional_homologation.py`, `issuance/nfse_dps_builder.py`, `runtime/canonical_fiscal_composition.py` ou o teste de recuperação sem o dono | `CODEOWNERS` e check de caminho | Proprietário |

**Salvaguarda:** o agente pode tentar editar o próprio CI para afrouxá-lo. Por isso `.github/workflows/**`, o ruleset e o `CODEOWNERS` ficam sob aprovação do proprietário. Já existem `nfcore-plan-governance.yml` e o check `execution-plan`; o conteúdo exato deles não foi auditado e pode ser ampliado em vez de duplicado.

## 5. EGM (Elephant-Goldfish Model): camada de planejamento, em piloto

- O que é: plugin de código aberto (Apache 2.0, "not an officially supported Google product") com sete skills: `egm-brainstorm`, `egm-draft`, `egm-resolve`, `egm-bootstrap`, `egm-review` (cinco etapas, relatório por etapa), `egm-review-loop` e `egm-drift-report`. Revisão por subagentes em contexto novo; para se não houver subagente.
- O que não faz: não impede o agente de ignorar regras durante a implementação, não bloqueia merge, não conhece a norma fiscal. O próprio projeto diz que não substitui testes nem julgamento humano. O Claude Code tem comando de instalação documentado, mas não consta na lista de suporte oficial.
- Piloto proposto (duas semanas): (a) `egm-review` na especificação do B17a antes de qualquer código; (b) `egm-drift-report` semanal entre cronograma, documentos e código. O pacote de laboratório com Codex foi enviado pelo proprietário e nada nele foi executado.
- Métricas: achados Blocker pegos antes de existir código; PRs refeitas; drafts abertos; afirmações de "pronto" sem evidência. Se as métricas não mudarem, descarta-se.

## 6. Protocolo de aprovação por conversa (decisão do proprietário, 12/11/2026)

O proprietário **não** abre o GitHub para revisar nem aprovar. Os agentes pedem a permissão e o proprietário decide por conversa, em linguagem simples.

### 6.1 Níveis

| Nível | Classe de mudança | Quem decide |
|---|---|---|
| **N1 — automático** | Apenas documentação **que não altera ordem de prioridade, regra ou escopo**; apenas testes sem alterar código de produção. CI verde no HEAD exato, checklist do bloco completo e conferência independente de outro agente. | Ninguém (auto-merge), **depende de configuração única do proprietário** (ver 6.5) |
| **N2 — decisão em conversa** | Qualquer alteração em `src/`; qualquer alteração em fronteira protegida; mudança de prioridade, ordem ou escopo nos cronogramas; nova dependência; mudança de contrato de API. | Proprietário, por mensagem curta |
| **N3 — sempre o proprietário, com confirmação explícita** | Promoção para `production` (deploy automático a cada 5 minutos); migração ou DDL (incluindo a v22 da #427); certificado A1, Vault e segredos; `tpAmb=1` ou qualquer ativação de produção fiscal; cobrança e licença (Cakto); alteração de CI, ruleset, `CODEOWNERS` ou permissões; homologação externa; apagar ou forçar push. | Proprietário, por mensagem curta, citando o item |

Em caso de dúvida sobre o nível, aplica-se o **mais alto**.

### 6.2 Como o agente pede

O agente **não faz merge, deploy nem aplica migração**. Ele publica um comentário na PR e na issue #447, com o título `PEDIDO DE APROVAÇÃO`, neste formato:

1. **Nível** (N2 ou N3) e **PR + SHA do HEAD** a que o pedido se refere.
2. **Bloco** do cronograma.
3. **O que muda**, em até 5 linhas, em linguagem simples.
4. **Evidência**: links dos runs de CI, testes executados e o checklist do bloco.
5. **O que NÃO foi provado.**
6. **Risco e como reverter.**
7. **Decisão pedida**, numa frase (por exemplo: "aprovar o merge da PR #N").

### 6.3 Como o proprietário decide

O proprietário responde na conversa com o assistente, por exemplo "aprovo" ou "não, porque...". A decisão vale **somente para o SHA citado**. Commit novo na PR invalida a aprovação. **Silêncio não é aprovação.**

### 6.4 Execução

Com a aprovação, o assistente executa o merge se o acesso e o ruleset permitirem. Caso contrário, informa o que falta. O assistente registra a decisão do proprietário na PR, citando data e SHA. O assistente nunca aprova nem mescla por conta própria; só por pedido expresso do proprietário, que pode ser permanente para uma classe (por exemplo, "mescle PRs só de documentação quando a CI estiver verde").

### 6.5 Limites práticos

- **Os agentes executores não escrevem na conversa do proprietário com o assistente.** Os pedidos chegam por comentário na PR e na issue #447. O assistente os vê enquanto a sessão estiver ativa e assinada na PR, ou quando o proprietário pedir ("o que está esperando minha decisão?"). Para não depender disso, pode-se agendar um resumo periódico (decisão do proprietário, 6.7).
- **N1 exige configuração única do proprietário no GitHub:** ligar auto-merge e ajustar o ruleset para exigir checks, e não aprovação humana, nas classes de baixo risco. O assistente não altera ruleset.
- Se o ruleset da `main` hoje exigir aprovação humana, o merge por conversa continua bloqueado até esse ajuste.

### 6.6 O que o agente nunca faz

Merge, deploy, migração, mudança de ruleset ou permissão, ou qualquer ação de N3, sem a aprovação registrada. Agente aprovando PR de agente não conta como aprovação humana nos níveis N2 e N3.

### 6.7 Decisões pendentes do proprietário

1. Autorizar a implementação de T1 a T6, em ordem de retorno (T1, T2, T3 primeiro).
2. Definir N de T3 e o limite de tamanho da regra 10.
3. Autorizar o piloto do EGM e onde ele roda (Codex no Windows do proprietário ou outro).
4. Definir quem faz a auditoria independente de fechamento (regra 11).
5. Configuração única de auto-merge e do ruleset para o N1 (6.5).
6. Resumo periódico agendado das decisões pendentes (6.5): sim ou não, e com que frequência.
