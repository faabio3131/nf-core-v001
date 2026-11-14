# Jundiaí/SP — auditoria técnica independente do pacote GissOnline 2.04 (14/11/2026)

**Escopo:** evidência pública e correções na branch independente `audit/jundiai-giss-official-20261114`, derivada da PR #479 no commit `ab7a7f68746d620edd6ef76675d039dcef28ee3b`. A PR #479 do Agente A **não foi alterada**. PR #475 (Barueri) permanece dependência de integração.

## Evidência oficial coletada — sem suposições

Origem institucional: https://jundiai.giss.com.br/giss-ajuda/desenvolvedores.html

Os artefatos oficiais foram obtidos por HTTPS diretamente do portal do município, no runner do GitHub Actions, e suas identidades estão reproduzíveis em `contracts/official/jundiai/giss_v2_04/manifest.json`.

| Fonte | SHA-256 dos bytes originais |
|---|---|
| `Schemas_XSD-Servicos_Prestados.rar` | `c14a542de5fa2ce1a6a2b43da6e4eb0bebab12e6ebc850fe24dbdc8f6bb04356` |
| Manual Serviços Prestados V1.8 (PDF) | `cdf8095944bbe0308d7df11a9632da78cba85b1daa3973dfdd51a86f9b4b58fd` |
| Manual de Retorno V1.0 (PDF) | `8becda8d0a97a34fe938baef6709dd8bee7867c40cc4defc54b775d670fd0db1` |
| Manual ABRASF 2.04 (PDF) | `d6ac7c1237a9064042df63bb7af2b539676f8b3589bdfb3fea8378a1b2f10bb9` |

- **24 de 24 XSDs extraídos, pinados e compilados**, sem dependências internas ausentes; resultado e hashes em `schema-validation.json`. A compilação prova a sintaxe e as referências do pacote, não a semântica da emissão em produção.
- Os builders de **emissão de lote, emissão com RTC 2026, cancelamento e duas variantes de consulta por RPS** passaram contra as respectivas XSDs oficiais, 5/5 na execução de auditoria após duas correções.
- O endpoint público de WSDL de produção e o de homologação retornaram **HTTP 400 sem autenticação mTLS**. O manual técnico identifica certificado ICP-Brasil necessário. **Não foi capturado nem versionado o WSDL autenticado; não foram inferidos SOAPActions, binding ou operações.** A matriz de produção depende da captura autenticada por credenciais oficiais e da auditoria posterior, não de um arquivo ilustrativo.
- Este repositório não deve conter certificado A1, senha, chave privada ou credenciais de cliente.

## Quatro defeitos confirmados por contratos e jornada HTTP

**Falha 1 — namespace de ConsultaNfseRpsEnvio.** O serializer `jundiai_giss_rps_query_builder.py` emitia os elementos diretos `IdentificacaoRps` e `Prestador` no namespace de `tipos-v2_04.xsd` em lugar do namespace do elemento da operação. Auditoria XSD independente: emissão PASS, cancelamento PASS, consulta FAIL; corrigidos os dois elementos diretos e atualizado teste de regressão. A outra implementação, `jundiai_giss_request_builder.py`, já usava o namespace correto.

**Falha 2 — RTC `pRedutor` obrigatório.** O pacote oficial `tipos-v2_04.xsd` declara `pRedutor` obrigatório antes de `vBC` em `TCRTCInfoValoresIBSCBS`. O builder original omitia o elemento; a auditoria fiscal estendida evidenciou rejeição do XML de IBS/CBS. Correção: percentual explícito da política fiscal revisada `government_reduction_percent`, validação, serialização na ordem exigida; nunca presumir zero. Ajustados configuração e testes de valores inválidos.

**Falha 3 — bloqueio da preparação HTTP do RPS.** O serviço canônico `FiscalApplicationService.prepare_nfse_authorization` ainda mantinha allowlist fixa de três municípios (Cajamar, Barueri, Osasco), apesar de Jundiaí já constar no registro SP4. A chamada real do Portal resultava em `NATIVE_NFSE_INVALID_FISCAL_FACTS` (HTTP 400); a causa `SP4 municipal original RPS requires reviewed scope and series` foi capturada no traceback. Substituída a lista local pela autoridade única `SP4_MUNICIPAL_PROVIDERS.values()`, com prova de preparação, RPS persistido e replay HTTP.

