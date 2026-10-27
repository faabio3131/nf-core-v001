# NFV1-P05-T01 / P6-T01-B02 — Google Secret Manager: checkpoint de bootstrap staging (2026-10-11)

> Tipo: evidência de operações externas reais, **não** certificação do Secret Manager nem autorização de produção. Documento aditivo; não altera plano, ledger, domínio, adapter, CI ou infraestrutura Railway.

## Fonte de verdade e baseline verificados

- Repositório: `faabio3131/kordena-fiscal-engine-v2`; branch canônica `main`.
- HEAD de entrada: `d90f6f91ba7b86b6b66ff0160ba34a5a1d47e06f` (PR #164 MERGED).
- GitHub CI `#786` (run `38156539236`) e NFCore Plan Governance `#207` (run `38156539243`): `completed/success`, exact SHA de entrada.
- Zero PRs abertas na consulta de entrada. 27/59 tarefas concluídas **internamente**; primeira pendência `NFV1-P05-T01`. Externo continua não certificado.
- Autorizações de política: `docs/NFV1_P06_T01_SECRET_PROVIDER_POLICY_PROPOSAL_2026-10-09.md`, seleção GSM aprovada em 2026-10-09. Execução solicitada pelo dono em 2026-10-11 para retomar CURRENT e configuração governada do GSM staging.

## CURRENT → TARGET e escopo executado

**CURRENT anterior:** projeto `fm-nfcore-staging` criado, mas integração GSM/IAM/canal operacional não verificada. 

**TARGET desta intervenção limitada:** verificar identidade de projeto/faturamento, habilitar somente a API oficial do GSM, criar duas identidades de workload separadas sem gerar chaves ou grants de acesso e obter recibos reproduzíveis. Não criar versão de segredo, conceder IAM, ativar aplicação, SQL, deploy ou certificação indevida.

## Evidência externa (Google Cloud CLI na estação autorizada)

Projeto `fm-nfcore-staging`:
- Project number `672015004427`, lifecycle `ACTIVE`.
- Billing vinculado e habilitado: `billingAccounts/016B57-5C2987-E32800` (`billingEnabled: true`). Orçamento conhecido da conta: R$ 30 mensal com alertas, compartilhado entre projetos. **Orçamento exclusivo NFCore ainda não certificado**; alerta não impõe bloqueio de gastos.
- `secretmanager.googleapis.com`: inicialmente desabilitada; habilitação aprovada pela interação em 2026-10-11 e concluída com operação `operations/acat.p2-672015004427-0c8029b9-30a6-4272-8161-a1d179b57050`. Nova leitura de `gcloud services list --enabled` devolveu `state: ENABLED` no projeto/número exatos.
- `gcloud secrets list --project=fm-nfcore-staging --format=json` retornou `[]`: **nenhum recurso Secret criado**.
- Listagem anterior de service accounts: `[]`.
- Criadas separadamente:
  - API: `nfcore-stg-api@fm-nfcore-staging.iam.gserviceaccount.com`;
  - Worker: `nfcore-stg-worker@fm-nfcore-staging.iam.gserviceaccount.com`.
- `gcloud iam service-accounts list` retornou ambas ativas (`disabled: false`).
- `gcloud iam service-accounts keys list --managed-by=user` retornou `[]` para **ambas**.
- **Não foram geradas nem consultadas chaves privadas**, concedidas roles de acesso a Secrets, criados secrets/versions, exportados bytes, alteradas variáveis do Railway, feitos deploys, SQL, migrations, backup/restore ou emissão fiscal.
- A habilitação da API e criação de service accounts **não certificam custo futuro zero**, disponibilidade, IAM efetivo ou acesso a segredo.

## Gate externo aberto / riscos

`P6-T01-B02`: **PARCIALMENTE AVANÇADO, NÃO RESOLVIDO**. Confirmados projeto, faturamento habilitado, API GSM e duas identidades segregadas. Pendentes:
1. Orçamento/alertas com escopo do projeto e impacto financeiro aprovado; não tratar orçamento como hard cap.
2. Prova de identidade do runtime Railway: priorizar WIF somente após confirmar emissor OIDC/X.509 do processo. Exceção de chave service account de staging depende de aprovação operacional explícita, canal protegido e rotação <=30 dias; **não criar chave por conveniência**.
3. Recursos/versões de secrets sintéticos autorizados, allowlist exata por workload, IAM `roles/secretmanager.secretAccessor` **no recurso exato**, sem grant de projeto, browser ou controle de escrita ao runtime.
4. Audit Logs Data Access realmente emitidos/retidos em destino separado, recovery/delayed destruction e testes reais `ALLOW` de workload autorizado e `DENY` de workload/escopo não autorizado, sem material secreto em logs.
5. Bootstrap canônico API/Worker ligado aos bindings reais/versões pinadas, sem segundo control plane nem handler/tenant implícito; Worker `0/1` e staging drift históricos exigem nova prova operacional.
6. Backups/restore PG18 reais, migrations/read-only/schema, SHA reconciliado e rollout somente após autorização e gates de `P05-T01`.

## Decisões e estado

- `EXTERNAL_SECRET_BACKEND_CERTIFIED=NOT MET`
- `NFV1-P05-T01=[ ] BLOCKED_EXTERNAL`
- `STAGING_CURRENT_SHA_E2E_CERTIFIED=NOT MET`
- `PRODUCTION_APPROVED=NO`
- `COMMERCIAL_LIVE=NO`
- 27/59 internas inalteradas. Não avançar `P05-T02`.

## Próxima ação exata

Inspecionar IAM e canal de identidade Railway sem leitura de credenciais, estabelecer orçamento exclusivo de staging, revisar allowlist de recursos de teste, obter aprovação operacional específica para estratégia WIF ou chave temporária protegida e somente então certificar leitura/negação GSM real. Qualquer PR de documentação deste checkpoint exige CI/governança antes de merge separado; nenhum merge automático.
