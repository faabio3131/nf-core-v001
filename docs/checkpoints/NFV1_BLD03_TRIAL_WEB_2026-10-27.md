# NFV1-BLD-03 — cadastro de trial no Portal

Base: main e751ffb368828ea3387b0f49eeab5e467e2ce4ba (#259). Construção interna em andamento; não certificar Web publicada ou oferta comercial.

Delta: página trial.html na aplicação existente, catálogo governado, criação anônima sem cookies/HMAC/tenant fornecido pelo browser, recuperação com mesma chave após falha/reload e mensagens honestas de indisponibilidade. Origin é repassado intacto pelo proxy; consulta POST ao catálogo preserva a allowlist existente e permite Origin no browser same-origin. Sem novo serviço, migração, preço/duração definidos em runtime ou transporte de e-mail real.

Reuso: GovernedTrialService, pricing administration, provisioning, HumanIdentity, PasswordRecovery, subscription e PostgresPublicTrialAbuseGate. Testes browser incluem cenário real PostgreSQL em schema descartável único e mailbox sintética exclusivamente no harness loopback; criação canônica de tenant/OWNER/subscription, perda de resposta após commit, replay, ativação e login. Harness de teste nunca é composição de staging.

Validação local inicial: 19 testes dirigidos API/proxy/governança PASS; frontend 18 PASS, lint/typecheck/build PASS. Browser local bloqueado por download incompleto do Chromium e ausência de PostgreSQL; CI remota deve provar cenários completos antes de aceite. Não classificar falha de infraestrutura como teste aprovado.

PR #237 auditada e seu teste reaproveitado em tests/runtime/test_nfv1_public_trial_postgres.py: schema UUID descartável próprio, migração canônica sem número histórico fixo, 12 tentativas concorrentes por duas instâncias, limite compartilhado e recusa sem tabela. A PR legada só deve ser encerrada como substituída após integração/CI deste delta. Proxy rejeita Authorization no ingresso público para não convertê-la em chamada anônima ao remover o header.

Pendências externas preservadas: binding administrativo GSM, catálogo/duração/origens aprovados e publicação explícita. Portal acompanha main e auto-deploy permanece habilitado; a autorização pontual da #259 não altera a regra permanente. Site fm-site-novo não foi alterado. BLD-03 não está DONE.
