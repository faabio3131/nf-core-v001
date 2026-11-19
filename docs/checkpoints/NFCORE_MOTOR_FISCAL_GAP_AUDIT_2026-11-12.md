> **REGISTRO HISTÓRICO RECUPERADO EM 16/11/2026 — PR #448, origem `aa7ce1553d260a13fc105e3b1b324af964e72cca`.**
> O conteúdo original abaixo foi preservado integralmente. Afirmações de CURRENT, lacunas, prioridades, responsáveis, autorizações e estado de CI referem-se à data do documento. Para o estado vigente, consulte `docs/audit/NFCORE_PR_RECONCILIATION_LEDGER_CURRENT.md`, o GitHub e as decisões posteriores em `AGENTS.md`.
> A recuperação não reabre etapas integradas, não altera a prioridade de 13/11 ou a responsabilidade do Integrador de 15/11, não implementa travas e não certifica cobertura. T2 já possui implementação parcial posterior; esta especificação não prova T1/T3–T6 nem enforcement administrativo.

# NFCore V1 — Diagnóstico técnico de conclusão do motor fiscal proprietário
**Data de corte:** 12/11/2026 (Brasil)  
**Status global:** **MOTOR IMPLEMENTADO EM PARTES, FECHAMENTO OPERACIONAL E HOMOLOGAÇÃO PENDENTES. NÃO CERTIFICADO PONTA A PONTA.**  
**Finalidade:** estabelecer o inventário real do que falta para concluir o motor fiscal e o emissor nativo NFCore, sem depender de Bling, Odoo, qualquer ERP ou plataforma externa de gestão.  
**Base examinada:** `production@ea4bdd3bcb9b61e6522081a14e5cc9ad1ced9599` e `main@ef7ebe7e104f0e49897075cd961d51a052948b43`; commits e PRs deste documento são fotografias deste instante, não o estado garantido no host.  
**Fronteiras:** leitura de código e metadados GitHub + sinais públicos de readiness; **não** inclui execução ponta a ponta com A1 real, análise de segredos, logins de tenant ou transmissão fiscal oficial. Ações remotas, deploy e DDL **não foram executados** nesta auditoria.

> **Regra de verdade:** existência de classes, CI verde, catálogo de provedores, `/health/ready`, seis handlers no `/runtime/profile` ou simulações não constituem prova de nota autorizada. Um município só recebe status *homologado* mediante resposta oficial documentada por operação, ambiente, regime e competência. Nunca inferir 22/22.

## 1. Veredicto — onde está o motor

O motor fiscal próprio **não está ausente e não depende de Bling**. Seu núcleo está distribuído entre os modelos de domínio, serviços canônicos, control plane de perfis/vínculos, A1 Vault, assinatura XMLDSig, regras/validação, numeradores, lifecycle/idempotência, gateways fiscais, persistência de arquivos e superfícies Portal. O problema é a conclusão e demonstração de todos os elos na jornada nativa.

**Implementações observadas na `production`:**
- NF-e 55: `src/kordena_fiscal/application/nfe_preparation.py:prepare_nfe_sale` reserva número, monta e assina XML, verifica schema/assinatura e persiste preparação em transação; `gateway/nfe_sp_homologation.py` suporta transporte oficial governado em homologação.
- NFC-e 65: `issuance/nfce.py` contém componentes de preparação/assinatura/persistência; **não comprova sozinho** um cadastro e uma emissão completa pela interface.
- NFS-e Nacional: `application/service.py:prepare_nfse_authorization` reserva idempotência, cria lifecycle e arquiva `prepared-nfse`; `issuance/nfse_dps_builder.py` monta/valida/assina DPS; `gateway/nfse_nacional_homologation.py` transmite via SEFIN em `tpAmb=2`.
- Segurança/tenancy: `web/portal_api.py:/certificates/a1` recebe A1 com sessão/CSRF e escopo de unidade, `vault/a1_preflight.py` verifica identidade/validade; `gateway/fiscal_tls.py` implementa mTLS TLS 1.2+ com par temporário; `web/portal_runtime.py:_register_fiscal_profile` cadastra `FiscalProfile`.
- Processamento: `application/service.py:authorize_prepared_document`, `runtime/provider_issuance_handler.py`, `runtime/provider_operation_wiring.py`, recovery com consulta e lifecycle/idempotência; `application/outbox_worker.py` implementa worker de outbox durável.
- Portal: `portal/app.js` tem seleção de unidade/ambiente, operação fiscal, consulta e download autenticado de artefatos de arquivo; `web/portal_runtime.py:fiscal_artifact` valida escopo e integridade.
- Operação: na evidência do host de 12/11, schema fiscal 1..21 e Cakto 1..3 estavam aprovados; GSM Worker operante e healthy. **O GSM Worker não é prova de worker de emissão nem de resposta fiscal oficial.**

