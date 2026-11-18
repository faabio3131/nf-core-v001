# NFCore × Bling — ativação operacional governada na Contabo

**Atualização:** 2026-11-10. **Status:** preparação interna em PR, ativação real sujeita a gates de host e OAuth externo. Não confundir merge ou CI com conexão real.

## Autoridades únicas
- A API continua sendo `nfcore-api` — a mesma sessão humana, RBAC, CSRF e bindings fiscais canônicos. Nenhuma segunda API ou nova autoridade de empresa/tenant.
- O Worker usa a outbox fiscal existente, `NFCORE_WORKER_CONNECTOR=bling-multi` e a composição explicitamente autorizada, somente homologação.
- Credenciais OAuth, JWT, certificado A1 e chaves AES nunca são guardadas no Git; o Bling em si deve registrar uma aplicação e o estabelecimento deve consentir na tela oficial.

## Pré-condições bloqueantes — leitura sem efeitos
1. Confirmar `production` e SHA em `/opt/fm/nfcore/.deployed`; `tail -n 80 /opt/fm/nfcore/deploy.log`; verificar `/opt/fm/nfcore/.failed-sha` (se houver). Confirmar API/Portal/DB saudáveis por `docker ps` e healthchecks internos.
2. Examinar `crontab -l`, o compose instalado e `/opt/fm/nfcore/deploy.sh --check`. Não copiar scripts do Git sem diff/autorizar instalação.
3. Antes de qualquer DDL, confirmar backup verificado e escopo de schema PostgreSQL. A versão 19 é baseline histórico; **migrações Bling 20/21 só pela ferramenta canônica `scripts/ci/migration_guard.py`, com aprovação humana específica**, ensaio/rollback e sem automatizar `--apply` em `deploy.sh`.
4. Confirmar que não há variáveis globais legadas `NFCORE_BLING_COMPANY_ID`, `TENANT_ID`, `UNIT_ID`, `ENVIRONMENT` no modo multi-installation.
5. Confirmar callback HTTPS da aplicação Bling registrado no provedor: `https://app.nfcore.com.br/v1/portal/integrations/bling/oauth/callback` e escopos aprovados (IDs exatos concedidos pela aplicação Bling, compatíveis com o retorno `scope` do OAuth; nunca códigos inventados); validar origem/rota no proxy reverso.
6. Obter `NFCORE_BLING_CLIENT_ID` e dois segredos reais fora do chat/Git: Client Secret do aplicativo (também usado para assinar webhooks pelo Bling) e master-key (base64 de 32 bytes). Não criar chave HMAC independente. Não inventar credenciais, códigos de empresa ou IDs de status.

## Ativação da API EXISTENTE — somente após aprovação de host/migration
- Copiar o modelo versionado `deploy/contabo/.env.bling.api.example` para o arquivo host-owned `/opt/fm/nfcore/.env.bling.api`; inserir *somente* `CLIENT_ID` e scopes reais; chmod 0600 e ownership correto.
- Montar os arquivos sigilosos no diretório host-owned fornecido por `NFCORE_BLING_SECRETS_HOST_DIR`, modo 0700, dono UID/GID 10001, arquivos individuais modo 0600. Ambos API e Worker executam como UID/GID 10001. Evitar symlinks no caminho dos segredos.
- Depois de um ensaio `docker compose config` com as variáveis necessárias (não imprimir o config completo pois contém dados sensíveis), ativar de forma **durável** o overlay `deploy/contabo/compose.bling.api.opt-in.yml` por symlink host-owned `/opt/fm/nfcore/docker-compose.override.yml`. O Compose passará a incorporar o overlay automaticamente ao deploy pull normal. **Não criar um compose paralelo nem alterar o Dockerfile.**
- Validar `NFCORE_BLING_INSTALLATIONS_ENABLED=true`, schema 1..21 completo e cada arquivo secreto legível *dentro* da API, sem imprimir conteúdo; health de `nfcore-api` e Portal. Em erro: remover apenas o override controlado, recriar API no compose base e confirmar readiness. Não dar rollback de schema destrutivo.

## Política fiscal por instalação — construção interna multiempresa

A API Bling multi-instalação usa uma **única autoridade de regras fiscais**,
o preparador nativo e os perfis canônicos do NFCore. A política fiscal **não**
pode ser um arquivo global para todos os estabelecimentos. O modo multi exige o
diretório read-only `NFCORE_BLING_FISCAL_POLICY_ROOT` montado em
`/run/nfcore/bling-policies`; o caminho correspondente no host fica em
`NFCORE_BLING_POLICIES_HOST_DIR` e deve ser criado por operador autorizado,
com permissões de diretório 0700, titularidade UID/GID 10001, arquivos 0600.
É proibido colocar documentos fiscais, políticas de clientes ou segredos no Git.

