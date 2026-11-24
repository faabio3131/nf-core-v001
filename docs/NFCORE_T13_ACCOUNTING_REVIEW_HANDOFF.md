# T13 — Aprovação Contábil Auditável

Data: 24/11/2026. Issue #602. Branch feat/nfcore-economy-t13-accounting-approval. Base certificada db75317f26b8a56b23b2d6f0266befc629db2bd1. T12 #600 pós-merge #45414580213 SUCCESS, 7032 Python PASS / 1 SKIP / 84 E2E. Não herdar a certificação para T13.

## CURRENT → TARGET, escopo e autoridade

CURRENT: T01 repositório imutável com RLS FORCE e os quatro eixos de escopo; T10 radar consultivo federal/estadual/municipal; T12 comparação anual consultiva; sessão, RBAC, unidades e MFA v24 existentes. A branch histórica 1a839b3b contém protótipo de cálculo/XML ICMS, não o fluxo contábil. Preservada para avaliação na T14, sem cherry-pick antecipado.

TARGET: decisão humana auditável sobre resultado determinístico atual. Reutilizar T01, T10, T12, autoridade de cadastro/perfil/regime, sessão, RBAC, CSRF e MFA. Nada em T14, emissão, pagamento, crédito ou opção fiscal é autorizado por esta etapa.

## Implementação

- Papel canônico accountant, designado somente pelo owner, com unidades explícitas e permissões de leitura; admin, auditor, operador, billing e owner não decidem em nome do contador. MFA obrigatória no login quando configurada, step-up recente obrigatório no endpoint de decisão, inclusive nova checagem imediatamente antes da escrita. Sem MFA configurada, decisão 503. Reuso da mesma sessão e gestão de papéis.
- application/accounting_review.py: target estrito, comando explícito approve/reject/revoke, referência profissional e do parecer declaradas, fundamentação, actor_id e horário UTC pelo servidor, attestation_type authenticated_human_step_up. O registro é evidência da ação humana autenticada, NÃO assinatura digital ICP-Brasil ou verificação cadastral do CRC. Nenhuma credencial ou segredo é requerido no parecer.
- Persistência na mesma fm_economy_snapshots do T01, schema nfcore.accounting-review/v1, identidade determinística por emissor/competência/target, digest do escopo e resultado, versão append-only, referência ao digest anterior, checagem de integridade e histórico paginado. Lock transacional e versão otimista serializam decisões concorrentes, idempotência por request_id na mesma stream; replay exato mais recente não duplica decisão, reutilização histórica é conflito. Aprovação atual precisa ser revogada antes de substituição no mesmo resultado. Substituição de evidência torna decisão stale, sem apagamento.
- cognitive/accounting_review_api.py: reconstrói o resultado do radar ou comparador por autoridades existentes dentro de transação escopada. T10: fontes federal/estadual/municipal, rejeita busca truncada, candidato ausente/ambíguo; vínculo de regra e snapshot com versões/digests e resultado. T12: quatro snapshots T11 atuais, contexto mensal do regime e digest do resultado; sem aceitar valores do browser. Se o sujeito deixa de ser elegível, histórico continua legível quando o emissor canônico está acessível, decisão bloqueada.
- POST /v1/portal/cognitive/economy/accounting-review: consulta ou decisão, sessão + audit.read + unidade/ambiente habilitados + CSRF, command extra forbid, 409 em conflito, 422 quando evidência de decisão inválida, 503 indisponibilidade. Feature flags canônicas NFCORE_COGNITIVE_ENABLED e NFCORE_ECONOMY_ENABLED. Sem nova migration nem segunda API/identidade.
- Portal na mesma Reforma Tributária: consulta do parecer sobre o resultado do radar/T12, histórico por referência (somente leitura), digest, versão, fatos e fontes legais, situação pendente/aprovada/rejeitada/revogada/desatualizada. Formulário contábil usa step-up existente; payload inclui somente referências, fundamentação e precondições, sem campo de valor aprovado editável.

## Limites e decisões de engenharia

Aprovar é registrar um parecer humano vinculado ao resultado, nunca aplicar benefício, realizar economia, modificar regime, autorizar emissão ou pagamento. A referência profissional declarada não prova inscrição CRC ativa; parecer real e verificações externas são dependências de ativação, não da construção. T05 é diagnóstico consultivo de Fator R, não caminho de aplicação T14; não é promovido por este endpoint. T11 é insumo de T12. Não há ampliação de cobertura territorial, nem concessões reais. T14 deve revalidar a decisão e toda a evidência no momento de aplicação, pois uma importação concorrente pode tornar um resultado anteriormente aprovado stale; não usar status histórico como autorização. #593 e #601 permanecem separados. P3-03 documental T12 reconciliado nesta branch. Sem alteração de migrations, autoridades tributárias ou cálculo do XML.

## Gates e reprodução

- Ruff/Mypy, regressões de identidade/MFA/RBAC, validação HTTP, PostgreSQL 16 real (mesma migration T01, RLS, cadeia de eventos, replay, conflito, revogação, invalidado após T12/T11 superseded, municipal sintético), frontend lint/typecheck/test/build, Playwright, Docker, CI integral do HEAD e revisão independente.
- Local: usar PYTHONPATH=src para evitar pacote editável de outra worktree; 31 testes focais Python PASS; suíte real PostgreSQL T01/T13 2 PASS, incluindo jornada HTTP e callbacks de MFA na fronteira (MFA real em testes de segurança separados); 30 testes frontend PASS e build PASS. Typecheck inicial após lookup detectou union JS, corrigida e retestada PASS. Mypy integral local encontrou dependências externas ausentes e APIs POSIX no Windows, não certificado integralmente neste host. A CI Linux é obrigatória; não remover testes nem ocultar falhas. E2E focal Chromium: 3 PASS (radar, comparador e decisão MFA com backend simulado), configuração estática isolada no Windows; CI integral do HEAD publicado pendente.

## Estado e continuidade

Candidata em construção/certificação, sem merge, deploy ou promoção. Depois de testes locais e PR Draft, consultar CI exata, gerar pacote incremental e obter parecer independente Gemini. Só então solicitar autorização de merge; T14 permanece bloqueada até CI pós-merge e documentação final. Não transformar engenharia interna em aprovação fiscal real.