## 2. Matriz priorizada de lacunas de engenharia

**Legenda:** `IMPLEMENTADO` = código identificado, **não** validação operacional; `PARCIAL` = contrato ou jornada incompleta; `NÃO COMPROVADO` = faltam evidências; `EXTERNO` = exige credencial/provedor/contribuinte real. **P0** bloqueia o piloto nativo da respectiva modalidade ou a integridade de sua evidência; **P1** bloqueia uso operacional repetível; **P2** amplia cobertura/certificação.

| ID | Prioridade | Eixo | Estado / problema comprovado ou a verificar | Conclusão verificável |
|---|---|---|---|---|
| MF-01 | P0 | Emissor nativo | `portal/app.js:operationPayloadForSelection` exige `document_id` previamente preparado para `issueFiscalDocument`; o serviço canônico existe, mas **não foi identificada rota/jornada completa de preparo manual da NFS-e** no Portal. | Formulário autenticado monta dados, valida, grava documento fiscal canônico e devolve `document_id` sem ERP. |
| MF-02 | P0 | Contrato completo NFS-e | `NfseCanonicalDocument` conserva só `service_taker_reference`; `nfse_dps_builder.py` **não constrói grupo `toma`** (nem resolve dados do tomador). O fato de um tomador ser opcional em certas hipóteses **não** autoriza omiti-lo nos cenários que o exigem. | Snapshot imutável de tomador/identidade/endereço e mapeamento condicional conforme schema/regras com testes de omissão permitida e obrigatoriedade. |
| MF-03 | P0 | Numeração DPS | `nfse_dps_builder.py:_derive_dps_numbering` gera `nDPS` pelo hash e declara a estratégia `PROVISIONAL`; não é autoridade sequencial. PR **#427** propõe serial durável e schema v22, mas está em **Draft, com conflitos/mergeable=false**; não está em `production`. | Numeração transacional por emitente/série/ambiente e escopo governado, concorrência/replay/recovery comprovados; reconciliar #427 sem duplicar implementação, aprovar migração separadamente. |
| MF-04 | P0 | Regras NFS-e | Builder fixa `regEspTrib=0` e `tribISSQN=1`; `regApTribSN=3` é documentado como provisório em caso de excesso de sublimite. `nfse_preaudit.py` diz que isenção/não incidência/exportação/imunidade não possuem flag explícita em `NfseServiceLine`. | Representar e validar as hipóteses tributárias relevantes por perfil/competência/município; bloquear os cenários não suportados, sem declarar cobertura universal. |
| MF-05 | P0 | Arquivo oficial NFS-e | `NfseAuthorizationResult` não carrega `authorized_xml`; o `authorize_prepared_document` arquiva `AUTHORIZED_XML` apenas se o resultado for `AuthorizationResult` (XML de NF-e/NFC-e). NFS-e autorizada hoje pode ter chave/referência, mas **sem prova de persistência do XML oficial** pelo mesmo caminho. | Recuperar XML oficial autorizado por serviço nacional, verificar vínculo/chave/protocolo/assinatura conforme schema, persistir imutavelmente por tenant/unidade e disponibilizar via Portal. |
| MF-06 | P0 | Impressão NFS-e | `archive/danfe_pdf.py` renderiza **DANFE de NF-e modelo 55**; `web/portal_runtime.py:fiscal_artifact` usa o mesmo renderer na ação de PDF. **DANFSE para NFS-e não identificada** no caminho nativo. | Gerar e expor DANFSE/representação oficial apropriada à NFS-e a partir do XML e evidência autorizados, sem usar DANFE NF-e como substituto. |
| MF-07 | P0 | Prova externa | Nenhuma emissão com A1 real, resposta oficial autorizada e arquivo integral do piloto foi certificada nesta auditoria. `/runtime/profile` mede composição. `fiscal_production_activated=false` não impede homologação, mas **produção fiscal real está bloqueada**. | E2E **homologação oficial** com contribuinte autorizado, `tpAmb=2`, evidência verificável da autorização, XML e visualização. Depois gate separado para produção. |
| MF-08 | P0 | Cobertura real | Os 22 municípios de SP foram indevidamente chamados de certificados; #445/#446 corrigem a matriz. Provedor potencial ≠ WebService integrado, homologado e operacional. | Matriz por IBGE/modelo/regime/competência/operação com provas individuais. Frente de Cajamar/Osasco/Barueri/Jundiaí é **do outro executor**. |
| MF-09 | P0 | NF-e/NFC-e manual | `prepare_nfe_sale` e módulos NFC-e existem, mas é preciso **comprovar** originação manual de produto/item/tomador, cálculos, numeração, pagamento/CSC/QR quando aplicável e ligação ao Portal, sem depender de pedido Bling. | E2E nativo separado para NF-e 55 e NFC-e 65 com XSD, assinatura, resultado e XML/representação auxiliar corretos. |
| MF-10 | P1 | Resposta/erros visíveis | `provider_issuance_handler.py` devolve `rejection_reason` pelo código; `FiscalIntentRecovery.project` devolve `state` e `reference_id`, sem preservar na projeção os detalhes do retorno; `portal/app.js` mostra recibo interno, não `cStat/xMotivo` ou código/motivo equivalente de forma completa. | UI consulta e exibe código/motivo saneados, estado definitivo ou incerteza; não confunde `recorded` com autorização. |
| MF-11 | P1 | Recuperação e não duplicação | Idempotência e recuperação com consulta existem, mas não há ensaio oficial comprovado de timeout, reenvio, duplicidade, reboot e retorno tardio para o piloto. | Injetar falhas e provar **uma única nota** por intenção, consulta antes de retransmitir, lifecycle/arquivo atômicos. |
| MF-12 | P1 | Consulta/cancelamento NFS-e | `reconcile_prepared_nfse_authorization` existe; a API genérica de cancelamento usa `FiscalOperationsClient` (NF-e/eventos). **Não declarar cancelamento/substituição de NFS-e Nacional como operacional** sem adaptador, XML/evento e homologação comprovados. | Matriz de suporte real a consulta/cancelamento/substituição por provedor; implementar faltantes e certificar retornos oficiais. |
| MF-13 | P1 | XML e provas | Para NF-e, `AUTHORIZED_XML` é persistido quando `AuthorizationResult.authorized_xml` está presente; o renderizador DANFE valida `nfeProc`. Falta certificar end-to-end a retenção, protocolo, hash, origem, leitura por outra sessão e exportação por competência; NFS-e tem a lacuna MF-05. | Download seguro e arquivo reconciliado com protocolo, dados mínimos de auditoria e filtragem de competência. |
| MF-14 | P1 | Cadastro/provisionamento | Portal já cadastra perfil, e A1 em `homologation`; falta provar num tenant piloto real que CNPJ, IM/IE, CNAE, regime, dados de endereço, bindings do provedor e certificado no Vault são consistentes e resolvidos pelo mesmo processo de transmissão. | Preflight integrado, sessão→tenant→unidade→perfil efetivo→A1→binding→ambiente, com erros claros e bloqueio antes do POST oficial. |
| MF-15 | P1 | Segurança/transporte | `fiscal_tls.py` implementa mTLS, mas a cadeia ICP-Brasil efetivamente aceita na imagem/host, endpoints, políticas TLS, assinatura por provedor e rotação de certificado exigem validação operacional. | Provas de TLS, C14N/XMLDSig, trust store, versão de XSD, revogação/expiração A1, controle de segredos e fail-closed. |
| MF-16 | P1 | RTC e tributação | `compliance/rtc.py`, `rtc_calculation_preview.py` e perfis canônicos existem, mas **não** declarar completude fiscal para todos os CST, regimes, exceções, IBS/CBS e competência sem matriz aplicável + validação normativa atual. | Matriz de regras por modelo/regime/competência/cenário, dados oficiais versionados e regressões de NF-e/NFC-e/NFS-e. |
| MF-17 | P1 | Certificação automatizada | Existem testes de XSD, gateways, signing, Portal e e2e sintéticos. Não são equivalentes a A1 real nem resposta oficial. Falta um **gate mestre** que atravesse todos os limites com fixtures e variações, mais evidência externa. | Teste canônico de cada família + integração contra homologação oficial, matriz de casos positivos/negativos e artefatos reproduzíveis. |
| MF-18 | P2 | Operação e escala | Outbox worker, health, recovery, backup e observabilidade têm implementação. Falta certificar robustez sob volume, restart, erro de provedor e recuperação de desastre ligados ao emissor nativo, não apenas health do GSM. | Testes de concorrência, DLQ/retries, workers e disaster recovery sem dupla emissão ou perda de autorização. |

