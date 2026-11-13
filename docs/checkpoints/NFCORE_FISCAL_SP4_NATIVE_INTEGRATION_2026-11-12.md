# NFCore — Integração candidata #446 + #449 (12/11/2026)

**Estado:** integração de engenharia não mergeada nem implantada, sem homologação fiscal. **Base SP4:** #446 HEAD cdd097953761fd122abe1bc9c4469030749f399e. **Emissor nativo:** #449 HEAD d6f8f1c37377e5dcb4077410ee035cb5b7ede0a4 (CI de origem verde). **PR #427 numeração durável** permanece Draft/conflictiva.

## Reconciliação sem duplicação
- Gateway Nacional de #446 preservado integralmente: bloqueio por regime/competência SP e propagação de XML oficial associado à chave.
- Builder DPS de #446 conserva derive_national_dps_id para recuperação Nacional GET, com grupo toma do NfseServiceTaker da #449.
- Teste de recuperação preserva SP4 (#446) e adiciona testes de tomador, fingerprint e archive (#449).
- Demais 18 arquivos exclusivos da #449 incorporados sem editar as branches originais.
- Consulta Nacional usa GET sem reenvio POST; binding QUERY distinto. A #427 só será integrada após numeração/transação/migration aprovadas.

## Gates pendentes
- CI completa e governança sobre HEAD integrado, testes HTTP, XMLDSig, archive, DANFSe, PostgreSQL, frontend e E2E.
- P0: serial DPS durável (#427); tributação/competência; schema oficial atual; UI integrada; cenários tributários.
- SP4 #446 permanece candidata: canais municipais e homologação externa NÃO certificados.
- Nenhuma emissão com A1 real, merge/deploy/DDL/produção autorizada neste checkpoint.
