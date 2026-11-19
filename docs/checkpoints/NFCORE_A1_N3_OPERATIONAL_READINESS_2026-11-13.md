# NFCore A1 / SISTEM — N3, persistência e recuperação (13/11/2026 UTC)

## Decisão N3 do proprietário

Autorização explícita na conversa de 12/11/2026 (America/Sao_Paulo):
auditar cofre A1 na Contabo em modo somente leitura, corrigir persistência/backup
se necessário, executar gates, e **somente após comprovação técnica** realizar
merge e deploy da PR #462 para testar cadastro em homologação.

Limites: não permite emissão fiscal em tpAmb=1, migration fiscal/v22, afrouxar
auth/RBAC/tenant/CSRF, tocar nas branches dos agentes A/B nem copiar segredo
para Git/chat/log. O arquivo PFX da SISTEM existe fora do servidor, mas
não existe prova de upload ou armazenamento no cofre operacional.

## CURRENT (documentação e código observáveis)

- Repo: `faabio3131/nf-core-v001`, PR #462, branch
  `fix/nfcore-a1-status-proof-sistem-20261112`.
- Baseline antes do N3: `main@7cf89e7fa85c14ddf36654052b6830b9fae9b478`;
  `production@ea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599`.
- PR #462, antes dos novos arquivos N3:
  `5e108da20e3cbecbc637ced2c9bbca68b3ec3559`,
  CI #2625 **SUCCESS** e demais quatro gates aprovados.
- `EncryptedA1Vault` permanece autoridade única, criptografia AES-GCM com
  AAD por namespace/tenant/unidade/ambiente/CNPJ e chave externa de 32 bytes.
- `portal/app.js` tinha regex inválida para .pfx/.p12 na versão publicada;
  a PR corrige e acrescenta GET autorizado `/v1/portal/certificates/a1/status`.
- Compose versionado original não tinha volume A1; backup versionado cobre
  somente banco. Isto **não comprova** a configuração do host real.
- Auditoria operacional via Desktop Commander impossibilitada nesta sessão:
  dispositivo `DESKTOP-URCTNQ1` offline; cota remota restante 0%.
  **Nenhuma sessão SSH, modificação no cofre, restart ou deploy foi feita.**

## Evidência nova da auditoria Contabo — 13/11/2026

Na VPS `vmi3692211`, o auditor A1 instalado via Plano B retornou
`DEPLOY_SHA_EXACT=PASS` e `A1_VAULT_INFRA_GATE=PRECHECK_LOCAL_PARCIAL`.
`docker inspect` confirmou **um bind RW** com origem e destino
`/var/lib/nfcore/vault`. Diretório/permissões/formato da chave presentes;
**nenhum `*.a1.enc` no instante da leitura**. Backup externo, custódia
externa da chave e recuperação isolada seguem **NÃO VERIFICADOS**.
A configuração efetiva do Compose do host ainda deve ser inspecionada;
a versão no Git de `compose.prod.yml` não documenta esse bind.

**Decisão de continuidade:** preservar o bind atual; não criar segundo cofre,
não trocar `NFCORE_A1_VAULT_DIR` para `/var/lib/nfcore/a1-vault`.
Reconciliação de overlay opt-in: usar destino
`/var/lib/nfcore/vault`, com a fonte `NFCORE_A1_VAULT_HOST_DIR`
definida para a mesma origem auditada e prova do Compose efetivo antes de
recreate. Evitar duplicar a montagem se o Compose host já a declara.

## Engenharia preparada na própria PR #462

- `deploy/contabo/compose.a1-vault.opt-in.yml`: overlay **não ativado**,
  bind preexistente com `create_host_path: false`, destination fixa
  `/var/lib/nfcore/a1-vault`, usa mesmo `nfcore-api` e Vault canônico.
- `deploy/contabo/a1-vault-ops.py`: operação host-side com restic para
  backup cifrado remoto de `*.a1.enc` e restauração **somente em diretório
  temporário isolado**, comparando SHA-256 dos registros cifrados.
  Recusa diretório não restrito, owner inesperado, symlinks, arquivos
  desconhecidos, repositório local e senha restic exposta em permissões.
  Não lê nem registra A1 em claro, senha do PFX ou chave mestra.
- `tests/web/test_a1_vault_infra_contract.py`: testes de contratos,
  fail-closed, Compose e recuperação sintética. **CI final do novo HEAD
  ainda deverá ser verificada após as alterações.**

### Procedimento obrigatório no host: não trocar a ordem

1. **Somente leitura.** Confirmar `.deployed`, `production`, revisão ativa,
   contêiner, `docker inspect` sem imprimir `.env`, existência de volume,
   owner/permissões, presença de registros cifrados e se a chave mestra está
   configurada; executar
   `python3 deploy/contabo/audit-a1-vault-readonly.py` quando o script estiver
   disponível no checkout operacional. Saída parcial NÃO comprova restore.
2. Se houver registros `*.a1.enc` em camada efêmera, **preservá-los antes
   de montar qualquer volume que os ocultaria**. Congelar escritas durante a
   transferência controlada somente de ciphertext para o destino durável e
   comparar hashes/contagens, sem trocar a chave mestra. Se a procedência
   for ambígua, suspender substituição do contêiner; não repetir upload.
