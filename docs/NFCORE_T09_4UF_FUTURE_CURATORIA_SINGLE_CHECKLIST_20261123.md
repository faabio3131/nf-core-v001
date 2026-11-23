# NFCore T09 — Backlog único da PR futura de curadoria documental: RR, PA, AP, SE

**Origem:** PR #592, decisão do Diretor em 23/11/2026. **Sem escopo de implementação do motor**. Este checklist é o único ponto de entrada das quatro UFs na **PR futura** de curadoria jurídica. **Nenhuma busca nova foi feita nesta etapa de transferência**.

**Regra de aceite para cada UF/modalidade:** arquivar fonte oficial original com URL, publicador, data/competência, páginas/dispositivo, SHA-256 dos bytes íntegros; reconciliar alterações/sucessão, CONFAZ/depósito e jurisprudência quando necessários; documentar cenários positivos e negativos determinísticos; revisão jurídica independente; CI verde; importar apenas se `APLICAVEL_CERTIFICADO` e cumpridos os controles fiscais. **Na ausência de prova, manter bloqueio operacional**; não declarar inexistência a partir de timeout/WAF. Atos concessivos individuais são dependências de habilitação de cliente real, não pré-requisito para a pesquisa interna. 

## RR — RICMS-RR, Anexo I, art. 1º, LXVII (insumos agropecuários)

- [ ] **Consulta Tributária SEFAZ-RR nº 24/2024, 05/11/2024**, inteiro teor oficial e SHA-256. Fonte oficial identificada: `https://www.sefaz.rr.gov.br/downloads?catid=1404&id=25395&m=0&task=download.send` (redirecionamento não arquivado).
- [ ] **RICMS-RR Decreto 4.335-E/2001, Anexo I, art. 1º, LXVII**, texto consolidado **até a competência de 2026** e SHA-256; conferir Decreto **30.363-E/2021** e limite histórico de **31/12/2025**. A consolidação de outubro/2026 foi identificada, mas seus bytes não foram obtidos.
- [ ] **Atos estaduais publicados nos DOEs de 2025/2026** que prorroguem, alterem ou extingam expressamente o **inciso LXVII**; se inexistentes, obter **consolidação/certidão oficial abrangente** da competência e documentar critério de exaustividade. Índices SEFAZ já hashados não substituem a certidão.
- [ ] **Convênio ICMS 100/1997 e alterações CONFAZ** aplicáveis a 2026, com internalização estadual específica: não equiparar prorrogação CONFAZ automaticamente à vigência estadual nem confundir isenção com redução de base.
- [ ] Revisão contraditória e testes positivos/negativos por produto, operação interna, temporalidade e exceções, mantendo negativa operacional enquanto não comprovado.

## PA — Lei 6.913/2006, Decreto 2.490/2006, ADI 3779

- [x] **DOE-PA nº 33.584 de 23/03/2018**, Decreto **2.014/2018** Apêndice I itens **13 e 32**: original arquivado com SHA-256 `6dbf8fdb313e6673ce6105b9c6e74714070adaa220e39cbd2187840ef4abf0a0`.
- [x] **Decreto 2.490/2006** histórico ALEPA, SHA-256 `313fe0b074d55dedbff71ba148b7e703a96da1611341aee0ae074ceaa5278ad3`; **STF ADI 3779** HTML de decisão SHA-256 `aede1b1a62bca6bdf677a8c0a54313a61785cd538a1b05ce6a91a96e2c0b5ac5`.
- [ ] **Acórdão/dispositivo final e eventuais efeitos supervenientes da ADI 3779**, com fonte oficial e SHA-256, confrontando expressamente a Lei **6.913/2006**.
- [ ] **Lei estadual 8.930/2019**, arts. 2º–8º, texto oficial original/DOE e SHA-256 (localizada em `https://www.legispara.pa.gov.br/lei/5169`, bytes ainda não arquivados).
- [ ] **Certificado de Registro e Depósito / planilha PNTT-CONFAZ** vinculada ao inventário da Lei **6.913/2006** e do Decreto **2.490/2006**, incluindo o alcance material de cada modalidade e prazo/concessão após 2019.
- [ ] Consolidar eventual **lei/decreto sucessor, alterações e outorgas vigentes na competência 2026**, sem revalidar automaticamente lei inconstitucional.
- [ ] Revisão independente e testes positivos/negativos para eventual sucessão; manter **`NAO_APLICAVEL_CERTIFICADO` apenas quanto à utilização isolada da Lei 6.913/2006 original**, nunca à totalidade das possíveis sucessões.

## AP — pescado (Decreto 3.599/2001; legislação 2025/2026)

