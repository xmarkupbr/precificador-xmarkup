// Adicione estas funções ao script.js e modifique a função recalculateRow existente

function getCurrentPricingMethod() {
    // Para a página de resultados (sidebar)
    const selector = document.getElementById('pricing_method_selector');
    if (selector) {
        return selector.value;
    }
    
    // Para o formulário inicial
    const checkedRadio = document.querySelector('input[name="pricing_method"]:checked');
    if (checkedRadio) {
        return checkedRadio.value;
    }
    
    return 'simple_margin'; // padrão
}

function recalculateRowContributionMargin(row) {
    // Obter os parâmetros de configuração para Margem de Contribuição
    const contributionMargin = parseFloat(document.querySelector("input[name='contribution_margin']").value.replace(',', '.')) / 100 || 0.3;
    const fixedCosts = parseFloat(document.querySelector("input[name='fixed_costs']").value.replace(',', '.')) || 0;
    const monthlySalesQty = parseInt(document.querySelector("input[name='monthly_sales_qty']").value) || 100;
    
    const comissoes = {
        site: parseFloat(document.querySelector("input[name='comissao_site']").value.replace(',', '.')) / 100 || 0,
        ml: parseFloat(document.querySelector("input[name='comissao_ml']").value.replace(',', '.')) / 100 || 0,
        shopee: parseFloat(document.querySelector("input[name='comissao_shopee']").value.replace(',', '.')) / 100 || 0,
    };
    const fretes = {
        site: parseFloat(document.querySelector("input[name='frete_site']").value.replace(',', '.')) || 0,
        ml: parseFloat(document.querySelector("input[name='frete_ml']").value.replace(',', '.')) || 0,
        shopee: parseFloat(document.querySelector("input[name='frete_shopee']").value.replace(',', '.')) || 0,
    };
    
    const qtdInput = row.querySelector("input[name='qtd[]']");
    const qtd = parseFloat(qtdInput.value) || 0;
    if (qtd <= 0) return;

    // Calcula o custo unitário do produto
    const valorTotal = parseFloat(row.dataset.valorTotal) || 0;
    const totalValorItensNFe = allRows.reduce((sum, el) => sum + parseFloat(el.dataset.valorTotal), 0);
    
    const proporcao = totalValorItensNFe > 0 ? valorTotal / totalValorItensNFe : 0;
    const freteItem = proporcao * (parseFloat(row.dataset.freteTotal) || 0);
    const seguroItem = proporcao * (parseFloat(row.dataset.seguroTotal) || 0);
    const outrosItem = proporcao * (parseFloat(row.dataset.outrosTotal) || 0);
    const descItem = proporcao * (parseFloat(row.dataset.descTotal) || 0);
    const impostos = parseFloat(row.dataset.impostos) || 0;

    const custoTotal = (valorTotal + impostos + freteItem + seguroItem + outrosItem - descItem);
    const custoUnit = custoTotal / qtd;

    // Calcula o rateio de custos fixos por unidade
    const fixedCostPerUnit = monthlySalesQty > 0 ? fixedCosts / monthlySalesQty : 0;

    row.dataset.custoUnitario = custoUnit;
    row.querySelector(".cell-custo-unitario").textContent = formatCurrency(custoUnit);

    // Calcula os preços usando Margem de Contribuição
    const precos = {};
    
    Object.keys(comissoes).forEach(plataforma => {
        // Custo variável total = custo unitário + frete do canal
        const variableCost = custoUnit + fretes[plataforma];
        
        // Adiciona o custo fixo unitário
        const totalCostWithFixed = variableCost + fixedCostPerUnit;
        
        // MC efetiva = MC desejada - comissão do canal
        const effectiveContributionMargin = contributionMargin - comissoes[plataforma];
        
        if (effectiveContributionMargin <= 0 || effectiveContributionMargin >= 1) {
            // Se a margem efetiva for inválida, usa um preço mínimo
            precos[plataforma] = totalCostWithFixed * 2;
        } else {
            precos[plataforma] = totalCostWithFixed / (1 - effectiveContributionMargin);
        }
    });

    // Atualiza os preços na interface
    Object.keys(precos).forEach(plataforma => {
        const span = row.querySelector(`.cell-preco-${plataforma} span`);
        if (span) {
            span.textContent = formatCurrency(precos[plataforma]);
            // classList para manipular classes CSS.
            if (precos[plataforma] < custoUnit) {
                span.classList.add("bg-danger", "text-white", "p-1", "rounded");
            } else {
                span.classList.remove("bg-danger", "text-white", "p-1", "rounded");
            }
        }
    });
}

