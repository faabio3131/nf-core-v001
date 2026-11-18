# SP: correlação de respostas fiscais — 16/11/2026

Base de implementação: `bfd5d0d4d53525b50603e1a14275d2689bab7383` (#514). Integrar sequencialmente na candidata #468; nenhuma mudança de endpoint, política tributária, numeração ou autoridade.

## Achado e decisão

A revisão independente da cadeia #446/#450/#461 reproduziu sucesso indevido: pedido SP modelo 55/série 1/faixa 50–51 recebia `ACCEPTED` diante de resposta `cStat=102` de UF31/outro CNPJ/modelo65/série9/faixa999. O código conferia esses identificadores apenas quando `_state == "31"`. O mesmo condicionamento aparecia em consulta e cancelamento SP.

Aplicar os controles de correlação a todas as UFs suportadas, usando a UF do gateway e a solicitação canônica. Campos diretos únicos: UF/chave na consulta; órgão/chave/tipo/sequência no cancelamento; UF/ano/CNPJ/modelo/série/faixa na inutilização. Nunca inferir sucesso por código/protocolo desacompanhado de identidade correspondente. A disponibilidade da inutilização SP durante transição continua intacta.

Rejeições oficiais podem omitir campos condicionais: exigir conjunto completo para sucesso 102 ou 135/155, permitir opcionais ausentes em rejeição, recusar opcionais presentes divergentes/duplicados. UF/órgão e ambiente continuam obrigatórios. Fonte: schemas versionados `xml/official/MG_LIFECYCLE_20261105/nfe/leiauteInutNFe_v4.00.xsd`, `leiauteConsSitNFe_v4.00.xsd` e `event/leiauteEvento_v1.00.xsd`; documentação primária https://moc.sped.fazenda.pr.gov.br/NFe_NFCe/NFe_NFCe/RecepcaoEventoGeral.html e MOC 7.0 seção 5.3.2 https://www.nfe.fazenda.gov.br/portal/exibirArquivo.aspx?AspxAutoDetectCookieSupport=1&conteudo=LrBx7WT9PuA%3D .

## Revisão e provas

Revisor independente `review_legacy_equivalence`, contexto isolado, sem edições. Identificou o defeito e revisou a correção. Uma versão intermediária exigia opcionais também nas rejeições; corrigida antes de publicar. Revisor validou rejeição mínima de inutilização pelo XSD e confirmou `REJECTED/215`, sem protocolo de sucesso. Relatou 106 testes PASS no conjunto focal SP/MG; integrador executou 136 testes PASS incluindo política SP. Ruff e Mypy 417 fontes aprovados. Suíte integral em execução no checkpoint; CI remota necessária no commit publicado.

Hashes SHA-256 do delta revisado:

- `src/kordena_fiscal/gateway/nfe_sp_operations_homologation.py`: `d7961a5aedec73034af9cc459bf9c6bb53e0fdf7b4bb514429d05febf200cd40`.
- `tests/gateway/test_sp_operation_response_correlation.py`: `96b121f4c28b6679c588e2eaaf00e9c4ebb4a7ab4f0e58377fa12a07582adc68`.

Aceite: respostas corretas permanecem aceitas; cada campo faltante, divergente, duplicado ou aninhado em sucesso é recusado; rejeição mínima permanece rejeição; dados conflitantes na rejeição são recusados. A1 sintético e transporte simulado, sem chamadas oficiais.

Limites: correlação não certifica schema integral de todos os retornos, confiança do signatário, unicidade do envelope completo nem homologação externa. Não é execução do protocolo EGM original. GET NFS-e/XSD/ICP e demais pendências do release permanecem abertas.
