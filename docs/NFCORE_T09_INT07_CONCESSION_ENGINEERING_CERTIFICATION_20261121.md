# NFCore T09 — INT-07: guarda determinístico de concessão individual

**Escopo:** somente engenharia consultiva, sem documento real de contribuinte, sem parecer independente e sem ativação fiscal.

## Contrato determinístico

- Cada política revisada precisa declarar `individual_concession_required` como booleano explícito. Política antiga sem essa decisão é recusada na decodificação, sem presumir dispensa.
- A evidência de concessão individual pertence ao snapshot de fatos, e portanto ao digest atestado pelo HMAC interno com CNPJ, competência, tenant/unidade e versão da regra.
- Quando a regra exige concessão, `individual_concession` deve conter `status=active`, `issuer_cnpj` igual ao emissor canônico, `uf` idêntica, `competence` mensal exata, `document_reference` não vazia, `review_reference` vinculada e vigência que cubra **todo o mês**. Ausência, estado não confirmado, divergência, vencimento parcial, `revoked`, `expired`, `suspended` ou `denied` retornam `insufficient_basis`, nunca `potential`.
- Quando a norma comprovadamente dispensa concessão individual, o revisor assina `individual_concession_required=false` e os fatos trazem `status=not_required`, `document_reference`, `review_reference` e `competence`. Uma regra que exige concessão não pode utilizar a dispensa.
- O controle é uma **triagem determinística baseada em registros internos**, não consulta contínua ao órgão estadual. Não detecta revogação que não tenha sido registrada no dossiê; o fluxo real deve atualizar e reconciliar as informações antes da utilização fiscal.
- Os fixtures e documentos sintéticos dos testes não comprovam concessões reais. Mesmo `potential` continua `advisory_only`, `human_review_required`, `eligibility_certified=false` e `issuance_authorized=false`.

## Provas de regressão adicionadas

Cenários para exigência e dispensa formal; ausência; status pendente, revogado, expirado, suspenso e negado; CNPJ e UF divergentes; competência e referência de revisão incompatíveis; documento vazio; início tardio ou vencimento durante o mês; prazo ausente; regra legada; adulteração de um recibo HMAC e revogação com HMAC válido. Certificação cumulativa depende do workflow **FM NFCORE V1 CI no HEAD deste commit**.

## Separação dos gates

- **INT-07 (engenharia):** verificar a execução e aprovar testes/CI no HEAD.
- **EXT-02:** obtenção/validação real de TARE, adesão, resolução ou concessão vinculada a CNPJ é sempre externa; sem evidência não há fruição.
- **INT-03/04/05/06/08/09:** documentação normativa, cenários ancorados nos atos, revisão contraditória real e aceite humano não são concluídos por testes sintéticos.