3. Prover diretório dedicado **fora do checkout Git e da camada efêmera**,
   na instalação auditada `/var/lib/nfcore/vault`, dono UID/GID 10001,
   permissão 0700 (arquivos 0600). Usar mesmo caminho como
   `NFCORE_A1_VAULT_HOST_DIR` na configuração privada do Compose.
4. Prover destino restic **realmente fora da VPS** com autenticação própria:
   `RESTIC_REPOSITORY` remoto e `RESTIC_PASSWORD_FILE` absoluto,
   regular e permissão 0600. O backup restic é cifrado novamente com senha
   **diferente da chave AES-GCM do A1**. Inicializar repositório por
   procedimento operacional autorizado. Nunca publicar essas variáveis
   com valores reais no GitHub.
5. Executar, sob identidade host autorizada com acesso à pasta 10001 e ao
   repositório, `python3 deploy/contabo/a1-vault-ops.py backup` e
   `python3 deploy/contabo/a1-vault-ops.py restore-test`. A segunda operação
   restaura a um diretório temporário e valida equivalência de ciphertext;
   não escreve no Vault vivo. Verificar existência de cron/systemd de backup
   recorrente, retenção e alertas, sem confundir script com automação ativa.
6. Preservar cópia **separada da VPS e do repositório restic** da chave mestra
   `NFCORE_A1_VAULT_KEY_BASE64`, sob custódia governada e acesso restrito.
   Validar em ambiente isolado que ciphertext restaurado + **mesma chave**
   recuperam A1 sintético ou autorizado, com escopo correto, sem imprimir
   segredo/PKCS#12. Sem essa prova, o backup do Vault NÃO está certificado.
7. **Só após todos os gates acima:** posicionar overlay ao lado do compose
   efetivo e habilitá-lo na mesma composição canônica, sem trocar
   `NFCORE_A1_VAULT_KEY_BASE64`. Validar `docker compose config`,
   `docker inspect` após subida, diretório durável, leitura por escopo,
   rollback, health/readiness, e nova auditoria sem segredos.
   Não alterar o compose efetivo automaticamente a partir do GitHub.
8. Revalidar CI integral no HEAD final da PR. Se aprovado, verificar merge
   em `main`, certificar o HEAD integrado e promover à branch
   `production` **exclusivamente dentro deste N3** e com o preflight
   do cofre comprovado; deploy automático pull só ocorre após a promoção.
   Conferir `.deployed`, GET `/health/ready`, Portal, resposta autorizada
   `stored/absent/unverifiable` no tenant/unidade/ambiente do piloto.
9. Upload do PFX verdadeiro da SISTEM é uma operação sensível separada,
   executada pelo operador autorizado pelo Portal, uma vez, somente em
   `homologation`. Comparar resposta POST com segundo GET e após
   recriação controlada do contêiner. **Não realizar emissão fiscal real**
   nem proclamar homologação por resultado sintético.


## Ensaio mínimo sem serviço externo — ciphertext A1 (N3)

Na PR #462, o mesmo \`deploy/contabo/a1-vault-ops.py\` ganhou **exportação
offline de ciphertexts já AES-GCM**, sem alterar o EncryptedA1Vault:
\`offline-export /caminho/absoluto/novo.zip\` e
\`offline-restore-test /caminho/absoluto/arquivo.zip\`.

- Exige pelo menos um registro \`*.a1.enc\`, modo privado e UID do Vault;
  rejeita arquivos inesperados, symlinks e destino de exportação existente.
- O pacote é ZIP **sem criptografia adicional**: contém apenas os ciphertexts
  AES-GCM do Vault, **nunca** a chave mestra ou um PFX em claro. A chave
  permanece sob a custódia externa já comprovada. O pacote não oferece
  sigilo se a chave mestra for comprometida; guarde ambos separados.
- A restauração de ensaio vai para diretório temporário isolado, valida nomes
  restritos, manifest, tamanhos e hashes, e **não escreve no Vault vivo**.
- O teste automatizado integra um PFX sintético válido ao EncryptedA1Vault,
  exporta, restaura em caminho separado e resolve **com a mesma chave sintética**,
  incluindo negativa de outro tenant e deteção de adulteração. Nenhum
  certificado de cliente ou chave mestra real participa da CI.
- \`CHECKSUM_PASS\` não certifica restore criptográfico real nem cópia offsite.
  \`offline-export\` imprime \`OFFSITE=NOT_VERIFIED\` até o proprietário
  transferir o pacote cifrado para armazenamento fora da VPS e confirmar hashes.
- Com o Vault real vazio na auditoria, **não existe backup real de registro A1**
  a validar ainda. Após o primeiro upload legítimo, executar o export offline
  e copiar para PC/USB em local seguro, sem substituir as cópias da chave mestra.
  Backup agendado/com retenção e prova de recuperação de certificado real
  permanecem pendentes.

**Atenção:** exportar para pasta privada separada do Vault, nunca dentro dele;
não incluir dados reais, certificados ou segredos no GitHub ou logs.

## Go/No-Go

**NO-GO operacional enquanto host/backup externo/escrow/restore não tiverem
evidência.** A correção da regex e CI verde não substituem persistência real.

O alvo é publicar a mesma Web/API com cofre durável, recuperável e testado,
sem criar segundo segredo, segundo Vault, aplicação paralela ou atalho
de segurança.

Registro final pendente: SHA final da PR #462, CI, prova de host, prova de
backup externo, prova de escrow, prova de restore, merge, promoção,
deploy e readback no escopo da SISTEM.
