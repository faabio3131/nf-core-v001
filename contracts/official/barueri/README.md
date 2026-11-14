# Barueri/SP — XML_RPS_Schemas_V01 (contratos de requisição, 2026-11-14)

A cópia ZIP original do proprietário foi preservada byte a byte para verificações de
engenharia **offline**, sem tráfego com a Prefeitura.

- Arquivo: `XML_RPS_Schemas_V01.zip` (4.291 bytes, 4 XSD e 4 exemplos XML).
- SHA-256: `3fb4b61f013e1c0a0d156913230643a2f4accb7486343854c7295c1a1dee9aa4`.
- Fonte municipal declarada: https://www.barueri.sp.gov.br/nfe/Manuais/XML_RPS_Schemas_V01.zip
- WSDL fornecido pelo proprietário: `wsrps-homologacao(1).wsdl` (11.218 bytes),
  SHA-256 `37f7859c6b87d681b410d83c4b969f0f997d161cc548787e5b98dd3af9d58964`.
  Fonte informada: https://testeeiss.barueri.sp.gov.br/nfeservice/wsrps.asmx?wsdl
- Namespace: `http://www.barueri.sp.gov.br/nfe`.
- SOAP 1.1 mTLS: `https://testeeiss.barueri.sp.gov.br/nfeservice/wsrps.asmx`.
- SOAPAction: `http://www.barueri.sp.gov.br/nfe/{Method}`.
- Operações: `NFeLoteEnviarArquivo`, `NFeLoteStatusArquivo`,
  `NFeLoteListarArquivos`, `NFeLoteBaixarArquivo`.
- Testes: `tests/gateway/test_barueri_official_xml_contracts.py`
  intercepta bytes de `BarueriPmb004HomologationTransport._send`
  e desserializa `MensagemXML` do envelope real para validar contra os
  XSDs originais do ZIP, com casos positivos e negativos.

**Escopos distintos:** o ZIP define o XML interno SOAP (`VersaoSchema=1`);
o leiaute PMB004 é um TXT de largura fixa com regras fiscais e RTC próprias
(v4.4, 28/05/2026). Nenhum desses testes representa autorização municipal,
homologação externa ou aprovação comercial.

**Proveniência:** hash é prova de integridade do upload, não comprovação
independente do download municipal na data. Sem certificado ou segredo aqui.
