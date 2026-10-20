# FM Tecnologia — Blueprint de hospedagem Contabo multiproduto (Kordena, AtendeVendeIA, NFCore)

**Data:** 2026-10-20  
**Classificação:** DECISÃO APROVADA + CURRENT parcial observado + TARGET arquitetural.  
**Status:** DOCUMENTADO; não configura por si só o servidor, não comprova deploy, não autoriza cutover.  
**Repositório de registro:** `faabio3131/nf-core-v001` (documentação de continuidade do Commercial Launch).  
**Origem:** instruções do responsável FM e captura do painel Nginx Proxy Manager na VPS Contabo de 20/10/2026.

## 1. O que está confirmado — sem ampliar indevidamente

- A FM adquiriu uma **VPS Contabo Cloud VPS 4, 8 GB RAM**, na região US-central, mostrada como **em execução** no Customer Panel. O valor mensal de R$ 43 foi informado pelo responsável; não foi auditado em fatura.
- Uma captura posterior mostra **Nginx Proxy Manager (NPM) v2.16.0**, acessado em `http://<IP-DA-VPS>:81`, com conta administrativa autenticada.
- **NPM CURRENT conforme captura:** 0 Proxy Hosts, 0 Redirection Hosts, 0 Streams e 0 404 Hosts. Significa que **nenhum hostname dos três SaaS estava mapeado nesse painel** no instante da captura.
- O responsável informou que a **Evolution API e seu banco** foram ativados no servidor para atender o AtendeVendeIA. **ESTADO NÃO COMPROVADO** por esta captura; validar health, compose, versão, persistência e rede no inventário.
- Em auditoria anterior, SSH/TCP 22 da VPS respondeu, enquanto 80/443 não respondiam; autenticação SSH root com chave do computador autorizado falhou. **Rever CURRENT antes de qualquer acesso**, pois o servidor pode ter mudado.
- O endereço público do painel NPM usa **HTTP na porta 81**. Se aberto na internet, isso é **risco crítico de exposição administrativa/credenciais**; auditar ACL/firewall, restringir acesso via VPN/túnel/allowlist e habilitar proteção adequada antes de produção. Não bloquear 81 nem ativar firewall remotamente sem acesso de recuperação confirmado.
- A imagem **não prova** Docker networks existentes, configuração de Postgres, TLS, Evolution API healthy, hostnames, backup ou contêineres dos produtos.

## 2. Decisão aprovada FM

Hospedar inicialmente **Kordena, AtendeVendeIA e NFCore** na mesma VPS Contabo, **preservando cada SaaS funcional como produto independente**. Usar **Docker Compose por produto**, sem segundo frontend ou backend de negócio e **NPM existente como reverse proxy comum**.

**Princípio constitucional:** uma máquina compartilhada não é licença para compartilhar banco, autenticação, tenant, volumes, credenciais, segredos ou permissões entre SaaS.

- Projetos Compose independentes: `fm-kordena`, `fm-atendevendeia`, `fm-nfcore`.
- Cada projeto tem múltiplos contêineres conforme sua aplicação REAL: Web, API, Worker e banco. Não presumir que uma aplicação inteira cabe num único contêiner.
- Identidades DB independentes (role, base, senha e privilégios). Preferir bancos separados (ou instâncias segregadas se risco/capacidade exigir); jamais usar a mesma base/tabelas com separação apenas por prefixo.
- Volumes e armazenamento XML/PDF, cache, filas, logs operacionais, artefatos de cliente, certificados e secrets isolados.
- Não expor PostgreSQL, Redis/filas, Evolution ou portas internas da aplicação publicamente; usar `expose` e redes Docker fechadas. Toda rota HTTP pública passa pelo NPM, em 80/443 com TLS.
- Recursos: estabelecer cotas CPU/RAM/PIDs, limites de filas, healthchecks, log rotation, reserva de memória para SO/banco/proxy e monitoramento. Os **8 GB são TARGET sujeito a ensaio de carga**, não uma certificação de que os três SaaS suportarão qualquer volume.
- Backups criptografados **fora da VPS** por produto, restauração isolada comprovada, retenção, observabilidade e reversão, antes de mover estado real.
- Integração entre SaaS somente via contratos/API autenticados, tenant/host_system governados, egress estrito e autorização; a rede compartilhada não concede autoridade de acesso.

## 3. Diretórios operacionais propostos (TARGET; confirmar existentes)

```text
/home/SaaS/
├── infra/            # NPM existente, Evolution e infraestrutura compartilhada governada
│   └── (inventariar serviços/volumes antes de editar)
├── atendevendeia/    # compose exclusivo: API, Web, workers; DB e volumes próprios
├── kordena/          # compose exclusivo: API, Web, workers; DB e volumes próprios
└── nfcore/           # compose exclusivo: API, Portal, Worker; DB e volumes próprios
```

**Importante:** esta estrutura de pastas veio da proposta fornecida pelo usuário; **não foi verificada no filesystem**. Não criar ou sobrescrever arquivos `/home/SaaS/infra/` até realizar inventário e backup do NPM/Evolution existentes.

## 4. Topologia correta da "ponte" Nginx Proxy Manager

O usuário propôs uma rede Docker global `saas-network` ligando todos os contêineres. **Não adotar acesso plano de todos os contêineres à mesma rede**, pois isso permite comunicação lateral entre bancos e APIs.

Desenho proposto:

```text
                   Internet TLS 443/80
                           |
                    NPM EXISTENTE (infra)
                           |
           ┌───────────────┼────────────────┐
           |               |                |
     edge-atende       edge-kordena      edge-nfcore
           |               |                |
       Web / API        Web / API        Portal / API
           |               |                |
    private-atende   private-kordena   private-nfcore
           |               |                |
     DB + Worker       DB + Worker      DB + Worker
           |
    evolution-edge    (integração estritamente definida
           |            entre backend Atende e Evolution)
      Evolution API
```