Cada instalação usa o nome do arquivo derivado **somente** dos valores
canônicos do vínculo fiscal, em `[host_namespace, tenant_id, unit_id,
environment, company_id]`. O prefixo é sempre `bling`, o ambiente operacional
do Worker é `homologation`, e o identificador da empresa é o validado pelo
provedor. O algoritmo é
`sha256(json.dumps(lista, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()`.
Para cada hash `H`, existem exatamente dois artefatos:

- `H.json`: a política fiscal já revisada pelo contador e vinculada aos
  perfis da empresa; segue o contrato de
  `contracts/integrations/bling-fiscal-policy.example.json`.
- `H.sha256`: 64 caracteres hexadecimais minúsculos do SHA-256 **dos bytes
  exatos de H.json**, com newline final opcional.

Para obter H em ambiente de configuração autorizado, sem acessar credenciais:

```python
import hashlib
import json
material = ["bling", "TENANT_CANONICO", "UNIDADE_CANONICA", "homologation", "EMPRESA_BLING"]
slot = hashlib.sha256(
    json.dumps(material, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
).hexdigest()
print(slot + ".json", slot + ".sha256")
```

Ao trocar uma política é preciso criar **nova versão e novo digest**, mantendo
a revisão humana e a trilha de auditoria do preparador. Nunca reutilizar
`policy_id + version` com conteúdo diferente: o archive canônico já bloqueia
conflitos. A instalação diferente não lê nenhuma política substituta, e um
artefato ausente, adulterado ou com symlink bloqueia apenas aquela preparação.

**Compatibilidade:** o modo single-company legado continua aceitando
`NFCORE_BLING_FISCAL_POLICY_FILE` e `NFCORE_BLING_FISCAL_POLICY_SHA256`,
mas o modo multi rejeita essas variáveis para evitar isolamento ilusório.
O diretório pode ficar vazio durante cadastro OAuth; isso deixa a preparação
fiscal daquele cliente bloqueada até a política aprovada ser configurada.
O sistema jamais inventa tributos nem empresta política de outro tenant.

**Aceite interno sem clientes ou certificados:** testes com várias identidades,
políticas isoladas, políticas ausentes, hash adulterado, symlinks, legacy mode,
configuração Docker read-only e a suíte completa de assinatura/XSD, API/Portal,
RBAC, E2E e PostgreSQL. A configuração de valores legais e assinatura real de
A1 são pré-requisitos externos do estabelecimento, não código pendente.

## Operação Web
1. Proprietário/administrador com `integration.manage` abre **Integrações > Centro de Operações Bling** e seleciona a unidade autorizada.
2. O painel lista apenas os vínculos `host_namespace=bling` dessa unidade. Se nenhum existir, é obrigatório criar o vínculo fiscal pelo fluxo canônico de gestão; não aceitar tenant/unit informados pelo navegador como autoridade.
3. Informar ID da empresa Bling, cadastrar e clicar **Conectar / reautorizar no Bling**. O browser navega à origem oficial HTTPS do Bling. Ao autorizar, retornar ao portal e atualizar a lista; o callback OAuth consome um `state` de uso único atrelado à sessão. Sem autorização externa, a instalação permanece indisponível.
4. Definir IDs de status autorizado/rejeitado **daquela conta Bling**, usando mapeamento por revisão CAS; valores diferentes, positivos. Não compartilhar IDs entre empresas.
5. Simular recebimento de pedido, revisão humana, preparação e recuperação de webhook com duas unidades. Provar que nenhuma recuperação emite NF-e por si. Verificar dead-letter/erro, revogação OAuth, reautorização e replay seguro.

6. Configurar **Pedidos de Venda** (eventos `order.created`, `order.updated`, `order.deleted`, versão `v1`) na aba Webhooks do aplicativo Bling, utilizando **a URL exata de instalação exibida no painel**, `https://app.nfcore.com.br/webhooks/bling/installations/{installation_id}`. Não usar callback OAuth como webhook. O HMAC deve validar `X-Bling-Signature-256` com Client Secret real. A emissão de evento exige o token OAuth autorizado; checar 202 e idempotência sem emissão duplicada. Fonte: https://developer.bling.com.br/webhooks

