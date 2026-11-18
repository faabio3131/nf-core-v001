# NFCore × Bling — Fechamento interno, gates separados e plano 19 → 21

**Data:** 2026-11-10 (BRT)  
**Classificação:** plano de implantação governada / evidência parcial, **não é certificado de produção ou homologação**.  
**CURRENT:** main `545b7606208eedf77b3fd6b852ccb82b4716f6b8` antes desta PR, production `61015a837be8b2e5e3b0f1cdb5fb14c5c875fb91`. Esses SHAs são checkpoints históricos: consultar GitHub novamente antes de executar.
**Servidor:** Contabo vmi3692211; checkout `/opt/fm/nfcore/src`.

## 1. Diagnóstico baseado na auditoria autenticada

GitHub Actions run [#42941524225](https://github.com/faabio3131/nf-core-v001/actions/runs/42941524225) executou a auditoria read-only via chave SSH exclusiva e comando forçado, com `production` pinada:

| Gate | Observação | Classificação |
|---|---|---|
| SSH GitHub Actions → Contabo | comando remoto executado; resposta sanitizada autenticada | **PASS** do canal |
| .deployed / log / container API, Portal, DB / readiness / backup checksum | todos PASS | **PASS** baseline local |
| `SCHEMA_PRODUCTION_GUARD` | PASS no schema 19 com Bling desligado | **PASS** do baseline, não de Bling |
| `BLING_SCHEMA_20_21` | PENDING, esquema 1..19 | **BLOQUEIO DE ATIVAÇÃO** |
| `BLING_API_FLAG`, `BLING_SECRET_MOUNTS` | PENDING | **BLOQUEIO EXTERNO/CONFIGURAÇÃO** |
| `BLING_POLICY_MOUNT`, `BLING_POLICY_ARTIFACTS` | PENDING | **BLOQUEIO DE CONFIGURAÇÃO/CLIENTE** |
| `BLING_WORKER_RUNNING` | PENDING | **BLOQUEIO DE ATIVAÇÃO CONTROLADA** |
| OAuth real, pedido real e SEFAZ/A1 | UNVERIFIED_EXTERNAL | **NÃO HOMOLOGADO** |

**Não repetir geração de chave nem cadastro de Secrets:** os quatro Secrets e a conexão SSH já foram validados pela execução. A falha da run é **Bling não ativo**, não erro do Plano B.

## 2. Matriz interna x externa — sem cliente cadastrado

| Item | Construção interna | Exigência operacional/externa |
|---|---|---|
| Migrações 20 e 21 | Implementadas e exercitadas no CI em banco isolado; plano de produção read-only desta PR | Aplicação DDL somente por operador autorizado, após backup/restauração ensaiada |
| API OAuth multiempresa | Mesmo `nfcore-api`, RBAC, CSRF, bindings e armazenamento criptografado | Registrar aplicativo Bling e prover Client ID/Secret/scopes reais |
| Worker multiinstalação | Código `bling-multi` e Compose opt-in sem serviço paralelo | Provisionar credenciais e iniciar somente após gates/autorização |
| Política fiscal escopada | Preparador e armazenamento por instalação; testes negativos | Política tributária aprovada da unidade/contador; A1 quando emissão exigir |
| Web/Portal | Painel de operações e rotas governadas | OAuth real, status IDs específicos daquela conta |
| Emissão NF-e homologação | Preparação, assinatura/XSD sintética e outbox testáveis sem cliente | Certificado A1, credenciais oficiais, endpoints e evidência da resposta real |

**Nunca introduzir instalação fictícia, certificado de teste ou tokens sintéticos na produção apenas para deixar um gate verde.** O objetivo interno é produto configurável e testado, não simular estabelecimentos reais.

## 3. Ordem técnica de promoção futura (NÃO EXECUTAR AUTOMATICAMENTE)

### Etapa I — certificar esta PR na main

- Lint, Mypy, Pytest, PostgreSQL isolado, CI completa, front Web, Docker e teste dos overlays.
- Teste `deploy/contabo/test-bling-worker-opt-in.sh`: verifica que o worker não entra no Compose base, não publica portas, só inicia mediante perfil autorizado, não tem root/capabilities, usa DB canônico e falha sem arquivo de configuração ou secrets.
- Teste `tests/runtime/test_bling_production_migration_plan.py`: rejeita migrado parcial 20, lacunas, Cakto divergente, ambiente errado e ausência de DB; permite somente 1..19 ou 1..21, sem gravar.
- Auditoria no GitHub separa prova de SSH/baseline do gate Bling: **um step verde não transforma o worker/integração PENDING em PASS**.
- Antes de merge, conferir status e policy da branch protegida e autorização específica.

### Etapa II — release de código na production (sujeita a autorização)

- Reconciliar `main`, `production`, PR de release #420, CI, impactos e gatilhos de deploy.
- Construir release que mantenha Bling **desativado**. O guard existente aceita **exatamente schema 19 ou 21** quando opt-in desligado, para evitar bloqueio no intervalo de migração. Schema parcial 20 nunca é permitido para code-only deploy.
- Verificar deploy em runtime real `.deployed`, log, health, plano de rollback e integridade do backup. Não presumir que merge da main implica publicação.

### Etapa III — migrations 20/21 governadas (sujeita a OUTRA autorização)

1. Fazer inventário de banco/schema e confirmar migrações 1..19, Cakto atual, sem alterações concorrentes.
2. Garantir backup verificado e **ensaio de restore em banco isolado**, com janela e lock do cron para não concorrer com deploy. Não executar DDL no caminho automático.
3. Rodar **somente leitura** o planejador com o código recém-promovido, no ambiente real autorizado:

   ```bash
   python scripts/ci/migration_guard.py --plan-production-bling
   ```

   Exige `NFCORE_ENVIRONMENT=production`, `DATABASE_URL` injetados pelo runtime autorizado. A saída esperada no baseline é `pending=20,21`; schema parcial, Cakto desatualizado ou tabela ausente bloqueiam. **Não digitar DATABASE_URL ou senha em logs, CLI ou chat.**
4. Somente após aprovação humana explícita e preflight PASS usar a autoridade **existente** `scripts/ci/migration_guard.py --apply`, em job governado com `NFCORE_BLING_INSTALLATIONS_ENABLED=true`, `NFCORE_SCHEMA_MIGRATION_APPROVED=true`, `NFCORE_PRODUCTION_APPROVAL=PRODUCTION_APPROVED` e o mesmo banco de produção. O comando aplica via migrações canônicas **20 e 21** e retorna versões efetivas; nunca inventar ferramenta DDL alternativa.
5. Reexecutar `--plan-production-bling`: `pending=NONE` e schema 1..21. Conferir SQL catalog/índices e integridade. Não realizar rollback destrutivo do schema; em falha, parar, investigar e seguir runbook de recuperação aprovado.

**Perigo:** o `--apply` canônico deve ser executado apenas com as flags e aprovação corretas. Com Bling desligado o mesmo comando pode não aplicar 20/21. Nunca executar em container de aplicação durante startup ou por cron.

### Etapa IV — API e worker Bling

- Sem cliente, **não** ativar OAuth nem usar credenciais falsas. Completar provisionamento operacional dos diretórios host-owned fora do Git (segredos e políticas fiscais por tenant), com UID 10001 e mounts read-only, conforme [runbook](bling-operational-activation-contabo.md).
- Após registro real de aplicação Bling e obtenção segura de ID/Secret/scopes, ensaiar Compose, habilitar somente o overlay API governado no **mesmo** serviço; confirmar `nfcore-api` e Portal saudáveis.
- Em momento separado e autorizado, habilitar perfil `bling-worker-authorized`, com A1 e rotinas fiscais bloqueadas até configuração externa. Confirmar health, idempotência, nenhuma operação antes da aprovação humana e nenhuma conexão cruzada entre unidades.
- O worker permanece opt-in e sem reinício automático até decisão operacional. Nenhum comando desta PR inicia worker nem altera flag em produção.
- Políticas fiscais de clientes reais não devem ser colocadas no Git ou replicadas entre instalações. Diretório vazio corresponde a instalação aguardando onboarding, **não** a deficiência de algoritmo.

### Etapa V — homologação e Go/No-Go

- Contabilidade cadastra estabelecimento e valida vínculo fiscal da unidade, inscrição, políticas fiscais e A1 real.
- Usuário autorizado realiza OAuth no Bling, mapeia IDs de status por instalação e configura webhooks.
- Testa pedidos de venda de homologação, envio autorizado, retorno de status, recuperação e falhas de rede; audit trail sem tokens/CPF/CNPJ brutos.
- Obter respostas oficiais do Bling/SEFAZ quando necessárias e manter resultados separados da prontidão interna.
- Somente então certificar operacional/comercialmente aquele escopo/cliente. Nenhuma transferência automática de autorização entre tenants.

## 4. Matriz de aceitação — zero clientes

| Gate | Resultado aceitável sem clientes |
|---|---|
| Código, CI e testes de migração 20/21 em banco isolado | PASS com logs e SHAs |
| Código, UI, testes do Worker e Compose opt-in | PASS com mocks e fixtures isoladas, sem produção |
| GitHub Actions SSH, host e backups | PASS de canal/baseline com prova remota |
| Banco Bling 20/21 no host real | PENDING até aprovação e aplicação real |
| OAuth, policies de empresa e Worker operacional | PENDING até configuração real |
| NF-e oficial com A1 / Bling conta externa | EXTERNAL_UNVERIFIED até teste autorizado |

## 5. Riscos e pendências

- PR #420 é uma candidata de release contra `production`, mas seu HEAD era anterior ao merge #421. Não usá-la sem reconciliar a branch e os gates.
- O script de auditoria instalado no host é root-owned e pinado por digest. **Não alterar o script remoto nesta PR**; qualquer atualização dele exige instalação explícita e revisão da cadeia de privilégio.
- Certificação de CI deve ser realizada no HEAD exato; atualizações depois de testes exigem nova verificação.
- O resultado `BLING_OPERATIONAL_NO_GO_PENDING_MIGRATIONS_OAUTH_POLICY_WORKER` é intencional e deve permanecer vermelho até existir operação real válida.
