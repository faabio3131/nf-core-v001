# NFCore — SP4: Cajamar, Barueri, Osasco e Jundiaí (12/11/2026)

**Escopo pedido pelo proprietário:** concluir um único bloco operacional antes do aceite, sem promover casos parciais como municípios prontos. Escopo adicional SP4 dentro da issue #445 e PR #446. Não alterar BH #440, Bling, credenciais e Contabo.

**NÃO É FECHAMENTO.** A homologação da contabilidade está planejada para 13/11, 09h BRT. Todo código deste documento é de **branch isolada**, sem merge/deploy; testes executados com serviços sintéticos não são respostas oficiais de prefeitura. A ausência de credencial do emissor/contrato não autoriza simular uma NFS-e real.

## Auditoria atual: quatro municípios e dois canais distintos

| Emissor (IBGE) | Canal federal quando MEI (desde 01/09/2023) / ME-EPP Simples (competência desde 01/11/2026) | Canal municipal quando legalmente aplicável | Código interno nesta PR | Critério ainda não comprovado |
|---|---|---|---|---|
| Cajamar (`3509205`) | NFS-e Nacional, apenas com binding e A1 do contribuinte | GeisWeb, versão/endpoint e liberação por CNPJ a conferir na fonte municipal | `cajamar_geisweb_homologation.py` fail-closed | WSDL/XSD próprio vigente, XMLDSig de Cajamar, credenciamento e E2E de emissão, consulta e cancelamento |
| Barueri (`3505708`) | NFS-e Nacional, idem | Prefeitura, RPS em arquivo PMB004; WebService de remessa/status/retorno | `barueri_pmb004_homologation.py` fail-closed | Builder/validador de **todos** os campos PMB004, numeração única, resposta final correlacionada ao XML e lifecycle |
| Osasco (`3534401`) | NFS-e Nacional, idem | Prefeitura EissNfe, WCF SOAP com métodos RTC_ e chave própria do contribuinte | `osasco_rtc_homologation.py` fail-closed | WSDL/hash vivo validado, XML completo do RTC, conversão do resultado em NFS-e oficial e fluxo de cancelamento |
| Jundiaí (`3525904`) | NFS-e Nacional, idem | GissOnline V2 (ABRASF 2.04+RTC, **não** usar Ginfes legado) | `jundiai_giss_homologation.py` fail-closed | Pacote XSD vigente validado, XMLDSig envelope, prova por RPS/lote e cancelamento com resposta oficial |

O roteador principal `_GovernedNfseRouter` reconhece os canais Nacional e WebISS Extrema. Nesta PR, os quatro transportes municipais foram criados como fronteiras opt-in **mas ainda não são adaptadores completos do domínio `NfseAuthorizationRequest` nem compõem o runtime de produção**. Não são consideráveis operacionalmente integrados.

## Entregas implementadas na branch sem fingir E2E

- Nacional (comum aos 4): guard SP obrigatório por regime e competência antes do A1; autorização mTLS para homologação; XML oficial ligado à chave; DPS determinística recuperada por ID; GET /dps -> GET /nfse sem novo POST; binding específico `QUERY` no Control Plane antes da consulta; testes de regressão por cidade e isolamento A1/HTTP. **Lacunas:** numeração fiscal durável para nDPS, eventos de cancelamento/substituição, composição da interface e prova de persistência/arquivo PDF completo.
- Cajamar: contrato de transporte com WSDL/XSD pinados por port, A1, proibição fiscal de emissão municipal de MEI/Simples em competência obrigatória nacional, cancelamento exigindo aprovação humana, endpoint restrito por HTTPS/allowlist. Falta contrato vigente específico comprovado e o pipeline de XMLDSig/serialização.
- Barueri: cabeçalho PMB004 de 25 bytes e CRLF, bloqueio de competências nacionais, emissão via `NFeLoteEnviarArquivo`, status e arquivo de retorno via SOAP/mTLS; `OK200` não é tratado como autorização de nota. Falta construir e verificar a linha completa do RPS/RTC PMB004 e interpretar cada retorno final.
- Osasco: envelope WCF, chave só de cofre/porta autorizada, método RTC de emissão/consulta e cancelamento documentado, payload com estrutura e schema verificados por dependência externa; resposta `Erro=false` nunca se promove automaticamente para nota emitida. Falta extrair XML verificável da nota e vincular ao RPS/documento fiscal.
- Jundiaí: fronteira GissOnline V2, XSD e assinatura obrigatórios (injeção de validador oficial, pacote não disponível no repo), métodos recebimento/consulta/cancelamento, consulta nunca reenvia lotes; `Situacao=4` sem conciliação por RPS não promove emissão. Falta pacote atual de XSD e resposta oficial assinada.
- CI geral, integrações e testes de banco dependem de sucesso no **HEAD exato**; CI antiga não certifica novo commit.

