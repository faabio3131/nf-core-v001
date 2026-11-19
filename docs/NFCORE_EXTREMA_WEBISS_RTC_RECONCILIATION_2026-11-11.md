# NAT-MG-W1 / Extrema (3125101) — reconciliação de contrato WebISS 2026

**Data:** 2026-11-11. **Estado:** `INTERNAL_INCOMPLETE / NOT_CERTIFIED / EXTERNAL_HOMOLOGATION_PENDING`.
**Regra aprovada:** não classificar Extrema como 100% concluída nem promover outro município antes de todos os gates internos. Código, PR, manual encontrado e CI verde isolada não são entrega integral.

## Evidência verificável e grau de autoridade

1. **Fonte municipal:** [WebISS Extrema](https://extremamg.webiss.com.br/) comunica que o ambiente próprio foi adaptado à RTC, que publicou XSD, exemplos e manuais atualizados em *Manuais → Nota Fiscal de Serviços Eletrônica* e que ainda podem ocorrer ajustes no ambiente restrito. A publicação do aviso **não fornece por si só o pacote fiscal completo nem autoriza transações**.
2. **Evidência independente específica da cidade:** [Senior eDocs 5.8.16](https://documentacao.senior.com.br/documentoseletronicos/notasdaversao/5-8-16/) registra WebISS **2.02 + IBSCBS** de Extrema e a rejeição **E160** por geração incorreta da ordem dos elementos do grupo `dest`; a identificação deve ser o primeiro elemento.
3. **Evidência operacional independente:** [Focus NFe — Extrema](https://focusnfe.com.br/guides/nfse/municipios-integrados/extrema-mg/) classifica o provedor como WebISS, exige certificado digital, informa homologação disponível, cancelamento ativo e separação do emissor nacional por regime. Os links são portais de acesso, **não são prova do endereço SOAP `/ws/nfse.asmx`**.
4. **Material técnico do mesmo fornecedor, mas de outro município:** pacote público [Web Services — Formiga/MG](https://drive.google.com/drive/folders/17fjTuXT_eNSFOjsRluq0EFDa8jadU-4c) divulgado no [fórum ACBr](https://www.projetoacbr.com.br/forum/topic/87596-colabora%C3%A7%C3%A3o-mapeamento-da-migra%C3%A7%C3%A3o-das-cidades-nfs-e-nacional-e-reforma-tribut%C3%A1ria/page/3/). Contém `nfse_v2_02-IBSCBS.xsd`, `xmldsig-core-schema20020212.xsd`, manual V5.0, guia e XMLs de exemplo. **Fonte de pesquisa e contraste, NÃO XSD certificado de Extrema.** Nenhum SHA deste pacote foi promovido ao registro de XSD municipal aprovado.

## Auditoria independente dos arquivos obtidos

| Arquivo público | SHA-256 | Resultado |
|---|---|---|
| `nfse_v2_02-IBSCBS.xsd` (Formiga) | `4caeadd9b4993b7741d7a83aa80601ac5743524d5af7bdd14f862fed053c7003` | Compilou localmente com lxml, sem consulta de schema por rede |
| `xmldsig-core-schema20020212.xsd` (Formiga) | `95e4cdab281a964f966f04493b95924864caa412c47664a4760c5dce50f885c6` | Importador do XSD acima; não é pin de Extrema |

Contratos estruturalmente confirmados nessa referência do provedor:

- `tcInfDeclaracaoPrestacaoServico` tem `IBSCBS` opcional na sequência posterior ao incentivo fiscal, além do serviço e prestador; `tcDadosServico` inclui `CodigoNbs`.
- `TCRTCInfoIBSCBS` ordena `finNFSe`, `indFinal?`, `cIndOp`, `tpOper?`, `gRefNFSe?`, `tpEnteGov?`, `indDest`, `dest?`, `imovel?`, `valores`.
- `TCRTCInfoDest` requer primeiro uma identificação exclusiva `CNPJ/CPF/NIF/cNaoNIF`, depois `xNome`; `end`, `fone` e `email` são posteriores e opcionais. Isso é compatível com a divergência E160 identificada para Extrema.
- Regra documentada de coerência: `indDest=0` não pode criar destinatário distinto; `indDest=1` exige `dest`.
- O manual informa métodos de envio síncrono/assíncrono, consulta, cancelamento e substituição. Os exemplos disponibilizados incluem **campos vazios**, assinaturas antigas ou material ilustrativo que não passa integralmente no XSD; **não** são fixtures oficiais prontas para homologação.

## CURRENT → TARGET e execução

| Dimensão | CURRENT observado | Target / gate obrigatório |
|---|---|---|
| Família de XML | Código do NFCore inicialmente usava ABRASF 2.03 normalizado; PR #423 já aceita versão 2.02 mediante validador injetado | XSD **exato** de Extrema 2026 revisado, registrado com hash e golden tests completos |
| RTC/E160 | PR #423 adiciona pré-validação `dest` e coerência `indDest` sem reordenar XML assinado | Teste negativo E160 e positivo contra XSD municipal realmente obtido |
| Identidade e segurança | Vínculo exato, CNPJ, A1, XMLDSig e ausência de downgrade parcialmente implementados | Confirmar controles com envio real controlado, isolamento tenant/unidade e resposta do município |
| Endpoint | URL de portal/rota presumida não equivale a WSDL fiscal assinado | Endereço, método, versão e SOAPAction **provados** e vinculados por ambiente; default sem rede |
| Contrato fiscal canônico | `NfseCanonicalDocument` contém `service_taker_reference`, mas não contém os dados estruturados completos de tomador/destinatário e tributos RTC necessários ao RPS municipal | Estender apenas o domínio canônico, armazenamento e application conforme necessidade, sem criar segunda autoridade |
| Ciclo comercial | `exchange_prepared` permanece primitiva do transporte; não há E2E real de Extrema em API/Web | Emissão, consulta, cancelamento, substituição quando autorizada, evento, PG, Web, autorização e recuperação idempotente |
| Tests / CI | Gates em execução/falha por revisão; testes sintéticos não provam prefeitura | Ruff, Mypy, Pytest, PostgreSQL, frontend, build, containers, E2E e CI integral verde no mesmo HEAD |
| Externo | Certificado/credenciamento e resposta oficial não recebidos | `BLOCKED_EXTERNAL` até homologação autorizada com contador |

**Decisão:** não copiar o XSD de Formiga para `PINNED_WEBISS_MG_2026_SCHEMA_DIGESTS["3125101"]` sem comprovar equivalência com o documento **publicado pelo próprio portal de Extrema**. `ABRASF 2.03`, testes com monkeypatch e arquivos públicos de outro município não substituem a autoridade do pacote fiscal municipal.

**Proibição:** não fazer merge/deploy, criar credenciais reais ou transmitir uma NFS-e sem gate e autorização específicos.


## Confirmação direta do próprio webservice municipal (nova evidência)

O [NfseWSService de Extrema](https://extremamg.webiss.com.br/ws/nfse.asmx?op=SubstituirNfse) expõe páginas de descrição pública do SOAP 1.1, com **Host `extremamg.webiss.com.br` e POST `/ws/nfse.asmx`**, cabeçalho `Content-Type: text/xml; charset=utf-8`, `SOAPAction` com prefixo `http://nfse.abrasf.org.br/`, request `{Método}Request`, response `{Método}Response`, e dois filhos string `nfseCabecMsg` e `nfseDadosMsg` no pedido; resultado `outputXML`.

Operações confirmadas no **serviço PUBLICADO do próprio município**, não apenas em fornecedor terceiro:

| Função SOAP | Evidência municipal | Situação de contrato |
|---|---|---|
| `RecepcionarLoteRps` | https://extremamg.webiss.com.br/ws/nfse.asmx?op=RecepcionarLoteRps | Método / SOAPAction / wrapper público confirmados |
| `ConsultarNfseServicoPrestado` | https://extremamg.webiss.com.br/ws/nfse.asmx?op=ConsultarNfseServicoPrestado | Método e consulta específica de notas confirmados |
| `CancelarNfse` | https://extremamg.webiss.com.br/ws/nfse.asmx?op=CancelarNfse | Método e envelope confirmados; efeitos fiscais dependem de resposta |
| `SubstituirNfse` | https://extremamg.webiss.com.br/ws/nfse.asmx?op=SubstituirNfse | Método confirmado; não equivale ao cancelamento comum |

**Segregação CRÍTICA:** `https://extremamg.webiss.com.br/ws/nfse.asmx` é o endpoint publicado no host operacional municipal. Sua existência NÃO confirma ambiente *homologação*. A URL `https://homologacao.webiss.com.br/ws/nfse.asmx` não foi confirmada pelo município; por isso o transporte de homologação permanece sem destino padrão e bloqueia envio. Não realizar POST para o endpoint público para testar acesso. Sem documentos de homologação/credenciamento e autorização expressa, conservar `EXTREMA_INTERNAL_COMPLETE = false`.

**Divergência funcional reconciliada no adaptador (sem certificar fluxo final):** o NFCore tinha apenas `ConsultarLoteRps`; a PR #423 recebeu também `ConsultarNfseServicoPrestado`, com `Pagina` obrigatório conforme XSD de referência WebISS 2.02, SOAPAction próprio, operação de leitura e vínculo fiscal `QUERY`. Restam integração do retorno de consulta na aplicação, certificado/ambiente, schema exclusivo de Extrema e jornadas API/Web; não confundir método de transporte implementado com recuperação fiscal end-to-end certificada.
