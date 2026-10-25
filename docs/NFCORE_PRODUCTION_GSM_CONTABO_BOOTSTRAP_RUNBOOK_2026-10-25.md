# NFCore — composição GSM de produção na Contabo (runbook)

**Estado:** contrato interno; nenhum acesso ao Google Cloud ou ao servidor novo foi executado. Produção fiscal: BLOCKED_EXTERNAL.
**Base:** main@476e97b79202e45369156144f9c4e10fe9dd478e. Destino futuro vmi3692211, **não** vmi3683268.
**Release:** SHA da branch protegida production, atualizado exclusivamente por PR aprovado. Esta PR não faz merge ou deploy.

## Current → Target

- Staging continua em scoped-staging-sa-v1, projeto/contas/piloto fixos; código e runbook P05 permanecem intactos.
- Production recebe scoped-production-sa-v1 e duas contas: nfcore-api e nfcore-worker, com e-mails independentes, secret references, resources e cloud versions distintas. Projeto parametrizado mas sujeito a NFCORE_GSM_ALLOWED_PROJECTS, com validação de project ID e número canônico.
- Nenhuma identidade ou escopo vem da requisição HTTP/outbox. Falhas em IAM, arquivo de identidade, GSM CRC, envelope, tenant/unidade ou binding mantêm o Worker parado. Apenas claims restritas ao escopo e à operação deliver_webhook; fiscal environment fica HOMOLOGATION até aprovação de produção fiscal em outra fase.

## Escolha de credencial

| Modalidade | Avaliação | Situação |
| --- | --- | --- |
| Chave service account eterna | risco persistente de vazamento e impossibilidade de limitar exposição | NÃO RECOMENDADA |
| Uma chave exclusiva por API/Worker com rotação planejada | funciona fora do GCP; depende de arquivo privado, IAM mínimo e reconciliação frequente | bootstrap production implementado |
| Workload Identity Federation (WIF) | melhor segurança, sem chave persistente; exige IdP externo OIDC/SAML/X.509 confiável, issuer/audience/subject e refresh | TARGET PREFERENCIAL, não ativado |

**Recomendação:** WIF como destino ideal depois de comprovar um IdP legítimo para a identidade contínua do processo na Contabo. OIDC de GitHub Actions sozinho **não** atesta o Worker persistente na VPS. Sem IdP atestado disponível, usar no primeiro deploy contas SA distintas, chave nova emitida uma vez para o ambiente produtivo, **não eterna**: rotação antes de 90 dias, revogação da antiga após troca testada, logs IAM e fail-closed da validade. O código recusa janela de bootstrap maior que 90 dias ou vencida, mas metadata não comprova o estado IAM. Expirar automaticamente a chave produtiva no Google não substitui operação preventiva de rotação e pode causar indisponibilidade.

## Passos humanos do Fábio no Google Cloud (não executados)

1. Acessar Google Cloud Console como proprietário. Criar ou escolher projeto **exclusivo de produção**, distinto de fm-nfcore-staging; confirmar project ID, project number, billing, alertas e ativação da Secret Manager API. Não reutilizar qualquer segredo do piloto.
2. Criar duas contas de serviço separadas dentro do projeto: nfcore-api e nfcore-worker. Não conceder Owner/Editor ou secretmanager.admin. Uma conta não deve poder obter tokens da outra.
3. Criar dois recursos Secret Manager com finalidade assinada e escopo explícito (Worker assina, API verifica). Restringir roles/secretmanager.secretAccessor **no recurso exato** à respectiva conta e exigir aprovação humana para gerenciar versões ou alterar IAM. Habilitar Cloud Audit Logs Data Access, monitorar acessos negados e mudanças em IAM.
4. Provisionar material de assinatura **da aplicação** em cada segredo via envelope canônico encode_gsm_envelope(binding, material) com SecretBinding de runtime_environment=production, workload_id nfcore-worker ou nfcore-api, tenant, unit, canonical version e cloud version numérica. Garantir mesmo contrato de chave e referência quando a API precisar verificar assinatura do Worker; não assumir que duas chaves diferentes são intercambiáveis. Jamais copiar envelope do Railway.
5. Para bootstrap SA, **somente se política IAM permitir** criar uma chave de conta de serviço por workload. Instalar cada JSON fora de chat, e-mail, GitHub e logs, via canal privado do operador, no servidor **novo**. Montar arquivos 0600 read-only, com UID exclusivo de cada container, sem exposição em variáveis de ambiente, sem GOOGLE_APPLICATION_CREDENTIALS nem defaults/ADC. Registrar private_key_id e created-at diretamente do IAM e agendar rotação antes de 90 dias. Se IAM bloquear criação, não contornar.
6. Alternativa WIF futura: providenciar emissor OIDC/SAML/X.509 independente verificável para a VPS; configurar workload identity pool/provider, conditions que vinculam audience, issuer e subject a workload único, grants restritos e teste negativo anti-spoofing. Abrir PR separada para modo federado, nunca interpretar JSON federado como chave SA do modo atual.
7. Revisar negações cruzadas API/Worker e staging/production. Registrar somente IDs, política, metadados e eventos de auditoria, **nunca bytes dos segredos**. Nenhuma ação deste documento foi executada.