## Gates de aceite SP4: um único lote, sem certificação parcial

1. Por cidade: regra municipal e estadual por competência e perfil MEI/SN/normal, inscrição municipal/ISS e prestador.
2. Pela rota nacional: DTO da DPS, assinatura XMLDSig conforme XSD corrente, A1/escopo, sequenciamento durável por CNPJ/série, homologação de emissão, GET/recuperação, cancelamento/substituição por eventos e comprovantes XML/DANFSe/PDF.
3. Pela rota municipal: **pacote oficial de WSDL/XSD pinado por hash**, assinatura obrigatória, endpoints oficiais, credenciais apropriadas, preparação canônica de RPS, emissão, consulta, cancelamento, substituição se aplicável, serialização de retornos e prova por RPS/ISS.
4. Persistência/transação e isolamento: Controle de acesso empresa/unidade, idempotência, retries/timeout sem double-submit, saga de emissão pendente, operador humano para cancelamento, evidências por documento e observabilidade sem segredos.
5. Gateway no runtime principal + portal com prova por HTTP e botão, testes unitários e integração banco PostgreSQL, CI completa verde no SHA final.
6. Testes **reais** no endpoint de homologação **com A1 autorizado, CNPJ/IM habilitado** para cada município/canal efetivamente usado. Anotar resposta/identificador/falha e anexar evidência sem chaves/PII no GitHub.
7. Aprovação humana para qualquer merge/deploy/ativação fiscal. Só declarar 100% de cidade após cumprir 1–7.

## Fontes técnicas consultadas

- Nacional: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual
- Receita/CGSN 191/2026: https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/agosto/simples-nacional-nfs-e-nacional-sera-obrigatoria-para-me-e-epp-a-partir-de-1o-de-novembro-de-2026
- Cajamar: https://cajamar.sp.gov.br/fazenda/servicos-online/ ; referências não-oficiais (não constituem aceite municipal): https://atendimento.tecnospeed.com.br/hc/pt-br/articles/1500006998382-Documenta%C3%A7%C3%A3o-T%C3%A9cnica-Padr%C3%A3o-GeisWeb20
- Barueri: https://portal.barueri.sp.gov.br/secretarias/secretaria-de-financas/nota-fiscal ; https://www.barueri.sp.gov.br/nfe/Manuais/RPS_Layout-v4.2.pdf ; https://www.barueri.sp.gov.br/nfe/Manuais/XML_RPS_Versao_01.pdf
- Osasco: https://nfe.osasco.sp.gov.br/EissnfeWebApp/portal/NfEletronica.aspx ; https://nfe.osasco.sp.gov.br/EissnfeWebApp/Portal/Manual/Geracao%20de%20NFS-e%20Via%20Web%20Service%202.1.pdf
- Jundiaí: https://jundiai.giss.com.br/giss-ajuda/desenvolvedores.html ; https://jundiai.giss.com.br/giss-ajuda/manuais/Manual%20T%C3%A9cnico%20-%20Servi%C3%A7os%20Prestados%20-%20V1.8.pdf

**Risco documental:** a comunicação pública de Barueri exibe literalmente `31/11/2026`, dia inexistente, no corte do PMB003. Não codificar essa data sem retificação oficial.

## Avanço posterior — roteamento canônico opt-in e evento Nacional (12/11/2026)

A auditoria inicial deste documento foi superada **apenas** nos pontos explicitados a seguir; os gates 1–7 continuam abertos.

