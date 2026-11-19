# NFCore — Plano B de acesso e auditoria Contabo sem Desktop Commander

**Data:** 2026-11-10. **Prioridade:** preparar homologação fiscal de 11/11.
**Estado CURRENT confirmado em 10/11/2026:** SSH restrito GitHub Actions→Contabo **ATIVADO E TESTADO**. Bling operacional permanece **NO-GO**. Este documento não autoriza migração, deploy ou operação fiscal.
**Servidor alvo conhecido:** Contabo `vmi3692211`, aplicação em `/opt/fm/nfcore`.
**Autoridade:** produção é o host real; o código e a CI do GitHub não provam estado do host.

## Checkpoint CURRENT comprovado — não repetir configuração

Evidência primária: [GitHub Actions run #42941524225](https://github.com/faabio3131/nf-core-v001/actions/runs/42941524225), main `545b7606208eedf77b3fd6b852ccb82b4716f6b8`, production `61015a837be8b2e5e3b0f1cdb5fb14c5c875fb91` (SHA histórico; reconfirmar antes de operações futuras).

- `main` protegida pelo ruleset `proteger-main`, com checks `quality` e `execution-plan`.
- Environment `nfcore-contabo-audit` tem reviewer `faabio3131`, bypass administrativo desabilitado e branch explicitamente limitada à `main`.
- Os **quatro** Secrets `NFCORE_AUDIT_HOST`, `NFCORE_AUDIT_USER`, `NFCORE_AUDIT_SSH_PRIVATE_KEY`, `NFCORE_AUDIT_KNOWN_HOSTS` foram cadastrados em GitHub Environment, nunca no Git.
- Bootstrap do host retornou `PLAN_B_HOST_BOOTSTRAP_PASS`; o comando forçado da conta `nfcoreaudit` foi executado por um runner GitHub com host key pinado.
- Audit report retornou `DEPLOY_SHA_EXACT=PASS`, backup/checksum PASS, container DB/API/Portal PASS, readiness PASS e schema guard baseline PASS.
- A execução geral terminou FAILURE **por pendências de Bling**, não por SSH: `BLING_SCHEMA_20_21=PENDING`, worker/segredos/políticas pendentes e `RESULT=CODE_READY_BUT_BLING_NOT_ACTIVE`.
- **Acesso GitHub Actions→VPS comprovado. Bling operacional NÃO comprovado.** Não gerar nova chave, repetir cadastro de Secrets, habilitar fiscal real ou reimplantar os scripts SSH para tentar deixar verde.
- A PR #422 separa o PASS visível do canal da falha de prontidão Bling sem enfraquecer o bloqueio; é candidata até CI e integração autorizadas.

Os avisos históricos de branch não protegida e secrets ausentes abaixo foram superados pela configuração comprovada em 10/11/2026; não segui-los como tarefas pendentes.

## Objetivo e limites

Substituir a dependência operacional do Desktop Commander por canais permanentes:
1. **SSH local** pelo computador do operador: alternativa imediata, sem conector pago.
2. **GitHub Actions manual com SSH restrito:** uma auditoria de host com saída sanitizada, por chave dedicada e comando forçado; não é um deploy.
3. **Contabo VNC:** recuperação de emergência quando o SSH está indisponível. A Contabo exige cliente VNC externo e ativação pode exigir reboot; não habilitar nem reiniciar por conveniência em véspera de homologação.

Este plano não cria API, worker, persistência, agente ou credencial paralela. Não instala software de gestão remota de terceiros no host.

## A. Diagnóstico imediato via SSH local — sem automação/credencial nova

No computador já autorizado, usar Windows PowerShell ou terminal Unix:

```powershell
ssh -V
ssh fmadmin@<IP_OU_HOST_VALIDADO_DA_VPS>
```

`fmadmin` é a identidade registrada nos runbooks, **não prova** que a chave local já existe. O endereço vem do painel Contabo, nunca de um IP inventado no chat. Em primeira conexão, confirmar a impressão digital do host por meio independente antes de aceitá-la. A senha/chave privada nunca é enviada para ChatGPT.

No shell do host, **comandos somente leitura**:

```bash
printf 'DEPLOYED='
sed -n 's/^SHA=//p' /opt/fm/nfcore/.deployed
printf 'FAILED_SHA_PRESENT='
test -s /opt/fm/nfcore/.failed-sha && echo YES || echo NO
printf 'BRANCH='
git -C /opt/fm/nfcore/src rev-parse HEAD
printf 'DEPLOY_LOG_MARKER='
grep -E 'DEPLOY OK [a-f0-9]+' /opt/fm/nfcore/deploy.log | tail -n 1
printf 'API='
docker inspect --format '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' nfcore-api
printf 'PORTAL='
docker inspect --format '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' nfcore-portal
printf 'DATABASE='
docker inspect --format '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' nfcore-db
```

NÃO executar `docker compose up`, `deploy.sh` sem `--check`, migrations, `cat .env` ou comandos que revelem Docker environment/segredos. Não publicar a saída de `docker inspect` completa, IDs de tokens, arquivos A1 ou logs brutos de aplicação. Se `fmadmin` não tiver acesso de leitura ao Docker, interromper e usar um operador autorizado; não elevar privilégios automaticamente.

O diagnóstico do Bling completo está em `deploy/contabo/bling-operational-host-audit.sh` (main). Pode ser executado no host **apenas após obter uma cópia revisada, conferir seu SHA-256 e confirmar permissões**, com o SHA exato da branch `production`. Ele exige que a API e o Worker Bling estejam ativados para retornar PASS; se apenas o teste fiscal direto estiver em escopo, classificar essas pendências separadamente, não fingir que o Bling foi homologado.

## B. Canal auditável e reutilizável: GitHub Actions → SSH com comando forçado

Workflow proposto: `.github/workflows/contabo-readonly-host-audit.yml`.

**HISTÓRICO ANTERIOR À PROTEÇÃO DE MAIN (SUPERADO EM 10/11/2026):** o repositório
`faabio3131/nf-core-v001` é **público** e a branch `main` consta como
**NÃO PROTEGIDA** (`protected=false`). O workflow verifica
`github.ref_protected == true` e **não executa a auditoria** enquanto a
proteção não estiver efetivamente habilitada. Antes de adicionar a chave
SSH aos Secrets é obrigatório: (a) configurar proteção de `main` por
branch protection/ruleset com revisão e checks; (b) configurar o
environment `nfcore-contabo-audit` com **required reviewers** e restrição
à branch protegida; (c) validar ambos no GitHub. Se o plano atual do
GitHub não suportar os controles necessários, **não armazenar a chave
nesse workflow**; usar SSH direto e outra arquitetura de autenticação
aprovada. Não contornar o guard para conseguir verde.

**Pré-condições de ativação humana, fora do repositório:**
- Aprovar formalmente a criação da identidade **exclusiva `nfcoreaudit`**, SEM grupo `docker`, `sudo` ou `admin`, SEM senha de login, e sem acesso SSH interativo pela chave de auditoria. Acesso ao socket Docker equivale a privilégios elevados: **nunca conceder acesso direto ao socket ao usuário SSH**.
- Aplicar o único privilégio excepcional por `sudoers`: executar **apenas e sem argumentos** `/usr/local/libexec/nfcore-audit/root-audit.sh` como root, mediante `sudo -n`, com entrada estritamente validada contendo apenas SHA da produção e digest do script. Exemplo revisável `deploy/contabo/nfcore-audit.sudoers.example`. Validar com `visudo -cf` antes de instalar em `/etc/sudoers.d/`; não instalar com o workflow. Esse helper executa exclusivamente o auditor imutável e nunca executa comandos livres.
- Instalar toda a cadeia executável em `/usr/local/libexec/nfcore-audit/` (não em `/opt/fm/nfcore`, cuja árvore pode ser alterada por operações de deploy): `host-audit-command.sh` como `ssh-gate.sh`, `root-host-audit.sh` como `root-audit.sh`, e `bling-operational-host-audit.sh` com o mesmo nome. Os três arquivos devem ser `root:root` e `0755` ou `0555` e não conter symlinks.
- Auditar também **cada ancestral**: `/`, `/usr`, `/usr/local`, `/usr/local/libexec`, `/usr/local/libexec/nfcore-audit`, além dos três scripts. Cada componente precisa ser root-owned, não symlink e sem escrita por grupo/outros. O root helper falha com `NO_GO_UNTRUSTED_AUDIT_PATH` em caso de violações. Não corrigir chmod/chown de diretórios do sistema automaticamente.
- Manter o `authorized_keys` da conta de auditoria sob controle administrativo, sem possibilidade de alteração pela conta de auditoria. A permissão operacional para Docker fica **somente dentro do script raiz pré-revisado**, sem `sudo su`, `sudo bash` ou shell administrativo.
- Criar um novo par Ed25519 exclusivo para esta auditoria em equipamento seguro; **não reutilizar** chave pessoal ou credencial de deploy e **não publicá-la** no repositório ou no chat.
- Conferir hashes dos **três** scripts contra o commit aprovado e validar o sudoers de exemplo. Instalação inicial requer autorização específica da administração Contabo. **Esta PR NÃO instala os arquivos no host e não altera privilégios.**
- Restringir a chave pública em `authorized_keys` com `restrict,command="/usr/local/libexec/nfcore-audit/ssh-gate.sh"`. Isso veta shell arbitrário, encaminhamentos e pseudo-terminal pela chave de auditoria. Conservar a chave SSH de acesso de emergência do operador separada.
- No GitHub, criar environment `nfcore-contabo-audit` e, quando disponível no plano, exigir revisão humana e limitar execuções à branch `main`. Configurar os segredos **nesse environment**, não em arquivos versionados:

| Nome | Conteúdo protegido |
|---|---|
| `NFCORE_AUDIT_HOST` | IP ou hostname validado da VPS, sem porta ou protocolo |
| `NFCORE_AUDIT_USER` | Conta SSH de auditoria com a chave pública restrita |
| `NFCORE_AUDIT_SSH_PRIVATE_KEY` | Chave privada exclusiva, sem passphrase, protegida no GitHub |
| `NFCORE_AUDIT_KNOWN_HOSTS` | Chave pública do **servidor SSH** validada fora da conexão; nunca confiar apenas em `ssh-keyscan` |

**Como acionar quando estiver configurado:** GitHub → Actions → `NFCore Contabo Read-only Host Audit (Plan B)` → Run workflow na branch `main`, informando o SHA completo **atual** de `production`. O workflow valida esse SHA no GitHub, a assinatura SSH do host previamente pinada e o digest SHA-256 do script de auditoria instalado no host. Toda requisição que falhar nesses gates retorna `NO_GO` e não tenta um deploy.

O comando forçado autoriza **somente** `nfcore-audit <SHA_40> <SHA256_SCRIPT_64>`; a conta SSH não tem Docker nem sudo geral. Ela envia apenas os dois digests a um helper root-owned sob uma regra sudoers que autoriza **um único binário/script sem argumentos**. O helper valida toda a cadeia de arquivos/diretórios e executa exclusivamente o auditor de código fixo. Os scripts instalados são root-owned e a chave SSH nunca executa código fornecido pelo chamador. O workflow não faz checkout da branch `production` para execução remota, não envia arquivos executáveis, não habilita modos privilegiados do Docker e não imprime segredos.

**Evidência:** workflow com head `main`, SHA de `production`, status `DEPLOY_SHA_EXACT`, `SCHEMA_PRODUCTION_GUARD`, backups, API/Portal, Bling e `RESULT`. A saída de SSH é filtrada para chaves e estados permitidos; nem o stdout bruto nem o stderr bruto são publicados.

**Limite do resultado:** `HOST_GATES_PASS_EXTERNAL_STILL_UNVERIFIED` prova somente preflight local do host. OAuth Bling real, política do CNPJ/unidade do teste, A1 e resposta da SEFAZ permanecem gates próprios.

**Custos:** não há créditos do Desktop Commander envolvidos. Execuções GitHub Actions podem consumir minutos/recursos do plano contratado; confirmar limites e política da conta, sem pressupor custo zero ilimitado.

## C. Contingência VNC oficial da Contabo

Na indisponibilidade de SSH, entrar em `my.contabo.com`, localizar a VPS e verificar `Servers & Hosting → VPS/VDS → More → VNC control`. Segundo a documentação oficial, VNC exige um aplicativo cliente externo e a habilitação pode exigir reinicialização. Não reiniciar a VPS nem habilitar VNC em horário produtivo sem aprovação e janela segura. Preferir SSH se funcional.

Referências oficiais:
- https://contabo.freshdesk.com/en/support/solutions/articles/103000337806-how-do-i-enable-disable-vnc-for-my-server-
- https://contabo.freshdesk.com/en/support/solutions/articles/103000407800-how-to-connect-to-your-server-using-vnc

## Critério de aceite do Plano B

- [x] Branch `main` efetivamente protegida e GitHub environment com required reviewers (antes de instalar secrets).
- [x] Comandos SSH de somente leitura executados na VPS correta, com identidade do host verificada.
- [x] Instalação root-owned dos três scripts, ancestralidade confiável e sudoers de comando único sem argumentos (aprovação específica).
- [x] Usuário SSH sem grupo Docker e sem sudo geral; chave exclusiva com forced command, sem shell interativo e sem forwardings.
- [x] GitHub environment e secrets configurados fora do Git, com aprovação quando suportada.
- [x] Execução do workflow em `main`, com SHA `production` correto, PASS/NO_GO real (não simulação).
- [x] Audit trail persistente e classificação de erros sem informações confidenciais.
- [ ] Após verificação do host, gates separadamente autorizados para migration, OAuth, Worker e A1/homologação.

**Canal Plano B validado; Bling operacional e homologação continuam NO-GO enquanto não houver evidência.** Nenhuma parte do Plano B autoriza merge na branch `production`, mudança em firewall/DNS, instalação de credenciais ou emissão fiscal.
