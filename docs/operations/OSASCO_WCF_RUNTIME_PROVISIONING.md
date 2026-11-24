# Osasco — provisão revisada no entrypoint canônico (13/11/2026)

Escopo: PR #469, dependente da integração cumulativa #468. Esta especificação documenta a **construção interna**, não a homologação da prefeitura.

## Ligação do processo

O executável `kordena_fiscal.runtime.api:app` usa a mesma `FiscalApplicationService`, PostgreSQL, Portal, RPS e estados de autorização da NFS-e nacional e de Cajamar. Ao encontrar `NFCORE_OSASCO_WCF_CONFIG_PATH`, registra o provider `osasco-rtc-homologation` por `osasco_port_builder`, sem descobrir CNPJ/segredos e sem transmitir no startup. Um caminho configurado e inválido causa falha de composição; um caminho ausente mantém o comportamento anterior.

O manifesto é um **arquivo local fora do Git**, sem chave municipal:

```json
{
  "wsdl": {"file": "municipal.wsdl", "sha256": "<SHA-256 real do arquivo>"},
  "binding_name": "<nome literal do binding SOAP 1.1 inspecionado>",
  "schemas": {
    "issue_request": {"file": "issue.xsd", "sha256": "<SHA-256 real>"},
    "query_request": {"file": "query.xsd", "sha256": "<SHA-256 real>"},
    "cancel_request": {"file": "cancel.xsd", "sha256": "<SHA-256 real>"},
    "full_invoice_response": {"file": "full-response.xsd", "sha256": "<SHA-256 real>"},
    "cancel_response": {"file": "cancel-response.xsd", "sha256": "<SHA-256 real>"}
  },
  "issuers": [{
    "tenant_id": "<tenant cadastrado>", "unit_id": "<unidade cadastrada>",
    "issuer_cnpj": "<CNPJ apenas dígitos>",
    "municipal_registration": "<IM exata do perfil fiscal>",
    "policy": {
      "source_normative": "<proveniência jurídica revisada>",
      "rule_version": 1,
      "effective_from": "<AAAA-MM-DD>", "effective_through": null,
      "municipal_service_code": "<serviço municipal validado>",
      "national_taxation_code": "<código nacional validado>",
      "activity": "<atividade validada>", "class_trib": "<classificação RTC validada>",
      "nbs_code": "<NBS validado>", "incidence_location": "<local validado>",
      "operation_indicator": "<indicador validado>", "service_city": "Osasco",
      "service_city_ibge": "3534401", "service_state": "SP",
      "recipient_street_type": "<tipo revisado>",
      "iss_rate": "<decimal>", "pis": "<decimal>", "cofins": "<decimal>",
      "csll": "<decimal>", "income_tax": "<decimal>", "inss": "<decimal>",
      "other_taxes": "<decimal>", "test_only": true,
      "no_iss_incidence": false, "additional_info": ""
    }
  }]
}
```

Os valores entre `<...>` são campos de preenchimento pela auditoria fiscal, **não valores admitidos automaticamente**. A política vigente deve ser obtida de fonte normativa e contrato efetivo, não de defaults. As cinco XSDs devem validar os documentos reais do método correspondente; XSD genérico de fixture não serve para homologação. O parser de WSDL aceita somente binding SOAP 1.1 verificado e mapeia as três operações exatas `RTC_EmitirNFE`, `ConsultarNotaCompleta` e `Cancelar`. Os artefatos precisam existir no diretório do manifesto e ter SHA-256 exato.

## Segredo municipal e operação

`NFCORE_OSASCO_GSM_ALLOWED_RESOURCES` é uma lista separada por vírgulas com paths `projects/PROJECT/secrets/SECRET`, pertencentes ao `NFCORE_GSM_PROJECT_ID` aprovado. A identidade da API usa `NFCORE_GSM_API_SERVICE_ACCOUNT` e a credencial montada conforme `production_credentials`; ela não é a identidade A1. A chave de 36 caracteres só é recuperada no momento do POST SOAP, por referência `CREDENTIALS` do Control Plane e `SecretResolutionService`, com conferência tenant/unidade/ambiente/provider/CNPJ/IM. Provisão em staging requer injeção explícita de um `FiscalSecretVault` por composição controlada; nenhuma identidade de produção é reutilizada automaticamente em staging.

A jornada sintética deve validar Portal → preparação nativa → reserva RPS durável → emissão WCF → consulta XML completo → arquivo autorizado; cancelamento normal (N) e substituição (S) passam pela mesma API/Portal/UoW. **Importante:** o verificador de cancelamento construído no manifesto somente verifica a resposta contra XSD e devolve `None` (indeterminado); confirmação fiscal só é possível com verificador semântico oficial independente, ainda não integrado a esta configuração. Não tratar `CancelarResponse`/HTTP 200 como cancelamento confirmado.

## Gates pendentes antes de publicação

1. CI integral no **HEAD exato** da correção e posterior merge virtual acumulado com a #468; revisão de ownership A/B e concordância dos checkpoints.
2. Obter WSDL, XSDs e amostra municipal válidos em 2026, revisar SOAPAction, campos RTC e critérios semânticos de autorização/cancelamento por contribuinte; chave e vínculo fiscal reais permanecem externos.
3. Consultar **somente leitura** o PostgreSQL da Contabo para identificar a tabela de controle de migrations e confirmar aplicação/hashes 19, 20, 21, **22** e existência das tabelas `fm_nfse_dps_counters`, `fm_nfse_dps_reservations`. A v22 cria duas tabelas e é aditiva; **se ausente, não executar DDL nem migration sem autorização N3 específica**, backup/restore ensaiado e plano de rollback. Usar os guards read-only existentes. Não inserir credenciais ou SQL de alteração no GitHub.
4. Verificar divergências `main` × `production`, backup, smoke de runtime e rollout/rollback pelo deploy oficial. Nenhum sinal de CI sintética equivale à homologação fiscal externa.

**Estado nesta PR:** implementação de composição e testes sintéticos sob CI; sem merge, deploy, DDL, dados fiscais reais ou certificado de prefeitura.
