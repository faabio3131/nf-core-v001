# NFCore T09 — Kit Windows e protocolo de curadoria em 3 frentes

**Escopo**: PR #592, apenas pesquisa/arquivamento de fontes legais de 8 UFs.
**Não é** parecer externo, importação de benefícios, ativação de regras fiscais,
autorização de crédito, homologação estadual ou concessão por contribuinte.

## Frente 1: capturas locais que falharam no runner

1. Abrir o documento legal oficial usando navegador Windows; conferir o
   endereço HTTPS, o ato, número, data, publicação e se a página não é
   apenas índice, notícia, erro 403/502 ou exigência de captcha.
2. **Se o navegador acusar erro TLS, não ignorar o alerta nem usar
   `curl -k`, `verify=False` ou desativar certificados.** Obter uma fonte
   equivalente do DOE ou da Assembleia/Casa Civil com TLS válido.
3. Para PDFs, baixar o arquivo **original**, jamais usar "Imprimir em PDF"
   (o PDF refeito não são os bytes originais). Para HTML, salvar "página
   somente HTML" e preservar a URL inicial/final. Conteúdo após execução
   JavaScript pode não ser a publicação oficial, validar manualmente.
4. Colocar os arquivos com nomes exatos do `links_validos.json` em
   `fontes/`. Para itens ainda sem URL exata (`source_url=null`),
   localizar primeiro a fonte primária e preencher HTTPS oficial; uma
   captura sem URL terá hash íntegro, mas procedência **não certificada**.
5. Executar no PowerShell, na pasta extraída do kit:

```powershell
py -3 .\obter_e_hashear_fontes.py --hash-local
Get-ChildItem .\fontes\ -File | ForEach-Object {
    [PSCustomObject]@{
        Arquivo = $_.Name
        Bytes = $_.Length
        SHA256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
} | Format-Table -AutoSize
```

6. Examinar `manifesto_sha256_reais.json`: o contador `hashed_count`
   mede **integridade de bytes locais**, não valida o autor, a vigência,
   a fonte oficial nem o conteúdo normativo. Itens faltantes ficam
   `missing`, páginas de erro, HTML curto, PDF truncado e extensões
   inconsistentes ficam `rejected`.
7. Compactar apenas documentos públicos de `fontes/`, mais
   `links_validos.json` e `manifesto_sha256_reais.json`:

```powershell
Compress-Archive -Path .\fontes, .\links_validos.json, .\manifesto_sha256_reais.json -DestinationPath .\T09_fontes_publicas.zip -Force
```

**Lote A (prioritário):** AC, PA e PI, incluindo as mudanças de 2018,
2020 e 2025 que alteram o marco temporal. O Decreto 2.490/2006 do PA
já teve cópia capturada pelo Actions; isso **não** comprova todas as
alterações.

**Lote B:** AL, AP, RJ, RN e SE. Excluir notícia bloqueada da ALERJ
da lista de originais obrigatórios. O RJ requer, no mínimo, cotejar
Portaria SSER 345/2023 e alterações 350/2024, 362/2024 e 431/2025
à luz da Lei 6.331/2012.

### Correção relevante de AC

A Portaria SEFAZ/AC 140/2025 consta no índice público como norma
sobre **autorregularização fiscal** (Portaria 523/2023), não como
regulamento material da Lei 1.358/2000. Foi retirada do conjunto
de originais obrigatórios desta candidata. Priorizar Lei 1.358/2000,
Decreto 4.196/2001, Lei 3.460/2018 e Decreto 11.618/2025.

## Frente 2: reconciliação por norma, competência e operação

Para cada candidata (`UF + ato + competência + cenário`) preencher,
a partir de fontes primárias e suas versões:
- texto oficial original e **prova de publicação**;
- datas de início/fim e cadeia de alterações, revogações e prorrogações;
- LC 160/2017, Convênio ICMS 190/2017 ou rota CONFAZ específica,
  somente quando juridicamente aplicáveis;
- operações, NCM/CNAE/CFOP, ST, DIFAL, regime e condições de adesão;
- decisão individual exigida e casos positivos/negativos reproduzíveis;
- revisão contraditória independente do autor do dossiê.

Não transformar documentos capturados em `internal_curatorial_accepted=true`.
Esse campo só pode ser decidido pelo responsável autorizado, após
**todas** as evidências acima e reconciliação do cenário. Nem o hash
nem um parecer externo substituem aprovação interna real.

## Frente 3: governança fiscal e separação das autoridades

- **Padrão da aplicação existente**: a evidência do CNPJ reside em
  `facts["evidence"]` e o motor canônico exige
  `individual_concession_review`. Na falta de evidência mandatória,
  retorna `insufficient_basis`. Isso não valida autenticidade
  de um documento anexado por si só.
- **Curadoria interna**: fonte, hash, cadeia temporal, testes, revisão
  contraditória e aceite humano auditável. Um `draft` continua não
  executável. Não inserir digest no campo de uma norma diferente.
- **Parecer contábil/jurídico externo**: dependência
  `EXTERNAL_DEPENDENCY/PENDING_NOT_RECEIVED` até documento genuíno.
  **Não é produzido por IA**, nem pode ser substituído pelo parecer
  oficial da PGE sobre outro contribuinte.
- **Atos individuais**: dependem de cliente, competência e órgão
  concedente. Nunca vinculá-los genericamente às 27 UFs.
- **Importação/sistemas reais**: sem HMAC/aceite do responsável,
  fontes verificadas do ato exato e demais gates, nenhuma promoção
  de `review_status`, autorização de cálculo ou deploy.

**Segurança:** não anexar atos privados, CNPJ, credenciais ou
certificados de clientes no ZIP público. Armazenar documentos
individualizados na área segregada e protegida da operação.

## Gates e classificação

| Etapa | Critério | Situação |
|---|---|---|
| Pesquisa geográfica | uma candidata por UF | 27/27 draft |
| Arquivo técnico local | bytes + SHA-256 + fonte declarada | pendente dos downloads locais |
| Consolidação normativa por caso | redações, vigência, operação, CONFAZ | pendente |
| Revisão contraditória | revisor distinto e evidência verificável | pendente |
| Aceite interno | decisão humana auditável após gates | pendente |
| Parecer externo | profissional habilitado assinou | pendente |
| Concessão individual | por CNPJ e competência, se exigida | pendente |
| Benefícios importados/aplicáveis | aprovação e gates determinísticos | **0/27** |

A fila `links_validos.json` contém **endereços candidatos**, e não
URLs juridicamente validadas. O kit é deliberadamente **offline**.