- NPM pode conectar-se às **redes edge individuais** para alcançar apenas containers-alvo (Web/API). Cada banco/worker fica em **rede privada do respectivo produto**, sem ligação direta ao NPM.
- `edge-atende`, `edge-kordena`, `edge-nfcore` são nomes conceituais, **não redes criadas**; definir nomes `external: true` somente depois da criação governada e auditoria de privilégios.
- A Evolution API mantém sua própria rede/DB; liberar ao backend Atende acesso estritamente necessário por rede/conector. Nenhum banco da Evolution é compartilhado com Kordena/NFCore.
- NPM é infraestrutura administrativa altamente privilegiada com alcance às três bordas; endurecer e monitorar esse ponto de falha. Só ele deve publicar 80/443. **Não subir Caddy/Traefik adicionais disputando essas portas.**
- Sem exposição de portas de banco ou serviços ao host salvo ligação `127.0.0.1` temporária e autorizada para diagnóstico. Não expor interface NPM `:81` livremente na internet.

## 5. Roteamento: exemplos NÃO equivalem a domínios existentes

| Produto | Nome público | Serviço interno ilustrativo | Estado |
|---|---|---|---|
| AtendeVendeIA | `atendevendeia.com.br` | `atendevendeia_api:8000` e frontend real | Domínio informado como ativo anteriormente; **reconfirmar DNS, porta interna e nome de serviço** |
| Kordena | `kordenaia.com.br` | `kordena_web:3000` e API própria | Domínio oficial previamente adquirido; `kordena.com.br` é prioridade futura, **não assumir posse** |
| NFCore | **domínio oficial ainda a decidir/verificar** | `nfcore_portal:8081`, `nfcore_api:8080` | `nfcore.com.br` no exemplo NÃO significa registro ou DNS; **não usar 4000 como porta real por dedução** |

Os destinos finais devem ser obtidos de `docker compose config`, logs e testes dentro das redes. **NPM Proxy Hosts CURRENT = 0**. Antes de criar hosts, confirmar DNS, nomes de contêiner, network membership, health e certificados TLS.

## 6. Fontes canônicas CURRENT dos produtos (rever SHA ao executar)

- **Kordena:** `faabio3131/fm-ai-platform` (backend Python e Web Next.js). Não reutilizar configuração desatualizada sem comparar PRs e main.
- **AtendeVendeIA:** `faabio3131/fm-vendedor-recuperacao-vendas` possui `deploy/hetzner/docker-compose.prod.yml` com Web/API/Worker/Postgres, script de backup e rollback. **Não copiar esse Compose integralmente** porque ele sobe um segundo Caddy e tem seu próprio DB; adaptar para NPM existente. Reconciliar também `faabio3131/-FM-Assistant-Base` e `faabio3131/FM-Core-Base-` antes do artefato final.
- **NFCore:** `faabio3131/nf-core-v001`, atualmente usa `Dockerfile.api`, `Dockerfile.portal`, `Dockerfile.worker`, `compose.yaml`; portas verdadeiras 8080 e 8081. O Compose corrente tem defaults de **desenvolvimento** (HTTPS off, segredo em memória, senha local), **NÃO válido como produção**.
- Preservar staging Render/Railway/Vercel e dados enquanto a migração não estiver certificada. Não reconstruir frontend nem domínio fiscal.

## 7. Plano executável e critérios de aceite

1. **Auditoria read-only da VPS** por SSH autenticado com chave: SO, usuário, rootless/sudo, kernel, atualizações, RAM/swap, disco, Docker/Compose, NPM/Evolution, redes, volumes, processos, porta 81, firewall, backups, DNS e segredos. Não realizar reset/reinstall.
2. **Congelar inventário e backup** das configurações e volumes existentes (especialmente NPM/Evolution); guardar recovery off-host; testar restauração isolada.
3. **Endurecer borda:** restringir admin NPM :81, TLS e controles de acesso, regras 22/80/443 auditadas e recuperação da sessão; não fechar SSH sem acesso de console comprovado.
4. **Criar compose por produto** na mesma fonte canônica do código, redes edge/private e limites; usar Secrets em local protegido, sem valores reais no repo; healthchecks e CI lint/config.
5. **Deploy inicialmente sem tráfego público** de um produto por vez, com migrações separadas governadas, teste de autenticação/RBAC/tenant, controle de falhas, Redis/Evolution se aplicável e smoke E2E.
6. **Reconciliar proxy/DNS/TLS** sob autorização específica; adicionar Proxy Hosts NPM somente após API e Web saudáveis e domínios verificados; não mover três domínios em um único cutover.
7. **Certificar produção/rollback:** logs, métricas, backup/restore, limites, incident runbook e Go/No-Go humano. Preservar ambientes antigos até aceite.

**Bloqueios CURRENT:** não há prova de SSH admin funcional, não há inventário verificado de NPM/Evolution, não há validação de capacidade real de 8GB e 0 Proxy Hosts estão configurados na captura. Nada disso pode ser declarado DONE apenas pelo texto de configuração.

## 8. Sobre o "script que faz a ponte"

O usuário mencionou que disponibilizará um script. O texto recebido **não inclui um script executável completo**, apenas layout, exemplos de Compose e diretrizes de proxy. Ao receber o arquivo de script, fazer revisão de segurança e impacto, confrontar repositórios e compose atuais, proteger credenciais e compatibilidade do NPM existente, testar em modo read-only/dry-run e só executar alterações governadas após aprovação. Não aceitar scripts que apaguem dados, abram bancos publicamente, desativem segurança ou criem autoridade paralela.
