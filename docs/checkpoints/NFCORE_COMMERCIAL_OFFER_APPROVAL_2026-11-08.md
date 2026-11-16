# NFCore V1 — decisão comercial vigente e aprovação para publicação
**Data:** 2026-11-08 (America/Sao_Paulo)
**Autoridade:** proprietário do NFCore
**Estado da decisão:** APROVADA PARA PUBLICAÇÃO COMERCIAL PELO FLUXO ADMINISTRATIVO CANÔNICO
**Estado da execução:** NÃO PUBLICADO / VERIFICAÇÃO OPERACIONAL PENDENTE
**Fontes:** decisão atual do proprietário; `config/commercial/plans.json`; código e endpoints de pricing/release; GET público real `/v1/commercial/offer` da Contabo em 08/11.

## Oferta vigente — substitui os três planos de 01/11
| Plano | Preço mensal BRL | Mensal equivalente anual BRL | Documentos incluídos/mês | CNPJs | Excedente BRL/documento |
| --- | ---: | ---: | ---: | ---: | ---: |
| Starter | 99,00 | 79,00 | 300 | 2 | 0,25 |
| Pro (Growth) | 249,00 | 199,00 | 1.500 | 5 | 0,15 |
| Business (Scale) | 590,00 | 490,00 | 6.000 | 20 | 0,08 |
| Enterprise (Hub) | 1.490,00 | 1.190,00 | 25.000 | variável/contratual | 0,04 |

Os limites e valores acima reproduzem o candidato versionado em `config/commercial/plans.json`. O período anual equivalente deve ser cobrado conforme o contrato e a referência real do gateway; não pressupor cobranças automaticamente ativas. Decisão posterior do proprietário em 06/11 confirma os quatro preços mensais e franquias de documentos como substitutos dos anteriores.

**Trial:** 14 dias sem cartão, 50 documentos conforme política candidata, sem autorização automática para emissão fiscal real; homologação externa e autoridade de produção seguem independentes. A candidata `commercial_plan_candidate.py` exporta planos desabilitados (`enabled=False`) por design; apenas a publicação por administrador deve criar a versão comercial ativa.

## Proibição de atalhos
- Não publicar os planos históricos Essencial/Crescimento/Escala, de 01/11, como preços atuais.
- Não confundir `APPROVED_PRODUCT_PROPOSAL_NOT_PUBLISHED` com `PUBLISHED`.
- Não inserir dados diretamente no PostgreSQL para contornar sessão, CSRF, `platform_admin` ou versionamento.
- Não criar usuários/clientes de teste por SQL ou script administrativo; usar jornada normal `/trial.html` → ativação por e-mail → login.
- Não afirmar que volume incluso, excedente, CNPJ, rate limit, trial e faturamento estão efetivamente aplicados sem validação dos respectivos ledgers/quotas.
- Não aprovar fiscal production, ambientes externos, credenciais, deploy ou merge por inferência desta decisão.

## CURRENT operacional verificado em 08/11
- No endpoint público `GET /v1/commercial/offer`: `pricing.status=unpriced`, `release.status=unavailable`, `purchase_enabled=false`, `trial_enabled=false`.
- `NFCORE_PUBLIC_TRIAL_ALLOWED_ORIGINS=https://app.nfcore.com.br` foi configurada na Contabo em 08/11: rota de planos passou de 404 para 503 com `Origin` válido por falta de liberação comercial. `/health/ready` permaneceu HTTP 200.
- A API de administração existente exige sessão humana de `platform_admin`, CSRF, controle de versão e auditoria. A aprovação do proprietário não é uma sessão autenticada.
- A PR #389 é trabalho separado de administração do piloto de HOMOLOGAÇÃO, não condição para publicar preços.

## Próxima execução autorizada quando houver sessão admin
1. Conferir `GET /v1/admin/pricing` e `GET /v1/admin/commercial-release`, sob sessão `platform_admin` existente.
2. Validar se a implementação durável de quotas, CNPJs, contagem de documentos, IA, excedentes e conversão trial está pronta. Não declarar comercialização integral se não estiver.
3. Construir e submeter via `POST /v1/admin/pricing` nova versão ativa da oferta aprovada, com `expected_version` correto, auditada com ator real.
4. Registrar a decisão governada em `POST /v1/admin/commercial-release`, com referência humana `NFCORE_DIRECTOR_COMMERCIAL_OFFER_APPROVAL_2026-11-08`. A liberação não deve ativar pagamento se checkout/fulfillment não estiverem prontos.
5. Verificar `GET /v1/commercial/offer`, `POST /v1/public/trial-plans` com `Origin: https://app.nfcore.com.br`, e a jornada real de uma conta limpa pelo site.
6. Registrar SHA implantada, CI, estado de checkout, ativação de e-mail e evidência E2E. Não afirmar aprovação fiscal real.

**Nota:** o registro desta decisão documental não é publicação operacional e não autoriza alterar diretamente o banco ou desabilitar gates.