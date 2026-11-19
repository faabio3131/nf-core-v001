# Decisões tributárias nacionais no preparo existente

O formulário NFS-e existente usa a mesma preparação, numeração, arquivo e assinatura. O browser informa fatos/revisão, mas não escolhe códigos de tratamento. Somente o canal nacional consulta `NFCORE_NFSE_FISCAL_POLICY_ROOT`; Simpliss e SP4 conservam contratos próprios.

## Instalação

O operador fiscal deve fornecer um JSON revisado; o repositório não instala valores tributários fictícios. Executar no ambiente da imagem:

```bash
python -m kordena_fiscal.runtime.native_nfse_policy /caminho/revisado.json --directory /caminho/absoluto/nfse-policies
```

Combinar `deploy/contabo/compose.nfse-policy.api.yml` com os overrides reais já usados pelo host, definindo `NFCORE_NFSE_POLICIES_HOST_DIR`. Não substituir montagens de A1, Bling, banco ou políticas de vendas. Instalação requer arquivo e pin por escopo; depois que uma versão foi usada, alterações requerem nova versão. Alteração concorrente do par é recusada, nunca aceita parcialmente.

## Contrato do artefato

Raiz exata: `schema_version=1`, `policy_id` (até63 caracteres), `version` (inteiro positivo), `host_namespace`, `tenant_id`, `unit_id`, `environment`, `document_kind="nfse"`, `rules` (1 a500).

Cada regra contém `rule_id` (único, até63 caracteres), `selector` e `treatment`. Seletor exige correspondência exata, sem wildcard: `issuer_profile_id`, `issuer_profile_version`, `issuer_cnpj`, `issuer_tax_regime`, `issuer_municipality_ibge`, `service_state_code`, `service_municipality_ibge`, `national_taxation_code`, `municipal_service_code`, `taker_country`, `iss_withheld`, `nbs_code`, `municipal_taxation_detail`, `source_normative`, `rule_version`. NBS/cTribMun podem ser null somente quando a classificação revisada assim determinar; nenhum valor do formulário é substituído silenciosamente.

Tratamento exige todos os campos canônicos: `iss_taxation_code`, `special_regime_code`, `normative_reference`, `rule_version`, `effective_from`, `effective_to`, `simples_assessment_code`, `result_country_code`, `immunity_type_code`. Datas ISO; limite final exclusivo; campos condicionais não aplicáveis devem ser null. Os códigos devem ser os aprovados pelo responsável fiscal e aceitos pelo domínio/XSD. País do tomador não determina exportação nem país de resultado do serviço. ISS tributável continua exigindo valor positivo neste incremento; operações não tributáveis exigem ISS zero e sem retenção.

O JSON é limitado a1MiB, tem chaves únicas e pin SHA-256. A aplicação preserva bytes integrais no arquivo fiscal e congela policy_id/version na autoridade durável de configuração existente. O documento contém identificação da regra e digest no tratamento, ambos cobertos pelo fingerprint. Replay conserva snapshot de perfil e decisão, sem depender do arquivo vigente; alteração de fatos continua conflitante.

Ausência da variável mantém somente o comportamento tributável anterior. Variável vazia, diretório/arquivo inexistentes, pin inválido, escopo divergente, regra ausente/ambígua ou validade incompatível causam recusa antes da reserva e do A1. Não configurar este override em uma unidade sem as decisões revisadas exigidas.

## Limites de certificação

Este mecanismo não é catálogo nacional/municipal completo, parecer de incidência, cadastro automático de cTribMun/NBS nem homologação externa. Não certifica BH integral por instalar um arquivo. Permanecem necessários revisão normativa/tabelas por cenário, cadeia/revogação de recibos e operação fiscal externa. Nenhum dado real ou segredo está incluído nas fixtures de teste.

A variável é habilitada por instância de API: todos os escopos nacionais atendidos por ela precisarão de seu arquivo revisado. Uma unidade sem arquivo será recusada. Inventariar os escopos antes de habilitar o override; não tratar a ausência de arquivo de uma unidade como fallback permitido.

## Alíquota ISS revisada (MF-04)

Para operação nacional tributável em que o domínio exige destaque, a decisão revisada precisa incluir `treatment.iss_rate` como string decimal com duas casas. O valor deve provir de revisão fiscal efetiva para o cenário; não há alíquota padrão. A preparação confronta o ISS informado com a base tributável e a alíquota aprovada, arredondando em centavos, e recusa inconsistências. O DPS utiliza a alíquota original aprovada, não uma aproximação obtida dividindo um valor monetário arredondado. A decisão integra o fingerprint e o arquivo durável; snapshots antigos sem esse campo continuam legíveis. A transmissão real nacional recusa política sem alíquota exata quando o destaque é exigido, e o Portal indica revisão pendente. MEI, regimes sem destaque e hipóteses não tributáveis mantêm as invariantes já existentes. A informação de alíquota não substitui comprovação legal de deduções, benefícios, regimes, competência ou homologação.

## Mensagem complementar fiscal revisada (MF-04)
O tratamento nacional aceita `complementary_information` opcional (1–2000 caracteres não vazios), pertencente à decisão revisada do servidor, não a um checkbox ou texto livre de autorização no navegador. A mesma DPS canônica inclui `serv/infoCompl/xInfComp`, e o arquivo e fingerprint preservam a informação. Não altera por si a retenção, o regime ou o benefício: o responsável fiscal deve revisar o conteúdo, a elegibilidade e a competência. Para Belo Horizonte, a orientação SMFA/DFAT de 29/10/2025 atualizada em 14/08/2026 (https://prefeitura.pbh.gov.br/fazenda/bhiss/avisos) indica o uso de xInfComp em mensagens relativas à retenção e a alíquota de 3% no benefício cooperativo identificado por nBM. A camada de transmissão recusa benefício BH com taxa divergente; não inventa alíquota ou comprova enquadramento. A dedução por documentos ainda requer contrato de evidência, referências e controles de uso próprios dentro da autoridade existente.
