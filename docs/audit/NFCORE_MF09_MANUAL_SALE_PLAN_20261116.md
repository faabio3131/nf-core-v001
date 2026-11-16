# MF-09 — fechamento da emissão manual no Portal

16/11/2026. CURRENT remoto: main549ab3c0, productionea4bdd3b, candidata4689bd66f73 após integração515; recibo nacional51616938448 ainda em validação. Base local31c152ee (árvore8e012c1b igual516). Ordem do proprietário: reconciliar PRs e concluir engenharia interna, usando CI como gate e não como atividade substituta.

CURRENT: preparação atômica NF-e55, TaxRuleEngine, perfis emitente/produto, A1, arquivo, transmissão/reconciliação/XML/PDF existentes. A preparação de venda só é acessível por Bling. NFC-e65 tem gateway MG e QR v3 online verificado, mas não builder concreto a partir de itens.

TARGET/escopo: adaptar fatos de venda manual no mesmo Portal para CanonicalFiscalDocument; estender builder/preparação existentes para modelo65 MG online; reutilizar catálogo, regras revisadas pinadas no servidor, UoW, sequência por modelo, assinatura/XSD, arquivo e operações fiscais já presentes. NF-e55 SP/MG e NFC-e65 MG em homologação. Sem nova API fiscal, engine, numeração, autenticação ou persistência paralela. Não construir contingência sem contrato, não inferir regra a partir de checkbox, não transmitir na preparação.

Mapa de impacto: extrair parser de regra/revisão do destinatário do adaptador Bling para módulo neutro com compatibilidade; policy manual por escopo canônico/modelo com hash; adapter estrito de itens/pagamentos; builder55/65 e preparo atômico; operação prepareNativeSale e consulta de configuração no Portal; formulário de venda na tela Emissões; testes HTTP/persistência/XSD/replay/UI. Áreas protegidas: tenant, unidade, ambiente, RBAC/CSRF, Vault, claim/idempotência e cálculo tributário. Nenhuma migration.

Aceites: somente produtos/emitente/regras vigentes do servidor; payload não seleciona XML/provedor/contador/tenant/taxas; valores reconciliados; replay idêntico sem nova reserva/assinatura e conflito de conteúdo sem efeitos; falha antes do commit reverte reserva/lifecycle/arquivo; modelo65 com chave65 e suplementoQR3 correto; fluxo manual usa authorize/query/download existentes; testes de isolamento e HTTP; regressão Bling; revisão independente e CI final cumulativa.

Pendências globais continuam separadas: MF04/BH, eventosGuarulhos, confiança/históricoFIS03, reconciliação das origens e infraestrutura. Este bloco não as declara resolvidas.

## Decisões de revisão e escopo adicional necessário

Revisão independente encontrou colisão de numeração entre hosts Bling e Portal.
A mesma tabela fm_fiscal_sequences é reutilizada com linha de autoridade legal
por CNPJ/ambiente/modelo/série, ownership do tenant e lock PG por identidade legal.
Nenhuma migration adicionada. Todos os pipelines de documento fornecem emitente;
writers duráveis sem identidade são recusados. Maior contador legado é preservado;
política conflitante, ownership divergente e legado órfão exigem reconciliação.
Plano operacional e limitações de adoção em docs/operations/NFCORE_MANUAL_SALE_RUNTIME.md.

Também corrigidos: tratamento de TaxRuleNotFound/Ambiguity; replay antes da policy
atual com readback dentro da mesma UoW; correção de fatos após400/403/422;
instalador/validador de policy e overlay Compose read-only.

Jornada real HTTP revelou defeito anterior na montagem SOAP: mover a árvore
assinada introduzia default namespace do serviço no nfeProc. O gateway agora
preserva a árvore original e seu contexto de namespaces em SOAP e arquivo.
Testes verificam assinatura em ambos, três variantes de namespace e PDF real
DANFE/DANFC-e; nenhum teste válido foi removido.

Revisor independente:163PASS/25PG SKIP/0FAIL sobre31c152ee+delta local;
três variantes adicionais SOAP/archive PASS. Ruff, Mypy421 fontes e frontend
lint/typecheck/26 testes/build PASS. Chromium local não instalou (download
inválido); quatro cenários Playwright novos exigem CI. Suíte integral local
anterior identificou cinco fixtures de numeração sem CNPJ; corrigido contrato
das fixtures e retestes passaram. Nova suíte integral final e CI com PG
permanecem obrigatórias no SHA publicado. Revisão não equivale ao EGM original
nem a fechamento global.
