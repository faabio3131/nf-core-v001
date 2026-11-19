# NFCore — Reordenação da fila SP-22 por reaproveitamento de bloco de engenharia (13/11/2026)

**Documento:** NFV1-SP22-REORDER-001
**Data:** 2026-11-13
**Status:** decisão de **ordem de execução** (planejamento). NÃO é certificação técnica, NÃO altera nenhum estado `INTERNAL_COMPLETE`/`NOT_CERTIFIED`/`EXTERNAL_BLOCKED` já registrado, e NÃO toca na matriz `docs/coverage/NFCORE_SP22_OPERATION_READINESS_2026-11-12.json` (que vive na branch da PR #446, ainda Draft/aberta — este documento não faz merge nem edição daquele artefato).
**Autoridade:** decisão expressa do proprietário (Fábio) em 13/11/2026, nesta conversa.
**Relação com documentos existentes:** este arquivo **complementa** o banner de 12/11/2026 em `AGENTS.md` (prioridade SP-22: Cajamar → Osasco → Barueri → Jundiaí → demais) e o checkpoint de auditoria de 13/11 em `docs/NFCORE_NATIONAL_COVERAGE_MASTER_SCHEDULE_2026-11-07.md`. Não revoga nenhum dos dois; define o que vem **depois** da onda atual.

---

## 1. Decisão do proprietário

1. **A onda atual não é interrompida.** Cajamar (piloto, fora do catálogo dos 22, já em PR #463), Osasco, Barueri e Jundiaí seguem até o fim na ordem já registrada em `AGENTS.md` (12/11/2026).
2. **Santana de Parnaíba entra na onda atual**, junto com Osasco/Barueri/Jundiaí — motivo: é um sistema isolado (Smarapd, próprio), do mesmo tipo de trabalho artesanal que Osasco e Barueri já exigem, então faz sentido executar junto enquanto a equipe está no modo "integração isolada" em vez de reabrir esse modo de trabalho depois.
3. **Depois que essa onda fechar (Osasco + Barueri + Jundiaí + Santana de Parnaíba + Cajamar), a nova ordem por Grupo de Engenharia (seção 2) entra em vigor** para o restante dos 22 municípios de SP.

Motivo da reordenação: priorizar os municípios que compartilham o **mesmo provedor/webservice** de algum município já em construção, para que um único bloco de código sirva a várias cidades ao mesmo tempo — ampliando a cobertura mais rápido — e deixar para o final os sistemas isolados/próprios (sem reaproveitamento, cada um é uma obra única, como Cajamar levou 3 dias sozinho).

---

## 2. Grupos de engenharia (ordem de execução após a onda atual)

### Grupo 2 — NFS-e Nacional exclusivo (executar primeiro: menor esforço, transporte já existe em código)
- **Salto** — confirmado: prefeitura migrou para emissão **exclusiva pelo Portal Nacional** desde 11/2026 (fonte: NotaGateway, matéria dedicada).
- **Louveira** — indício forte, não primário: página da Actana (revenda) afirma homologação ao "Sistema NFS Nacional". Precisa confirmação com a prefeitura antes de certificar.
- **Por que primeiro:** o transporte do Ambiente Nacional (`nfse_national_homologation.py` / `nfse_nacional_homologation.py`) já é código real. O único bloqueio é que `mg_nfse_channel_guard.py` hoje só libera elegibilidade de canal para `state_code == "MG"` — generalizar essa regra para qualquer UF quando o provedor correto é o Nacional desbloqueia este grupo quase sem código novo de integração municipal.

### Grupo 1 — Família GINFES / GISS Online (maior bloco reaproveitável)
- Já confirmados antes desta pesquisa: **Guarulhos, Santos, São Caetano do Sul, Suzano** (Ginfes) e **Jundiaí** (GissOnline — já está na onda atual).
- **Novo nesta pesquisa: Guarujá** — documentação técnica da Senior (duas versões) lista "SP | GUARUJA | GISSONLINE", reforçado por notícia de 2015 citando `guaruja.ginfes.com.br`. **Isso contradiz o rótulo ambíguo atual da matriz do PR #446** (`['sigiss','betha','e-receita','nfse-nacional']`) — Guarujá provavelmente não precisa de bloco novo, reaproveita o de GINFES/GISS.
- **Indício fraco: Itu** — tópico de fórum ACBr de 2026 menciona "NFSe para Itu/SP em 2026 - GISS". Fonte de desenvolvedor, não oficial; tratar como candidato a confirmar, não como certo.
- **Por que em segundo:** é o maior cluster (6-7 cidades potenciais no mesmo padrão ABRASF/GINFES). Construir esse bloco uma vez libera o maior número de municípios por unidade de código escrito.

### Grupo 3 — DSF
- **Campinas, Sorocaba** — mesmo provedor, 2 cidades.

### Grupo 5 — Provedor ainda não identificado (resolver antes de sequenciar; não pular a fila sem saber onde encaixa)
Pesquisa de 13/11/2026 não encontrou fonte confiável para:
- **Itapevi** — único sinal indireto: documentação da Senior cita "SILTE - ISS" para Itapevi, mas é fonte de integrador terceiro, não da prefeitura.
- **Jandira** — nenhum provedor nomeado em fonte confiável.
- **Mairiporã** — nenhum provedor nomeado em fonte confiável (um registro da Senior cita "ETRANSPARENCIA", mas parece ser sistema de portal de transparência, não webservice de NFS-e — não usar sem confirmação).
- **Arujá** — nenhum provedor nomeado em fonte confiável.
- **Monte Mor** — nenhum provedor nomeado em fonte confiável.

Esses 5 continuam, na matriz do PR #446, com o mesmo rótulo ambíguo de 4 candidatos (`sigiss`, `betha`, `e-receita`, `nfse-nacional`). Só contato direto com a secretaria de finanças de cada prefeitura resolve — o mesmo caminho usado para Cajamar. Depois de identificado o provedor real, cada um desses migra para o Grupo 1 ou Grupo 2/3 (se compartilhar provedor com alguém já construído) ou para o Grupo 4 (se for sistema próprio/isolado).

### Grupo 4 — Isolados / sistemas próprios (executar por último: sem reaproveitamento, cada um é obra única)
- **Barueri** (próprio) — já na onda atual.
- **Osasco** (RTC isolado) — já na onda atual.
- **Santana de Parnaíba** (Smarapd) — adicionado à onda atual por esta decisão (seção 1, item 2).
- **São Paulo (capital)** — Nota Paulistana, sistema único, não se repete em nenhuma outra cidade do catálogo.
- **São Vicente** — indício (não confirmado) de sistema próprio, segundo conteúdo de blog (Actana); sem fonte oficial da prefeitura. Tratar como candidato a Grupo 4 até confirmação; se na verdade usar SIGISS/Betha/e-Receita, migra para onde couber.

---

## 3. Ordem final de execução (após a onda atual fechar)

**Grupo 2 → Grupo 1 → Grupo 3 → Grupo 5 (resolver provedor, depois reclassificar) → Grupo 4.**

Esta ordem maximiza quantos municípios ficam operacionais por bloco de código escrito, porque os grupos 2, 1 e 3 são os que têm maior razão cidades-cobertas/esforço-de-engenharia; o Grupo 5 precisa de descoberta antes de poder ser sequenciado com segurança; e o Grupo 4 fica por último porque cada cidade ali é um custo fixo que não se divide entre várias cidades, exatamente como Cajamar exigiu 3 dias de trabalho dedicado para servir só a ela mesma.

**O que isto NÃO faz:** não certifica nenhum município, não altera CI, não autoriza merge, deploy, credencial real ou ativação fiscal de produção, e não substitui o checklist técnico de `UF_100_COMPLETA` nem o gate per-city de NFS-e já descritos no cronograma mestre. É só a ordem em que os blocos de engenharia devem ser atacados.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
