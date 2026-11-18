# NFCore — Diagnóstico do cadastro A1 / SISTEM (12/11/2026)

**Estado:** IMPLEMENTED_NOT_CERTIFIED / DEPLOY NÃO AUTORIZADO.
**Identidade do cliente piloto:** SISTEM (CNPJ mascarado), sem armazenar segredos neste documento.
**Escopo:** Cadastro A1 via Portal, unidade SISTEM - MATRIZ, ambiente Homologação.
**Fonte de verdade:** código atual do GitHub, validação de runtime ainda pendente.

## Fatos confirmados

- A1 da SISTEM foi exportado do Windows em PKCS#12 (.pfx) com chave privada.
  O usuário confirmou êxito na exportação; isso não comprova armazenamento no servidor.
- Capturas do Portal mostram a unidade e ambiente selecionados, mas nenhuma
  mensagem de gravação e lista genérica de configurações vazia. Essa lista
  **não consulta** o arquivo criptografado no cofre A1.
- A branch `production` na data tinha POST
  `/v1/portal/certificates/a1`, que responde com `status=stored`,
  `expires_at` e `fingerprint_sha256` após provisionar o A1.
  **Não havia GET de consulta/readback** nem exibição persistente do estado.
- `EncryptedA1Vault` utiliza AES-GCM e arquivos cifrados com escopo de
  tenant, unidade, ambiente e CNPJ. Seu armazenamento está condicionado a
  `NFCORE_A1_VAULT_DIR` e `NFCORE_A1_VAULT_KEY_BASE64`.
- A composição versionada `deploy/contabo/compose.prod.yml` não evidencia
  volume durável montado para o cofre; `backup.sh` e `restore-test.sh`
  só demonstram cobertura PostgreSQL.
  **Não se verificou a configuração efetivamente implantada na Contabo.**

## Correção interna proposta

- Criar `EncryptedA1Vault.inspect`: busca o registro somente no escopo
  autorizado, confirma decriptação e revalida o PKCS#12, retornando apenas
  metadados não secretos; ausente é distinto de ilegível.
- Criar GET autenticado e autorizado
  `/v1/portal/certificates/a1/status` para unidade, CNPJ e homologação.
  Respostas: `stored` (validade/fingerprint), `absent` (sem arquivo)
  ou erro `A1_STATUS_UNVERIFIABLE` (existe mas não recuperável).
- Adicionar ao formulário o botão **Verificar A1 armazenado**, sem
  solicitar arquivo ou senha novamente. Após POST, executar uma segunda
  leitura GET e comparar a impressão digital, evitando confirmação apenas
  por HTTP 200. Mensagens não devem prometer backup ou persistência pós-deploy.
- Tratar `InvalidCertificateMaterialError` como falha controlada de
  validação A1 (422), sem propagar stacktrace ou qualquer conteúdo do PFX.
- Testes sintéticos com certificado não real: não existência, gravação, leitura,
  isolamento tenant/unidade, reinício do objeto de cofre, corrupção, RBAC,
  resposta a PFX inválido, contrato frontend.

## Limites / gates ainda abertos

- [ ] CI completa no HEAD exato da PR; testes dirigidos concluídos.
- [ ] Conferir no runtime da Contabo apenas a presença de configuração
  completa de vault, sem imprimir, exportar ou registrar a chave mestra.
- [ ] Confirmar caminho `NFCORE_A1_VAULT_DIR` em mount persistente privado
  fora da camada efêmera do container; permissões e owner auditados.
- [ ] Backups cifrados do diretório do cofre e da chave mestra **separados**
  da VPS, com retenção controlada e restore real em ambiente isolado.
- [ ] Aprovação do proprietário sobre estratégia futura de custódia A1
  (Secret Manager ou KMS envelope); não modificar custódia por impulso.
- [ ] Merge e publicação autorizados separadamente, com smoke somente leitura.
- [ ] GET real no ambiente do piloto retorna `stored` e confirma readback;
  `absent` ou `unverifiable` continuam como pendências explícitas.
- [ ] ICP-Brasil: cadeia/revogação e homologação oficial fiscal externas.

**Nenhuma senha, PKCS#12, chave mestra, serial ou fingerprint real do piloto
foi colocado em código, documento, issue, PR ou chat.**


## Auditoria documental/infraestrutura de 12/11/2026 — resultados

**RUNTIME NÃO AUDITADO**: o Desktop Commander mostrou o computador
DESKTOP-URCTNQ1 offline e a cota mensal de execução remota em 0%.
Não houve sessão SSH, leitura do contêiner real ou inspeção do vault da SISTEM.
Assim, **não existe prova nem de presença nem de ausência do A1** no servidor.

Evidências do código de `production@ea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599`:

1. `runtime/api.py` cria `_entrypoint_certificate_vault` através de
   `EncryptedA1Vault.from_environ()`; sem ambas as variáveis
   `NFCORE_A1_VAULT_DIR` e `NFCORE_A1_VAULT_KEY_BASE64`,
   nenhum Vault é injetado no Portal. A ausência de uma delas, isoladamente,
   provoca indisponibilidade de configuração.
2. `deploy/contabo/compose.prod.yml`: o serviço `nfcore-api` usa
   `.env`, mas **não declara volume durável do cofre**, ao contrário do
   volume do PostgreSQL.
3. `deploy/contabo/deploy.sh`: o processo de deploy faz `docker compose
   up -d nfcore-api nfcore-portal`, o que pode recriar o contêiner.
   Um A1 salvo somente na camada gravável do contêiner não está protegido
   contra substituição do contêiner. Isso é um **risco condicional**;
   a configuração efetiva do host pode ter sobreposições não versionadas.
4. `deploy/contabo/backup.sh` usa `pg_dump` e não inclui registros
   `*.a1.enc`. `restore-test.sh` só testa a restauração do PostgreSQL;
   ele não prova restauração do Vault e da chave mestra.
5. A função `EncryptedA1Vault.provision` cria arquivo criptografado
   `*.a1.enc` com permissões restritas e AEAD vinculada a
   host/tenant/unidade/ambiente/CNPJ. O código não prova que a gravação
   efetivamente ocorreu no runtime do piloto.

**Instrumento de preflight read-only criado (não executado na VPS):**
`deploy/contabo/audit-a1-vault-readonly.py` na PR #462. Ele lê o
`docker inspect nfcore-api` sem imprimir seu conteúdo e inspeciona apenas
metadados de diretório e contagem de arquivos cifrados, sem abrir A1.
Informa somente SIM/NAO/NAO_VERIFICADO. Mesmo que esse preflight passe,
o readback específico da empresa e o restore em ambiente isolado
continuam obrigatórios. Os resultados do preflight **não substituem**
provas de backup externo ou cadeia ICP-Brasil.

**Estado real do piloto:** `A1_STATUS_UNVERIFIED`.
**Estado do código de verificação:** `IMPLEMENTED_NOT_CERTIFIED`
até CI completa no HEAD final.
**Próximo gate:** acesso autorizado à Contabo somente leitura, inspeção do
mount efetivo, presença de arquivos cifrados, localização do backup externo,
comprovação de cópia protegida da chave mestra e teste isolado de recuperação.
**Proibido** reiniciar, substituir contêiner, limpar diretório, reenviar PFX,
imprimir `.env`/secrets ou efetuar deploy durante a auditoria.
