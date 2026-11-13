# NFCore SP-22 — Recuperação operacional e governança para contabilidade (12/11/2026)

**Ordem do proprietário:** interromper BH em seu checkpoint da [PR #440](https://github.com/faabio3131/nf-core-v001/pull/440#issuecomment-6815184034) e priorizar SP para a visita à contabilidade de **13/11/2026**. Este documento não altera automaticamente a fila dos demais agentes; demais branches e serviços não podem ser sobrescritos.

**Base auditada:** `main@ef7ebe7e104f0e49897075cd961d51a052948b43`. Issue de reconciliação: [#445](https://github.com/faabio3131/nf-core-v001/issues/445). PR R16 #355 anteriormente mesclada. Nenhuma evidência de 22 transportes reais/homologação. Qualquer informação histórica de "22 certificados" deve ser tratada como afirmação **não comprovada** até prova por município.

## Limites do catálogo vs. operação

O dicionário `SP_MUNICIPAL_CANDIDATES` contém 22 IBGEs e nomes de famílias provedoras **candidatas**, não contratos homologados. `GovernedSpMunicipalProviderResolver` só seleciona provedor quando existe binding canônico aprovado por tenant, unidade, ambiente, operação e município. `build_governed_sp_municipal_gateway` existe, mas **não foi encontrado seu uso na composição principal da API**. `nfse_paulistana_envelope.py` constrói `TesteEnvioLoteRPS` offline, que não equivale a emissão municipal real. Rota de três cidades do piloto (Cajamar, São Bernardo, São Paulo) **não** é a mesma lista dos 22, nem prova homologação.

| Município | IBGE | Evidência de implementação municipal na `main` | Aceite |
|---|---|---|---|
| Barueri | `3505708` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| São Paulo | `3550308` | Paulistana (teste sem emissão) + rota Nacional pendente | NÃO CERTIFICADO |
| Campinas | `3509502` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Sorocaba | `3552205` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Guarulhos | `3518800` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Santos | `3548500` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| São Caetano do Sul | `3548807` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Jundiaí | `3525904` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Suzano | `3552502` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Santana de Parnaíba | `3547304` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Osasco | `3534401` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Itapevi | `3522505` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Jandira | `3525003` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Mairiporã | `3528502` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Arujá | `3503901` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Louveira | `3527306` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Valinhos | `3556206` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Itu | `3523909` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Salto | `3545209` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Monte Mor | `3531803` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| Guarujá | `3518701` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |
| São Vicente | `3551009` | Somente catálogo de seleção; provedor ainda não certificado | NÃO CERTIFICADO |

## Correções prioritárias P0

1. **CGSN 191/2026:** NFS-e nacional obrigatória a ME/EPP Simples em competências desde **01/11/2026**; 01/09 foi revogado. Não usar data de requisição para decidir competências retroativas até 31/10. Prefeitura confirmou que legado poderá servir retroativos antes da competência de corte, sujeito a contrato real.
2. **Autônomos / profissionais liberais da capital:** transição municipal anunciada para **03/08/2026**, conforme categoria; **não** inferir regime ou usar a mesma regra ME/EPP para autônomos/MEI.
3. **SEFAZ-SP 55/65:** inutilização descontinuada desde **01/11/2026**; impedir inclusive chamada direta de adaptador antes de tocar Vault A1. NFC-e SP65 não possui ciclo estadual comprovado de QR Code, contingência, cancelamento e recuperação.
4. **Emissão e artefatos:** demonstrar sessão real → empresa/unidade/perfil fiscal (CNPJ/IE/IM) → preparação/autorização → consulta → XML protocolado + DANFE/PDF, com tenant/RBAC, logs, replays e falhas; proibir documento sintético como prova oficial.
5. **Cada um dos 22:** norma municipal e regime/competência, contrato de envelope real, XSD/hash, XMLDSig, endpoint mTLS ou autenticação municipal, competência ISS, número RPS/DPS, autorização/consulta/cancelamento/substituição, evidência de resposta oficial, CI/E2E e homologação externa quando permitida.

## Critério de aceite da reunião de 13/11/2026

**Podem ser apresentados como demonstráveis somente fluxos que tenham testes e provas exatas da versão instalada**, por exemplo cadastro, navegação, permissões e preparação sintética, se validados. **Não afirmar que a plataforma já pode emitir notas reais em qualquer um dos 22** sem certificado do emitente, credenciamento, contrato aplicável e resposta fiscal oficial. Para emissão comercial real imediata, a contabilidade deverá continuar usando o emissor oficial/provedor já habilitado do contribuinte até a homologação do NFCore.

**Inventário mínimo para um piloto legítimo:** município IBGE do estabelecimento prestador, regime tributário vigente por competência (MEI/ME/EPP/normal), CNPJ, IE/IM conforme documento, CNAE/serviços, credenciamento SEFAZ/município, A1 autorizado da empresa, CSC/QR aplicável à NFC-e, ambiente e autorização expressa para eventual homologação. Nunca enviar PFX/senhas em chat, GitHub ou artefatos públicos.

## Evidência e fontes

- Matriz executável e explícita de não certificação: `docs/coverage/NFCORE_SP22_OPERATION_READINESS_2026-11-12.json`; testes: `tests/control_plane/test_sp22_operation_readiness_matrix.py`.
- Corrigir SP capital: `src/kordena_fiscal/gateway/municipal_sp_routing.py`; testes da competência retroativa.
- Guard direto inutilização: `src/kordena_fiscal/gateway/nfe_sp_operations_homologation.py`; regressão sem acesso a Vault/HTTP.
- Prefeitura SP: https://prefeitura.sp.gov.br/web/fazenda/w/usoemissornacional
- Receita Federal: https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/agosto/simples-nacional-nfs-e-nacional-sera-obrigatoria-para-me-e-epp-a-partir-de-1o-de-novembro-de-2026
- Portal NFS-e, competência: https://www.gov.br/nfse/pt-br/noticias/nfs-e-informa-diretrizes-sobre-a-obrigatoriedade-da-emissao-da-nfs-e-nacional-para-optantes-do-simples-nacional/
- SEFAZ SP: https://portal.fazenda.sp.gov.br/servicos/nfe/Paginas/Sobre.aspx
- Auditoria histórica: `docs/NFV1_SP_ABSOLUTO_ENGINEERING_AUDIT_2026-11-05.md`.

**Estado após checkpoint:** `SP22_INTERNAL_INCOMPLETE`. Qualquer mudança exige PR/commit SHA, suite integral, testes de provedor e provas individualizadas. Nenhum merge/deploy/transmissão fiscal real automático.