### Atenção a ramos e divergências

Os blobs de `issuance/nfe_nfse.py`, `application/service.py`, `web/portal_runtime.py`, `gateway/nfse_nacional_homologation.py` e `portal/app.js` **diferem entre `main` e `production`** no corte desta auditoria. Antes de implementar MF-01 a MF-18, comparar os dois ramos e trabalhos abertos para não introduzir regressão. O builder da DPS `issuance/nfse_dps_builder.py` tem o mesmo blob nos dois ramos, incluindo as limitações citadas.

## 3. Cadeia correta do emissor próprio

```text
Portal NFCore (cadastro manual) OU API própria OU conector opcional
  → sessão/RBAC + tenant/unidade + ambiente
  → perfil fiscal efetivo + tomador/destinatário + dados comerciais
  → classificação fiscal, tributação, competência, provedor por IBGE/modelo
  → NUMERAÇÃO DURÁVEL (NF-e/NFC-e/DPS) + pedido canônico + idempotência
  → preparação/transação/arquivo do pedido
  → A1 Vault + pré-validação do CNPJ + XML oficial XSD + XMLDSig
  → gateway governado + SEFAZ/SEFIN/município em homologação
  → resultado: AUTORIZADA / REJEITADA / PENDENTE OU DESCONHECIDO
  → consulta/reconciliação oficial (sem emissão duplicada)
  → protocolo e XML oficial autorizados em arquivo imutável
  → Portal: mensagem clara, consulta, download e DANFE/DANFSE correto
```