## Bootstrap do PostgreSQL novo e vazio (quando autorizado em etapa posterior)

1. NÃO transportar tabela secret_bindings do Railway. Instalar schema via migrations canônicas **somente após autorização específica**; banco novo, identidade e credenciais distintas. Não ligar Worker.
2. Fornecer à API os metadados de ambas as funções (tabela abaixo), sem ativar NFCORE_API_GSM_MODE. Habilitar temporariamente NFCORE_PRODUCTION_GSM_BINDINGS_MODE=platform-admin-v1.
3. Iniciar API com perfil production e secret_backend external. **Dependência de banco vazio:** primeiro criar a identidade humana por jornada canônica real/autorizada (nunca copiando staging). Conceder platform-admin somente mediante aprovação específica usando o script existente scripts/admin/set_platform_admin.py e seu gate NFCORE_PLATFORM_ADMIN_CHANGE_APPROVED. Não usar esse script sem autorização e não inventar usuário administrativo. Login com usuário individual habilitado e plataforma-admin na autenticação **canônica**, sessão cookie e CSRF. Fazer POST **sem body** para /internal/production/gsm-bindings via origem administrativa protegida. A rota aceita metadata exclusiva da configuração server-side, valida duas referências e usa SecretBindingAdministration.put com optimistic revision 0 e auditoria SECRET_REFERENCE_BOUND, ator/correlation-id. Referência duplicada diverge com 409; replay exato é idempotente.
4. Ler apenas metadata/auditoria pelo mecanismo administrativo: duas linhas independentes em fm_secret_bindings, runtime_environment production e workloads distintos. Não persistir material de segredo. Se registro foi parcialmente concluído, repetir comando autenticado é seguro; não editar SQL manualmente.
5. Retirar NFCORE_PRODUCTION_GSM_BINDINGS_MODE e confirmar que a rota não registra nada quando desabilitada. Somente após IAM/envelopes autorizados habilitar NFCORE_API_GSM_MODE= scoped-production-sa-v1 com credencial de API; a leitura real deve concluir antes da API informar prontidão. Depois habilitar Worker GSM; missing/bad binding ou segredo impede readiness contínuo.
6. Mudança futura de binding/version é uma operação humana governada: não fazer UPDATE SQL nem rotação automática, preservar auditoria. Não habilitar fiscal production.

## Variáveis NFCORE_* necessárias / opcionais por serviço

Itens marcados **base** são requeridos pelo contrato do serviço; **condicional** depende da funcionalidade habilitada. Os nomes e finalidades são públicos; **valores não são fornecidos aqui**.

