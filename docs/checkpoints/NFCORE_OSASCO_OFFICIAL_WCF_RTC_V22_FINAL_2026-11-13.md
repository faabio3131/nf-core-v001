# NFCore — Osasco RTC: aceite técnico interno e contrato público v2.2

Checkpoint de 13/11/2026, consolidado após as PRs #469 e #472 na candidata #468.

## Evidência oficial, sem credenciais de contribuinte

- Fonte primária: manual Prefeitura de Osasco, Emissão de NFS-e Web Service v2.2 (OUT/2026): https://nfe.osasco.sp.gov.br/EissnfeWebApp/Portal/Manual/Geracao%20de%20NFS-e%20Via%20Web%20Service%202.2.pdf
- Contrato oficial público: https://homolog-nfe.osasco.sp.gov.br/EissnfeWebServices/NotaFiscalEletronica.svc?singleWsdl
- Download byte a byte autorizado somente por GET, executado no GitHub Actions https://github.com/faabio3131/nf-core-v001/actions/runs/43549195714 — SUCCESS.
- WSDL preservado em contracts/official/osasco/homologation/NotaFiscalEletronica.singleWsdl.xml: 161631 bytes, SHA-256 0e6798bbe317e690d0795cdfac876225961686d8a77cccbbf92c9aab6b50b22c.
- Seis XSD municipais completos preservados no mesmo diretório, com hashes individuais e namespaces em audited-contract.json; nenhum WSDL, XSD ou resposta foi inventado.
- Binding exato BasicHttpBinding_INotaFiscalEletronicaServico. SOAPActions oficiais: http://tempuri.org/INotaFiscalEletronicaServico/RTC_EmitirNFE, http://tempuri.org/INotaFiscalEletronicaServico/ConsultarNotaCompleta e http://tempuri.org/INotaFiscalEletronicaServico/Cancelar.

## Entregas internas implementadas

1. Contrato fiscal RTC do manual v2.2 integrado pela PR #472 (merge 01764013 na PR #468): alíquota ISS, ResponsavelTributario P/T, PIS/COFINS próprios versus retidos, ValoresCartorios somente com classificação revisada, ClassTrib/NBS/indicador. Simples Nacional continua no roteamento nacional.
2. Fábrica api:app, habilitação governada NFCORE_OSASCO_WCF_CONFIG_PATH, mesmo FiscalApplicationService, Portal, persistência, idempotência, escopo tenant/unidade/CNPJ/IM e SecretResolutionService/Control Plane/A1 sem segundo motor fiscal.
3. Seis XSDs oficiais compilados com imports vinculados em memória e sem rede por runtime/osasco_official_schema.py. A revisão do manifesto seleciona official_xsd_package por seis SHA-256; a compatibilidade do manifesto legado de cinco schemas permanece isolada.
4. DataRecibo de emissão corrigido para xs:dateTime, validado diretamente contra o XSD oficial. Emissão, consulta e cancelamento usam métodos e namespaces verificados.
5. CancelarResponse oficial somente promove estado se resposta única com Erro=false e sem erro, após correspondência do documento original; resposta incerta conserva o estado e não reenvia POST inadvertidamente.
6. Teste completo pelo HTTP do Portal usando a mesma fábrica executável da API, duas reservas RPS duráveis, emissão, recuperação de XML, cancelamento tipo S, replay idempotente e substituta emitida/consultada, transporte SOAP sintético mas WSDL/XSD reais.

## Matriz de certificação

- Testes fiscais RTC v2.2 PR #472 / CI https://github.com/faabio3131/nf-core-v001/actions/runs/43547389335: SUCCESS.
- CI cumulativa A1 + Cajamar + RTC v2.2 após merge #472 / https://github.com/faabio3131/nf-core-v001/actions/runs/43548918425: SUCCESS.
- Download íntegro de contrato oficial / https://github.com/faabio3131/nf-core-v001/actions/runs/43549195714: SUCCESS.
- Gate dirigido XSD municipal real / https://github.com/faabio3131/nf-core-v001/actions/runs/43549946912: SUCCESS.
- Gate dirigido XSD municipal + Portal/api:app e jornada total / https://github.com/faabio3131/nf-core-v001/actions/runs/43550202665: SUCCESS.
- O fechamento somente se certifica após CI dirigida e CI integral SUCCESS no SHA da presente branch e, depois de merge na #468, CI integral SUCCESS no SHA cumulativo final.

## Limites e reconciliação de governança

O WSDL e os XSD reais são metadados públicos oficiais e foram verificados; as notas e chaves usadas nos testes são sintéticas. A engenharia interna não depende de certificado ou conta de cliente. Homologação fiscal municipal verdadeira (emissão, consulta, cancelamento e substituição perante a prefeitura com credenciais de contribuinte) fica registrada como EXTERNAL_HOMOLOGATION_PENDING e não pode ser inferida dos testes. Não houve POST municipal real, deploy em production, migração DPS v22 em Contabo nem merge na main.

As branches proprietárias dos Agentes A/B permanecem preservadas. Revisão de ownership e release governada continuam pré-requisitos independentes à publicação produtiva.
