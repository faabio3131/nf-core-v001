# PR440 — sucessores canônicos e pendências preservadas

Auditoria de 16/11/2026. Origem: `2e30447d66e184be6e3fbdb2baf04db75be4b451`.
Comparação: candidata nacional `af1f7b58794beba42a92718dea40a44fb1ef90fa`
e árvore cumulativa de Guarulhos `d7fd30ee411ac12f691a957a9a204b9c1f46d737`.
Revisão independente não encontrou justificativa para reintroduzir os módulos
antigos ou uma segunda autoridade DPS. Encerrar a origem como substituída não
conclui Belo Horizonte nem certifica emissão real.

| Origem #440 | Sucessor na mesma aplicação |
|---|---|
| `national_service_nbs` | `nbs_code`, classificação arquivada e fingerprint |
| Regime especial vindo do navegador | `NfseNationalTaxTreatment`, política revisada no servidor |
| `prepareBhNfse` | `prepareNativeNfse`, testes BH HTTP e formulário existente |
| `national_dps_schema` / `sqlite_national_dps` | `nfse_dps_numbering_schema` / `sqlite_dps`, migração 22 e reserva transacional |
| Schema selecionado pela cidade | Seleção por perfil, ambiente e vigência |
| Eventos nacionais offline | Cancelamento 101101 com transporte/reconciliação; substituição por DPS vinculada |

## Diferenças intencionais

A origem compartilhava o contador legal do CNPJ entre tenants/unidades.
O CURRENT mantém contador legal único e recusa tomada por outro escopo,
conforme `test_dps_legal_cnpj_sequence_cannot_be_taken_over_by_another_scope`.
Não declarar equivalência literal nem recuperar a implementação antiga.

O evento 105102 offline da origem não prova um fluxo operacional perdido.
A substituição atual emite DPS vinculada e verifica a correlação das notas.
Não acrescentar um POST independente somente para reproduzir arquivos históricos.
Recibos atuais exigem correlação e validação mais fortes; XML sintético incompleto
de testes antigos não constitui critério de aceite da autoridade atual.

## Fonte histórica recuperada

`docs/history/20261116/pr440/NFCORE_BH_NATIONAL_INTERNAL_CHECKPOINT_2026-11-11.md`
é cópia byte a byte da origem. `source-manifest.json` registra commit, blob, tamanho
e SHA256. É evidência histórica, não CURRENT, não homologação. A branch é preservada.

## Pendências continuam abertas

A [issue #426](https://github.com/faabio3131/nf-core-v001/issues/426) continua sendo
o gate integral MG/BH. Permanecem: tabelas e decisões tributárias municipais,
incidência, retenções, deduções, benefícios, regimes/competências, matriz positiva
e negativa, E2E operacional por emitente, EGM e homologação externa real.
A política genérica sem catálogo revisado não fecha BH; o caminho tributável
sem política não exige universalmente classificações BH.

CI verde de um incremento não fecha essas pendências. Nenhuma emissão real,
deploy ou migração produtiva foi realizado por esta reconciliação.
