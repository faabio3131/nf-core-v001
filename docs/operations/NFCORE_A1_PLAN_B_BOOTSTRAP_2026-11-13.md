# N3 — Bootstrap independente do PC para auditoria A1 (13/11/2026)

## Escopo
Este bloco **habilita o caminho de auditoria**, não publica a aplicação A1,
não modifica o Vault e não muda as configurações de produção.

Decisão humana N3 em 13/11/2026: instalar o auditor A1 na Contabo, utilizando
o Plano B restrito, sem depender de Desktop Commander. Este PR independente
foi extraído seletivamente da PR #462 para resolver a dependência circular:
auditar a persistência ANTES de efetuar qualquer merge/deploy da #462.

## Evidência e CURRENT
- `faabio3131/nf-core-v001`, base `main@7cf89e7fa85c14ddf36654052b6830b9fae9b478`.
- `production@ea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599` na
  verificação inicial: revalidar imediatamente antes da auditoria.
- Plano B SSH original autenticado na Contabo em 11/11/2026,
  run `43118619235`, baseline de API/Portal/DB aprovado;
  **Bling operacional não aprovado** nesse run. Não havia auditoria A1.
- No momento de criar este bloco, o acesso genérico à VPS **não**
  estava disponível pelo Desktop Commander (PC offline, cota 0%).
- `main` e `production` protegidas. Verificar environment
  `nfcore-contabo-audit` e segredos sem ler seus valores.
- A CI da PR #462 `#2660` foi SUCCESS com 4106 PASS, 3 SKIP;
  isso **não** comprova a instalação A1 no host.

## Alterações permitidas
- Reutilizar o forced-command SSH existente (`nfcoreaudit`).
- Adicionar verbo de auditoria fixo `nfcore-a1-audit`, sem shell remoto.
- Adicionar auditor Python somente leitura com SHA de `.deployed` pinado,
  booleanos de presença de mount, permissões e chave de formato válido.
- Adicionar workflow manual em `main` protegida e ambiente isolado,
  com saída estritamente sanitizada.
- Preservar comandos Bling e GSM, sem ampliar acesso a Docker para o usuário SSH.

## Instalação raiz requerida (NÃO executada pelo GitHub)

A mesma identidade de SSH de auditoria não pode instalar arquivos: ela tem
um comando forçado e `sudo` limitado ao helper root-owned. Não contornar
essa proteção. A instalação inicial/atualização de helpers exige
**canal administrativo autenticado da Contabo** (conta de operação distinta
e autorizada) e validação da identidade do host.

Com `main` do bootstrap aprovado e integrada, um administrador legítimo deve:

1. Confirmar a VPS `vmi3692211`, `/opt/fm/nfcore/.deployed`,
   SSH host fingerprint, o SHA exato de `production` e a presença
   atual dos scripts instalados em `/usr/local/libexec/nfcore-audit`.
   **Não imprimir arquivos de configuração nem segredos.**
2. Obter os três arquivos publicados do commit aprovado e conferir
   digests SHA-256 contra o commit revisado, **fora da árvore de
   implantação mutável**:
   - `deploy/contabo/host-audit-command.sh` → `ssh-gate.sh`
   - `deploy/contabo/root-host-audit.sh` → `root-audit.sh`
   - `deploy/contabo/audit-a1-vault-readonly.py` →
     `audit-a1-vault-readonly.py`
3. Fazer backup operacional dos arquivos existentes, preservar ownership
   root:root, modos 0555/0755, diretórios ancestrais não graváveis por grupo
   ou outros, sem symlinks; preservar `authorized_keys` e sudoers
   existentes, **não criar sudo irrestrito**. Nenhuma chave deve ser
   exibida em logs ou no chat.
4. Verificar que `nfcoreaudit` continua sem grupo `docker`, `sudo`
   ou `admin`. Executar auditoria de regressão dos antigos modos
   `nfcore-audit` e `nfcore-gsm-audit` pelo workflow original.
5. Acionar em Actions na branch protegida `main` o workflow
   **NFCore Contabo A1 Vault Read-only Audit (Plan B)** com o SHA
   de `production` atual. Ele valida SSH pinado, SHA, digest dos
   scripts e envia somente estados em vocabulário fechado.
   O programa remoto não pode retornar PFX, chave ou senha.
6. Se o preflight indicar montagens efêmeras, proteger registros existentes
   **antes** de qualquer Docker recreate ou alteração de volume. Após
   backup realmente remoto, escrow da chave mestra e restore isolado
   comprovados, seguir o runbook N3 na PR #462.

## Gate de fechamento
- Código, CI, revisão e merge da PR *deste bootstrap* são distintos
  da instalação física: **merge não é ativação operacional**.
- `A1_VAULT_INFRA_GATE=PRECHECK_LOCAL_PARCIAL` é sucesso **parcial**
  e **não** certifica backup offsite/escrow/restore real.
- `A1_VAULT_INFRA_GATE=REPROVADO_OU_INCONCLUSIVO` impede deploy da #462.
- Não promover `production`, reiniciar VPS, subir contêiner, fazer
  alterações fiscais ou enviar certificado antes dos gates reais.

Próximo registro obrigatório: PR de bootstrap, HEAD, CI, merge, instalação
do root-owned helper, workflow SSH, preflight A1 e plano de rollback.
