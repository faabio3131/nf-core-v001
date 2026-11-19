# Osasco RTC: ativação api:app e contrato municipal atualizado

**Fonte primária municipal atual — aplicação do motor e revisão do provedor:** Prefeitura de Osasco, [Geração de NFS-e via Web Service v2.2, OUT/2026](https://nfe.osasco.sp.gov.br/EissnfeWebApp/Portal/Manual/Geracao%20de%20NFS-e%20Via%20Web%20Service%202.2.pdf), publicada na página [Manuais do Sistema](https://nfe.osasco.sp.gov.br/EissnfeWebApp/Portal/Manuais.aspx). Substitui v2.1 abril/2026.

## Invariantes da ativação

A API canônica aceita a variável NFCORE_OSASCO_WCF_CONFIG_PATH com caminho absoluto para manifesto operador de homologação. Não existe API paralela ou outro banco; o mesmo FiscalApplicationService/UoW reserva o RPS original antes do POST. O binding do contribuinte permanece no Control Plane, separado por tenant/unidade/CNPJ/inscrição municipal/perfil fiscal, com resolução de referência de credencial pelo mesmo SecretResolutionService, FiscalSecretVault e GSM com identidade de workload. O manifesto não contém chaves fiscais, segredos ou senha.

A configuração revisada exige SHA-256 de WSDL original e cada XSD do conjunto revisado; verifica os métodos RTC_EmitirNFE, ConsultarNotaCompleta e Cancelar na binding SOAP 1.1; valida XML de solicitação, consulta e cancelamento e as respostas oficiais com o schema específico. Um HTML de landing page WCF NÃO substitui o arquivo XML WSDL.

O RTC municipal é somente para competência 2026 em diante e contribuinte com regime NORMAL (TaxRegimeCode=3) e perfil fiscal revisado. Simples Nacional segue o roteamento nacional pertinente.

## Fontes oficiais para baixar os artefatos

- WSDL homologação: https://homolog-nfe.osasco.sp.gov.br/EissnfeWebServices/NotaFiscalEletronica.svc?wsdl
- WSDL único homologação: https://homolog-nfe.osasco.sp.gov.br/EissnfeWebServices/NotaFiscalEletronica.svc?singleWsdl
- Produção, para referência SEM SUBMETER OPERAÇÃO: https://nfe.osasco.sp.gov.br/EissnfeWebServices/NotaFiscalEletronica.svc?wsdl

Na estação autorizada, obter BYTES originais (não XML convertido em texto sem atributos). Verificar estrutura, imports/includes, binding e SOAPActions; salvar cada arquivo XSD revisado e calcular SHA-256. Recomenda-se:

    curl --fail --location --proto '=https' --tlsv1.2 \
      'https://homolog-nfe.osasco.sp.gov.br/EissnfeWebServices/NotaFiscalEletronica.svc?singleWsdl' \
      --output osasco-homolog-2026.wsdl
    sha256sum osasco-homolog-2026.wsdl

As ferramentas de leitura públicas consultadas retornaram o texto XML sem os atributos de namespaces/operadores; esse texto não pode ser usado como prova byte-a-byte nem para gerar hash verdadeiro. Não inventar hash, XSD, SOAPAction ou retorno fiscal.

## Manifesto operador reconciliado com o entrypoint da PR #468/#469

O formato válido é o da implementação canônica em runtime/osasco_environment.py, também descrito no runbook OSASCO_WCF_RUNTIME_PROVISIONING.md. O objeto JSON aceita **exatamente** os grupos wsdl, binding_name, schemas e issuers:

- wsdl: objeto {file, sha256}, com WSDL local e hash real.
- binding_name: identificação literal do binding SOAP 1.1 no WSDL da prefeitura.
- schemas: cinco objetos {file, sha256} independentes, de nomes issue_request, query_request, cancel_request, full_invoice_response, cancel_response.
- issuers: lista de {tenant_id, unit_id, issuer_cnpj, municipal_registration, policy}, com uma combinação única de tenant/unidade/CNPJ e inscrição municipal confrontada com o perfil canônico.
- policy: fonte, versão de regra, data inicial/final, código de serviço municipal, código nacional de tributação, atividade, classificação tributária, NBS, indicador de operação, local de incidência, município, UF, tipo de logradouro do tomador, ISS e valores federais revisados. Cada valor monetário JSON deve ser string decimal.
- Na versão **2.2**, policy também aceita os campos **opcionais** pis_own e cofins_own (strings decimais, valores próprios distintos das retenções), e cartorio_values (null ou objeto com os oito campos vl_contrib_sta_casa, vl_emolumento, vl_fundo_tj, vl_intimacao, vl_min_publico, vl_repasse_estadual, vl_sefaz, vl_sinoreg, todos decimais). Ausentes, esses campos permanecem com zero ou null sem criar dedução.

Não usar no manifesto as chaves mode, wsdl_file, wsdl_sha256, xsd_resources, xsd_roots, profile_id, profile_version ou gsm: elas pertencem a um protótipo isolado da PR #466, **não** são aceitas pela candidata de integração #468. O GSM é configurado fora do manifesto por NFCORE_GSM_PROJECT_ID, NFCORE_GSM_PROJECT_NUMBER, NFCORE_GSM_API_SERVICE_ACCOUNT e NFCORE_OSASCO_GSM_ALLOWED_RESOURCES. Staging exige uma autoridade de segredo externa explicitamente injetada; a implementação não reutiliza credencial de produção em staging.

Esses dados são atribuição de operador com cadastro de CNPJ/IM válido e regras tributárias revisadas; nenhum valor fictício deve ser promovido ao servidor.

## Correções da v2.2 (outubro/2026)

O manual atual adicionou os campos ResponsavelTributario (P=prestador, T=tomador) e ValoresCartorios (somente perfis autorizados de cartórios). ResponsavelTributario é opcional, derivado de SubstituicaoTributaria quando ausente, e o adaptador pode enviá-lo com a mesma classificação fiscal canônica. Os montantes dos cartórios não podem ser inventados.

O manual manda valor Aliquota 0.00 no regime NORMAL, calculado pela Prefeitura; exceção para ST de serviço prestado fora de Osasco, quando a alíquota revisada da localidade externa deve ser informada. Separar ISS retido, PIS/COFINS retidos e PIS/COFINS próprios. Os códigos ClassTrib, NBS e IndOperacao são classificados por fonte verificada; não deduzir bases de IBS/CBS de valores brutos.

As notas RTC usam RPS durável original e emissão com tentativa idempotente, consulta read-only pelo recibo e XML completo. Cancelar N versus S exige aprovação humana, prova oficial e vínculo por nota. O teste sintético não é homologação externa.

## Critérios de fechamento

CI no HEAD final, incluindo Ruff, MyPy, Pytest, PostgreSQL, Portal HTTP com transporte SOAP simulado, operações de emissão/consulta/cancelamento/substituição e A1 sem perda de isolamento. A versão real de WSDL/XSD, a chave municipal autorizada e os recibos reais do fisco devem ser validados separadamente. Nenhuma implantação produtiva, DDL, mudança de segredo ou emissão fiscal real é parte desta execução.