## Ativação do Worker existente — etapa SEPARADA da API
- É **opt-in**, fora do compose base e do cron. Montar os mesmos segredos com permissões e dot-env apropriados, usando `compose.bling.worker.opt-in.yml`; confirmar o DB e a identidade antes do start.
- Verificar a configuração do Vault A1 para autorização fiscal; sem certificado real da contabilidade, não marcar emissão como homologada. Sem A1 o processamento deve permanecer bloqueado com erro verificável.
- Smoke do processo e estado de health do Worker; duas empresas/unidades isoladas; confirmação de reprocessamento e rollback que preserva outbox. A decisão de transmitir NF-e em homologação requer confirmação da contabilidade.

## Auditoria de host sem credenciais expostas (10/11/2026)

O procedimento seguinte é **somente leitura**. Deve ser executado no host
Contabo pelo operador autorizado depois de confirmar a branch de produção.
Ele não faz deploy, não instala segredos, não aplica migrations e não transmite
documentos fiscais:

```bash
bash /opt/fm/nfcore/src/deploy/contabo/bling-operational-host-audit.sh \
  61015a837be8b2e5e3b0f1cdb5fb14c5c875fb91
```

O SHA acima é o release Bling #415 de 10/11; para versões posteriores use
o SHA real de `production` verificado no GitHub. Não extrapolar esse
checkpoint para releases futuros.

A auditoria devolve apenas `PASS / PENDING / BLOCKED` e identificadores
de commit. Verifica `.deployed`, `.failed-sha`, marcador `DEPLOY OK`,
integridade de backup recente, containers, readiness interno, migração fiscal/Cakto,
esquema Bling 20/21, flag e montagens dos segredos OAuth na API e health do Worker.
Nenhum conteúdo secreto é impresso. O resultado
`HOST_GATES_PASS_EXTERNAL_STILL_UNVERIFIED` **não significa** que Bling
OAuth real, pedido ou A1/SEFAZ estejam homologados.

A auditoria também exige `BLING_POLICY_MOUNT=PASS` (bind mount real,
read-only, no caminho canônico da API) e
`BLING_POLICY_ARTIFACTS=PASS` (ao menos um arquivo de política encontrado e
todos os arquivos presentes aprovados pelo mesmo `BlingSalePreparer` do
runtime, incluindo vínculo de escopo e digest). Diretório vazio significa
`PENDING`; ausência, symlink, conteúdo adulterado ou mount gravável significa
`BLOCKED`. Essa prova **não confirma** que todas as instalações tenham
política aprovada: o escopo exato da empresa do teste deve ser exercitado no
Portal antes de transmitir. Nenhum dado da política é impresso pelo script.

Se retornar `BLOCKED` ou `PENDING`, registrar somente a saída
dessas chaves sem adicionar logs brutos e não forçar deploy, DDL ou emissão.
O operador valida consentimento real da conta Bling e ciclo fiscal oficial
separadamente. A aprovação humana continua obrigatória para migrações e
ativação dos serviços que modifiquem o estado de produção.

## Evidência exigida para encerramento
Registrar commit em `production`, SHA no `.deployed`, `DEPLOY OK`, lista de containers, migrações 1..21, `/health/ready` interno, API OAuth pronta, Worker health, consentimento real Bling por tenant, ID de status mapeado e ciclo de pedido de teste. **Nenhuma dessas evidências é substituída por CI verde isolada.**

## Contratos oficiais verificados para o teste real

- Webhooks: o cabeçalho `X-Bling-Signature-256` é HMAC-SHA256 assinado com o Client Secret do aplicativo OAuth; o runtime reutiliza exatamente essa chave. Fonte: https://developer.bling.com.br/webhooks
- JWT: utilizar `enable-jwt: 1` no token OAuth e em requisições autenticadas à API Bling. Fonte: https://developer.bling.com.br/migracao-jwt
- Identidade: a API pode responder `data.id` numérico; comparar com o identificador configurado da empresa após conversão textual exata, sem inferência de tenant/unidade.

## Gates de liberação do callback e JWT — revisão 10/11/2026

- O callback OAuth pode produzir JSON para APIs ou redirect 303 para a aplicação Web. A assinatura de retorno do handler deve ser a classe-base `Response`, não a união de classes de resposta, porque FastAPI rejeita este tipo na compilação do roteador. Testar a rota com `TestClient` efetivo.
- Os testes de transporte devem exigir `enable-jwt: 1` em pedidos, atualizações e identificação de empresa, conforme contrato oficial Bling. Nunca remover o cabeçalho de produção para fazer testes antigos passarem.
- A correção de import do teste do proxy deve importar o mesmo `scripts/serve_portal.py` do repositório de maneira independente do PYTHONPATH da wheel, sem trocar o handler ou dispensar o teste.
- CI e Governança do HEAD exato da PR #412 são critérios obrigatórios; testes de revisão anterior ou cancelados não certificam o release.