- `canonical_fiscal_composition.py` agora aceita `sp4_municipal_gateways` e `sp4_municipal_query` como adaptadores `NfseGatewayClient`/`NfseQueryClient` **injetados**. O roteador valida o provider exato, município do prestador, escopo e pré-auditoria, e exige autorização separada de `QUERY` no Control Plane. Não há adaptadores canônicos efetivos instanciados para os quatro provedores, nem ativação automática destes canais. O operador não deve inferir que passar um transporte HTTP ao roteador equivale a completar o contrato `NfseAuthorizationRequest`.
- `nfse_nacional_event_homologation.py` acrescenta fronteira isolada de `POST /nfse/{chave}/eventos` para cancelamento `e101101` com aprovação humana, A1, assinatura do pedido, exigência de validadores XSD/XMLDSig (pedido e resposta), binding `cancel`, resposta correlacionada, proteção anti-retry e testes sintéticos. **Ainda não compõe o Portal nem a máquina de estados fiscal e não certifica cancelamento/substituição.** Eventos com análise fiscal e substituição precisam de contratos próprios.
- Regressões de catálogo corrigidas: Osasco usa indicação de WCF RTC próprio, Jundiaí de GissOnline. O inventário `SP22` permanece não-autorizativo e nenhum município recebe estado CERTIFIED.
- Testes novos de preaudit, roteamento, isolamento por cidade/tenant, competência e evento Nacional foram incluídos; a CI integral é válida apenas para seu HEAD final. **Nenhuma transmissão real foi realizada.**

