# RTC-01 — Registro de normas vigentes, integridade e impacto (30/10/2026)

**Estado:** IN_PROGRESS — controles de integridade internos implementados; artefatos binários oficiais, hashes e avaliação operacional ainda pendentes.  
**Dependências:** RTC-00 em `main` via PR #267, merge `9e1b155a4256c7be486466135cc2c6c9c2c91300`; não substituir os contratos existentes.

## Fontes oficiais atuais identificadas

| Documento/artefato | Versão / publicação | Uso no NFCore | Prova / próximo delta |
|---|---|---|---|
| NT 2025.002 | 1.52 / 01-10-2026 | Campos CBS, IBS, IS e validação NF-e/NFC-e | Baixar PDF/leiaute/XSD oficiais, verificar hash e golden XML; referência em `config/rtc/official-baseline-2026-10-30.json` não constitui schema |
| NT 2026.007 | 1.10 / 01-10-2026 | Regras cadastrais de contribuintes para NF-e/NFC-e | Testar respostas oficiais e requisitos sem sobrepor a autoridade cadastral do tenant |
| NT 2026.008 | 1.00 / 01-10-2026 | Alterações de leiaute e regras de validação | Investigar interações e evitar regressão de schemas |
| NT 2026.010 | 1.00 / 01-10-2026 | Modelo de DANFE para RTC | Revisar representação/DANFE apenas onde o produto publica esse documento |
| NT 2026.006 | 1.00 / 25-08-2026 | Vínculo NF-e e transação financeira ligada ao split payment | Estudar evento/contrato; não integrar movimentação financeira sem aprovação |
| NT 2023.002 | 1.02 / 27-10-2026 | Redução de autorização assíncrona; descontinuação de inutilização em jurisdições específicas | **Impacto de segurança e lifecycle**: avaliar datas e UF por contrato oficial antes de mudar endpoint; preservar idempotência e histórico |
| Informe Técnico 2025.002 | **1.70 / 01-10-2026** | Tabelas CST/cClassTrib/cCredPres IBS/CBS | 1.60 está NÃO VIGENTE; baixar tabelas v1.70 da fonte oficial, registrar checksums e validar schemas antes de qualquer cálculo |\n| Informe Técnico 2023.002 | 2.10 / 04-09-2026 | Tabela CFOP | Verificar versionamento, integridade e vigência |
| Informe Técnico 2024.001 | 2.40 / 03-09-2026 | Tabela NCM a partir de 01-10-2026 | Evitar classificar produtos por catálogo desatualizado |
| Cronograma oficial RFB/CGIBS | atualizado 28-10-2026 | Obrigatoriedade por documento e empresa | Separar publicação de leiaute, vigência, obrigatoriedade, validação e homologação |

**Fonte oficial dos informes técnicos vigentes:** https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=hXzemuyNHW4%3D  \n**Fonte oficial das tabelas:** https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=%2FNJarYc9nus%3D  \n**Fonte principal da lista de NTs:** https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=04BIflQt1aY%3D  
**Cronograma oficial:** https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria-do-consumo/orientacoes-da-reforma-tributaria/cronograma

As NTs acima devem ser lidas **na íntegra** antes de qualquer alteração de cálculo, XML ou protocolo. Esta lista não presume que versões de tabelas especiais e NFS-e sejam as mesmas de NF-e.

## Contrato RTC-01 implementado na candidata

- `RegulatoryArtifactPin` e `RegulatoryBaseline` continuam sendo autoridades de registro.
- `compliance/rtc_evidence.py` verifica conteúdo binário com SHA-256 usando comparação segura; ausência de checksum, conteúdo vazio, conteúdo alterado ou pin inválido falha fechado.
- O verificador é puro e offline: **não faz scraping, download, seleção de fonte, publicação, habilitação fiscal ou alteração de regra**. A proveniência jurídica e a aprovação humana precisam existir antes de marcar um artefato como confiável.
- Testes sintéticos isolados verificam integridade, adulteração e falhas. Nunca chamar um fixture sintético de XSD ou XML oficial.

## Próximos trabalhos internos RTC-01

1. Buscar e armazenar as URLs oficiais diretas de PDF, tabelas CST/cClassTrib, alíquotas, XSD e documentação de NFS-e nacional, sem copiar dados de terceiros sem permissão.
2. Verificar SHA-256 dos downloads e registrar o hash e a versão na baseline após revisão de origem, publicações e vigência.
3. Construir teste de conformidade de esquema com **XML de referência validado** e prova de versão, antes de ligar a emissão.
4. Identificar as diferenças do CRT versus o regime de IRPJ/CSLL e vincular RTC-02 ao cadastro canônico.
5. Atualizar código/estado de operações afetadas pela NT 2023.002 apenas após extrair prazos e UFs dos próprios documentos, não de inferência.
6. Deixar RTC-01 `IN_PROGRESS` enquanto arquivos/XSD/tabelas faltarem, mesmo com a CI verde.

## Regra de merge e de disponibilidade

A integração desse verificador na `main` **não certifica RTC-01 como concluído** nem libera tributação real. Esta PR pode ser integrada quando CI/Governança do HEAD forem verdes e o diff não afetar código de produção. O próximo item continua sendo a coleção dos artefatos oficiais e matriz de classificação para RTC-02/03. Nenhuma migration, deploy, alteração de segredo, conta, provedor, checkout ou emissão real.