- [ ] **Decreto AP 3.599/2001 integral**, DOE **nº 2.669, de 21/11/2001**, e sua **republicação DOE nº 2.751, de 25/03/2002**, com SHA-256 e alterações até 2026.
- [ ] **Certificado AP/CONFAZ nº 14/2018, Anexo I item 11**, respectiva planilha de depósito/PNTT, original e SHA-256; vincular ao diferimento do pescado sem confundir com crédito presumido industrial.
- [x] **Lei AP 3.395/2025, DOE nº 8.566**, Anexo II item 8, SHA-256 `d4c6b485514ac97dc3bbe8418b07ff7324984e58670d056601be0d6c8a3fff44`.
- [x] **Decreto AP 2.349/2026, DOE nº 8.631, 07/04/2026**, SHA-256 `8db2b8901a3774739846444691b8caced5bd549759537e28182fc19782bcf9c5`; **Decreto AP 2.656/2026, DOE nº 8.639, 17/04/2026**, SHA-256 `6b0c7f575d89cea05b7d031778a326d2a4d85f51458abf052a63720a576f7bd0`.
- [x] **Lei AP 3.490/2026, DOE nº 8.659**, SHA-256 `9180d91856bd3d955cc99a1a1e5b9c5f789131253e97a947e2d2f3ffde3f9523`; ausência do Decreto 3.599 em seu Anexo não prova extinção do regime.
- [ ] Reconciliação **material/temporal** do Decreto 3.599 com os atos de 2026, incluindo art. 3º e art. 9º do Decreto 2.656, Lei 3.395/2025 e eventuais atos posteriores aplicáveis.
- [ ] Revisão jurídica independente e testes positivos/negativos do diferimento, estabelecimento industrializador, operação interna e crédito presumido distinto; **concessão individual CONDI/SEFAZ só para ativação real quando exigida**.

## SE — PSDI, Lei 3.140/1991, Decreto 29.935/2014

- [x] **Lei 3.140/1991**, compilação ALESE até 2026, SHA-256 `520b1a1f93b9a1c6c8ec5d315d5d885ec436df4236f7c46dfbdc9a21b9c080a5`; **Decreto 29.935/2014** histórico PGE, SHA-256 `ca18358fccdfd93259819b1ab1d2fe7347b7084cde54d9660b3c8d0ffc67b3b8`.
- [ ] **Lei SE 8.490/2018**, arts. 1º–3º e Anexo Único item 1, publicação original/DOE integral e SHA-256. Texto ALESE localizado: `https://aleselegis.al.se.leg.br/Arquivo/Documents/legislacao/html/l84902018.html`.
- [ ] **Certificado de Registro e Depósito SE/CONFAZ nº 13/2018**, **planilha/atos depositados por modalidade**, original e SHA-256. **Certificado nº 126/2024 não substitui 13/2018**, porque tem outro escopo.
- [ ] **DOE-SE de 16/10/2024, Decreto 820/2024** (efeitos indicados a partir de 23/07/2024), original e SHA-256.
- [ ] **DOE-SE de 26/11/2024, Decreto 868/2024** (efeitos intramês), original e SHA-256.
- [ ] Consolidar leis/decretos de 2025–2026, inclusive **Lei 9.494/2024, 9.812/2025 e 9.943/2026**, com provas e competência de efeitos.
- [ ] Fechar **cada uma das seis modalidades** da matriz `NFCORE_T09_SE_PSDI_MODAL_MATRIX_20261123.json`: `SE_PSDI_NEW_INDUSTRY_8`, `SE_PSDI_NEW_INDUSTRY_6_2`, `SE_PSDI_DOMESTIC_RAW_DEFERRAL`, `SE_PSDI_CAPITAL_GOODS_DEFERRAL`, `SE_PSDI_IMPORTED_RAW_DEFERRAL`, `SE_PSDI_EXISTING_INDUSTRY_GROWTH`. Não converter 8% ou 6,2% sobre ICMS devido em alíquota nominal; não confundir diferimento com isenção.
- [ ] Revisão contraditória e testes positivos/negativos por modalidade/competência; resolução **CDI individual apenas para habilitação real do contribuinte**, não pré-requisito à pesquisa normativa pública.

## Gate único de fechamento da PR futura

- [ ] Cada norma/alteração/CRD tem arquivo, SHA-256, origem, data, competência e vínculo preciso com a hipótese selecionada, ou impedimento formal justificando decisão segura limitada.
- [ ] Análise temporal e normativa conclui aplicabilidade ou inaplicabilidade com alcance explícito, sem deduzir inexistência de ato a partir de erro de download.
- [ ] Testes positivos e negativos, contrato fiscal e isolamento de tenant executados e CI do HEAD cumulativo verde.
- [ ] Revisão jurídica independente documentada e aprovação humana se necessária.
- [ ] Somente após esses gates a PR documental futura pode propor reclassificação: nunca importar nem ativar automaticamente regra por ter sido pesquisada.

**Acesso restrito**: se a planilha PNTT/CONFAZ não for pública, solicitar acesso/fornecimento por canal institucional legítimo à autoridade competente, sem supor que o Diretor deva conseguir o arquivo pessoalmente. **Nenhuma pendência da PR futura bloqueia o fechamento técnico interno da PR #592.**
