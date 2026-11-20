# MFA (app autenticador) no portal

## Regra aprovada (Fábio, 20/11/2026)

Aprovada depois de comparar Conta Azul, Omie, Domínio e Bling.

- **Fator:** código TOTP de app autenticador (Google Authenticator, Microsoft Authenticator, Authy, 1Password). Não usa SMS.
- **Obrigatório para:** dono, administrador, administrador da plataforma e qualquer perfil com `certificate.manage` ou `document.issue` (hoje, também o operador).
- **Opcional para os demais.** O dono pode exigir o app de todos da empresa em **Segurança**.
- **Lembrar este navegador:** 30 dias. O token fica num cookie `HttpOnly`, `Secure`, `SameSite=Strict`, restrito a `/v1/auth`, e o banco guarda só o hash.
- **Step-up:** pede um código novo, válido por 5 minutos na sessão, antes de:
  - enviar ou trocar o A1;
  - cadastrar o perfil fiscal, declarar o regime ou trocar o CRT;
  - criar ou alterar usuários;
  - decidir egress de produção;
  - mudar a política de MFA, gerar novos códigos de recuperação ou resetar o MFA de um membro.
- **Recuperação:** 10 códigos de uso único, mostrados uma única vez. Quem tem `user.manage` pode resetar o MFA de outro membro (celular perdido), com step-up. O reset encerra as sessões desse membro.

## Segurança

- **Segredo TOTP:** cifrado com AES-GCM usando a chave externa `NFCORE_HUMAN_MFA_KEY_BASE64` (32 bytes, separada da chave do A1). O AAD é a conta, então o segredo não pode ser movido para outra conta.
- **Proteção contra repetição:** cada passo de 30 s é aceito uma vez só, por um UPDATE condicional (`last_step`).
- **Concorrência:** com dois workers, só um aceita o mesmo código. O teste PostgreSQL comprova isso.
- **Desafio de login:** uso único, vale 5 minutos e trava depois de 5 erros. A sessão só é criada depois do segundo fator.
- **Força bruta:** o step-up e a confirmação da ativação ficam limitados a 5 tentativas a cada 5 minutos.
- **Sessões antigas:** uma sessão aberta antes de ligar o MFA, de quem é obrigado a usá-lo, recebe `MFA_ENROLLMENT_REQUIRED` em todo o portal até ativar o app.
- **Risco aceito:** na primeira ativação, quem tem só a senha pode cadastrar o próprio app, o mesmo comportamento dos concorrentes. A mitigação é ligar o MFA logo após a virada e cada pessoa ativar no primeiro acesso.

## Como ligar (exige migração 24 — aditiva)

O MFA vem **desligado**. A virada v21→v23 certificada fica igual; a v24 só entra quando o MFA for ligado.

1. **Gerar a chave no servidor, sem exibir:** `head -c 32 /dev/urandom | base64 > /opt/fm/secrets/nfcore-mfa.key && chmod 600 /opt/fm/secrets/nfcore-mfa.key`. Fazer o backup da chave junto do cofre: perder a chave obriga todos a reativar o app.
2. **Aplicar a migração 24** pelo guard governado, com `NFCORE_HUMAN_MFA=enabled`, `NFCORE_SCHEMA_MIGRATION_APPROVED=true` e, em produção, `NFCORE_PRODUCTION_APPROVAL=PRODUCTION_APPROVED`. A 24 só cria tabelas novas.
3. **Configurar a API** com `NFCORE_HUMAN_MFA=enabled` e `NFCORE_HUMAN_MFA_KEY_BASE64`. Sem a v24, a API não sobe (fail-closed).
4. **No próximo login**, dono, administradores e operadores verão a tela de ativação com QR code.

Com o MFA desligado, a v24 instalada é tratada como drift. A volta atrás é desligar a variável. As tabelas aditivas podem ficar.