As origens (Portal manual, API NFCore, conector de ERP) **convergem no mesmo motor fiscal**. Um ERP externo **não é pré-requisito**. Emissão real só após permissão humana apropriada e homologação em cada canal; `status=recorded` de intent não é autorização.

## 4. Cronograma técnico de fechamento — sem reconstruir o motor

### Bloco E0 — Baseline e rastreabilidade (antes de modificar código)
- [ ] Comparar `main`, `production`, `.deployed`, `deploy.log`, issues/PRs abertas e arquivos tocados pelos executores. Confirmar SHA e saúde sem escrever no servidor.
- [ ] Marcar responsáveis exclusivos: **#427 numeração DPS**, **#445/#446 municípios SP**, **#447 emissor nativo**; não executar duas correções concorrentes no mesmo módulo.
- [ ] Preparar matriz `FATO / INFERÊNCIA / NÃO VERIFICADO` e corpus de cenários da contabilidade; nenhum número de certificação sem evidência.

### Bloco E1 — Fechar contratos fiscais canônicos (interno)
- [ ] MF-02: identificação/resolução do tomador e mapeamento condicional ao XML.
- [ ] MF-04: regime especial, incidência, tributação municipal e opções/fallback de ISS, com regras e competência explícitas.
- [ ] MF-03: concluir #427, conflitos, versionamento, migração v22 **apenas após aprovação específica**, concorrência e replay.
- [ ] MF-05: captura/consulta/validação/arquivamento do XML autorizado NFS-e com garantia de integridade e vínculo.
- [ ] MF-06: DANFSE correta para NFS-e; MF-13: exportação de XML/protocolo por competência.
- [ ] Revisar NF-e/NFC-e (MF-09, MF-16) sem declarar todos os cenários tributários certificados.

