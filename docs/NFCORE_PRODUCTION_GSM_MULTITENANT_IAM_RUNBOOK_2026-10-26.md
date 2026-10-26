# NFCore production — GSM multi-tenant e privilégio mínimo

Status: PR interna; NÃO executado em Contabo vmi3692211 nem Google Cloud. Não altera PR #241, main, production, P05/staging nem homologa fiscal (BLOCKED_EXTERNAL).

## Current → Target

Current: scoped-production-sa-v1 aponta a tenant/unit/destination estáticos no ambiente.
Target opt-in: multi-tenant-production-sa-v1 sobre **a mesma** API, PostgreSQL, outbox, Worker, SecretBindingAdministration e política egress. Sem .env por cliente, sem chave IAM por cliente, sem reiniciar processo por onboarding. Todas as claims usam OutboxClaimSelection exato; wildcard continua proibido.

## IAM: permissões precisas, com resource e principal

| Identidade | Acesso concedido | Escopo IAM | Proibido |
| --- | --- | --- | --- |
| nfcore-api SA | nenhum acesso GSM **necessário** para a API administrativa de bindings: somente atualiza metadata sob sessão humana platform_admin/CSRF no PostgreSQL. Se o probe de API for habilitado, roles/secretmanager.secretAccessor **somente** no segredo próprio de verificação da API | recurso específico API no projeto de produção | nenhuma permissão secretmanager.secrets.create, secretmanager.versions.add/destroy, secretmanager.secrets.update, setIamPolicy, IAM.serviceAccounts.createKey, roles/owner, roles/editor, projeto inteiro como secretAccessor |
| nfcore-worker SA | roles/secretmanager.secretAccessor (permissões exatas: secretmanager.versions.access, resourcemanager.projects.get e resourcemanager.projects.list; **não** inclui secretmanager.versions.get) | **cada** segredo explicitamente aprovado daquele cliente no projeto GCP production. Não conceder projeto inteiro, pastas ou organização; a lista de grants cresce por segredo, não por chave IAM | nenhuma permissão de criar/alterar/apagar segredo, versão, IAM, billing ou outras contas de serviço |
| Operador humano FM designado | permissões administrativas necessárias no Google para criar recurso e versão, configurar IAM do recurso, após aprovação humana de cada tenant | GCP production separado, MFA/logs; segregação de funções recomendada | nenhuma conta API/Worker recebe as permissões do operador |
| Cliente tenant | nenhum acesso IAM à infraestrutura da FM por padrão | n/a | nunca criar credencial JSON de serviço por cliente |

O role gerenciado roles/secretmanager.secretAccessor é concedido **no secret**, não no project. O acesso de leitura do Worker é limitado tanto pelo IAM do Google quanto pelo metadata canônico, allowlist do projeto, SecretBinding rev/bind/tenant/unit/purpose/versão exata, CRC e envelope assinado por metadados. A API não faz chamada de criação/update no Secret Manager.

**Quem cria o segredo de novo cliente?** O operador humano FM de infraestrutura aprovado, no Google Cloud Console (ou fluxo futuro de aprovações humanas com automação de IAM restrita, em mudança separada). A API faz APENAS o registro de metadata autorizado depois que o humano criou o recurso e concedeu à identidade fixa do Worker secretAccessor **naquele recurso**. Não é exigida nova key service account, nenhum arquivo JSON novo ou .env/restart por cliente. A chave de conta de serviço da plataforma segue rotação governada existente; ideal futuro WIF com IdP atestado fora do GCP.

## Bootstrap humano de cada novo tenant (quando aprovado)