**Pendência crítica de produto compartilhado:** a preparação direta no Portal está sendo trabalhada por outra frente (#447), e a numeração fiscal nacional durável não pode ser substituída pelo hash provisório. Para a homologação na contabilidade, não presumir que a tela final já está ligada aos gateways da branch.

**Conclusão de engenharia ainda proibida:** faltam schemas completos, builders fiscais canônicos, normalização inequívoca das notas por RPS, XML/PDF, cancelamento/substituição integrado e provas fiscais externas por município. A primeira ocorrência de `OK200`, `Erro=false` ou `Situacao=4` **não** é evidência de documento autorizado.


## Diretriz do proprietário — construção primeiro (12/11/2026)

**Interpretação operacional obrigatória:** NFCore ainda está em construção e não possui
clientes ativos para esta trilha municipal. Não transformar falta de certificado A1,
credenciamento, WSDL do contribuinte ou resposta real da prefeitura em interrupção
da engenharia interna: continuar implementando builders, drivers, validadores,
contratos, adapters, operações, recuperação, arquivos, testes e integração, com
fixtures sintéticas e parametrização por contribuinte.

**Separar duas coisas:** (1) *software construído e testado internamente* e
(2) *homologação externa/produção fiscal de contribuinte*. A ausência de (2)
não proíbe desenvolver (1) nem exige adicionar travas redundantes no produto.
Os controles fiscais essenciais e a precisão dos status permanecem para evitar
atribuir autorização oficial a uma resposta sintética; não reescrever componentes
existentes apenas para acrescentar bloqueios especulativos.

**Cronograma atualizado aplicável:** documento
`docs/NFCORE_FISCAL_ENGINE_EXECUTION_SCHEDULE_2026-11-12.md` na PR #453
e instruções do Agente A fornecidas pelo proprietário em 12/11/2026.
Ordem **Cajamar → Osasco → Barueri → Jundiaí**; depois os demais do SP-22,
sujeitos à ordem escolhida pelo proprietário; MG-W1 preservada em checkpoint,
DF/GO/MT/MS somente depois de SP-22 e do gate interno de MG-W1.
Não começar B17a antes da reconciliação #450/#427/#446: primeira entrega
de B17a será PR somente de especificação, revisada com o Agente B.
A frente municipal não assume nem reimplementa o núcleo fiscal do Agente B.
A integração externa depende de artefatos oficiais não substituíveis por
simulação e permanece em coluna de certificação separada.

**Fronteiras de código do Agente B a preservar:** não alterar
`gateway/nfse_nacional_homologation.py`,
`issuance/nfse_dps_builder.py`,
`runtime/canonical_fiscal_composition.py` e
`tests/runtime/test_nfv1_nfse_preparation_recovery.py`
sem reconciliação específica. Não mesclar, publicar, migrar banco, transmitir
documentos fiscais reais nem acionar credenciais do contribuinte sem autorização.


## Bloco Agente A — engenharia dos quatro drivers / build interno

A revisão da frente respeita o cronograma da PR #453 e o arquivo
`instrucoes-agente-A-cobertura-municipal.md`: foco primeiro em construir
um adaptador funcional com contratos próprios, provas de consulta e testes,
sem reinventar o motor tributário do Agente B e sem interromper tarefas de
programação por falta de A1 ou cadastro de contribuinte.

| Município | Construído nesta frente | Ainda necessário para gate interno de ponta a ponta |
|---|---|---|
| Cajamar (3509205) | Consulta GeisWeb por lote original, XML determinístico com CNPJ do transmissor e prestador, número reservado, assinatura e XSD por port, interpretador de retorno por RPS/competência/valor, ponte canônica | Builder emissor integral e campos tributários/tomador, pacote de XSD do provedor aplicável a 2026, assinatura real por contrato pinado, arquivamento/DANFSe, cancelamento/substituição e E2E Portal |
| Osasco (3534401) | Envelope oficial WCF `ConsultarNotaCompleta` por `NumeroReciboUnico`, autenticação externa por IM, RTC `EmitirNFE` e consulta em fronteira, teste para não confundir ACK com nota, roteamento canônico | Builder completo de `RTC_EmitirNFE` com IBSCBS/código de serviço e tomador, interpretador da NotaFiscalRelatorioDTO 2.1 e validação de XML, cancelamento/substituição, E2E Web |
| Barueri (3505708) | RPS PMB004 v4.2: montagem do lote, CRC do total/retido, linha RTC/ADN, cabeçalho/rodapé, transporte SOAP assíncrono, status/download, recuperação sem protocolo por lista do envio original, parser do arquivo de retorno municipal v3, GET XML original por URL oficial e ponte canônica | Builder fiscal dos **campos internos** de RPS e RTC v4.2 (depende da política tributária canônica), verificação oficial de schema e notas XML/XMLDSig, cancelamento/substituição, PDF, E2E |
| Jundiaí (3525904) | GissOnline 2.04, envelope SOAP/mTLS, consulta pelo RPS original com `Prestador`, `IdentificacaoRps`, série e IM, assinatura/XSD por port, reconciliação `CompNfse`, batch com protocolo e consulta, ponte canônica | Builder completo de `EnviarLoteRpsEnvio` e campos RTC com XSD vigente, assinatura e XSD hash do RAR atual, cancelamento/substituição, XML/DANFSe, E2E Web |

**Fontes verificadas, não confundidas com homologação de contribuinte:**

- GeisWeb 10.2, 13/11/2020, seção 13.3 (ConsultaLoteRps com
  `CnpjCpf`, `Consulta/CnpjCpfPrestador`, `Consulta/NumeroLote`):
  https://atendimento.tecnospeed.com.br/hc/pt-br/article_attachments/1500009353402/Manual_GeisWeb20.pdf
  A documentação Tecnospeed atualizada em 23/12/2025 confirma características
  do padrão Cajamar, mas **não fixa por si o WSDL/CNPJ vigente**.
- Osasco, prefeitura, manual 2.1 de abril/2026, páginas 32–38, consulta
  completa, cancelamento, campo `NumeroReciboUnico`, chave WCF própria:
  https://nfe.osasco.sp.gov.br/EissnfeWebApp/Portal/Manual/Geracao%20de%20NFS-e%20Via%20Web%20Service%202.1.pdf
- Barueri, prefeitura, `RPS_Layout-v4.2.pdf`, janeiro/2026 e guia
  v1.07 de janeiro/2026 para remessa PMB004; retorno
  `NFE_Layout-v3.pdf`, agosto/2025; WebService XML_RPS versão
  disponibilizada em junho/2021 com `NFeLoteListarArquivos` e envio por data:
  https://www.barueri.sp.gov.br/nfe/Manuais/XML_RPS_Versao_01.pdf
- Jundiaí, portal GissOnline, `Manual Técnico - Serviços Prestados - V1.8`,
  seção 7.1.5 com `ConsultarNfseRpsEnvio`, `IdentificacaoRps` e
  `Prestador`, e pacote XSD vigente listado em
  https://jundiai.giss.com.br/giss-ajuda/desenvolvedores.html

**Integração compartilhada:** código `Sp4MunicipalCanonicalGateway`,
`Sp4ReviewedMunicipalPorts`, `sp4_municipal_provider_bridges.py` e
`sp4_municipal_request_factories.py` ligam os componentes na fronteira
canônica, mas a composição final do Portal, a disponibilidade de dados
tributários completos e os builders de emissão pertencem a contratos
de outras frentes. O catálogo SP22 não ativa provedores sozinho.

**Status real:** `IMPLEMENTED_NOT_CERTIFIED` para o conjunto; homologação
municipal `EXTERNAL_BLOCKED` por contribuinte sem certificado/IM/credencial
e, em alguns casos, por ausência de contrato e fixture final pinada.
A inexistência desses insumos **não impede** a continuação da programação.
O CI deve ser validado no commit final, nunca herdado de sha anterior.


## Implementação adicional SP4 — serializers de emissão canônica (12/11/2026)

Novos componentes desta etapa, todos **na branch da PR #446**, isolados
do núcleo fiscal do Agente B:

| Município | Emissão construída | Ponte de uso e testes | Limites ainda não resolvidos |
|---|---|---|---|
| Cajamar | `gateway/cajamar_geisweb_issue_builder.py`: `EnviaLoteRps` com emitente, lote, número do RPS original, ISS, tomador e assinatura/XSD por injeção. | `build_cajamar_geisweb_issue_request_factory` + `test_cajamar_geisweb_issue_builder.py`. | Contrato GeisWeb vigente e assinatura/XSD pinados, outros cenários de serviço, tratamento integral dos retornos e publicação em runtime Portal. |
| Osasco | `gateway/osasco_rtc_issue_builder.py`: WCF `RTC_EmitirNFE`, registro original e tributação revisada; campo de credencial vazio até o transporte scoped. | `build_osasco_rtc_issue_request_factory` + `test_osasco_rtc_issue_builder.py`. | Paridade WSDL/DTO em outras modalidades fiscais, normalização do XML de NFS-e, PDF/Portal e cenários com outras rotas. |
| Barueri | `gateway/barueri_pmb004_record_builder.py`: RPS tipo 2, RTC/ADN tipo 4, codificação por posição e lote RPS tipo 1/9 já existente. | `build_barueri_pmb004_issue_remittance_factory` + `test_barueri_pmb004_record_builder.py`. | Tipos 3/5 e situações específicas de dedução/intermediário, schema oficial e reconciliação completa da remessa. |
| Jundiaí | `gateway/jundiai_giss_issue_builder.py`: `EnviarLoteRpsEnvio` ABRASF 2.04, original RPS/IM/tomador, `CodigoNbs` 9 dígitos, grupo `IBSCBS` quando tributação e base foram revisadas e informadas, assinatura/XSD por ports. | `build_jundiai_giss_issue_request_factory` + `test_jundiai_giss_issue_builder.py`. | Conferir XML final com RAR XSD vigente do GissOnline v1.8; assinar precisamente `InfDeclaracaoPrestacaoServico` e `LoteRps`; casos legais de substituição e integração de Portal. |

**Princípio da revisão:** gerar leiaute a partir do documento de domínio
imutável; não criar novo motor tributário, não remapear número de RPS,
não calcular IBS/CBS/ISS artificialmente nem usar sucesso HTTP como autorização.

**Critério de fechamento interno não alcançado:** factories ainda precisam
ser compostos com todos os campos e portas oficiais na árvore canônica final,
inclusive provas de respostas, PDF e simulação HTTP/Portal de todos os ciclos
(emissão, consulta, cancelamento, substituição quando legal).
Os arquivos XSD/WSDL de município ainda não foram todos pinados e verificados,
mas sua falta **não interrompe** o avanço em funcionalidades internas independentes.
A homologação real com A1/IM/credencial permanece em trilha externa.

**Controle de qualidade:** o aceite desta adição exige Ruff, Mypy,
Pytest e governança integralmente verdes no HEAD final da PR #446.
Não reutilizar a CI verde de um commit anterior como prova do novo código.
Não houve merge, deploy, migration, envio fiscal real ou alteração do Agente B.


### Complemento Barueri PMB004 — retenções e campos condicionais (12/11/2026)

- `barueri_pmb004_record_builder.py` agora gera registros **2, 3, 4 e 5**
  a partir de `Sp4OriginalRps` e `BarueriPmb004IssueFields` revisados.
- Registro **3**: retenções federais com códigos 01 (IRRF), 02 (PIS),
  03 (COFINS), 04 (CSLL), 05 (Previdência), repetíveis uma vez por código,
  com valores positivos, somatório dos valores efetivamente retidos no campo
  tipo 2 posições 484-498 e registro 9 posições 24-38.
- O assembler aceita opcionalmente **VN**, com a ressalva de que é
  `valor não incluso na base`, **não retenção**: participa do somatório
  do rodapé, mas não do campo de retenções do registro 2. Uma entrada VN
  tipada originada do motor fiscal/valor canônico ainda depende do contrato
  do Agente B; não criar montante econômico novo neste adaptador.
- Registro **5**: geração posicional de 697 bytes para os campos de
  crédito presumido, governo, referência de NFS-e anterior, locação de
  bens, doação e destinatário brasileiro diferente do tomador, inclusive
  regras condicionais ativadas pelo registro 4.
- Casos específicos de destinatário **estrangeiro**, classificação legal
  externa de crédito presumido e correlações completas NBS/LC116/indOp
  ainda exigem fontes e regras oficiais pinadas. Não marcar a cobertura
  fiscal universal como concluída por haver serializer para o leiaute.
- Testes dos lotes agora cobrem múltiplos registros tipo 3, duplicidades,
  números inválidos, divergência tipo 2 × tipo 3 × tipo 9, `VN` e
  condições de registro tipo 5 (Brasil).
- A CI integral `#43285291355` foi **SUCCESS** para o commit
  `d5b8e7203ad64f3895e2ff30cce6f295fb84cfa0`, **antes** destas
  novas alterações. Esta etapa de retenções e tipo 5 exige nova
  certificação do HEAD atualizado, sem reaproveitar o resultado anterior.


## Auditoria e correções SP4 — revisão de 12/11/2026

**CURRENT do código:** branch `fix/nfcore-sp22-legal-readiness-20261112`,
PR #446 OPEN/DRAFT. A CI anterior de `08ceb39` estava verde antes
destas alterações; nenhuma evidência do commit antigo certifica este conjunto.
**Sem merge, deploy, segredos, certificado de contribuinte ou emissão real.**

Correções municipais aplicadas nesta revisão:

- **Cajamar:** o `EnviaLoteRps` assinado precisa preservar também o
  endereço e identidade do tomador, ISS, regime, código de serviço,
  discriminação, base, alíquota e as retenções PIS/COFINS/CSLL/IRRF/INSS;
  testes de adulteração antes do port de assinatura e XSD. Corte de
  contribuintes Simples Nacional para o Emissor Nacional em **01/09/2026**,
  corrigido a partir do anúncio oficial da Prefeitura, publicado em 15/07/2026:
  https://cajamar.sp.gov.br/noticias/2026/07/15/empresas-do-simples-nacional-deverao-emitir-nfs-e-exclusivamente-pelo-emissor-nacional-a-partir-de-setembro/
  ; testes dos limites 31/08 e 01/09.
- **Osasco:** DTO `RTC_EmitirNFE` exige `ClassTrib` com 6 dígitos,
  `CodigoNBS` com 12 caracteres pontuados, `IndOperacao` com 6
  dígitos e `IdLocalIncidencia` de um dígito; cobertura de endereço
  condicional de prestação e `CodObra` com ordem alfabética WCF;
  cancelamento exige competência da NFS-e igual à do RPS original;
  testes negativos para campos malformados e incompletos.
- **Barueri:** arquivo PMB004 Tipo 2 não pode declarar retenção sem
  detalhamento Tipo 3; teto máximo da retenção igual ao valor da nota;
  `VN` é valor **não incluído na base**, não retenção federal e
  só pode ser montado quando for idêntico à dedução canônica já calculada.
  `3VN` reconcilia com o Tipo 9 sem inflar o campo de retenção Tipo 2.
  Foram acrescidos testes de valor zero, retenção excessiva e soma
  combinada de VN mais retenções federais.
- **Jundiaí:** árvore fiscal do `EnviarLoteRpsEnvio` é comparada
  integralmente antes/depois da assinatura, ignorando apenas elementos
  XMLDSig; qualquer modificação tributária ou de identificação falha
  antes de chamar o validador. `CodigoNbs` é opcional quando não há
  dados RTC; quando o grupo RTC estiver presente, exige NBS correlacionado.
  Testes cobrem ambos os caminhos.

**Limite de conclusão:** esses reparos são implementação e testes
propostos, não declaração de prontidão comercial nem homologação. Os
provedores municipais precisam de contratos oficiais WSDL/XSD pinados
e fixtures verificáveis de emissão, consulta, cancelamento e substituição;
o motor de apuração e o fluxo HTTP/Portal devem ser reconciliados com o
Agente B e com a PR de integração #450 sem editar suas autoridades.
Concluir internamente todos os cenários técnicos é obrigação distinta de
obter A1, IM, chave municipal e prova fiscal com contribuinte externo.
**Não inferir cobertura 100% de quatro municípios a partir de CI verde.**

**Gates desta revisão:** somente considerar aprovados se
`FM NFCORE V1 CI`, `NFCore Plan Governance` e
`PR Block Completeness` terminarem `SUCCESS` no HEAD exato após
este checkpoint. Não usar SHAs pré-revisão como evidência.
