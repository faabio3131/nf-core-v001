# NFCore — Plano B: manutenção administrativa temporária sem elevar a chave de auditoria

**Proposta de execução:** 2026-11-11. **Status:** código de bootstrap em PR; **nenhuma permissão da VPS foi modificada por este documento**.

## Decisão de segurança e escopo

- O proprietário autorizou temporariamente a via administrativa para concluir a construção operacional do NFCore. **Isso não autoriza `sudo ALL`, shell root remoto pela chave `nfcoreaudit`, alteração de SSH/firewall dos outros SaaS, deploy em `production`, migrations, criação de chaves reais ou transmissão fiscal fora de homologação.**
- Preservar **sem alterações** a chave `nfcoreaudit`, seu `authorized_keys` com `restrict,command=`, o usuário sem Docker e o `sudoers` de comando único sem argumentos. Seu propósito continua **exclusivamente leitura**.
- Usar uma **sessão administrativa autenticada de `fmadmin`** no host específico `vmi3692211`, por SSH/VNC oficial já autorizado e com elevação interativa do próprio operador. Não criar segundo serviço/daemon/API, túnel, agente ou autoridade de segredos.
- O privilégio administrativo fica limitado ao tempo da **sessão humana** para tarefas do NFCore revisadas e registradas; não criar um novo NOPASSWD persistente para o usuário de auditoria. Se for inevitável chave administrativa temporária, restringir à origem/operador, registrar vencimento explícito, remover ao encerrar o trabalho e manter acesso de recuperação separado. Não colocar chave em Git/Chat/Actions sem controle de environment e revisão humana efetiva.
- O ciclo é **Current → preflight → mudança pequena → smoke → evidência → rollback**, com backups e gates por operação. Proibido tocar IRON ou alterações de cobertura municipal de outro agente.
- Esta política é operacional e **não concede direitos por si só**. A elevação só existe na VPS se o operador tiver acesso administrativo real.

## Trabalho administrativo já autorizado: instalar auditoria GSM da PR #425

**Release revisada de auditoria:** PR #425 integrada a `main` em `9eefd5e68ba46dfbef2986c3265e1c760a1a3efa`. O novo bootstrap deve primeiro passar por revisão e CI e ser integrado a `main`; não executar scripts vindos de uma PR ou branch desprotegida.

**Pré-requisitos no host:**
- Autenticar `fmadmin` na VPS oficial, conferindo a identidade SSH do servidor por fonte independente.
- Confirmar `hostname -s` = `vmi3692211`; confirmar `sudo` funcional, sem entregar senha ao ChatGPT.
- Confirmar que a cadeia `/usr/local/libexec/nfcore-audit`, `ssh-gate.sh`, `root-audit.sh` e `bling-operational-host-audit.sh` está root-owned, não é symlink e não é gravável por grupo/outros.
- Executar o bootstrap **somente depois de conferir a revisão integrada no GitHub**; `production` e o checkout de aplicação não serão atualizados por este bootstrap.

**No shell SSH do `fmadmin` (não no ChatGPT):**

```bash
set -euo pipefail
cd /opt/fm/nfcore/src

# Fetch como operador comum, não como root. Sem checkout ou deploy.
git fetch --no-tags origin main
APPROVED_MAIN_SHA="$(git rev-parse refs/remotes/origin/main)"
printf 'REVIEW_MAIN_SHA=%s\n' "$APPROVED_MAIN_SHA"
# Pare se este SHA não coincidir com o merge revisado no GitHub.

BOOTSTRAP_DIR="$(mktemp -d)"
chmod 0700 "$BOOTSTRAP_DIR"
git show "$APPROVED_MAIN_SHA:deploy/contabo/bootstrap-gsm-plan-b.sh" > "$BOOTSTRAP_DIR/bootstrap.sh"
sha256sum "$BOOTSTRAP_DIR/bootstrap.sh"
# Compare este hash com o artefato/revisão aprovada antes da elevação.

sudo install -o root -g root -m 0500 "$BOOTSTRAP_DIR/bootstrap.sh" /root/nfcore-bootstrap-gsm-plan-b.sh
sudo /bin/bash /root/nfcore-bootstrap-gsm-plan-b.sh --check "$APPROVED_MAIN_SHA"
sudo /bin/bash /root/nfcore-bootstrap-gsm-plan-b.sh --apply "$APPROVED_MAIN_SHA"
rm -rf -- "$BOOTSTRAP_DIR"
```

O bootstrap `deploy/contabo/bootstrap-gsm-plan-b.sh` é um instalador **de escopo fixo**: carrega exatamente três arquivos por `git show <SHA>:<caminho fixo>`, exige `origin/main` no SHA aprovado, verifica root/hostname/trust/visudo, valida sintaxe, preserva backups anteriores e instala `root:root 0555` em:

1. `deploy/contabo/worker-readonly-preflight.py` → `/usr/local/libexec/nfcore-audit/worker-readonly-preflight.py`
2. `deploy/contabo/root-host-audit.sh` → `/usr/local/libexec/nfcore-audit/root-audit.sh`
3. `deploy/contabo/host-audit-command.sh` → `/usr/local/libexec/nfcore-audit/ssh-gate.sh`

Não altera `authorized_keys`, `sudoers`, credenciais, IAM, `.env`, banco, containers, Nginx, branch `production` ou qualquer outro SaaS. Backup root-only em `/var/backups/nfcore-gsm-plan-b/`. Falhas durante instalação acionam tentativa de rollback dos arquivos alterados. Se o bootstrap negar, registrar o estado e interromper, sem reduzir controles.

**Verificação seguinte:** GitHub Actions → `NFCore Contabo GSM Read-only Audit (Plan B)` → `Run workflow` pela `main` protegida, usando o SHA **completo atual** de `production`. Resultado `NO_GO_GENERAL_WORKER` é esperado se o worker ainda estiver ausente; essa prova não autoriza `docker compose up`.

## Acesso para as próximas operações de construção

A mesma sessão administrativa real pode executar operações **separadamente aprovadas e pré-auditadas** de identidade GSM, `.env.worker`, rollback, backup/restore e ativação; o bootstrap acima **não realiza nenhuma delas**. Antes de cada operação: congelar SHA, validar dados, provar recuperação e registrar GO/NO-GO.

**Risco de autorização provisória:** estender o `sudoers` do auditor ou manter chave SSH root ilimitada criaria acesso persistente sem distinção de operações. Isso não acelera o provisionamento inicial porque a alteração de autorização **também precisa ser instalada por alguém que já tenha root**. Por isso a via mais curta e segura é usar `fmadmin` com `sudo` durante sessões monitoradas, sem ampliar o canal de auditoria.

## Encerramento da exceção

Quando o último bloco operacional estiver certificado ou ao término da janela de manutenção acordada, encerrar sessões administrativas, revogar qualquer credencial temporária criada especificamente para elas, verificar `authorized_keys` e `sudoers`, auditar logs, confirmar que `nfcoreaudit` continua somente leitura e registrar o encerramento na issue de governança. Não vincular a exceção a um prazo indefinido sem revisão.

**Risco externo independente:** a emissão real fiscal exige CNPJ/unidade, A1 e credenciais de homologação oficiais; mesmo com host admin ativo, nenhuma transmissão externa pode ser declarada homologada sem resposta oficial.