1. A contratação/trial governa o tenant e a conta OWNER por serviços canônicos; a unidade é cadastrada no Control Plane (não cria unidade pela simples declaração de uma API pública).
2. FM revisa a unidade, finalidade do webhook, destino HTTPS, aprovação de egress e a regra de fiscal HOMOLOGATION. Nenhuma operação fiscal real é ativada.
3. Operador FM cria o segredo para o tenant/unidade no **projeto de produção allowlisted** e sua versão pinada, formato encode_gsm_envelope(binding, material), sem imprimir a chave HMAC. Não confundir material da assinatura com a chave IAM. Operador FM concede secretAccessor sobre este segredo à service account única nfcore-worker; jamais a API acesso amplo.
4. Admin humano com platform_admin autentica na API (sessão assinada e CSRF), habilita a **capacidade administrativa da plataforma** NFCORE_PRODUCTION_GSM_TENANT_ADMIN=platform-admin-v1 se aprovada para onboarding, e envia POST /internal/production/gsm-tenant-bindings com metadata SecretBinding exata, expected_revision 0, sem material secreto. Este gate pertence à plataforma, não varia por cliente.
5. API valida produção, projeto, papel Worker, unidade homologation cadastrada, identidade/scope/ref/versão; grava por SecretBindingAdministration.put com optimistic revision e auditoria SECRET_REFERENCE_BOUND. No ciclo seguinte, o Worker descobre a unidade, e somente seleciona jobs pelo escopo exato. A egress policy revalida aprovação, DNS e destino antes da transmissão.
6. Para revogar, admin envia mesma identidade/reference com state revoked e revisão incrementada, preservando metadata imutável. Na próxima descoberta, escopo desaparece; trabalho já em processamento reconsulta durable binding durante assinatura e não recebe material após revogação. IAM do Google deve também ser revogado pelo operador FM como defesa em profundidade. O processamento de outro tenant não para.
7. Rotação exige nova versão de GSM e metadata correspondente, aprovação humana; para uma segunda referência ativa da mesma unidade a descoberta nega ambiguidades. Planejar swap sem janela de duas chaves concorrentes, e verificar assinatura/remessa de cada cliente em E2E controlado.

## Controles de disponibilidade e limites

- Uma única instância de processo Worker; composição cria ciclos independentes por tenant com o DurableFiscalOutboxWorker canônico, lease, retry, idempotência e delivery audit.
- Justiça: uma claim por tenant por round-robin, até limite de 4096 unidades; não processar em produção fiscal real. Tenant novo entra no poll seguinte, tenant revogado sai no poll seguinte.
- Uma unidade com duas referências ativas ou múltiplos destinos ativos é negada, sem fallback arbitrário; as demais unidades permanecem elegíveis.
- Se a infraestrutura IAM falha, Secret Manager nega a operação; nunca entra fallback de chave local, ADC ou outro tenant. A saúde externa do GSM requer verificações operacionais reais.
- Projeto GCP production e identidades API/Worker permanecem únicos por workload; múltiplos tenants não implicam ampliação de permissões da API.
- Não aplicar deploy, migrations, segredo ou alteração em Cloud/servidor nesta PR. Não promover branch production nem declarar lançamento/homologação.

## Primeira conta da plataforma — trabalho já entregue em PR separada

PR #241: https://github.com/faabio3131/nf-core-v001/pull/241
HEAD anteriormente certificado 283fe8788e2ba49aff636080c4cffcff52d6ad4e. Bootstrap produção com NFCORE_ENVIRONMENT=production, NFCORE_PRODUCTION_APPROVAL=PRODUCTION_APPROVED, gate próprio, identidade FM OWNER + elevação platform_admin auditada, PasswordRecoveryService e Brevo para definir senha via link, recusa reexecução. Não duplicar neste código nem rodar o comando.

Depois de aprovação/promover futuramente a PR #241, operador humano executa o bootstrap uma vez; platform_admin publica catálogo versionado por /v1/admin/pricing; primeiro cliente real nasce de aquisição S2S ou trial governado, e unidade é registrada pelo Control Plane. O trial **pode continuar fechado** enquanto NFCORE_SITE_TRIAL_CHANNEL_READY não estiver habilitado e política de origem não aprovada. Fiscal real permanece BLOCKED_EXTERNAL.

## Riscos residuais

- A criação do recurso no Google continua ação humana: o cadastro do cliente não depende de deploy/restart nem IAM key nova, mas depende de autorização do segredo. Automação futura requer aprovação e desenho IAM próprios.
- O poll compartilha um processo; uma unidade lenta pode elevar latência de outras, apesar de batch size 1; avaliar pool/limites sem segunda autoridade de queue.
- Rotação e atomicidade Google Cloud vs PostgreSQL não são distribuídas; plano operacional precisa reconciliar versões, mudanças de binding e grants IAM.
- Concessão equivocada de secretAccessor no projeto inteiro aumentaria blast radius; essa configuração é explicitamente NÃO autorizada.
- CI sintética não confirma IAM real, E2E no servidor, DNS, segredo real, execução de webhook em produção nem homologação fiscal.
