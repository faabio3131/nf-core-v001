# Central de Economia Fiscal — cronograma de execução
Data: 20/11/2026. Autoridade: `agentes.md`. Base: `52568a3df46dc6cf608a22c7b9971266ce71cbef`.
Ordem inicial: T13/T14, T08–T10, demais entregas conforme v3. Promoção do bloco 5 depende das regras certificadas. A planilha v3 (33 tarefas) não estava acessível: não renumerar nem marcar tarefas sem confrontá-la.

| Bloco | Escopo original | Estado |
|---|---|---|
| 1 | Diagnóstico Simples / Fator R | Pendente |
| 2 | Segregação de receitas | Pendente |
| 3 | Incentivos por jurisdição / T08–T10 | Pendente |
| 4 | Comparador de regimes | Pendente |
| 5 | Aplicação prospectiva / T13–T14 | Parcial — incremento de cálculo e XML NF-e |
| 6 | Revisão histórica e recuperação | Pendente |

## Entrega inicial T13/T14
- Reutiliza NfeRateParameters, TaxRule, parser de política revisada, TaxRuleEngine e builder NF-e. Código pré-existente suporta redução CST20/70.
- Evidência de revisão, referência de aprovação, cBenef, vigência obrigatória (UF origem/destino, NCM exato, CRT normal, destinatário, NF-e venda). Expiração usa resolver existente; sem regra alternativa, bloqueia.
- CST20/40/41: modalidade expressamente parametrizada nominal menos devido, não fórmula universal; CST51: diferimento. XML e totalização com dedução explícita. Composição FCP/ST/DIFAL fora deste incremento. Nenhuma regra real SP/MG instalada.
- Fonte técnica: XSD versionado `src/kordena_fiscal/xml/official/PL_010g_v1.03/leiauteNFe_v4.00.xsd`, prod/cBenef, ICMS20, ICMS40, ICMS51. XSD não comprova elegibilidade legal. Fixtures sintéticas.
- Estado IMPLEMENTADO PARCIAL / NÃO CERTIFICADO. Testes adicionados, não executados. Pendentes: aprovação contábil vinculada ao resultado/snapshot exato, API/Portal, catálogo oficial, elegibilidade, BM NFS-e (reutilizar mecanismo existente), conciliação e dossiê, XSD integral e certificação. Não publicar em produção. Branch separada para evitar conflito com fechamento Claude.

### Verificações adicionais
Testes sintéticos de parsing, vencimento, rejeição de escopos incompletos, aprovação ausente, memória e fingerprint, XML completo com assinatura digital e XSD acrescentados. A execução local integral está bloqueada neste ambiente (DNS sem acesso ao GitHub, clone não realizado). Não certificar por inspeção de código; nenhum teste executado nesta etapa.
