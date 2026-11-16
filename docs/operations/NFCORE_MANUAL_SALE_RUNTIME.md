# Venda manual — configuração do runtime e autoridade fiscal

## Escopo implementado

Portal Emissões → Preparar NF-e/NFC-e → operação fiscal Emitir → consulta/arquivo
existentes. NF-e 55 SP/MG e NFC-e 65 MG online, em homologação. Preparação não
transmite nem simula autorização. Demais UFs, contingência e produção não são
declaradas disponíveis por este incremento.

O formulário utiliza a sessão, unidade e permissões existentes. Só transmite
fatos comerciais; não aceita tenant, XML, número, provedor ou alíquotas do browser.
O servidor resolve emitente, produtos, vínculo de autorização e regras revisadas.

## Política revisada e montagem

A política usa os mesmos contratos de regra e destinatário do Bling. Não copia
tributos de ERP nem seleciona percentuais por IA. Cadastro de emitente/produtos
e vínculos de provedor permanecem no Control Plane. Um artefato por unidade,
ambiente e modelo seleciona suas versões; taxas/CFOP/CST devem ser revisados
para os cenários que a empresa realmente atende.

Campos JSON obrigatórios: `schema_version:1`, `policy_id`, `version`,
`host_namespace:"fm-nfcore"`, `tenant_id`, `unit_id`, `environment:"homologation"`,
`document_kind:"nfe"|"nfce"`, `issuer_profile_id`, `issuer_profile_version`,
`products:{"product_id":{"version":1}}`, `series`, `sale_options` e `rules`.
`sale_options` segue `NfeSaleOptions`; `rules` segue `parse_sale_rule` em
`runtime/sale_facts.py`. A fixture `tests/test_native_sale.py` demonstra o
contrato com dados sintéticos, **não é uma política tributária para clientes**.
Uma versão já utilizada não pode mudar de conteúdo: incremente `version`.

Instalar somente um arquivo já revisado, usando o próprio validador do runtime:

```bash
python -m kordena_fiscal.runtime.native_sale_policy politica-revisada.json \
  --directory /opt/fm/nfcore/sale-policies
```

O comando valida esquema/escopo/regras e gera o nome derivado do escopo + pin
SHA-256. Não altera banco, certificado ou autorização do contribuinte. Diretório
e arquivos devem ser legíveis pelo UID não-root da API; não colocar segredos nele.

Definir `NFCORE_SALE_POLICIES_HOST_DIR=/opt/fm/nfcore/sale-policies` e combinar
`deploy/contabo/compose.sale.api.yml` com os arquivos Compose já ativos. A API
recebe montagem read-only em `/run/nfcore/sale-policies` e a variável
`NFCORE_SALE_FISCAL_POLICY_ROOT`. **Não substituir o override Bling**: combinar os
dois no arquivo/rotina efetivamente usado pelo deploy e auto-pull. O diretório
deve existir; Compose não cria um caminho vazio por engano. Validar `docker
compose ... config` antes de recriar a API. Montagem/configuração real no host
ainda precisa de evidência de implantação.

## Numeração legal e transição

O mesmo `fm_fiscal_sequences` passa a concentrar NF-e/NFC-e por
CNPJ + ambiente + modelo + série. `nfcore-legal-sequence` é namespace interno
da **linha de contador**, nunca escopo de documento, usuário ou autorização.
O tenant proprietário é conservado; o CNPJ ocupa a coluna unit_id dessa linha
interna. Não há tabela, migration, contador paralelo ou novo login.

No primeiro uso, o store incorpora o maior contador dos escopos históricos
do CNPJ e do escopo canônico atual. Políticas divergentes, outro tenant ou
troca histórica ambígua de CNPJ exigem reconciliação explícita. Os contadores
anteriores permanecem preservados. Chamadas configuradas antigas resolvem o
mesmo CNPJ; os pipelines que possuem documento canônico fornecem o emitente.
Contadores órfãos do mesmo tenant/série/ambiente em outro escopo impedem adoção
até o vínculo ser comprovado por perfil histórico e documentos arquivados.
Antes do rollout, inventariar também os órfãos de todos os tenants: sem prova
de emitente, não é possível certificar ausência de colisão histórica entre eles.
Não criar perfil fictício nem inferir CNPJ para liberar o gate.
Reservas duráveis55/65 sem perfil unívoco ou emitente canônico são recusadas;
somente a leitura de contador legado permanece disponível para reconciliação.

PostgreSQL serializa pelo lock transacional da identidade legal, independente
de canal/tenant; SQLite serializa a transação de escrita. **Na publicação,
parar os writers da versão antiga antes de iniciar os novos**. A chave física
antiga não impõe sozinha unicidade legal contra um processo legado: não fazer
rolling update misturando writers antigos/novos. Reversão exige interromper
emissões e reconciliar o high-water; não reiniciar versão antiga sobre aliases
desatualizados. Validar a origem dos números históricos antes da ativação real.
RPS municipal e DPS nacional não mudam neste ajuste.

## Recuperação e verificação

Mesma referência/fatos recupera o documento sem carregar política atual ou A1,
mesmo após rotação, sem reservar outro número. Alteração conflitante retorna409.
Falha determinística400/403/422 permite correção do formulário; timeout/5xx
mantém a tentativa original até recuperação. Preparação/arquivo e comandos
idempotentes pertencem à mesma transação. Erro antes do commit reverte todos.

Aceite operacional: carregar política da unidade → preparar venda → ver documento
READY_TO_TRANSMIT → transmitir pelo provedor configurado → consultar resultado
e baixar XML/PDF apenas se autorizado. Falta de A1/configuração, retorno fiscal
rejeitado e indisponibilidade externa devem aparecer como estados reais.
Testes sintéticos não equivalem a homologação SEFAZ.
