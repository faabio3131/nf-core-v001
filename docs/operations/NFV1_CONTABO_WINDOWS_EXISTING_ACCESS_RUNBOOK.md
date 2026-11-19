# Acesso existente Contabo pelo Windows — checkpoint para não perder a operação
**Data:** 2026-11-10 | **Produto:** FM NFCORE V1 | **Servidor:** vmi3692211

> Documento operacional versionado, **sem senhas, chaves privadas ou tokens**. O objetivo é preservar o acesso **já existente** antes de configurar o Plano B automatizado na PR #421. Não substituir a rotina funcional por scripts experimentais.

## Autoridades e estado

- VPS alvo conferida visualmente no painel Contabo pelo proprietário: `vmi3692211`, IPv4 `13.140.234.22`.
- Usuário de operação citado e utilizado nos acessos anteriores: `fmadmin`.
- Diretório da aplicação no servidor: `/opt/fm/nfcore`.
- Terminal do PC: Windows PowerShell, com OpenSSH disponível.
- Pasta local das identidades SSH do usuário atual: `$env:USERPROFILE\.ssh`.
- Arquivos locais verificados por teste de existência em 10/11/2026: `fm_contabo2`/ `fm_contabo2.pub`, `contabo_admin_ed25519`/ `contabo_admin_ed25519.pub`, `fmcc_contabo_deploy_20261024`/ `fmcc_contabo_deploy_20261024.pub`. O teste de existência **não** comprova permissão no servidor ou validade criptográfica.
- Teste com `contabo_admin_ed25519` forçada para `fmadmin@13.140.234.22`: `Permission denied (publickey)`. **Não insistir nem concluir que o acesso anterior foi perdido.**
- **CONFIRMADO PELO OPERADOR EM 10/11/2026, 20h25 BRT:** `ssh -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -i "$env:USERPROFILE\.ssh\fm_contabo2" fmadmin@13.140.234.22 "whoami"` solicitou a frase-senha local e retornou **`fmadmin`**, sem erro. Isto comprova execução de comando remoto read-only com esta identidade e endpoint. Não comprova estado de Docker/deploy nem conexão pelo GitHub Actions.
- Relato do proprietário: o acesso normal é realizado por **script local e senha digitada interativamente**. **Nome/caminho exatos desse script ainda não foram identificados nesta retomada; não substituí-los por suposição.**
- Histórico operacional recuperado: em 01/11/2026 foi registrado acesso funcional após `ssh-add "$env:USERPROFILE\.ssh\fm_contabo2"` e em seguida `ssh fmadmin@13.140.234.22`; a senha solicitada nesse caso era a **frase-senha da chave privada**, fornecida somente no terminal. Há ainda executores Python históricos em Downloads que pediam senha SSH; eles **não devem ser executados apenas para testar conexão**, pois têm ações administrativas.
- Outro histórico 24/10/2026 usou `ssh -tt fmadmin@13.140.234.22` para executar scripts de autorização/deploy no host. Esses scripts causavam alterações e não fazem parte do diagnóstico de acesso.

## Retomada segura sem Desktop Commander

Primeiro, localizar o script **exato** usado pelo operador antes de escolher outro método. Se o usuário optar por reproduzir o método de chave SSH comprovado no histórico, o diagnóstico somente leitura, sem senha embutida, é:

```powershell
# Verificar somente se o agente tem identidades; erros não alteram nada.
ssh-add -l

# Se não houver a identidade esperada, carregá-la: a senha da chave será
# solicitada pelo próprio PowerShell, nunca pelo ChatGPT.
ssh-add "$env:USERPROFILE\.ssh\fm_contabo2"

# Verificação de identidade do host habilitada, sem aceitar host desconhecido.
ssh -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -i "$env:USERPROFILE\.ssh\fm_contabo2" fmadmin@13.140.234.22 "whoami"
```

Se o serviço `ssh-agent` estiver parado, `ssh-add` pode falhar com erro de agente. **Não alterar configuração de serviços/registro nem elevar privilégios automaticamente.** Em vez disso, a operação de leitura pode testar a chave direta com `ssh -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -i "$env:USERPROFILE\.ssh\fm_contabo2" fmadmin@13.140.234.22 "whoami"`; isso pode pedir a frase-senha da chave local. Conectar com senha do servidor por script diferente requer localizar esse script e avaliar seu conteúdo sem exibir credenciais.

A opção `StrictHostKeyChecking=yes` exige que a identidade do servidor tenha sido validada e confiada previamente. Uma falha de host key **não** deve ser contornada com `-o StrictHostKeyChecking=no`.

**Critério de êxito atingido pelo operador em 10/11/2026:** comando remoto retornou `fmadmin`. O caminho **PC Windows → SSH → Contabo** está comprovado; **Work/cloud → SSH** continua `NOT_VERIFIED`. Não copiar a chave privada existente para o GitHub.


## Segredos — salvamento correto sem perda de acesso

- **Não versionar senha, frase-senha, token, chave SSH privada, `authorized_keys` ou `.env` em Git/GitHub.**
- Manter arquivos privados apenas em `%USERPROFILE%\.ssh` com permissões Windows adequadas; realizar backup **criptografado e controlado** em cofre de credenciais do proprietário, conforme política da FM Tecnologia.
- Guardar no cofre a senha/frase-senha com rótulo claro, distinguindo: senha SSH do servidor, frase-senha da chave privada, e senha usada por `sudo`. Nunca presumir que sejam iguais.
- Registrar no repositório apenas o procedimento, a chave **pública** quando necessário, os caminhos **não secretos**, as permissões necessárias e o resultado de testes.
- Não alterar ou remover o acesso administrativo original até que uma alternativa independente esteja configurada e testada de ponta a ponta.
- No Plano B, credencial de auditoria exclusiva deverá ser criada e armazenada em GitHub Environment protegido após ruleset da `main`, revisão humana e bootstrap no host, **nunca reaproveitando a chave privada `fm_contabo2` do operador**.

## Próxima ação documentada

1. Identificar o caminho/nome do script original no Windows e revisar apenas o fluxo de conexão (não executar instaladores antigos).
2. Comprovar um comando read-only de login `fmadmin` ao host `13.140.234.22`.
3. Preservar o acesso original intacto e então ativar a nova identidade SSH restrita da PR #421, com aprovação específica para mudanças administrativas no host.
4. Atualizar este runbook com o comando **realmente comprovado** e com evidências sem segredos.

**Este documento não certifica acesso nem autoriza modificações na VPS.**
