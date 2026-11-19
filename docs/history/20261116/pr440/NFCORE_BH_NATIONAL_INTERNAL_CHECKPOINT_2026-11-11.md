# NFCore / MG-W1 — Belo Horizonte (3106200)

**Data:** 11/11/2026. **Estado:** `INTERNAL_PARTIAL / CI_UNDER_REVIEW / EXTERNAL_HOMOLOGATION_PENDING`.  
**Trilha:** #440, isolada de Extrema, Bling, Contabo, Workers e demais municípios.  
**Regra:** não declarar Belo Horizonte 100% concluída antes da matriz fiscal, API/Web, eventos e certificação no HEAD exato.

## Evidências e autoridade

1. Fonte oficial municipal BHISS: https://prefeitura.pbh.gov.br/fazenda/bhiss/avisos — desdobramento CTISS/cTribMun (três dígitos), NBS a partir da competência 2026, regimes especiais, IM/inscrição municipal e regras de migração para o emissor nacional.
2. Fonte federal SEFIN: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual — XSD nacional v1.01 / 2026 e documentação de leiautes.
3. Fonte federal APIs: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/apis-prod-restrita-e-producao — SEFIN produção restrita distinta de ambiente real.
4. Manual oficial contribuintes: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-contribuintes-emissor-publico-api-sistema-nacional-nfs-e.pdf — métodos GET /dps/{id}, GET /nfse/{chaveAcesso} e eventos nacionais.

## Implementação candidata nesta PR

- Contrato canônico com CTISS (3 dígitos), NBS (9 dígitos) e regime especial BH explícito, revisado, sem inferência automática. Preserva fingerprints anteriores quando opcionais ausentes e impede replay com classificação alterada.
- Arquivo persistente com novos campos e proteção contra adulteração; arquivos antigos continuam decodificáveis.
- Reserva transacional de numeração DPS no UoW de preparação (stream 91, isolado de RPS municipal 90); archive SHA e recuperação após restart, bloqueio de série incompatível e reuso idempotente da numeração.
- Builder nacional escolhe XSD oficial v1.01 para BH; insere cTribMun/cNBS na ordem oficial e exige reserva DPS imutável antes de assinar. Sem certificado, prepara mas não transmite.
- Roteamento nacional governado por provider binding, pré-auditoria e escopo do emitente. Recuperação read-only por GET /dps/{id} e GET /nfse/{chaveAcesso}; não reenvia POST após resposta incerta e não toma 404 como rejeição definitiva.
- Operação portal `prepareBhNfse`, vinculada a sessão+CSRF+RBAC, empresa/unidade derivadas do servidor, revisão fiscal humana e confirmação explícita de que não houve autorização.
- Testes offline: campos, XSD, fingerprint, codec, pré-auditoria, UoW/restart, HTTP autenticado, Playwright, recuperação read-only e recusa de assinatura/número/provedor indevidos.

## Pendências internas obrigatórias para BH 100%

- [ ] CI completa verde no SHA final, com Pytest, Ruff, Mypy, Playwright, PostgreSQL, imagens e segurança.
- [ ] Cobertura e validação dos dados estruturados de tomador/intermediário para os casos BH, quando exigidos, incluindo IM e regimes especiais por perfil/competência.
- [ ] Tributos NFS-e Nacional/RTC 2026, retenções, deduções, benefícios, regras por serviço e períodos oficiais: concluir matriz normativa positiva/negativa com fontes e evidências reproduzíveis.
- [ ] Cancelamento nacional por evento assinado e XSD oficial (POST /nfse/{chaveAcesso}/eventos), consulta, reconciliação, provas e rollback.
- [ ] Substituição nacional por fluxo oficial suportado, cancelamento por substituição, correlação de notas antiga/nova e recuperação de falhas (sem confundir cancelamento simples).
- [ ] E2E autenticado completo no mesmo runtime para emissão nacional, consulta, cancelamento e substituição; permissões e status comprovados.
- [ ] Review de segurança e fiscal no HEAD exato; dossiê de fechamento/governança do EGM.

## Separação de ativação externa

Não há CNPJ/certificado real de contribuinte, credenciamento ou emissão oficial comprovada nesta branch. Homologação externa requer A1 válido e habilitação do emitente, teste assistido autorizado, provas e decisão humana; não pode ser simulada por CI. Não fazer merge, deploy ou alterar Contabo apenas com esta PR Draft.
