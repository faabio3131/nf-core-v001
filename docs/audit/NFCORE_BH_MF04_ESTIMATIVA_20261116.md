# MF-04/BH — regime de estimativa e tabela de regimes especiais

**Escopo:** Belo Horizonte/MG, IBGE 3106200, NFS-e Nacional em competência
compatível; implementação fiscal **interna sintética**, sem homologação oficial.

## Fontes primárias e datas

- PBH BHISS, aviso de 29/10/2025 atualizado em 14/08/2026:
  https://prefeitura.pbh.gov.br/fazenda/bhiss/avisos
  identifica regimes especiais municipais aceitos: 1 (ato cooperado),
  2 (estimativa), 4 (notário/registrador), 5 (profissional autônomo),
  6 (sociedade de profissionais), 9 (Proemp/outros). Código 0 indica nenhum.
  O código 3, embora existente na enumeração nacional, não foi listado
  entre os aceitos por BH nessa revisão.
- PBH BHISS, comunicado de 02/10/2026:
  https://prefeitura.pbh.gov.br/fazenda/bhiss
  enquadrados em estimativa documentam pela NFS-e Nacional as operações
  abrangidas a partir de 01/10/2026, com regEspTrib=2 e sem destaque
  do ISS; o recolhimento pela estimativa permanece no BHISS.
- Esquema nacional NT009 produção restrita, versionado nesta árvore:
  `src/kordena_fiscal/xml/official/NFSE_NACIONAL_1.01_NT009_20261020`.
  O campo tpRetISSQN é obrigatório no XSD; pAliq é opcional.

## Construção

1. A elegibilidade do canal nacional para regime NORMAL/BH foi incluída
   desde a competência 01/10/2026, sem alterar binding/autorização do
   Control Plane nem retroagir para competências anteriores.
2. Tratamento `tribISSQN=1` e `regEspTrib=2`, com decisão revisada/pinada
   por SHA-256, pode passar pela preparação canônica com ISS 0 e sem
   retenção. O builder existente não produz pAliq quando valor ISS é zero.
3. O domínio impede ISS destacado/retido no regime Estimativa (2) e nos atos
   cooperados (1) de Belo Horizonte; outros regimes mantêm tratamento
   próprio. A regra E0172 impede regime especial nas hipóteses não tributáveis.
   O instalador restringe BH à lista municipal publicada.
4. A cooperativa pode emitir sua segunda nota para o serviço próprio
   com `regEspTrib=0`, alíquota de 3% e benefício municipal `nBM`
   `31062000200004` em produção restrita. O valor diferente
   `31062000200002` é exclusivo de produção e é rejeitado no ambiente
   de homologação. `nBM` é campo opcional estruturado no XSD nacional,
   não dado controlado pelo navegador: ele vem de política fiscal
   versionada por contribuinte/competência/serviço e fica arquivado.
5. Testes sintéticos cobrem regime Estimativa (2), ato cooperado (1)
   sem ISS, nota própria (0) com benefício de 3%, XSD assinado,
   idempotência, arquivo imutável, código de benefício incorreto e
   confusão de ambiente. Estes testes não substituem o aceite fiscal.
4. Testes sintéticos HTTP→numeração→arquivo→DPS assinado/XSD e replay,
   bem como recusa de classificação/regime/competência incompatíveis.

## Limites de aceite

Não atribui Estimativa automaticamente a um contribuinte; exige política
fiscal revisada por escopo/perfil/competência. Não presume que todo serviço
ou regime seja elegível sem classificação, tabela municipal, código de
tributação, benefícios e retenções revisados. Não fornece contrato oficial
de emissão por contribuinte nem valida credencial real, LCR/OCSP, histórico
de autorização ou homologação externa. MG20/BH completo permanece dependente
da matriz positiva/negativa de outras hipóteses de tributação e da revisão
fiscal independente. Este bloco não altera Web de produção nem DDL.

## Referência adicional de cooperativas

A Prefeitura indica explicitamente `regEspTrib=1` sem imposto destacado para o ato cooperado auxiliar; uma segunda NFS-e sem regime especial corresponde ao serviço próprio. O benefício de 3% para a cooperativa corresponde ao identificador municipal `31062000200004` na produção restrita e `31062000200002` em produção.

Fonte primária: https://prefeitura.pbh.gov.br/fazenda/bhiss/avisos (bloco COOPERATIVAS). O documento não declara aprovado o enquadramento de nenhum CNPJ.
