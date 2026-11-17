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
3. O domínio impede ISS destacado/retido apenas no regime Estimativa
   (código 2); outros regimes mantêm tratamento fiscal próprio. A restrição
   nacional E0172 impede regime especial em não incidência, imunidade ou
   exportação. O instalador restringe BH à lista publicada.
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
