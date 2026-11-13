# NFCore — piloto da contabilidade SP-3 (13/11/2026, 09:00 BRT)

**Prioridade determinada pelo proprietário:** Cajamar em primeiro lugar; se a integração estiver incompleta, incluir Osasco e Barueri no mesmo diagnóstico/piloto. Esta trilha é **aditiva** à issue #445 e à PR #446, isolada de BH/PR #440, Bling, produção e Contabo. Nenhuma emissão produtiva é autorizada por este documento.

**Sem certificado de prontidão:** o catálogo de 22 municípios não inclui Cajamar; nem Cajamar, nem Osasco, nem Barueri possuem prova de NFS-e real ponta a ponta para um contribuinte autorizado nesta entrega. Não anunciar que três municípios estão certificados ou que a versão da PR foi implantada.

## Matriz específica do piloto

| Praça/IBGE | Cenário MEI (competência desde 01/09/2023) / ME-EPP Simples (desde 01/11/2026) | Demais regimes e competências históricas | Situação NFCore |
|---|---|---|---|
| Cajamar / `3509205` | **Emissor Nacional** por regime e competência; exigem-se cadastro/credenciamento da empresa e binding durável por tenant/unidade | Prefeitura usa plataforma municipal; GeisWeb aparece em documentação de terceiros, mas sem contrato de integração municipal autenticado pelo NFCore | Gateway nacional de homologação existe, guard SP testado; sem autorização externa, sem ciclo completo certificado |
| Osasco / `3534401` | **Emissor Nacional** quando exigido pelo marco federal; confirmar exceções com contador e canal oficial | Prefeitura mantém sistema e WebService próprios, RTC_ no WSDL de homologação, manual 2.1 (abr/2026), autorização e credencial próprias | Roteador canônico atual reconhece **somente Nacional e WebISS Extrema**; adaptador municipal Osasco e E2E ausentes |
| Barueri / `3505708` | **Emissor Nacional** quando exigido pelo marco federal | WebService próprio RPS/PMB, certificado digital, layouts PMB 003/004 e requisitos de 2026 | Roteador canônico atual reconhece **somente Nacional e WebISS Extrema**; adaptador PMB municipal e E2E ausentes |

**Conflitos normativos a revisar com a contabilidade:**

- Cajamar publicou em julho uma comunicação que dizia 01/09/2026, **anterior** à Resolução CGSN 191/2026 que transferiu para **01/11/2026** a obrigação nacional de ME/EPP Simples; a competência, não o dia da requisição, controla o corte.
- Osasco afirma preservar o próprio emissor e compartilhar NFS-e com o ambiente nacional em 2026; isso **não equivale** a permissão de usar o emissor municipal para todos os regimes após a obrigação federal. Confirmar o enquadramento do CNPJ e os métodos disponíveis em homologação.
- A página oficial de Barueri usa literalmente **31/11/2026**, data inexistente, ao anunciar o fim do PMB 003. **Não codificar esta data**. Exigir retificação oficial antes de aplicar uma data de bloqueio; PMB 004 ainda requer XSD, semântica e testes próprios.

## Engenharia verificada nesta branch

1. `NfseNacionalHomologationGateway` participa da composição canônica somente sob A1, DPS assinado, pré-auditoria e binding persistido. `_GovernedNfseRouter` autoriza o provedor Nacional somente quando o Control Plane tem vínculo exato de NFS-e para o emissor, escopo, ambiente e operação. Sem vínculo não há envio.
2. O gateway Nacional antes só invocava o guard específico de MG, que **não impedia SP**; a correção acrescenta um **guard SP obrigatório antes do cofre de A1** para regime/competência, mantendo os requisitos existentes de MG. Isso corrige uma ausência de rejeição de combinações indevidas, não representa uma nova integração externa.
3. A resposta nacional autorizada inclui o XML oficial correspondente à chave (após validação existente de chave/raiz), agora preservado em `NfseAuthorizationResult.authorized_xml`. Não declarar persistência de arquivo provada até passar pelo handler e pela prova de leitura do banco.
4. Regressões: teste dos três IBGEs no preflight positivo/negativo e isolamento do A1/HTTP, inclusão do XML do resultado; CI completa precisa passar no **HEAD exato**.
5. Limite grave conhecido: `_GovernedNfseRouter.query` ainda oferece recuperação somente do WebISS Extrema, **não** uma consulta Nacional de reconciliação; cancelamento/substituição nacional não estão certificados nesse roteador. Não tratar aceite de `authorize` como operação fiscal completa.

