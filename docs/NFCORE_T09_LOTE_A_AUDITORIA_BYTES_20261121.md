# T09 — Auditoria do Lote A recebido em 21/11/2026

**Fonte**: ZIP de documentos públicos enviado pelo usuário, `T09_Fontes_Lote_A.zip`.
**SHA-256 do ZIP**: `298d178d8bc5140badb81fad9b6c628c519723f673b970c9a2e287b8f092fcc7`.
**Classificação**: revisão técnica de integridade e identificação de atos,
**não** validação externa da origem, parecer profissional, prova de vigência consolidada
ou aprovação de benefício para cálculo tributário.

| UF | Nome do arquivo no ZIP | SHA256 real | Documento encontrado | Resultado |
|---|---|---|---|---|
| AC | AC_Lei_1358_2000.html | `306781dc3329c1c9d5955fa5636f3accc31654ece050a1b3dc4737bba653923a` | Lei 1.358/2000 | Ato identificado; revisão temporal ainda pendente |
| AC | AC_Decreto_4196_2001.html | `d4c3c4d54d104131f5cb43b51be7d1f5ce8fd1d0f26a0ce0e5ed26f007b12aa1` | **Decreto 8.701/2018**, que lista atos, incluindo 4.196/2001 | **REJEITADO COMO DECRETO 4.196/2001** |
| AC | AC_Decreto_11618_2025.html | `b9f9534525a8e60e61ac1c01752a0137c13f000b1351ba3d2d25827c3667dee7` | Decreto 11.618/2025 | Ato identificado; altera Decreto 4.196 |
| AC | AC_Lei_3460_2018.html | `d98520d93b21b25ff92400a1e8e28849d829ffc4887935eed93bf701f58f12f0` | Lei 3.460/2018 | Ato identificado; tema LC 160/reinstituição |
| PA | PA_Lei_6913_2006.pdf | `2d549170207872f2b76dabbd513b0837c435e4f00ab4a242e8fde9d4abe7c1f1` | Lei 6.913/2006, PDF de 5 páginas | Ato identificado **com divergência de data** |
| PA | PA_Lei_7485_2010.html | `94202d426bd3973876fbb5a73b97d257f9c79e0fa617a4970449b5c26d0306e2` | Lei 7.485/2010 | Ato identificado, altera Lei 6.913 |
| PA | PA_Decreto_990_2020.html | `013742c3c37debcea213322b36228d7deeb19052bfcef2980d5735c8dab6d0f6` | Decreto 990/2020 | Ato identificado, altera Decretos 2.489–2.492 |
| PI | PI_DOE_57_2025_Decreto_23672_2025.pdf | `4fa8c246f47267f84ca957a0054bf8418590d9490eaca911f2bc3dbbbbdaa5ad` | DOE-PI nº 57/2025; Decreto 23.672/2025 (PDF páginas 47–49) | Ato identificado; inclusão art. 25-A desde 01/04/2025 |

## Três achados que exigem conciliação

1. **AC falso positivo de arquivo**: URL `https://www.legis.ac.gov.br/detalhar/4520` retorna o
   Decreto 8.701/2018 (listagem de normas), não o Decreto 4.196/2001.
   Fonte primária alternativa localizada na SEFAZ/AC:
   `https://sefaz.ac.gov.br/2021/?p=14786`. Requer **novo download e novo SHA256**;
   não reutilizar hash do arquivo errado.
2. **PA inconsistência editorial**: primeira página do PDF da ALEPA traz
   `Lei 6.913, de 03 de agosto de 2006`; página 5 traz assinatura no
   `Palácio do Governo, 3 de outubro de 2006` e publicação no DOE
   `nº 30.779, de 04/10/2006`. A norma regulamentadora também cita
   3 de outubro. Arquivo original preservado **sem reescrita**;
   conciliar a data com o exemplar original do DOE antes de aceitar a cadeia.
3. **PI vigência temporal**: o DOE original confirma o Decreto 23.672,
   de 25/03/2025, incluindo o art. 25-A ao Anexo IV do Decreto
   21.866/2023, com efeitos declarados em **01/04/2025** e referência
   ao Convênio ICMS 224/2017. Isso não comprova alterações vigentes
   em toda a competência 2026. Falta versão consolidada do Anexo IV.

## Limites e gates (não alterar)

- Receber arquivo e computar hash prova **somente integridade dos bytes do anexo**.
  O ZIP não contém sessão HTTP assinada ou atestado de autenticidade de origem.
- Documentos legislativos podem conter redações antigas, alterações e
  condicionamentos de órgão concedente/contribuinte; a curadoria
  `27/27` não está concluída com este pacote.
- Falta o arquivo primário correto do **AC Decreto 4.196/2001** e
  consolidação **PI RICMS Decreto 21.866/2023, Anexo IV art. 25-A**;
  demais exigências por competência, CONFAZ/LC 160 e pareceres
  continuam em aberto.
- **Não houve** `internal_curatorial_accepted=true`,
  `review_status=reviewed`, assinatura independente, importação
  de incentivos, emissão, merge ou deploy.
- `source_sha256` do catálogo executável permanece **null**,
  `import_authorized=false`.
