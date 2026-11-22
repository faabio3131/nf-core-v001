# T09 — gate objetivo de curadoria, sem autoproclamar certificação

CURRENT de implementação: PR #592, HEAD de partida `fc55b87f2d4071e156f9b229230729c262ac0f3a`, Draft. Motor fiscal canônico intocado. O script read-only `scripts/nfcore_t09_curatorial_closure.py` reconcilia **27/27** identidades de UF e candidato entre fila, drafts e dossiês; bloqueia promoção fiscal por mera mudança de flags e separa requisitos normativos internos de uma concessão real de contribuinte (EXTERNA).

## Executar

```bash
python scripts/nfcore_t09_curatorial_closure.py
python scripts/nfcore_t09_curatorial_closure.py --require-closure
pytest -q tests/tax/test_t09_curatorial_closure_gate.py
```

Sem `--require-closure`, a auditoria retorna JSON estruturado com as pendências por UF e exit 0 caso o inventário seja íntegro. Com a chave, retorna exit 1 até comprovar todos os gates e correspondência dos 27 dossiês. CI executa os testes regressivos; não aplicar gate estrito em toda PR antes de completar a pesquisa.

## Critérios antes de aceitar curadoria interna
- Norma estadual exata e fonte original arquivada com SHA-256, cadeia completa e competência verificada.
- CONFAZ/LC160 ou fundamento alternativo comprovado, operação/CNAE/NCM/CFOP/ST/DIFAL e exceções.
- Determinação normativa da necessidade/dispensa de concessão individual (sem exigir concessão de contribuinte de verdade para pesquisar).
- Testes jurídicos completos reproduzíveis, revisão contraditória independente.
- Ato de aceite **humano** com `human_approval_record` e dupla consistência de dossiê e fila; a autenticidade do recibo não é atestada pelo JSON, deve ser validada nos controles canônicos governados.
- A aprovação da curadoria não ativa emissão fiscal e não valida credenciais ou concessões externas. `import_authorized` dos drafts continua falso, a única autoridade operacional continua sendo `verify_internal_review_approval` da aplicação.

## Limitações importantes
O script **não** é assinatura eletrônica, motor tributário alternativo, verificação de bytes original nem autorização de produção; detecta lacunas documentais e inconsistências. O atual snapshot permanece 0/27 aprovado e T10 bloqueada. A nova CI do HEAD resultante deve passar antes de certificar este próprio gate.

Os estados históricos fixados em `tests/tax/test_t09_normative_consolidation_work_queue.py` continuam verdadeiros para o CURRENT e não devem ser interpretados como uma API de aprovação futura.