### Bloco E2 — Completar entrada nativa no Portal (interno)
- [ ] MF-01: rota `prepareFiscalDocument` (nome a definir conforme contratos existentes, **sem criar API paralela**) exigindo RBAC, CSRF, idempotência, escopo derivado de sessão, tipagem forte e limites.
- [ ] Resolver `FiscalProfile` efetivo, dados do tomador, linha/serviço, ISS e política versionada **no backend**; navegador não pode forjar tenant, provider, certificado nem autorização fiscal.
- [ ] Preparar via `FiscalApplicationService.prepare_nfse_authorization` e/ou `prepare_nfe_sale` e persistir a referência; **não transmitir** durante a fase de simples preparação.
- [ ] UI fiscal: cadastro → prévia → validar → preparar → emitir → acompanhar → consultar → XML/PDF; erros reais saneados e recibo jamais confundido com autorização.
- [ ] Testes E2E com browser e backend reais para cada estágio, inclusive permissões de unidades distintas.

### Bloco E3 — Certificação interna (sem A1 de clientes)
- [ ] Testes XSD/XMLDSig/C14N com certificados de teste, XML golden aprovado, esquemas versionados.
- [ ] Casos positivos/negativos: tomador PJ/PF/estrangeiro quando suportados, IM, endereço, Simples/Normal, retenção, isenção, competência retroativa, serviço com dados insuficientes e regras específicas.
- [ ] Colisão/replay de número, requests paralelos, timeout de envio, queda do processo, resposta pendente, reconsulta e transição de estado.
- [ ] Verificar persistência transacional e consistência de `AUTHORIZED_XML`, `PROVIDER_RESPONSE`, `DANFE/DANFSE` e auditoria.
- [ ] Testes de API/Portal/migrações em PostgreSQL; lint, typecheck, segurança, build e CI completas no HEAD exato.

### Bloco E4 — Piloto com a contabilidade (externo, homologação)
- [ ] Escolher uma empresa emitente autorizada e primeiro **município + modalidade + competência** efetivamente suportados; na frente atual, priorizar Cajamar mas sem presumir o canal fiscal.
- [ ] Registrar perfil fiscal correto e fazer upload do **A1 real autorizado** diretamente no cofre. Não enviar PFX, senha ou segredo ao GitHub/chat.
- [ ] Inspecionar preflight de binding oficial, CNPJ, IM, código fiscal de serviço, competência, certificado, XML/XSD, ambiente `tpAmb=2`.
- [ ] Transmitir uma nota de homologação **com ciência do titular**; registrar resposta, protocolo, XML e chave verificável (mas mascarada na documentação).
- [ ] Consultar a nota por operação oficial; rejeição e timeout devem resultar em estado claro; cancelamento/substituição somente em canal suportado e autorizado.
- [ ] Registrar evidência no dossiê e avançar município a município, sem expandir status por extrapolação.

### Bloco E5 — Produção fiscal real (gate posterior e separado)
- [ ] Somente após E4, provas de desempenho/segurança, jurídico-fiscal aplicável, autorização humana expressa e registros de homologação por escopo.
- [ ] Ativar `tpAmb=1` e destinos produtivos **apenas** por configuração/código governados; hoje o gateway Nacional está restrito a `tpAmb=2` e o runtime público reportou `fiscal_production_activated=false`.
- [ ] Publicação em fases com rollback de código, **nunca rollback cego de emissão autorizada**, observabilidade, contingência e reconciliação.

## 5. Critérios formais de aceite e evidência

**Um módulo só está CONCLUÍDO quando:**
1. Contrato de entrada/saída implementado sem duplicar motor ou inserir dados fiscais inventados.
2. Dados segregados e protegidos (`tenant`, `unit`, `environment`, CNPJ, perfil efetivo, A1, RBAC).
3. Testes de sucesso/falha, replay, conciliação, segurança e UI todos verdes no commit exato.
4. Emissão autorizada distingue-se de preparação, fila, aceite HTTP e status sintético.
5. Para funcionalidade de provedor externo: resposta **oficial real de homologação**, XML/protocolo verificados, com cadeia de prova.
6. Evidências auditáveis com SHA/deploy, IBGE, modelo/ambiente, regime, competência, operação, versão de schema, resultado, protocolo mascarado, data e responsável.
7. Merge/deploy/migração e ativação obedecem aprovações específicas; sem declarar sucesso por antecipação.

