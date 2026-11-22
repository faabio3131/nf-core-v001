# MG — Reconhecimento COHAB/MG por nota fiscal — evidência oficial T09

A Resolução Conjunta SEF/Habitação nº 01, de 16/03/1998, publicada em 18/03/1998, está disponível no [portal oficial](https://www.fazenda.mg.gov.br/empresas/legislacao_tributaria/resolucoes/1998/rr0001_1998.html). O arquivo recebido `MG_ResolucaoConjunta_01_1998.html` possui **40.844 bytes** e SHA-256 real `125b051af5214d535ffa97b81ec2cab01c44620f73748be6f66876587c7d7edc`, conforme bytes locais conferidos em 22/11/2026. Arquivo constava do quinto lote recebido; não foi convertido em original do DOE por esta anotação.

O texto dos arts. 1º–5º exige, para as cinco classes de materiais especificados, obra residencial de baixa renda coordenada pela COHAB/MG, **reconhecimento prévio pela COHAB/MG**, observância do limite quantitativo do projeto aprovado ou reavaliação fundamentada e emissão do documento **“Reconhecimento de Benefício” para cada NF**. O art. 4º exige número/data do documento e valor do imposto dispensado nas informações complementares; o art. 5º disciplina entrega da via da NF em cinco dias úteis pelo destinatário. Em fraude, art. 6º estabelece cobrança integral com acréscimos.

A Resolução originalmente remete ao item 40 do Anexo IV do regulamento histórico; o atual item 26 do Anexo II do RICMS/2023 aponta para a mesma Resolução. **Não presumir que a simples referência atual certifique ausência de revogações/alterações procedimentais após 1998.** Reconciliação temporal e original do DOE continuam pendentes.

### Engenharia

Foram adicionadas quatro chaves de revisão necessárias aos cenários controlados da candidata MG no motor canônico: `mg_cohab_recognition_per_invoice`, `mg_project_quantity_limit`, `mg_invoice_recognition_number_date` e `mg_invoice_tax_dispensation_amount`. O teste remove cada evidência e exige `insufficient_basis`. Isso NÃO verifica concessão real nem aplica benefício, e preserva `advisory_only`, 0 importações e 0 certificados. Para um contribuinte real, o documento de reconhecimento por NF é dependência externa de uso, não impeditivo de testar a construção interna.

Fonte material correlata: https://www.fazenda.mg.gov.br/empresas/legislacao_tributaria/ricms_2023_seco/anexoii2023_3.html; item 26.1 exige desconto e anotação, prazo estadual textual até 31/12/2026. Conferir alterações e CONFAZ 136/97. A validade jurídica integral da candidata continua **NÃO CERTIFICADA**.
