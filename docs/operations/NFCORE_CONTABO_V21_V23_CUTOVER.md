# NFCore — transição v21 → v23 / recuperação pré-cutover

CURRENT confirmado em 18/11/2026: produção `ea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599`, schema v21, restore físico básico aprovado (53 tabelas). Candidata contém v22 (numeração DPS) e v23 (delegação A1). O deploy code-only atual não aplica DDL e seu rollback de API/Portal antigos não aceita o novo schema. O worker também precisa ser tratado como parte da mesma release.

## Gate novo (CI, sem tocar a VPS)

`scripts/ci/rehearse_v21_v23_cutover.sh` utiliza o código histórico exato e as imagens candidatas da própria CI. Constrói a base v21 pela autoridade original, usa PostgreSQL descartável em rede Docker Internal=true, backup/restore canônicos e guard de migration da candidata. Prova catálogo, preservação de tabelas e sentinel, idempotência, API runtime readiness, Worker ONESHOT, rejeição do rollback de imagem antiga sobre v23 e restauração para outro banco v21. Não é homologação fiscal, não utiliza credenciais GSM, não acessa a Contabo e não prova worker contínuo ou recuperação pós-reabertura.

## Sequência de implantação proposta — NÃO EXECUTAR antes de certificar

1. Consolidar #468/#498, verificar SHA exato em CI e parecer independente. Preparar os três artefatos API/Portal/Worker e fixar seus IDs, preservar composição efetiva, A1, políticas, confiança pública, segredos e mounts. Verificar cron/lock e plano de retorno. Não promover production antecipadamente (auto-pull).
2. Ensaiar o SHA final em ambiente isolado, incluir a jornada Web e os gates operacionais aplicáveis. Provar backup externo e recuperação, inventário de consumidores/leases e preservação da numeração fiscal anterior por emitente/município/ambiente/série. Não copiar credenciais produtivas para staging.
3. Aprovação humana específica da janela, DDL e release. Manter o cron code-only impedido de concorrer, adquirir lock exclusivo do deploy, fechar ingressos mutantes (incluindo integrações/webhooks), pausar consumidores com encerramento governado e comprovar ausência de writers locais/remotos antes do snapshot. Preservar DB anterior, volumes e imagens. Backup fresco, checksum e restore isolado comprovados; inventariar estado e mensagens externas incertas.
4. Aplicar pelo guard canônico `--apply` com flags de aprovação exclusivamente no processo one-shot, mantendo Bling opt-in intacto; validar ledger v23, tabelas, Cakto e invariantes. Não editar ledger, criar tabelas manualmente nem habilitar integrações fiscais.
5. Subir os três componentes com os artefatos certificados e validar health/readiness, smoke, segurança e isolamento antes de reabrir tráfego/consumidores. Verificar configuração real e publicar SHA/IDs somente após comprovação. Aprovação humana Go/No-Go.
6. Se um gate falhar **antes de qualquer escrita pós-snapshot ou efeito fiscal externo**, manter writers parados, recuperar snapshot em banco separado, verificar v21 e dados, direcionar a composição anterior completa à base recuperada apenas depois de provar isolamento/consistência. Não fazer restauração destrutiva automática sobre a base original. Reiniciar/reabrir somente após validação.
7. Depois de reabrir tráfego, o snapshot pré-cutover NÃO é rollback seguro: nenhuma restauração sobre dados novos, nem emissão por versão antiga sem garantias de numeração. Preferir suspensão governada e recuperação/forward fix; restauração pós-cutover exige reconciliação de dados e efeitos externos, aprovação e procedimento específico.

Este runbook define a fronteira segura; não concede autorização, não automatiza DDL produtiva e não encerra os gates físicos da Contabo, GSM, PKI/SEFIN, A1, EGM ou homologação. O ensaio automatizado deve ficar verde no HEAD exato.

## Controles operacionais disponíveis (E2/E6, 19/11/2026)

- **Congelar o cron na janela:** `touch /opt/fm/nfcore/.deploy-freeze` (ou o caminho definido em `NFCORE_DEPLOY_FREEZE_FILE`). Enquanto o arquivo existir, o `deploy.sh` do cron registra `FROZEN` e não faz nada. `--check`, `status` e o `--coordinated` aprovado continuam funcionando. Para reabrir, remova o arquivo.
- **Uma execução por vez:** o `deploy.sh` toma um `flock` em `/opt/fm/nfcore/.deploy.lock`. Se outra execução estiver rodando, o cron registra `SKIP` e o `--coordinated` é bloqueado com código 42.
- **Numeração da DPS após restaurar um backup:** antes de reabrir a emissão, descubra o último número de DPS realmente enviado para cada CNPJ, município, série e ambiente (pela SEFIN ou pelo portal municipal). Rode `scripts/admin/raise_dps_counter_floor.py` primeiro sem `--apply`, confira, e depois com `--apply`, informando quem aprovou e a referência. O contador só sobe e o comando fica auditado.

