# T09 — checkpoint de fechamento interno vs externo (21/11/2026)

## Autoridades e estados distintos

- `T09-ENGINEERING-CERTIFIED`: requer **CI integral SUCCESS no HEAD final**, testes específicos INT-07, integridade, RLS/RBAC, PostgreSQL e ausência de regressão; não exige parecer do contador.
- `T09-NORMATIVE-CURATION-CERTIFIED`: exige dossiê original com bytes arquivados, hash real, cadeia de alterações por competência, enquadramento/CONFAZ, cenários positivos e negativos baseados em dispositivos, revisão contraditória independente e aceite humano **por candidata**; não exige o parecer externo para a pesquisa.
- `T09-EXTERNAL-FISCAL-APPROVED`: requer os pareceres, atos individualizados e homologações efetivamente aplicáveis; não pode ser inferido de CI verde ou de aprovação interna.

## Matriz INT (checkpoint sem promoções automáticas)

| ID | Ação / evidência | Estado |
|---|---|---|
| INT-01 | Reconciliação do Lote A em `NFCORE_T09_LOTE_A_AUDITORIA_BYTES_20261121.md`: 8 originais examinados, um AC rejeitado como ato incorreto; não há hashes nas candidatas aprovadas | PARCIAL |
| INT-02 | Fila de 22 itens do kit Windows, 12 ainda faltantes conforme levantamento, originais adicionais localizados sem autenticar bytes | PENDENTE |
| INT-03 | Temporalidade, prorrogações, revogações e data conflitante Lei PA 6.913/2006 | PENDENTE |
| INT-04 | Enquadramento CNAE/NCM/CFOP/ST/DIFAL e operação em todas as 27 hipóteses normativas | PENDENTE |
| INT-05 | Rota CONFAZ/LC 160 por hipótese, não presumida | PENDENTE |
| INT-06 | Testes jurídicos positivos e negativos ancorados em atos reais, não nos fixtures sintéticos | PENDENTE |
| INT-07 | Novo guarda determinístico para concessão, expirado, revogado, desvio de CNPJ/UF e competência | IMPLEMENTADO, AGUARDA CI |
| INT-08 | Revisor contraditório distinto, com achados e correções por dossiê | PENDENTE |
| INT-09 | Aceite humano autorizado e rastreável de cada candidata | 0/27 |
| INT-10 | CI do HEAD `b8feea22` era SUCCESS (FM NFCORE V1 CI #44966185284); novas alterações exigem certificação em novo HEAD | NOVA CI NECESSÁRIA |
| INT-11 | Matriz, fila, dossiês e status separados por resultado | PARCIAL |

## Descoberta documental localizada em 21/11/2026 (não equivale a curadoria)

- **AC:** Decreto 4.196/2001 identificado na fonte primária SEFAZ/AC `https://sefaz.ac.gov.br/2021/?p=14786`; remete aos Decretos 12.360/2005, 6.221/2017 e 11.618/2025. A fonte confirma exigência de projeto e Termo de Acordo; não reutilizar hash do Decreto 8.701/2018 capturado incorretamente.
- **SE:** original do Decreto 29.935/2014 no portal PGE/SE `https://pge.se.gov.br/wp-content/uploads/2025/02/DECRETO-29-935-1.pdf`; art. 3º condiciona apoio fiscal a deliberação CDI e parecer fiscal prévio. Precisa conferir alterações posteriores e a Lei 3.140/1991, inclusive a lista da SEDETEC em `https://sedetec.se.gov.br/fai/legislacao-fai/`.
- **AL:** a SEFAZ identifica Lei 5.671/1995 e Decreto 38.394/2000 em `https://www.sefaz.al.gov.br/nise/faq/` (portal explicativo, **não original integral**). Assembleia registra Lei 7.770/2015 como alteração: `https://sapl.al.al.leg.br/norma/1189`. Original base e consolidação continuam pendentes.
- **RJ:** texto da Portaria SSER 345/2023 reproduzido em consulta oficial `https://portal.fazenda.rj.gov.br/consulta-tributaria/wp-content/uploads/sites/45/2025/08/025_2025.pdf`; **é parecer/consulta e não publicação originária**. Portarias 350/2024, 362/2024 e 431/2025 exigem textos primários do DOE e reconciliação; nenhuma foi marcada como obtida.
- **PI:** Decreto 23.672/2025/DOE 57/2025 é um ato alterador; não substitui a consolidação atualizada do Anexo IV art. 25-A do RICMS.

**Hashes de páginas de busca, texto produzido por IA e transcrições secundárias não são SHA-256 do original oficial.** Conservar `source_sha256=null`, `review_status=draft`, `import_authorized=false` nas 27 candidatas até a prova específica.

## Dependências EXTERNAS sem bloqueio indevido da engenharia

EXT-01 parecer jurídico-contábil assinado; EXT-02 concessões e adesões reais; EXT-03 certificados/credenciais; EXT-04 testes fiscais com clientes; EXT-05 publicações futuras de autoridade estadual. Cada uma bloqueia **somente** a operação real dependente, nunca a compilação, a curadoria documental ou os testes internos.

**T10, merge, deploy e utilização fiscal real permanecem sem autorização nesta rodada.**