// Substitua a função recalculateRow existente por esta versão que escolhe o método correto:
function recalculateRow(row) {
    const pricingMethod = getCurrentPricingMethod();
    
    if (pricingMethod === 'contribution_margin') {
        recalculateRowContributionMargin(row);
    } else {
        recalculateRowSimpleMargin(row);
    }
}

// Renomeie a função recalculateRow original para recalculateRowSimpleMargin
function recalculateRowSimpleMargin(row) {
    // Obter os parâmetros de configuração
    const margem = parseFloat(document.querySelector("input[name='margem']").value.replace(',', '.')) / 100 || 0;
    const comissoes = {
        site: parseFloat(document.querySelector("input[name='comissao_site']").value.replace(',', '.')) / 100 || 0,
        ml: parseFloat(document.querySelector("input[name='comissao_ml']").value.replace(',', '.')) / 100 || 0,
        shopee: parseFloat(document.querySelector("input[name='comissao_shopee']").value.replace(',', '.')) / 100 || 0,
    };
    const fretes = {
        site: parseFloat(document.querySelector("input[name='frete_site']").value.replace(',', '.')) || 0,
        ml: parseFloat(document.querySelector("input[name='frete_ml']").value.replace(',', '.')) || 0,
        shopee: parseFloat(document.querySelector("input[name='frete_shopee']").value.replace(',', '.')) || 0,
    };
    
    const qtdInput = row.querySelector("input[name='qtd[]']");
    const qtd = parseFloat(qtdInput.value) || 0;
    if (qtd <= 0) return;

    // data-* attributes são acedidos via `dataset`
    const valorTotal = parseFloat(row.dataset.valorTotal) || 0;
    const totalValorItensNFe = allRows.reduce((sum, el) => sum + parseFloat(el.dataset.valorTotal), 0);
    
    const proporcao = totalValorItensNFe > 0 ? valorTotal / totalValorItensNFe : 0;
    const freteItem = proporcao * (parseFloat(row.dataset.freteTotal) || 0);
    const seguroItem = proporcao * (parseFloat(row.dataset.seguroTotal) || 0);
    const outrosItem = proporcao * (parseFloat(row.dataset.outrosTotal) || 0);
    const descItem = proporcao * (parseFloat(row.dataset.descTotal) || 0);
    const impostos = parseFloat(row.dataset.impostos) || 0;

    const custoTotal = (valorTotal + impostos + freteItem + seguroItem + outrosItem - descItem);
    const custoUnit = custoTotal / qtd;

    row.dataset.custoUnitario = custoUnit;
    row.querySelector(".cell-custo-unitario").textContent = formatCurrency(custoUnit);

    const custoUnitComMargem = custoUnit * (1 + margem);
    
    const precos = {
        site: (1 - comissoes.site) !== 0 ? (custoUnitComMargem + fretes.site) / (1 - comissoes.site) : 0,
        ml: (1 - comissoes.ml) !== 0 ? (custoUnitComMargem + fretes.ml) / (1 - comissoes.ml) : 0,
        shopee: (1 - comissoes.shopee) !== 0 ? (custoUnitComMargem + fretes.shopee) / (1 - comissoes.shopee) : 0,
    };

    Object.keys(precos).forEach(plataforma => {
        const span = row.querySelector(`.cell-preco-${plataforma} span`);
        if (span) {
            span.textContent = formatCurrency(precos[plataforma]);
            // classList para manipular classes CSS.
            if (precos[plataforma] < custoUnit) {
                span.classList.add("bg-danger", "text-white", "p-1", "rounded");
            } else {
                span.classList.remove("bg-danger", "text-white", "p-1", "rounded");
            }
        }
    });
}

// Modifique a função saveChangesViaAjax para incluir os novos parâmetros:
function getParametros() {
    const params = {};
    const pricingMethod = getCurrentPricingMethod();
    
    // Adiciona o método de precificação
    params['pricing_method'] = pricingMethod;
    
    if (pricingMethod === 'contribution_margin') {
        // Parâmetros para Margem de Contribuição
        params['contribution_margin'] = document.querySelector("input[name='contribution_margin']").value;
        params['fixed_costs'] = document.querySelector("input[name='fixed_costs']").value;
        params['monthly_sales_qty'] = document.querySelector("input[name='monthly_sales_qty']").value;
    } else {
        // Parâmetros para Margem Simples
        params['margem'] = document.querySelector("input[name='margem']").value;
    }
    
    // Parâmetros comuns
    document.querySelectorAll("input[name^='comissao_'], input[name^='frete_']").forEach(input => {
        params[input.name] = input.value;
    });
    
    return params;
}

// Adicione este listener ao attachEventListeners() para o seletor de método na sidebar:
const methodSelector = document.getElementById("pricing_method_selector");
if (methodSelector) {
    methodSelector.addEventListener("change", function() {
        recalculateAllRows();
        saveParametersToLocalStorage();
    });
}