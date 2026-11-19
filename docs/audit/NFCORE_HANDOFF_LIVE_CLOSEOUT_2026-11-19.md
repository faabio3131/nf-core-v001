# NFCore — cronograma vivo e passagem de bastão

**Checkpoint recebido:** 19/11/2026, aproximadamente 15:20 UTC (12:20 BRT).  
**Repositório:** faabio3131/nf-core-v001.  
**Classificação:** passagem de bastão operacional CURRENT; não é certificação, autorização de release ou substituição do cronograma mestre.

**Ordem de leitura:** este documento inteiro, depois claude/nfcore-auditoria-codigo-2026-11-19.md (referência indicada no relatório recebido; indisponível nas duas branches de trabalho consultadas no registro), e os documentos CURRENT vinculados ao final. CI verde vale somente para o HEAD exato. Nunca declarar pronto por teste local. Não abrir PR sem pedido do proprietário. Não registrar PFX, senha, chave privada, token, cookie, conteúdo criptografado ou chave do Vault.

## 1. Estado das PRs e branches

| Item | Estado |
|---|---|
| [#564](https://github.com/faabio3131/nf-core-v001/pull/564), draft, base production, fix/portal-a1-upload-regex-20261119 | Corrige a validação de extensão A1: regex literal incorreta /\\.(pfx\|p12)$/i para /\.(pfx\|p12)$/i, em portal/app.js, com teste tests/test_portal_a1_upload_filter.py. HEAD c6bb04febc8d9c7ca8d2fc57d713436345aeb103, aberta e não mesclada, confirmado no GitHub. Teste local aprovado segundo o autor; CI integral nesse HEAD não verificada. Merge em production pode disparar deploy automático; exige aprovação explícita. |
| [#563](https://github.com/faabio3131/nf-core-v001/pull/563), draft, base integration/nfcore-a1-sp2-current-main-20261113 | FIS-03. CI vermelha em 2b0b82f por um teste (test_sp5_national_get_and_post_share_signed_receipt_verifier, assert antigo), segundo relatório recebido. Corrigido em 1da651e; HEAD 1da651e2e70f526ff290aea2421ea3a8215ac947, aberta e não mesclada, confirmado no GitHub. CI no HEAD não verificada. |
| fix/nfcore-eng-closeout-20261119 (sem PR; base #563 2b0b82f, conforme relatório recebido) | Commits b8590f1 (P1), 5f89f4f e 54f4fb3 (P2). Aproximadamente 2.670 testes locais passam, Ruff limpo, CI remota não rodada, conforme relatório recebido; resultados não reproduzidos nesta documentação. Não abrir PR sem pedido do proprietário. |

As duas branches de fechamento (fix/nfcore-eng-closeout-20261119 e work/nfcore-closeout-20261119) devem ser reconciliadas por conteúdo e ancestralidade, sem presumir integração. A existência deste documento na branch work não integra código das demais branches.

## 2. Entregue (código) — conforme passagem de bastão recebida

- **P1:** falha antes do envio vira FiscalPreDispatchError → documento REJECTED local (não fica preso em TRANSMITTING); 4xx estruturado da SEFIN deixa de ser escondido.
- **P2 (parcial):** transporte NFS-e Nacional ciente de ambiente (tpAmb 1/2 e URL). Produção só com NFCORE_NFSE_PRODUCTION_ENABLED=true, NFCORE_NFSE_SEFIN_PRODUCTION_URL (host oficial sefin.nfse.gov.br, validado) e autorização humana por célula exata (tenant, unidade, município), lida de NFCORE_NFSE_PRODUCTION_GRANTS_FILE (JSON no host; malformado = falha fechada). Composition root aceita escopo PRODUCTION só para provedor nacional. Portal permanece exclusivamente em homologação, de propósito (testes existentes exigem).
- Arquivos novos: gateway/nfse_national_environment.py; tests/runtime/test_p2_nfse_production_gate.py (28 testes); tests/runtime/test_p1_pre_dispatch_and_sefin_rejection.py.

## 3. Achados que bloqueiam produção ponta a ponta

- Validação do recibo NFSe XML aceita apenas perfil NT009 de produção restrita; falta pacote XSD oficial NFSe do perfil production-20260209; arquivos tipos* diferem entre pacotes. Sem isso não se comprova nota autorizada em produção. Faltam pins/PKI do signatário de produção.
- Consulta (nfse_national_query.py) e cancelamento/evento (nfse_nacional_event_homologation.py) fixos em homologação (URL e tpAmb=2).
- Corte de schema de produção 2026-12-01 exige revisão (xml/nfse_national_profiles.py).
- Vínculo do trial de staging (web/staging_gsm_binding_admin.py, not_after 2026-11-17) vencido: endpoint responde 409 em staging. Staging é ambiente de testes; Railway desligado 29/10, permanece nfcore-ensaio na Contabo, conforme relatório recebido. Não renovado; decisão do proprietário.

## 4. Jornada real com o certificado (em andamento)

Portal app.nfcore.com.br e API respondem 200, conforme relatório recebido. A1 recuperado no Windows com chave privada presente; exportação SISTEM_A1_RECUPERADO.pfx, 9.412 bytes, 19/11/2026 às 11:49 BRT. CNPJ emitente: 09107283000140. Vencimento mostrado pelo Windows: 12/11/2027. Tentativa de upload em Certificados → Homologação bloqueada pela validação frontend incorreta identificada na #564, antes de envio à API.

**Evidência operacional observada na captura do terminal:** container nfcore-api ativo/healthy; NFCORE_A1_VAULT_DIR apontava para /var/lib/nfcore/vault; busca por *.a1.enc no diretório não retornou nenhum arquivo. O upload não está comprovado, e o cofre consultado estava vazio naquele momento. Não confundir existência do diretório com armazenamento ou recuperação efetiva.

Senha e upload somente pelo proprietário no portal; não pedir senha no chat, não enviar PFX por GitHub e não excluir arquivo local. Após aprovação, CI e deploy da #564: Ctrl+F5, selecionar A1 e enviar, conferir confirmação de armazenamento, inspecionar arquivo criptografado no cofre e comprovar resolução/validação do A1 pelo backend no escopo correto. A mensagem de sucesso de upload sozinha não comprova recuperação. Se recusado, enviar captura sanitizada (cofre não configurado, vencido ou CNPJ divergente). Depois conduzir homologação autorizada: preparar, emitir, consultar, XML, cancelar, corrigindo falhas no código. Nenhuma transmissão fiscal real está autorizada por este documento.

## 5. Pendências de engenharia — ordem sugerida no relatório

- [ ] **P2 restante:** recibo/consulta/cancelamento em produção; depende de XSD oficial de produção.
- [ ] **P3:** semear numeração DPS por CNPJ/município/série/ambiente e trava contra restore sobre reservas fm_nfse_dps_*.
- [ ] **P4:** chave de proteção A1 fora de disco persistente; auditoria durável do upload/uso do A1; rate limit login/reset; fechar /internal, /runtime/profile, /docs; MFA/step-up.
- [ ] **P5:** política tributária instalável pela UI; traduzir erros NATIVE_NFSE_*; consulta NFS-e por referência; cadastro do emitente no fluxo correto.
- [ ] **P6:** retenções federais PIS/COFINS/CSLL/IRRF/INSS, vDesc, múltiplos serviços por DPS, sem inventar regra; respeitar contrato fiscal vigente.
- [ ] **P7:** trazer deploy.sh e restore-test.sh endurecidos da branch closeout (c8d0157, referência recebida ainda a conferir por diff); backup incluindo vault A1 e contadores; desligar cron durante janela autorizada; restore em nível de dados.
- [ ] **Fechamento:** suíte completa, Ruff, mypy, CI verde no HEAD exato de #563, #564 e closeout; reconciliar commits sem duplicar implementação, efetuar revisão independente.

## 6. Externo, operacional e governança — não confundir com código faltante

Homologação real com A1; cadeia ICP/pins de produção; janela de produção e migração v21→v23 com aprovação explícita do proprietário por CNPJ/município; Worker/GSM (limite de cobrança Google); catálogo/preços; ruleset de production com 0 aprovações (restabelecer 1 antes do primeiro cliente, mediante autorização); revisão independente. Estados de ambiente, cobrança e ruleset são relatados na passagem recebida, não revalidados nesta edição.

Cobertura nacional (6 de 42 municípios com adaptador próprio, todos só homologação, segundo o relatório recebido) fica fora do escopo deste pacote P1–P7. Isso não encerra nem reduz a obrigação já registrada de SP-22/MG-20 e Cajamar no Plano Mestre. Inventários de cobertura usam critérios diferentes; reconciliar individualmente, sem inferência de prontidão.

## 7. Como rodar localmente

Python 3.11+ com pip install -e .[dev]; PostgreSQL de teste e NFCORE_TEST_DSN/NFCORE_TEST_POSTGRES_DSN; pytest -o addopts=""; suíte completa aproximadamente 12 minutos na CI, segundo o relatório recebido. mypy somente em src. GitHub: sem gh no ambiente do autor, usar MCP; git push via HTTPS funciona conforme relato. Nunca executar testes em banco produtivo ou imprimir segredos.

## 8. Continuidade e vínculo com documentação CURRENT

- [Registro único de pendências](NFCORE_PENDING_REGISTER_CURRENT_2026-11-17.md)
- [Cronograma de fechamento REC-00 a REC-22](NFCORE_RECONCILIATION_CLOSEOUT_SCHEDULE_2026-11-17.md)
- [Reconciliação das 59 tarefas, SP-22/MG-20 e Cajamar](NFCORE_CURRENT_RECONCILIATION_59_TASKS_42_MUNICIPALITIES_2026-11-19.md)

Atualizar esta passagem a cada entrega efetiva com branch, commit, evidência de testes, CI e pendência residual. Manter histórico e distinguir IMPLEMENTED_NOT_CERTIFIED, INTERNAL_CERTIFIED, OFFICIAL_HOMOLOGATED, DEPLOYED e COMMERCIAL_APPROVED. Os resultados locais relatados não foram reproduzidos nesta edição. Nenhuma PR aberta, mesclada, CI disparada manualmente, alteração de ruleset, migração, upload de certificado ou deploy foi executado no registro deste documento.