| Variável | Serviço | Finalidade / condição |
| --- | --- | --- |
| NFCORE_ENVIRONMENT | API/Worker | base: perfil production |
| NFCORE_PERSISTENCE_BACKEND | API/Worker | base: backend postgres |
| NFCORE_SECRET_BACKEND | API/Worker | base: backend external |
| NFCORE_REQUIRE_HTTPS | API/Worker | base: transporte HTTPS |
| NFCORE_PUBLIC_HOSTNAME | API/Worker | base: hostname HTTP autorizado |
| NFCORE_ALLOWED_ORIGINS | API | CORS do Portal, sem wildcard |
| NFCORE_TRUSTED_HOSTS | API | hosts de proxy declarados |
| NFCORE_TRUSTED_PROXY_CIDRS | API | proxy de borda, sem rede global |
| NFCORE_PASSWORD_RESET_TTL_MINUTES | API | TTL de recuperação, condicional |
| NFCORE_COMMERCIAL_CHECKOUT_PROVIDER | API | checkout cadastrado, só depois de aprovação do canal |
| NFCORE_PUBLIC_TRIAL_ALLOWED_ORIGINS | API | canal público trial, condicional |
| NFCORE_SITE_TRIAL_CHANNEL_READY | API | readiness governada do canal externo, condicional |
| NFCORE_ACTIVATION_EMAIL_PROVIDER | API | integração email, condicional |
| NFCORE_ACTIVATION_EMAIL_API_KEY | API | credencial email, armazenar fora do Git, condicional |
| NFCORE_ACTIVATION_EMAIL_SENDER | API | remetente aprovado, condicional |
| NFCORE_ACTIVATION_BASE_URL | API | URL de ativação, condicional |
| NFCORE_ACTIVATION_EMAIL_TIMEOUT_SECONDS | API | timeout, condicional |
| NFCORE_WORKER_ONESHOT | Worker | ausente/falso no processo contínuo; true apenas probe CI |
| NFCORE_GSM_PROJECT_ID | API/Worker | base GSM: project ID produção |
| NFCORE_GSM_PROJECT_NUMBER | API/Worker | base GSM: número Google do projeto |
| NFCORE_GSM_ALLOWED_PROJECTS | API/Worker | base GSM: allowlist exata de projetos |
| NFCORE_GSM_API_SERVICE_ACCOUNT | API/Worker | base GSM: e-mail SA API |
| NFCORE_GSM_WORKER_SERVICE_ACCOUNT | API/Worker | base GSM: e-mail SA Worker, diferente |
| NFCORE_PRODUCTION_GSM_BINDINGS_MODE | API | bootstrap temporário platform-admin-v1, remover depois |
| NFCORE_PLATFORM_ADMIN_CHANGE_APPROVED | operação administrativa pontual | aprovação explícita para promover conta existente a plataforma-admin; não manter permanente |
| NFCORE_API_GSM_MODE | API | modo scoped-production-sa-v1, opcional até bootstrap completo |
| NFCORE_API_GSM_TENANT_ID | API | escopo da API, obrigatório no bootstrap |
| NFCORE_API_GSM_UNIT_ID | API | unidade exata, sem asterisco |
| NFCORE_API_GSM_SIGNING_REFERENCE | API | referência imutável de assinatura |
| NFCORE_API_GSM_SIGNING_VERSION | API | versão interna da referência |
| NFCORE_API_GSM_PROVIDER_ID | API | provider da assinatura |
| NFCORE_API_GSM_RESOURCE | API | resource GSM allowlisted |
| NFCORE_API_GSM_CLOUD_VERSION | API | versão cloud numérica fixa |
| NFCORE_API_GSM_CREDENTIAL_FILE | API | mount privado SA, se modo ligado |
| NFCORE_API_GSM_KEY_ID | API | private_key_id de IAM, se modo ligado |
| NFCORE_API_GSM_KEY_CREATED_AT | API | metadata IAM de criação |
| NFCORE_API_GSM_KEY_NOT_AFTER | API | prazo do bootstrap <=90 dias |
| NFCORE_WORKER_GSM_MODE | Worker | modo scoped-production-sa-v1, obrigatório |
| NFCORE_WORKER_GSM_TENANT_ID | Worker | tenant da claim de webhook |
| NFCORE_WORKER_GSM_UNIT_ID | Worker | unidade explícita |
| NFCORE_WORKER_GSM_SIGNING_REFERENCE | Worker | referência de assinatura |
| NFCORE_WORKER_GSM_SIGNING_VERSION | Worker | versão interna imutável |
| NFCORE_WORKER_GSM_PROVIDER_ID | Worker | provider assinado |
| NFCORE_WORKER_GSM_RESOURCE | Worker | segredo GSM allowlisted |
| NFCORE_WORKER_GSM_CLOUD_VERSION | Worker | versão fixa do GSM |
| NFCORE_WORKER_GSM_CREDENTIAL_FILE | Worker | mount privado SA Worker |
| NFCORE_WORKER_GSM_KEY_ID | Worker | private_key_id verificado |
| NFCORE_WORKER_GSM_KEY_CREATED_AT | Worker | metadata IAM de criação |
| NFCORE_WORKER_GSM_KEY_NOT_AFTER | Worker | prazo do bootstrap <=90 dias |
| NFCORE_WORKER_GSM_HOST_NAMESPACE | Worker | namespace canônico da claim |
| NFCORE_WORKER_GSM_DESTINATION_ID | Worker | destino aprovado do webhook |

**Também necessários, fora de NFCORE_**: DATABASE_URL da API e Worker (PostgreSQL canônico, fora do Git), PORT da API; configurações do build do Portal existentes. Portal não recebe credenciais GSM nem DATABASE_URL. NFCORE_DEV_* e NFCORE_STAGING_* são próprios de outros ambientes. Não ativar NFCORE_API_GSM_CREDENTIAL_JSON nem NFCORE_WORKER_GSM_CREDENTIAL_JSON em produção. Não inserir materiais de chave em Git ou ENV. Não confundir registros de health com comercial/fiscal pronto.

## Gates e riscos residuais

- CI, Ruff, Mypy, unit/integration e governança no SHA exato; staging regressions permanecem verdes; não alterar main/production nesta PR.
- Próxima fase: validar IdP ou rotação de SA, Google Cloud IAM, Cloud Audit Logs, API/Worker tenant/unit scope, metadata, assinatura, Secret Manager envelope, volume privado e revogação. Sem operação Google Cloud nesta PR.
- Backend Contabo requer defesa da VPS, isolamento Docker, filesystem/backup externo cifrado, monitoramento de chave/rotina de rotação e recovery. Carga/HA/backup não são certificados por esta PR.
- Não registrar bindings durante migration, não fazer deploy, DNS ou cutover sem autorização separada. Google Cloud e server vmi3692211 continuam não configurados por esta PR.
- CI sintética não comprova secret real acessível, homologação fiscal (BLOCKED_EXTERNAL), produção de emissão ou readiness comercial. Não promover PRODUCTION_APPROVED sem gates externos/humanos.

**Fontes:** Google Cloud Workload Identity Federation (IAM docs), Service Account Key Rotation e Best Practices; contratos canônicos da repository security/secret_binding.py, runtime/secret_manager.py e vault/google_secret_manager.py.
