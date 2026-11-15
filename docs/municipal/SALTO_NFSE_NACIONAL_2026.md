# Salto/SP — NFS-e Nacional — engenharia interna (15/11/2026)

**Município:** Estância Turística de Salto, São Paulo — **IBGE 3545209**. **Não confundir** com Salto Grande/SP (IBGE 3545407).

**Bloco:** NFCore V1 / SP-22 / Grupo 2 — Emissor Nacional, após Santana de Parnaíba. **Estado:** construção de testes municipais iniciada; não homologado externamente.

## CURRENT verificado no GitHub

- Branch-base certificada: `integration/nfcore-a1-sp2-current-main-20261113` @ `fead2f08de43da1bf837a646bbd64d133551f9fe`, com CI integral GitHub Actions #43748674148 SUCCESS; PR cumulativa #468 ainda não mergeada em `main`.
- Santana PR #496 já foi incorporada à PR #468; PR #501 do outro executor continua separada e não é alterada por esta frente.
- Emissor Nacional existente: `gateway/nfse_nacional_homologation.py` e `gateway/nfse_national_homologation.py`. DPS 1.01 XSD/XMLDSig, certificado A1, mTLS, retorno NFS-e XML assinado e lifecycle usam o mesmo Domain/Application/Control Plane.
- `mg_nfse_channel_guard.py` retorna sem bloquear municípios que não são MG. Não existe necessidade técnica de generalizar o filtro MG para Salto.
- O caminho canônico de autorização **não é** o catálogo municipal estático. Configuração durável explícita: `tenant + unit + homologation + NFSE + IBGE issuer 3545209 + AUTHORIZE + nfse-nacional-producao-restrita`. O Portal não determina provedor nem substitui RBAC.

## Evidência normativa — proveniência separada

1. **Comunicação municipal reproduzida por imprensa especializada, fonte secundária:** a Secretaria de Finanças de Salto teria determinado o uso exclusivo do Emissor Nacional desde **01/01/2026**, sob Decreto Municipal **319 de 23/12/2025**.
   - https://notagateway.com.br/blog/salto-sp-passa-a-emitir-nfs-e-exclusivamente-pelo-portal-nacional/
   - https://suzano.tv/2026/01/prefeitura-de-salto-informa-que-a-emissao-de-nfs-e-passa-a-ser-realizada-exclusivamente-pelo-portal-nacional/
2. **Apoio normativo municipal reproduzido em base legal não oficial:** Decreto 14/2026 em Salto descreve adequações ao Emissor Nacional e efeitos retroativos a janeiro/2026. **Pendente** obter o Decreto 319/2025 diretamente do Diário Oficial da Prefeitura para a matriz final de vigência por regime/especialidade.
   - https://leis.org/camara/sp/salto/lei/decreto/2026/14/decreto-n-14-2026-regulamenta-o-6-do-art-251-da-lei-municipal-n-3196-de-21-de-agosto-de-2013-instituindo-o-regime-especial-de-tributacao-para-fins-de-apuracao-e-recolhimento-do-imposto-sobre-servico-iss-paras-as-atividades-que-especifica-e-da-outras
3. **Fonte primária federal:** Receita Federal/CGSN Resolução 191/2026 exige, para ME/EPP do Simples, **Emissor Nacional desde competência 01/11/2026**, mesmo quando município mantém emissor próprio. O corte é por competência, não data de transmissão.
   - https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/agosto/simples-nacional-nfs-e-nacional-sera-obrigatoria-para-me-e-epp-a-partir-de-1o-de-novembro-de-2026/
   - https://www.gov.br/nfse/pt-br/noticias/nfs-e-informa-diretrizes-sobre-a-obrigatoriedade-da-emissao-da-nfs-e-nacional-para-optantes-do-simples-nacional/
4. **Aderência nacional municipal:** referências secundárias que examinaram a planilha oficial `municipios-aderentes-20260928.xlsx` apontam Salto como conveniado ativo/aderente ao Emissor Nacional. Conferir planilha governamental original para certificar essa classificação.
   - https://emitta.com.br/nfs-e/sp/salto/

**Regra de confiabilidade:** não inferir automaticamente que uma notícia secundária comprova cada hipótese de incidência do ISS, regime especial, retenção ou data retroativa. As regras de classificação fiscal permanecem no domínio governado e precisam de revisão humana. Este bloco não cria gateway, política de alíquota, binding global nem segundo registro de numeração.

## CURRENT → TARGET e critérios de aceite

- **CURRENT:** gateway nacional reutilizável, DB/UoW, emissão e arquivo fiscais nacionais operantes na candidata cumulativa; Salto não possui prova E2E própria e não é `INTERNAL_COMPLETE`.
- **TARGET:** mesmos fluxos canônicos para Salto (3545209), com contrato/snapshot municipal verificável, preparação Portal e API, recibo assinado e archive, consulta, cancelamento/substituição conforme contrato nacional suportado, replay idempotente, RBAC, spoofing cross-tenant, XSD, migrations/PG e CI integral.
- **Implementação deste primeiro lote:** parametrizar a regressão nacional HTTP/SEFIN sintética já existente para incluir Salto no regime normal, sem duplicar funções de emissão; testes municipais de vínculo durável, preparação/idempotência e negativas de autorização/ambiente. A fixture de perfil passa a usar o nome real Salto com IBGE 3545209.
- **Fora de escopo deliberadamente nesta revisão:** testes com credenciais A1 de cliente, chamadas SEFIN externas, homologação municipal oficial, qualquer alteração em `main`, `production`, Contabo ou migrations produtivas.

## Gate de fechamento

Somente marcar `INTERNAL_COMPLETE` após CI integral **SUCCESS no HEAD exato**, confirmação das jornadas nacionais de consulta/eventos para Salto e reconciliação eventual com as PRs cumulativas em avanço. Sem essa prova, estado é **IN_PROGRESS**.
