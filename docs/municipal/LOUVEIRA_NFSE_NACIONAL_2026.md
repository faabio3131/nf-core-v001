# Louveira/SP — NFS-e Nacional — Escopo e certificação SP-22

**Data de auditoria:** 15/11/2026. **Município:** Louveira/SP, **IBGE 3527306** (IBGE oficial).
**Frente:** Agente A (engenharia municipal); Integrador único faz o aceite e merge, após handoff formal na issue #447.
**PR-base confirmada antes do trabalho:** #468, branch `integration/nfcore-a1-sp2-current-main-20261113`, HEAD `2b79bb5ddb20971ceb940f458086db8cdad8f5f3`. Esta branch de Louveira é isolada; nenhuma alteração direta à #468, `main`, `production` ou Contabo.
**Estado ao criar o dossiê:** implementação e CI da PR específica pendentes; NÃO promover `INTERNAL_COMPLETE` sem CI integral no HEAD e aceite do Integrador.

## Fonte primária e decisão do canal

1. **Lei Municipal nº 3.023 de 26/11/2025**, Diário Oficial de Louveira, edição 2541A de 28/11/2025:
   https://www.dosp.com.br/leituratexto?p=MjM5ODkyMw%3D%3D
   - Art. 1º e 2º: instituem NFS-e padrão nacional e acesso ao Emissor Nacional para contribuintes de Louveira, inclusive PJ do Simples, MEI e imunes/isentos cadastrados.
   - Art. 2º §1º: a atividade precisa constar na lista fiscal aplicável. Esta PR não inventa enquadramento ou lista tributária.
   - Art. 2º §2º: regularidade cadastral do contribuinte; confirmação oficial não é inferida de dados da UI.
   - Art. 2º §4º e §5º: motivo de cancelamento e prazo de **até 15 do mês subsequente ao da emissão**.
   - Art. 5º: escrituração e importação de dados no sistema municipal continuam distintas do ciclo de emissão da NFS-e.
   - Art. 7º: identificação da opção pelo Simples; não substituir as decisões tributárias do Core por um texto arbitrário.
   - Art. 25: **autônomos e profissionais liberais cadastrados como pessoa física** usam **sistema municipal próprio**; o contrato desta PR é o Emissor Nacional de **PJ/CNPJ**, não declara homologia do canal PF.
   - Art. 28: efeitos desde **01/01/2026**.
2. **Prefeitura de Louveira, página oficial NFS-e:** https://louveira.sp.gov.br/servico/nfse-gov — migração ao Emissor Nacional.
3. **Diário Oficial, adesão ao convênio NFS-e Nacional (2025):** https://www.dosp.com.br/exibe_do.php?i=NjU2OTQ1
4. **IBGE:** https://www.ibge.gov.br/explica/codigos-dos-municipios.php — Louveira 3527306.
5. **Receita / Portal Federal NFS-e:** https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual — DPS e Eventos XSD 1.01, Emissor Público API, anexos.
6. Histórico anterior municipal (2024): NFE-CIDADES. **Não reutilizar esse canal antigo como autoridade atual do Emissor Nacional** nem criar segundo motor: https://www.louveira.sp.gov.br/conteudo/prefeitura-substitui-sistema-para-emissao-de-nota-fiscal

## CURRENT → TARGET, autoridade canônica

**CURRENT:** a PR cumulativa #468 possui motor NFS-e Nacional, Portal `prepareNativeNfse`, DPS 1.01, certificado A1/PKCS#12, mTLS, XMLDSig/XSD, emissão, consulta e recuperação GET, `cancelNationalNfse` 101101, `reconcileNationalNfseCancellation`, substituição por nova DPS `subst/chSubstda`, arquivos/estados, RBAC, tenant/unidade e idempotência. Código previamente certificado em Salto.

**TARGET INTERNO Louveira (PJ/CNPJ):**
- mesmo Emissor Nacional com **vínculo durável exclusivo** `tenant + unit + homologation + NFSE + IBGE 3527306 + operação + provider nacional`; frontend jamais escolhe provedor;
- emissão, consulta, XML, cancelamento, recuperação de cancelamento incerto e substituição na mesma API/Portal/UoW, sem município duplicado;
- recusa de estado/envio sem binding, revisão humana e autorização individual; isolamento tenant/unidade, replay idempotente sem duplo POST, arquivo fiscal validado;
- aplicação dos limites locais do **art. 2º §5º** nas tentativas de cancelamento/substituição, calculados a partir de `infNFSe/dhProc` no XML oficial assinado, não da data de preparação de DPS nem da competência;
- cálculos/decisões do ISS continuam no Core e exigem normativas e revisão humana conforme o regime. Não presumir atividade/isenção/retentor pelo município;
- teste puro dos limites de calendário local `America/Sao_Paulo`, inclusive 15/16, virada de dezembro, relógio UTC e timestamp sem timezone;
- regressões E2E HTTP sintéticas com A1 para Louveira: emissão/DPS assinatura, consulta recovery, cancelamento 101101 com evidência, substituição atômica, caminhos vencidos, autenticação/RBAC, binding e replay;
- CI integral sobre HEAD exato, governança, completude, frontend, PG/migrations quando previsto, contêiner, segurança, E2E, sem apagar testes.

**Nuance importante:** `dhProc` indica data/hora de validação da DPS e geração da NFS-e no XSD federal. Em Louveira, o prazo é contado da **emissão oficial da NFS-e**, **não** da DPS preparada internamente. O serviço lê o XML oficial arquivado, verifica assinatura/identidade e falha se `dhProc` estiver ausente, inválido, adulterado ou não possuir timezone. Revalida o prazo dentro da UoW que reivindica o evento, impedindo race de virada de mês. Reconsultas de evento já enviado não são cancelamentos novos e continuam permitidas após o prazo.

## Limites que não podem ser confundidos com implementação

A lei separa explicitamente profissionais/autônomos PF em **canal municipal próprio** (art. 25); esse contrato municipal não é o Emissor Nacional de PJ nem foi obtido/certificado nesta PR. A escrituração/guia municipal (art. 5º e seguintes) não é realizada pela emissão nacional e exige fluxo próprio quando fizer parte do escopo comercial. O processo não libera automaticamente atividades fora da lista, enquadramento tributário especial, nenhuma dispensa de ISS ou regularidade cadastral.

Homologação externa com SEFIN Nacional e identidade A1 verdadeira do contribuinte, comprovação de inscrição/regime real, disponibilidade municipal efetiva, produção, credentials, DNS/TLS e implantação permanecem **EXTERNAL_HOMOLOGATION_PENDING**, não substituídas por fixtures.

## Handoff e gates finais

1. Publicar PR específica em Draft para a candidata #468 com HEAD, diff e arquivos protegidos.
2. Certificar Ruff/Mypy, Pytest integral, frontend lint/typecheck/testes/build, E2E, Docker/smoke, security, migrações/PG e governança/completude.
3. Registrar na issue #447 PR, HEAD, CI URL/resultados, revisão de legislação e lacunas externas.
4. Status `READY_FOR_INTEGRATION_REVIEW` **somente após gate completo SUCCESS**; o Integrador é o único responsável por aceitar e executar merge na candidata e repetir a CI cumulativa.
5. Nenhum executor desta PR faz merge, deploy, credenciais reais, publicação, emissão fiscal real, migrations produtivas ou alteração de `main`.

**Status técnico nesta revisão documental:** código e testes em construção; usar execução GitHub CURRENT para certificação. A norma municipal não equivale à homologação externa.