## Roteiro de demonstração com o escritório

1. Confirmar **cidade do estabelecimento prestador** (não endereço do tomador), CNPJ, IM/IE conforme operação, regime MEI / Simples ME-EPP / normal e **competência do serviço**; registrar quem é titular do certificado.
2. Em ambiente de teste e com autorização expressa do contador, visitar `https://app.nfcore.com.br/trial.html`, cadastrar empresa/unidade, validar sessão e permissões e verificar o perfil fiscal; conferir versão realmente implantada, **não** assumir que a PR #446 já chegou à Contabo.
3. A1: só adicionar via cofre/interface autorizada no aplicativo; nunca por chat, repositório ou print. Para Nacional, confirmar credenciamento/API e o binding persistido `nfse-nacional-producao-restrita` para o **IBGE do prestador**; ausência do vínculo é bloqueio legítimo.
4. Preparar DPS com perfil fiscal e regras tributárias conferidos. Validar XSD/assinatura e apresentar **prévia sintética** somente como prévia. Se houver autorização específica, executar **uma** emissão em HOMOLOGATION (`tpAmb=2`) e salvar resposta/erros; documentos do ambiente de teste não possuem valor fiscal.
5. Consultar e reconciliar sem retransmitir automaticamente requisições com resposta ambígua. Testar cancelamento/substituição apenas se o adaptador efetivamente fornecer os contratos, credenciais e gatilhos seguros — até lá marcar **BLOQUEADO**.
6. Para Osasco e Barueri em regime/caso municipal, demonstrar o **portal oficial** e documentação de homologação, não simular a emissão via adaptadores inexistentes. Não inserir endpoints de terceiros em produção.

**Gate de conclusão:** (i) CI verde no commit final; (ii) assinatura/XSD; (iii) binding e A1 reais do emissor; (iv) autorização oficial em homologação; (v) consulta/reconciliação, cancelamento/substituição quando aplicáveis; (vi) XML/PDF arquiváveis e segregação tenant/unidade; (vii) versão exata realmente implantada. Até todos os gates, **INTERNAL_INCOMPLETE / EXTERNAL_HOMOLOGATION_PENDING**.

## Fontes primárias e contratos a inspecionar

- Cajamar, comunicado histórico: https://cajamar.sp.gov.br/noticias/2026/07/15/empresas-do-simples-nacional-deverao-emitir-nfs-e-exclusivamente-pelo-emissor-nacional-a-partir-de-setembro/
- Cajamar, serviços fiscais oficiais: https://cajamar.sp.gov.br/fazenda/servicos-online/
- CGSN 191/2026: https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/agosto/simples-nacional-nfs-e-nacional-sera-obrigatoria-para-me-e-epp-a-partir-de-1o-de-novembro-de-2026
- Portal Nacional, documentação vigente: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual
- Osasco, comunicado e WSDL homologação: https://nfe.osasco.sp.gov.br/EissnfeWebApp/portal/NfEletronica.aspx
- Osasco, manual WebService 2.1 abril/2026: https://nfe.osasco.sp.gov.br/EissnfeWebApp/Portal/Manual/Geracao%20de%20NFS-e%20Via%20Web%20Service%202.1.pdf
- Barueri, Secretaria de Finanças: https://portal.barueri.sp.gov.br/secretarias/secretaria-de-financas/nota-fiscal
- Barueri, manual WebServices e endpoint: https://www.barueri.sp.gov.br/nfe/Manuais/Guia_Conversao_RPS_Lote-v106.pdf
- Barueri, catálogo de manuais e esquemas: https://www.barueri.sp.gov.br/nfe/app/wfManuais.aspx
