# T09 — Matriz verificável das 27 UFs (CURRENT 21/11/2026)

**Classificação: MATRIZ DE COBERTURA, não catálogo de incentivos homologados.**

A lista geográfica usa as UFs oficiais do IBGE. O código define tipos de
ICMS, avaliação consultiva, importador de políticas revisadas, API e
persistência canônica; sem importação de atos de cada UF ainda **não
existem regras estaduais efetivamente certificadas**.

Requisitos de cada ato para mudar "NÃO VERIFICADO" a "REVISADO":
1. Lei/decreto/RICMS estadual identificado, consolidação/vigência por período,
   fonte HTTPS oficial e digest real de documento consultado.
2. Publicação e, conforme tipo, autorização em convênio CONFAZ, adoção
   estadual, reinstituição, depósito e certificado (LC 160/2017).
3. CNAE, NCM, CFOP, operação, regime, credenciamento e condições
   de fruição suportados por evidências documentais.
4. Análise tributária independente e teste de aplicação consultiva
   com ao menos um positivo revisado e negativos por UF.
5. Aprovação humana antes de associar efeitos à apuração ou emissão,
   em tarefa posterior com autoridade de aprovação específica.

| UF | Estado | Ato estadual comprovado | Regra elegibilidade revista | Homologação real |
|---|---|---|---|---|
| AC | Acre | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| AL | Alagoas | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| AP | Amapá | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| AM | Amazonas | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| BA | Bahia | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| CE | Ceará | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| DF | Distrito Federal | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| ES | Espírito Santo | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| GO | Goiás | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| MA | Maranhão | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| MT | Mato Grosso | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| MS | Mato Grosso do Sul | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| MG | Minas Gerais | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| PA | Pará | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| PB | Paraíba | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| PR | Paraná | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| PE | Pernambuco | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| PI | Piauí | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| RJ | Rio de Janeiro | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| RN | Rio Grande do Norte | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| RS | Rio Grande do Sul | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| RO | Rondônia | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| RR | Roraima | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| SC | Santa Catarina | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| SP | São Paulo | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| SE | Sergipe | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |
| TO | Tocantins | NÃO VERIFICADO | NÃO VERIFICADO | NÃO REALIZADA |

**TOTAL**: 27/27 UFs no índice de engenharia; 0/27 com atos estaduais
consolidados e homologados nesta entrega. Não é permitido substituir esta
matriz por contagem de testes sintéticos.

Fonte territorial:
https://www.ibge.gov.br/explica/codigos-dos-municipios.php

Fonte jurídica de referência, não substitutiva de ato estadual:
https://www2.camara.leg.br/legin/fed/leicom/2017/leicomplementar-160-7-agosto-2017-785276-normaatualizada-pl.html

PR de implementação deve certificar o software e deixar explícito
que a pesquisa só retorna regras humanas previamente carregadas; catálogo
sem regras reais retorna no_reviewed_catalog, nunca "nenhum benefício existe".


### Curadoria documental representativa publicada em 21/11/2026

Foram versionadas **27 candidatas de estudo não executáveis**, uma por UF
(`docs/NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json`).
Cada candidata identifica fonte, programa/dispositivo, requisitos e caso negativo,
mas todas permanecem `draft` e sem SHA256 real do texto consolidado,
parecer externo, direito fiscal ou importação. **A tabela anterior mantém 0/27
benefícios homologados**; não alterar o significado das colunas ou confundir
27 linhas documentadas com 27 benefícios juridicamente certificados.
