# T09 — Dossiê de evidências e solicitação de parecer ao contador

**Data:** 21/11/2026 · **PR:** #592 · **HEAD de partida:** `189deb39125c1c62b9614a546a21e9270cfbd028`.

**OBJETIVO.** Preparar a revisão jurídico-fiscal independente sem delegar à IA
a atribuição de certificação, sem reclassificar documentação como benefício
e sem criar autoridade fiscal paralela.

## Situação comprovada

- 27/27 UFs com 1 candidata de estudo por estado no catálogo documental.
- 24/27 UFs com cláusula, procedimento ou programa
  **diretamente inspecionado em fonte oficial** nesta reconciliação.
- 0/27 UFs com todo o material concessivo, suas alterações até a competência
  e condições por contribuinte legalmente consolidado e certificado.
- 0 pareceres de contador recebidos e 0 benefícios reais aprovados.
- `docs/NFCORE_T09_ACCOUNTANT_EVIDENCE_HANDOFF_V1.json` contém 27 casos,
  fontes e negativas, estado de cada gate e campos a preencher no parecer.
- Todos permanecem `review_status=draft`, sem crédito ou importação autorizada.

## Achados materiais — fontes governamentais verificadas

| UF | Regra ou programa | Evidência e principal trava |
|---|---|---|
| SP | RICMS Anexo III art. 41 c/c Anexo II art. 52 | 12% nominal apenas sobre saída interna abrangida; art.52 exclui consumidor final, especifica NCM; opção, substituição de créditos e validade até 31/12/2026. [Fonte I](https://legislacao.fazenda.sp.gov.br/Paginas/an3art041.aspx) · [Fonte II](https://legislacao.fazenda.sp.gov.br/Paginas/an2art052.aspx) |
| RS | RICMS Livro I art.32 CLXXXVI | NCM 9406.90.20/7308.20.00, deferimento e início mês subsequente, FGTS e INSS; sem opção aprovada não há direito. [Fonte](https://receita.fazenda.rs.gov.br/servicos-a-empresas/servicos?servico=1946) |
| GO | Lei 20.787/2020 ProGoiás, art.11 e §4º | Termo de Enquadramento, adimplência, exceções de dívida ativa e regularização; proibição de aplicação universal. [Fonte](https://goias.gov.br/industriaecomercio/lei-ordinaria-20-787-20-progoias/) |
| MG | RICMS 2023 Anexo II item 26 e 26.1 | Saída interna para habitação popular sob coordenação Cohab Minas, desconto no preço destacado em documento fiscal, prazo 31/12/2026. [Fonte](https://www.fazenda.mg.gov.br/empresas/legislacao_tributaria/ricms_2023_seco/anexoii2023_3.html) |
| PR | Paraná Competitivo, Dec. 7.721/2024 | Antigo Dec. 6.434/2017 revogado; NCM impedidas na Res. 304/2025 e resoluções 2026 para situações específicas. [Fonte](https://www.fazenda.pr.gov.br/Pagina/Parana-Competitivo) |
| PE | PRODEPE, Dec. 21.959/1999 | Portal SEFAZ registra ato alterador Dec. 61.000/2026; exigir decreto/ato concessivo e condições individualizadas. [Fonte](https://www.sefaz.pe.gov.br/Legislacao/Tributaria/Documents/legislacao/decretos/1999/Dec21959_99.htm) |
| PI | RICMS Anexo IV art.25-A, 178 XXXVIII e 17 | Comunicado UNATRI 1/2025: isenção de alguns itens, redução de base de outros; ovos constam no art.17, não art.25-A; exigem-se alterações até 2026. [Fonte](https://portal-admin.sefaz.pi.gov.br/wp-content/uploads/2025/03/SEI_GOV-PI-017374270-SEFAZ_-Comunicado-UNATRI.pdf) |
| MA | Mais Empresas, Lei 10.690/2017 | Carta Consulta e aprovação CONDEP; protocolo não é concessão nem define taxa universal. [Fonte](https://seinc.ma.gov.br/servicos/solicitar-beneficios-do-programa-mais-empresas-emissao-de-carta-consulta) |

**Esses são apontamentos preliminares de fontes oficiais, não parecer ou
confirmação de texto legal consolidado por competência.** Nas demais 3 UFs
a fonte indicada no dossiê anterior ainda é ponto de entrada, não
dispositivo integral inspecionado nessa rodada.

## Escopo e documentação indispensáveis para o parecer

Para **cada ato**: texto oficial completo, histórico das alterações e
vigência específica por competência; convênio CONFAZ e adoção estadual,
LC 160/2017 quando cabíveis; NCM/CFOP/CNAE/regime/UF de origem e destino,
ST/DIFAL; ato concessivo individual, status IE, opção, credenciamento,
carga tributária, contrapartidas, obrigações, vedações/estorno; originais
do documento e SHA-256 **realmente calculado**; um cenário positivo
documentado e negativos obrigatórios; identificação do profissional
habilitado, data, escopo do contribuinte, decisão expressa e assinatura.

**Termo que o contador deve emitir:** Parecer independente por versão
da candidata, UF, dispositivo, vigência/competência, fontes, verificações,
condições, impedimentos e decisão (aprovar/reprovar/aprovar com condições).
Exigir vínculo verificável entre o parecer assinado e o documento revisado.

O envio do dossiê **não foi realizado por e-mail ou portal**; o usuário
informou que o profissional da contabilidade será o responsável.
Quando recebido, o parecer deverá ser autenticado, revisado e somente
então originar nova política `reviewed` governada. T13/T14 são fases
posteriores, não atalhos para emissão ou crédito nesta T09.

**TRAVAS:** 0 de 27 políticas fiscalmente homologadas, 0 assinaturas
independentes, 0 fontes oficiais consolidadas com digest verificável,
0 integrações fiscais autorizadas; PR Draft, T10 bloqueada.

## Revisão complementar oficial e correção de domínio (21/11/2026)

A pesquisa revisou diretamente mais 11 fontes públicas: AC (Lei 1.358/2000
+ Decreto 4.196/2001), AP (COTRI), AM (Decreto 47.727/2023 e alterações 2026),
CE (ADECE/FDI), ES (SEFAZ/COMPETE), MT (Informação 124/2026), MS (LC 93/2001),
PA (Resolução 21/2020 individual), PB (FAIN e alteração 2026), SC (Pró-Emprego)
e SE (PSDI). `official_source_direct_inspection_count=19` significa
inspeção de **fontes governamentais com recortes**, NÃO auditoria da versão
integral de todas as normas, nem certificação do direito tributário.

**Correção AC:** Lei 1.358/2000 institui incentivo tributário na modalidade
de **financiamento direto**, associado ao ICMS próprio e investimento fixo,
não um crédito presumido genérico. A candidata foi reclassificada como
`special_regime` **provisória** até tipagem financeira/fiscal independente.
Fonte: https://sefaz.ac.gov.br/2021/?p=11726 ;
https://sefaz.ac.gov.br/2021/?p=14786 .

**MT:** Informação SEFAZ 124/2026 confirma redução de base do art.31-A Anexo V
prorrogada até 31/12/2027 pelo Decreto 1.802/2025. Diferimento interno
é regra distinta; jamais converter isenção, redução e diferimento entre si.
Fonte: https://app1.sefaz.mt.gov.br/sistema/legislacao/respostaconsulta.nsf/766feae0478e62780325673c0049468e/dfdffa903c8253dd03258e28005313b4 .

**PA:** Resolução 21/2020 é expressamente individual a uma empresa, não
concessão genérica. Fonte: https://www.sistemas.pa.gov.br/sisleis/legislacao/5840 .

**PB, SC e SE:** atos de conselho, TTD, habilitações específicas,
obrigações de emprego/escrituração ou vedação de enquadramento tornam
uma resposta baseada apenas no CNAE juridicamente insuficiente.

**Gates de acesso:** fontes de AL estavam em manutenção no acesso realizado;
portal legal RJ retornou bloqueio de segurança; RN/TO não exibiram o
texto integral, enquanto BA/RO/RR ainda requerem confrontar documentos
primários, suas alterações e concessões. Não usar espelho privado como
substituto de documento oficial. **3 UFs seguem sem inspeção direta
suficiente** neste pacote e, em todas as 27, falta a comprovação integral
por competência e parecer do contador.

## Consolidação documental complementar (21/11/2026)

Inspecionadas diretamente fontes fiscais oficiais adicionais para BA, DF,
RJ, RO e RN, elevando o conjunto a **24/27 com dispositivos/consultas
pesquisados**. Não significa que 24 UFs estejam legalmente homologadas.

- **BA, DESENVOLVE**: Regulamento Dec.8.205/2002, art.2 diferimento
  condicionado a habilitação, art.3 dilação até 72 meses e até 90% do saldo
  devedor próprio vinculado a investimento aprovado. O arquivo publicado
  pela SEFAZ/BA já indica Decreto 24.401/2026 entre modificadores.
  https://mbusca.sefaz.ba.gov.br/DITRI/normas_complementares/decretos/decreto_2002_8205_desenvolve.pdf
- **DF, EMPREGA DF**: Decreto 39.803/2019 art.7 e art.8 — projetos e
  aprovação; crédito presumido limitado a **até 67%**, não 67% automático.
  Exceções e setores excluídos; alterações de 2026 requerem reconciliação.
  https://www.sinj.df.gov.br/sinj/Norma/2257f831264c4e06850f0248431427df/Decreto_39803_02_05_2019.html
- **RJ, têxtil**: Lei 6.331/2012, art.2, redação Lei 10.983/2025,
  prevê crédito presumido para **carga tributária efetiva de 2,5%** em
  operações específicas. Isso não corresponde a crédito de 2,5% e não
  afasta vedações ao regime simplificado, cumulatividade e adesão.
  https://www3.alerj.rj.gov.br/lotus_notes/default.asp?URL=L0NPTlRMRUkuTlNGL2M4YWEwOTAwMDI1ZmVlZjYwMzI1NjRlYzAwNjBkZmZmLzY4ZDI2ZWU1OThmMWFlNzI4MzI1N2E5OTAwNjNiMzcxP09wZW5Eb2N1bWVudA%3D%3D&amp=&id=2
- **RO, CONDER**: Decreto 30.916/2025 altera Dec.12.988/2007 e
  exige manifestação GITEC/CRE/SEFIN e CONSIC para rever enquadramento
  em faixas superiores condicionado a empregos, além de restrições
  industriais. Texto em repositório SEFIN adverte não substituir DOE.
  https://www.sefin.ro.gov.br/portalsefin/anexos/D25-30916---Altera%2C-acresce-e-revoga-dispositivos-do-Regulamento-de-Incentivo-Tributario-aprovado-pelo-D07_-12.988.pdf
- **RN**: consulta oficial 015/2023 da SEFAZ trata produtores de peixes
  e camarões, crédito presumido sob Anexo 003, arts. 1,2,5 e 6; trata-se
  de manifestação sobre caso de 2023, não prova de benefícios em 2026.
  https://www.sefaz.rn.gov.br/postagem/respostas-de-consultas-2023/

**3 UFs com análise do ato primário ainda insuficiente** neste pacote:
AL (site de FAQ instável), RR (PDF legal retornado, leitura visual da
página normativa falhou) e TO (fonte legal indicada no índice, leitura
integral retornou erro). Mesmo nas 24 com trechos examinados,
**27/27 carecem de reconciliação integral temporal, evidência SHA256
oficial, direitos individuais e parecer jurídico-fiscal assinado**.


## Classificação formal de responsabilidade (decisão do proprietário em 21/11/2026)

A **consolidação jurídica normativa** de cada ato, alteração, exceção e competência é trabalho **INTERNO executável por agente IA especialista em direito tributário**: ver
`docs/NFCORE_T09_LEGAL_EXPERT_AI_WORKFLOW_V1.md` e fila de 27 recortes
`docs/NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json`.

O **parecer jurídico-fiscal independente** do contador é **DEPENDÊNCIA EXTERNA**. Ele **NÃO** é motivo para deixar paralisadas a pesquisa e a engenharia de curadoria, mas permanece **PENDENTE NÃO RECEBIDO** e é obrigatório para confirmar legalmente cada benefício antes de ativação/apuração/emissão. Documento e testes da IA não constituem parecer do contador.
