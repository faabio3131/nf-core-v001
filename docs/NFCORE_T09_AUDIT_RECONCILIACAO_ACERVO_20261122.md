# T09 — Auditoria consolidada de bytes e fontes (22/11/2026)

**STATUS:** rastreabilidade técnica de capturas, não curadoria jurídica aprovada. PR #592 — Draft.

## Resultado reproduzido sobre arquivos reais

Confrontados, por tamanho, SHA-256 e CRC, quatro acervos de evidências, sem tratar cópias repetidas como novos atos:

| Acervo | Registros com SHA-256 real | Situação |
|---|---:|---|
| Recebimento final dos cinco lotes | 50/50 | ZIP privado SHA-256 `584a0cd1458619b7033d39e95a7ee4cbe31558cba90cf0ee1cdab00e1f4cd547` |
| ZIP histórico de 12 originais candidatos | 12/12 | Dentro do ZIP de recebimento; não somar como documentos novos |
| Pesquisa normativa parcial, fontes | 29/29 | Dentro do ZIP de recebimento; não somar como atos novos |
| [Capture Public Evidence #45058617349](https://github.com/faabio3131/nf-core-v001/actions/runs/45058617349) | 21/21 capturas | 6 UFs falharam; ZIP externo SHA-256 `09b402253570e8ac301425b0bcbb28b2905a7a3db0f8b8126d8ae3f709337b5d` |
| [Official Alternative Trial #45064678960](https://github.com/faabio3131/nf-core-v001/actions/runs/45064678960) | 10/10 capturas | 8 tentativas falharam; ZIP SHA-256 `6fa3bcea57282312bb167033a20496d5659d772286317d33ec3c0cf205884145` |

**Consolidação:** 122 registros verificados criptograficamente, 108 conteúdos binários distintos por SHA-256; ao menos um documento capturado por 27/27 UFs, mas isso **não** significa 27 normas originais/atuais, 27 programas consolidados ou 27 benefícios aprovados.

**Falhas na coleta canônica recente:** AC (certificado TLS inválido), AP (conexão encerrada), PA, PI e SE (timeout) e RR (404). Para PA, o workflow alternativo capturou Decreto 2.490/2006 em `bancodeleis.alepa.pa.gov.br`; para AP capturou documento relativo a ato diferente e exemplo individual, **não** o dispositivo material geral; PI capturou notícia/portal, não o Anexo IV original; outras fontes locais continuam com autenticação do editor pendente. Não burlar TLS, inserir hash fictício ou substituir ato por notícia.

**Limites jurídicos do resultado:** um SHA-256 confere integridade do arquivo que foi recebido; não prova publicação em Diário Oficial, redação vigente em 2026, efeito de alteração posterior, depósito CONFAZ, aplicação por CNAE/NCM/CFOP, concessão a CNPJ, revisão independente ou autorização de cálculo. Todas as candidatas continuam draft; 0/27 aceitas, 0/27 regras importadas.

## Fonte de verdade de pesquisa

- `NFCORE_T09_CURADORIA_27UFS_CROSSCHECK_20261122.json` — 27 âncoras e cenários negativos individualizados, com 8 correções normativas supervenientes.
- `NFCORE_T09_DOSSIE_RECONCILIATION_V1.json` — dossiê de cada benefício e campo `supervening_2026_primary_examination` para AM/DF/GO/MT/PB/PE/PR/SC.
- `NFCORE_T09_RESEARCH_RESIDUAL_27UFS_20261122.md` — lacunas jurídicas verdadeiramente internas por UF.
- `NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json` — autoridade de gates; não alterar booleanos para simular conclusão.
- `scripts/nfcore_t09_verify_legal_capture_archive.py` e seus testes — auditoria do ZIP de 50, sem conceder efeito fiscal.

## Separação de fechamento

**Interno pendente:** fonte original governamental arquivada para cada ato, confronto editorial e histórico temporal por competência, cotejo jurídico material/NCM/CFOP/ST/DIFAL, comprovação da rota CONFAZ ou alternativa normativa, casos positivos e negativos ancorados em norma e revisão técnica contraditória. Os documentos já reunidos reduzem coleta, não dispensam esses gates.

**Externo:** aceite humano do produto, parecer profissional sobre uso real e concessão/credenciamento individual do contribuinte onde a lei determinar. A falta de itens externos não impede pesquisa interna, mas impede efeito fiscal real.

O encerramento técnico do gate de CI deve ser verificado no HEAD exato após esta atualização. Sem merge, deploy, alteração de alíquota ou autorização fiscal.
