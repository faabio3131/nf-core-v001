# PR423 — reconciliação da origem MG, sem conclusão do MG20

Origem confirmada: `94905c717bccfe127752c79c8f4020eda2b7c7d4`.
CURRENT comparado: `d7fd30ee411ac12f691a957a9a204b9c1f46d737`, cumulativo
sobre a candidata `af1f7b58794beba42a92718dea40a44fb1ef90fa`.
Dos 29 caminhos da origem, 15 são idênticos, 14 evoluíram e nenhum está ausente.
Catálogo de prioridade, matriz municipal, documentos de fonte e guard de canal
foram preservados. A branch original permanece disponível.

| Mecanismo da origem | Resultado da revisão independente |
|---|---|
| NF-e MG55 / NFC-e MG65 | Bindings e roteamento preservados; correlação compartilhada exige unicidade e UF/chave/evento exatos |
| WebISS | Consulta de notas prestadas preservada; XSD Extrema pinado, cobertura exata das assinaturas e eventos ampliados |
| Uberaba | Não herda indevidamente o pin de Extrema |
| NFS-e Nacional | Guard MG preservado; recibo validado por contrato mais rigoroso com identidade/schema |
| Runtime | Mesma composição e autoridade de provider binding, sem instância paralela |

Revisão independente: 176 testes focais MG/WebISS/schema/RTC/coverage PASS,
sem editar os arquivos. Não identificou funcionalidade essencial da origem
perdida no delta revisado. Parecer favorável a encerrar #423 como substituída,
após confirmar a CI cumulativa; não como conclusão dos 20 municípios.

A [issue #426](https://github.com/faabio3131/nf-core-v001/issues/426) permanece
ABERTA e é o destino explícito dos requisitos MG20. Matriz fiscal por cidade,
jornadas e operações reais, EGM e homologação externa não foram certificadas
por esta reconciliação. Não alterar os estados municipais para concluído.