**Falha 4 — reconciliação HTTP não repetível.** A recuperação fiscal T07 criava um único intent pela impressão digital de `operation + payload`. Depois de um primeiro resultado `pending`, outra consulta com chave HTTP diferente recebia `replay` do resultado pendente, sem chamar o gateway. Corrigida somente a operação de leitura `reconcileFiscalOperation` para identificar cada tentativa pela impressão digital e chave idempotente; operações mutantes preservam intent único por payload e não são reenviadas. Teste HTTP prova novo poll, autorização e replay da mesma chave sem nova consulta.

**Jornada HTTP/SQLite integrada:** SUCCESS em https://github.com/faabio3131/nf-core-v001/actions/runs/43643948125, com emissão sintetizada, RPS original durável, recuperação pendente → autorizada sem segundo POST, arquivo XML, scoped persistence, CSRF/HTTP e isolation. A resposta do provider e o XML autorizado são simulados, **não** homologação com Jundiaí.

Testes reprodutíveis:
- `python scripts/audit/jundiai_acquire_official_contracts.py` — coleta, integrity checks e registro do impedimento mTLS
- `python scripts/audit/jundiai_verify_official_schemas.py` — SHA-256 individual e compilação de 24 XSD
- `python scripts/audit/jundiai_test_xml_against_official.py` — valida os 5 casos reais de serialização com os contratos oficiais
- `pytest tests/gateway/test_jundiai_giss_issue_builder.py tests/gateway/test_jundiai_giss_rps_query_builder.py tests/gateway/test_jundiai_giss_cancellation_builder.py`

CI de auditoria: https://github.com/faabio3131/nf-core-v001/actions/workflows/jundiai-official-contracts.yml

## Achado na documentação oficial de substituição

O RAR publica `substituir-nfse-envio-v2_04.xsd` e `substituir-nfse-resposta-v2_04.xsd`, com operação XML `SubstituirNfseEnvio` e estrutura própria `SubstituicaoNfse/Pedido/Rps`. **Anomalia literal do publicador:** ambos XSDs usam o `targetNamespace` `http://www.giss.com.br/gerar-nfse-resposta-v2_04.xsd`, não um namespace que coincida com o nome do arquivo. Não alterar as fontes oficiais para “corrigir” essa anomalia sem manifestação do provider.

O manual ABRASF 2.04 descreve substituição atômica; o manual Giss técnico V1.8 não comprova a presença do método no WSDL do município. Portanto, o caminho `separate_original_cancel_then_replacement_issue` implementado na PR #479 **não está certificado como substituição municipal equivalente**. Necessária conferência de binding, operação e SOAPAction do WSDL autenticado; só então decidir por endpoint atômico ou fallback formalmente aceito pelo fornecedor.

## Limitações e próximas provas

- **HTTP + DB**: aprovada a jornada interna autenticada com SQLite, numeração durável, emissão simulada, recuperação, arquivo XML, replay e isolamento na CI #43643948125; permanece necessária a certificação de todos os gates no HEAD definitivo. O XML do provider no teste é sintético, **não** comprovante municipal emitido por Jundiaí.
- **WSDL mTLS**: obter contratos de homologação e produção por credencial oficial autorizada (sem vazar segredos) e fixar SHA, SOAPAction, namespaces, operações e versionamento; testar transporte com respostas oficiais representativas.
- **Cancelamento e substituição**: concluir a prova HTTP/UoW e o contrato municipal efetivo de substituição, com testes negativos, recuperação, concorrência e isolamento.
- **Governança**: Agente A deve reconciliar as correções da branch de auditoria à sua PR #479; Agente B realiza revisão independente após evidências completas; coordenador fará integração cumulativa somente depois de Barueri (#475). Nenhum merge na `main`, deploy ou emissão municipal real ocorreu nesta auditoria.

**Estado: construção interna ainda não certificada por inteiro; full backend regression em andamento.** Nenhum teste sintético ou CI genérico autoriza chamar a homologação externa de concluída.
