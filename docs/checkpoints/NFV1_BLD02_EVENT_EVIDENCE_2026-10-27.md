# BLD-02 — evidência durável dos eventos fiscais

Incremento dependente da PR #256 (`4903048bcb6b3b2b1ba04070c78ccf0589629889`),
cuja integração permanece condicionada à CI/Governança. Base main
`4b258afe19af8b532c3a8afc8543bfb1568d11dd`: CI pós-merge `40524003195` e
Governança `40524003091` SUCCESS. PR #255 de retorno visual aguarda seus gates.

## Autoridade e delta

O cliente existente valida identidade/escopo/request antes de devolver o resultado
de cancelamento ou inutilização. Quando a composição recebe aplicação durável e
retenção explícita, o handler agora grava resultado normalizado no FiscalArchive
pela FiscalApplicationService, antes de devolver a referência ao Portal. Usa
FISCAL_EVENT e media type específico; não cria segunda persistência nem grava
resultado bruto no recibo T07. Não copia justificativa, segredo ou mensagem livre
do provider. Conserva status, identidade do request/provider e protocolo/código.

Composição de eventos pode receber aplicação+retenção sem gateway de emissão;
isso não habilita emissão/reconciliação de documentos. Configuração incompleta ou
tipos inválidos continuam rejeitados. Chamadores antigos somente com client
preservam seu contrato sem alegar persistência; usar composição durável para a
jornada Web. Nenhum fake foi adicionado ao runtime.

Recuperação T07 consulta apenas evidência canônica do mesmo host/tenant/unidade/
ambiente, operação e correlação original. Exatamente uma evidência permite
recuperar a referência após interrupção entre archive commit e receipt finish.
Não reenvia ao provider; ausência/ambiguidade continua exigindo reconciliação.
Status recorded continua sendo registro de resposta, inclusive pending/rejected,
nunca confirmação fiscal. A UI recebe somente os metadados já autorizados.

## Validação e limites

Testes SQLite/HTTP durável: accepted/rejected/pending; perda de resposta após
arquivo; reconstrução da aplicação e replay sem dispatch; falha no arquivo
mantém resultado desconhecido sem retry externo. Cancelamento conserva protocolo
validado na mesma store. Casos PostgreSQL são executados na CI com banco descartável,
SKIP local por ausência de DSN. Suites dirigidas de recovery, wiring, emissão e
NFS-e PASS; Ruff global e Mypy de 227 fontes PASS. CI remota ainda obrigatória.

BLD-02 IN_PROGRESS. A gravação da evidência não sincroniza automaticamente o
lifecycle de um documento cancelado: o contrato Web atual informa access_key,
não uma associação durável comprovada ao document_id. Essa ligação permanece
pendente de implementação canônica; não inferir vínculo ou marcar CANCELLED por
recibo. NFS-e municipal, provider real, credenciais e homologação seguem separados.
Sem deploy, alteração de schema ou operação fiscal externa.
