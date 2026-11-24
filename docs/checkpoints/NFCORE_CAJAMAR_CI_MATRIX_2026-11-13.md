# Cajamar — matriz de certificação de branch isolada (13/11/2026)

A PR municipal canônica é #463, empilhada sobre #454. O workflow `.github/workflows/ci.yml` inclui `workflow_dispatch` e `push` nas branches `feat/nfcore-web-*`, mas PRs diretamente contra a branch de núcleo não executam CI de `pull_request`. Este commit mantém o mesmo conteúdo funcional da PR Cajamar e permite executar a matriz **FM NFCORE V1 CI** pela regra `push` já existente, sem modificar o workflow.

**Obrigatório:** verificar se o SHA da branch principal da PR #463 foi atualizado para o commit exato desta evidência. CI verde de outro SHA NÃO é certificação da PR. Este arquivo não altera autorização fiscal nem traz configuração externa.

Gates:
- Ruff, Mypy, Pytest com PostgreSQL
- WSDL/XSD/assinatura sintéticos somente, nunca homologação oficial
- Unidade/tenant, original RPS, replay, XML e normalização de resposta
- API/Portal/E2E, Docker, scans e backup/restore
- CI remota SUCCESS no HEAD exato
- Separação entre entrega interna `IMPLEMENTED_NOT_CERTIFIED` e `EXTERNAL_BLOCKED`

Restrição: nenhuma mudança de CI, ruleset, permissão ou merge foi autorizada pelo N2. A execução do workflow existente não modifica esses controles.
