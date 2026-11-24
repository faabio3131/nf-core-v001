# T09 — gate objetivo de curadoria, sem autoproclamar certificação

CURRENT de implementação: PR #592, HEAD de partida `fc55b87f2d4071e156f9b229230729c262ac0f3a`, Draft. Motor fiscal canônico intocado. O script read-only `scripts/nfcore_t09_curatorial_closure.py` reconcilia **27/27** identidades de UF e candidato entre fila, drafts e dossiês; bloqueia promoção fiscal por mera mudança de flags e separa requisitos normativos internos de uma concessão real de contribuinte (EXTERNA).

## Executar

```bash
python scripts/nfcore_t09_curatorial_closure.py
python scripts/nfcore_t09_curatorial_closure.py --require-closure
pytest -q tests/tax/test_t09_curatorial_closure_gate.py
```

Sem `--require-closure`, a auditoria retorna JSON estruturado com as pendências por UF e exit 0 caso o inventário seja íntegro. Com a chave, retorna exit 1 até comprovar os gates **INTERNOS** e correspondência dos 27 dossiês, independentemente de assinatura humana ou parecer contábil EXTERNOS. CI executa os testes regressivos; não aplicar gate estrito em toda PR antes de completar a pesquisa.

## Critérios antes de aceitar curadoria interna
- Norma estadual exata e fonte original arquivada com SHA-256, cadeia completa e competência verificada.
- CONFAZ/LC160 ou fundamento alternativo comprovado, operação/CNAE/NCM/CFOP/ST/DIFAL e exceções.
- Determinação normativa da necessidade/dispensa de concessão individual (sem exigir concessão de contribuinte de verdade para pesquisar).
- Testes jurídicos completos reproduzíveis, revisão contraditória independente.
- **Fechamento INTERNO:** evidência e dossiê tecnicamente completos, testes, revisão técnica independente e certificação de engenharia. Não exigir `human_approval_record`, parecer assinado de contador ou concessão individual real. O estado `COMPLETE_RESEARCH_INTERNALLY_VERIFIED` atesta somente dossiê internamente certificado — requer comprovação efetiva e não deve ser atribuído antecipadamente.
- **Aceite humano EXTERNO posterior:** aprovação de produto para promoção, com `human_approval_record` verificável na autoridade governada. O relatório read-only somente identifica sua pendência; não a autentica nem libera fiscalmente.
- **Parecer contábil EXTERNO e concessão real por contribuinte:** obrigatórios quando aplicáveis antes da fruição/ativação, nunca para encerrar a pesquisa ou testes internos.
- A aprovação da curadoria não ativa emissão fiscal e não valida credenciais ou concessões externas. `import_authorized` dos drafts continua falso, a única autoridade operacional continua sendo `verify_internal_review_approval` da aplicação.

## Limitações importantes
O script **não** é assinatura eletrônica, motor tributário alternativo, verificação de bytes original nem autorização de produção; detecta lacunas documentais e inconsistências. O atual snapshot permanece 0/27 aprovado e T10 bloqueada. A nova CI do HEAD resultante deve passar antes de certificar este próprio gate.

Os estados históricos fixados em `tests/tax/test_t09_normative_consolidation_work_queue.py` continuam verdadeiros para o CURRENT e não devem ser interpretados como uma API de aprovação futura.


## Separação constitucional aprovada em 22/11/2026

A solicitação do proprietário redefiniu formalmente o aceite humano da curadoria como **dependência externa de promoção**. O fluxo passa a ter **T09-INT (engenharia, normas, fontes, testes, revisão técnica, CI e documentação)** e, separadamente, **T09-EXT (aceite humano, parecer de contador e concessões de contribuintes, quando exigidos)**. A conclusão de T09-INT **não depende** de T09-EXT, mas a emissão/aplicação fiscal real permanece fail-closed até a aprovação na autoridade canônica. O fechamento interno ainda exige todas as provas técnicas e normativas; nenhuma pendência interna foi reclassificada artificialmente como externa.
