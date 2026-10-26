# NFCore V1 — bootstrap da primeira conta platform_admin em production

Estado: construção interna em PR. NÃO EXECUTADO na Contabo vmi3692211 nem no Google Cloud. Homologação fiscal BLOCKED_EXTERNAL.

## Diagnóstico

O portal não possui signup, o catálogo exige platform_admin e os canais de aquisição/trial exigem política comercial, catálogo e confiança de origem. O PostgreSQL com somente 18 migrations não tem uma identidade de plataforma. A CLI interna de bootstrap é uma exceção governada para o **primeiro humano da FM**, não para cadastro de clientes e nem endpoint web.

## Operação construída

- Script de uso único: scripts/admin/bootstrap_production_platform_admin.py, sem argumento de senha, sem acesso HTTP anônimo.
- Reusa CommercialCustomerProvisioningService para organização da FM + conta OWNER, PasswordRecoveryService para token de ativação one-time, e o adaptador Brevo canônico para envio do link.
- A promoção da conta criada para platform_admin e o evento HUMAN_ACCOUNT_UPDATED com ator production-bootstrap/correlação production-first-platform-admin são atômicos no adapter PostgreSQL canônico. Um lock PostgreSQL exclusivo protege a sequência de provisionamento e promoção de execuções simultâneas.
- Falha fechada se existe qualquer outro humano ou platform_admin; permite retomar somente a mesma conta OWNER de operação parcialmente concluída, antes de existir platform_admin. Depois do primeiro sucesso, toda reexecução é rejeitada sem qualquer outra promoção ou envio.
- Nenhuma nova tabela, persistência, autoridade de usuários, autenticação ou segredos. Nenhum seed durante startup. Não altera o contrato de staging e não ativa operação fiscal.

## Gates e configuração (somente nome/finalidade)

NFCORE_ENVIRONMENT: deve ser exatamente production.
NFCORE_PRODUCTION_APPROVAL: deve ser exatamente PRODUCTION_APPROVED (aprovação deste comando não certifica fiscal).
NFCORE_FIRST_PLATFORM_ADMIN_BOOTSTRAP: literal APPROVED_ONCE; remover depois do uso.
NFCORE_FIRST_PLATFORM_ADMIN_EMAIL: e-mail humano autorizado que deve coincidir com --email.
DATABASE_URL: PostgreSQL privado alvo de production.
NFCORE_ACTIVATION_EMAIL_PROVIDER, NFCORE_ACTIVATION_EMAIL_API_KEY, NFCORE_ACTIVATION_EMAIL_SENDER, NFCORE_ACTIVATION_BASE_URL, NFCORE_ACTIVATION_EMAIL_TIMEOUT_SECONDS, NFCORE_PASSWORD_RESET_TTL_MINUTES: configuração existente do Brevo/ativação.
Flags do comando: --email, --tenant-id, --legal-name. Não existe --password.
Não gravar credenciais ou dados de sessão em arquivo Git, log ou terminal compartilhado.

## Passos humanos de operação — NÃO executados nesta PR

1. Conferir aprovação explícita do Fábio, SHA revisado na branch protegida production, gate de CI e Governança, acesso administrativo ao servidor certo (vmi3692211), backups e ensaio de restauração. Não usar vmi3683268.
2. Confirmar que o PostgreSQL alvo está com 18 migrations e que não existe platform_admin. Revisar a identidade do e-mail FM autorizado, o domínio e o TLS/hostname do Portal.
3. Configurar TEMPORARIAMENTE todos os gates exatos, inclusive e-mail esperado, e credenciais Brevo já existentes num canal privado. Não colocar tokens reais na PR, shell history ou ChatGPT.
4. Rodar uma única vez a CLI interna do SHA aprovado, com --tenant-id identificando a **organização FM** (não uma academia cliente), --legal-name e --email previamente autorizados.
5. Verificar via interfaces administrativas somente leitura a organização, OWNER com platform_admin=true, token reset armazenado somente como hash e evento human_account.updated do Control Plane. Não copiar tokens para evidências.
6. Confirmar recebimento da mensagem Brevo; a pessoa autorizada abre o link e define sua própria senha no fluxo padrão, respeitando TTL e uso único.
7. Remover os gates efêmeros e fechar a sessão privilegiada. A segunda execução falha mesmo com gates reativados porque platform_admin já existe.
8. Se o envio do Brevo falhar APÓS promoção, usar o fluxo existente 'Esqueci minha senha' para reemitir link. Não reexecutar o bootstrap, não atribuir privilégios diretamente por SQL.

## Catálogo, primeira academia e trial

- A pessoa platform_admin ativada faz login e publica o catálogo em GET/POST /v1/admin/pricing, por CommercialPricingAdministrationService; requer autoridade global commercial_config.write, versão esperada e rastreabilidade. Preços/planos são configuração, não constantes por cliente.
- A organização criada pelo bootstrap é a organização interna de controle FM; não é a primeira academia contratante.
- O primeiro tenant de cliente deve nascer exclusivamente por aquisição assinada S2S ou trial público futuramente autorizado, mediante o fluxo canônico de provisioning, billing/trial e ativação. Unidade cadastrada por DurableControlPlaneService.onboard_unit com autorização unit.write e apenas escopo fiscal HOMOLOGATION. Nenhuma unidade é criada pelo bootstrap FM.
- O trial público pode continuar FECHADO até Go/No-Go: não habilitar NFCORE_SITE_TRIAL_CHANNEL_READY, origens públicas ou segurança de ingress externo. Publicar catálogo não libera automaticamente trials.

## Análise do Worker GSM — lacuna distinta e não corrigida nesta PR

CURRENT: production_gsm.py fixa por env NFCORE_WORKER_GSM_TENANT_ID, NFCORE_WORKER_GSM_UNIT_ID e NFCORE_WORKER_GSM_DESTINATION_ID. OutboxClaimSelection filtra uma partição exata. A rota /internal/production/gsm-bindings registra duas referências estáticas definidas por ENV. Portanto a composição é single-scope e não aceita onboarding multi-tenant dinâmico.
TARGET necessário antes do comercial: manter o único Worker canônico, com registry durável de escopos ativos, descoberta dinâmica e claim justa de múltiplos tenants/unidades. API administrativa com RBAC platform_admin e bootstrap/onboarding por cliente cria/revoga/rotaciona binding GSM por tenant/unidade/finalidade/versão, com envelope e IAM adequados. Worker resolve a autoridade para cada job e valida tenant, unidade, resource, destino, version, lease/idempotência, isolamento e revogação antes da saída. Nenhum wildcard, segunda API, outra persistência, outro Worker ou necessidade de editar ENV/reiniciar por novo cliente. Identidades Google podem permanecer por workload, não uma SA por cliente. Necessita PR separada, com testes cross-tenant, concorrência, revogação e onboarding sem restart.

## Riscos / limitação de atomicidade

O provisionador comercial atual commita organização, OWNER e token em etapas separadas, por seus repositórios canônicos. Este script os orquestra em uma operação, mas não há uma única transação contendo também o Brevo externo. A promoção platform_admin e o evento de auditoria são atômicos e nunca há administrador promovido sem auditoria. Uma falha pré-promoção pode deixar OWNER sem privilégios; retomada do mesmo e-mail é permitida somente sem administrador. Falha pós-promoção exige reset canônico e não novo bootstrap.
A CI não substitui teste operacional real de e-mail, backups, TLS ou homologação fiscal; fiscal permanece BLOCKED_EXTERNAL.