**Matriz mínima de testes externos por cidade/canal:**

| Operação | Prova exigida | Estado neste diagnóstico |
|---|---|---|
| Autorização/emissão | Recebimento oficial + autorização + protocolo válido | NÃO COMPROVADO |
| Consulta | Recuperação da nota por chave/identificador oficial | NÃO COMPROVADO |
| Cancelamento | Evento/resposta oficial confirmado, quando suportado | NÃO COMPROVADO |
| Substituição NFS-e | Operação oficialmente suportada e recibo reconciliado | NÃO COMPROVADO |
| Download XML | Conteúdo fiscal autorizado idêntico ao arquivado | **PARCIAL** (NFS-e não demonstrada) |
| PDF fiscal | DANFE/NFC-e ou DANFSE apropriados ao documento | **PARCIAL** (DANFSE não identificada) |
| Rejeição/timeout | Motivo e recuperação sem emitir duplicata | NÃO COMPROVADO em provedor oficial |

**Não confundir escopos:** (a) motor fiscal; (b) integração com ERP; (c) entrada pelo Portal; (d) cobertura estadual/municipal; (e) homologação externa; (f) licença/cobrança. Apenas (a)+(c)+(d aplicável)+(e) são essenciais à emissão de teste. Conector Bling e ativação OAuth não são gate do emissor NFCore.

## 6. Evidências técnicas verificáveis

**Arquivos inspecionados:**
- `src/kordena_fiscal/application/nfe_preparation.py`, `application/service.py` (preparo, numeração e lifecycle);
- `src/kordena_fiscal/issuance/nfe_nfse.py`, `issuance/nfse_dps_builder.py`, `issuance/nfce.py`;
- `src/kordena_fiscal/gateway/nfse_nacional_homologation.py`, `gateway/nfe_sp_homologation.py`, `gateway/nfe_sp_operations_homologation.py`, `gateway/fiscal_tls.py`;
- `src/kordena_fiscal/runtime/canonical_fiscal_composition.py`, `runtime/provider_issuance_handler.py`, `runtime/provider_operation_wiring.py`;
- `src/kordena_fiscal/web/portal_runtime.py`, `web/portal_api.py`, `web/fiscal_intent_recovery.py`, `portal/app.js`;
- `src/kordena_fiscal/archive/danfe_pdf.py`, `compliance/nfse_preaudit.py`, `vault/a1_preflight.py`;
- Evidências e limitações já registradas em issues **#445, #447** e PRs **#427, #441, #446**.

**Estado do repositório no corte:** #441 **MERGED** (somente dois arquivos host override + restauração isolada); #427 **OPEN/DRAFT, mergeable=false**, sem promoção; #446 **OPEN/DRAFT**, frente separada SP-22. A branch `main` é diferente de `production` e contém arquivos divergentes. Nenhuma das evidências auditadas permite afirmar que 22 municípios foram homologados ou que `tpAmb=1` está ativo.

## 7. Declaração final, sem maquiagem

- **Construído:** motor de domínio, persistência, assinatura, Vault, gateway de homologação e parte importante dos fluxos de NF-e/NFC-e/NFS-e.
- **Não fechado:** preparação manual integrada, suporte completo a dados/fiscalidade da NFS-e, autoridade de numeração DPS aprovada, recuperação de XML autorizado NFS-e e DANFSE, interface de erro/resultado.
- **Não certificado:** uma emissão oficial ponta a ponta por contribuinte autorizado, os quatro municípios prioritários e a alegada cobertura de 22 municípios.
- **Próxima entrega de engenharia:** fechar **MF-01 a MF-06** e seus testes internos, em paralelo ao trabalho municipal independente, sem esperar certificado real do contador para programar.
- **Estado proibido:** “100% pronto”, “22/22 certificado”, “produz nota real” ou “homologado” sem a cadeia de provas acima.

**Este relatório é diagnóstico técnico e plano de execução; não é certificação, mudança de código fiscal, merge, deploy ou autorização de emissão real.**
