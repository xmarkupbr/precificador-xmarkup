$(document).ready(function() {
    console.log("XMarkup JS: Documento pronto. Iniciando script.");

    function saveParametersToLocalStorage() {
        const params = getParametros();
        localStorage.setItem('xmarkup_params', JSON.stringify(params));
        console.log("Parâmetros guardados no Local Storage.");
    }

    function loadParametersFromLocalStorage() {
        const savedParams = localStorage.getItem('xmarkup_params');
        if (savedParams) {
            console.log("Parâmetros encontrados no Local Storage. A carregar...");
            const params = JSON.parse(savedParams);
            Object.keys(params).forEach(key => {
                $(`input[name="${key}"]`).val(params[key]);
            });
        } else {
            console.log("Nenhum parâmetro encontrado no Local Storage.");
        }
    }

    function formatCurrency(value) {
        if (isNaN(value)) return "R$ 0,00";
        return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);
    }

    function parseCurrency(text) {
        if (typeof text !== 'string') return 0;
        return parseFloat(text.replace(/[R$\s.]/g, "").replace(",", ".")) || 0;
    }

    function getParametros() {
        const params = {};
        $("input[name^='margem'], input[name^='comissao_'], input[name^='frete_']").each(function() {
            params[this.name] = $(this).val();
        });
        return params;
    }

    function recalculateRow(row) {
        const paramsConfig = {
            margem: parseFloat($("input[name='margem']").val().replace(',', '.')) / 100 || 0,
            comissoes: {
                site: parseFloat($("input[name='comissao_site']").val().replace(',', '.')) / 100 || 0,
                ml: parseFloat($("input[name='comissao_ml']").val().replace(',', '.')) / 100 || 0,
                shopee: parseFloat($("input[name='comissao_shopee']").val().replace(',', '.')) / 100 || 0,
            },
            fretes: {
                site: parseFloat($("input[name='frete_site']").val().replace(',', '.')) || 0,
                ml: parseFloat($("input[name='frete_ml']").val().replace(',', '.')) || 0,
                shopee: parseFloat($("input[name='frete_shopee']").val().replace(',', '.')) || 0,
            }
        };
        const qtd = parseFloat($(row).find("input[name='qtd[]']").val()) || 0;
        if (qtd <= 0) return;

        const valorTotal = parseFloat($(row).data("valor-total")) || 0;
        const totalValorItensNFe = allRows.reduce((sum, el) => sum + parseFloat($(el).data("valor-total")), 0);
        
        const proporcao = totalValorItensNFe > 0 ? valorTotal / totalValorItensNFe : 0;
        const freteItem = proporcao * (parseFloat($(row).data("frete-total")) || 0);
        const seguroItem = proporcao * (parseFloat($(row).data("seguro-total")) || 0);
        const outrosItem = proporcao * (parseFloat($(row).data("outros-total")) || 0);
        const descItem = proporcao * (parseFloat($(row).data("desc-total")) || 0);
        const impostos = parseFloat($(row).data("impostos")) || 0;

        const custoTotal = (valorTotal + impostos + freteItem + seguroItem + outrosItem - descItem);
        const custoUnit = custoTotal / qtd;

        $(row).data("custo-unitario", custoUnit);
        $(row).find(".cell-custo-unitario").text(formatCurrency(custoUnit));

        const custoUnitComMargem = custoUnit * (1 + paramsConfig.margem);
        
        const precos = {
            site: (1 - paramsConfig.comissoes.site) !== 0 ? (custoUnitComMargem + paramsConfig.fretes.site) / (1 - paramsConfig.comissoes.site) : 0,
            ml: (1 - paramsConfig.comissoes.ml) !== 0 ? (custoUnitComMargem + paramsConfig.fretes.ml) / (1 - paramsConfig.comissoes.ml) : 0,
            shopee: (1 - paramsConfig.comissoes.shopee) !== 0 ? (custoUnitComMargem + paramsConfig.fretes.shopee) / (1 - paramsConfig.comissoes.shopee) : 0,
        };

        Object.keys(precos).forEach(plataforma => {
            const span = $(row).find(`.cell-preco-${plataforma} span`);
            span.text(formatCurrency(precos[plataforma]));
            if (precos[plataforma] < custoUnit) {
                 span.addClass("bg-danger text-white p-1 rounded");
            } else {
                 span.removeClass("bg-danger text-white p-1 rounded");
            }
        });
    }

    function recalculateAllRows() {
        $("#tabela-produtos tbody tr").each(function() {
            recalculateRow(this);
        });
        updateResumo();
        updatePriceAlerts();
    }

    function updateResumo() {
        let totalQtd = 0;
        let custoTotal = 0;
        const totaisVenda = { site: 0, ml: 0, shopee: 0 };
        const precosMedios = { site: 0, ml: 0, shopee: 0 };
        
        filteredRows.forEach(row => {
            const qtd = parseFloat($(row).find("input[name='qtd[]']").val()) || 0;
            const custoUnit = parseFloat($(row).data("custo-unitario")) || 0;
            
            totalQtd += qtd;
            custoTotal += custoUnit * qtd;

            Object.keys(totaisVenda).forEach(p => {
                const preco = parseCurrency($(row).find(`.cell-preco-${p} span`).text());
                totaisVenda[p] += preco * qtd;
                precosMedios[p] += preco;
            });
        });

        const numTotalItens = filteredRows.length;
        $("#resumo-qtd-total").text(totalQtd.toFixed(0));
        $("#resumo-custo-total").text(formatCurrency(custoTotal));

        Object.keys(totaisVenda).forEach(p => {
            $(`#resumo-${p}-total`).text(formatCurrency(totaisVenda[p]));
            $(`#resumo-${p}-media`).text(formatCurrency(numTotalItens > 0 ? precosMedios[p] / numTotalItens : 0));
        });
    }

    function updatePriceAlerts() {
        $('[data-bs-toggle="tooltip"]').tooltip('dispose');
        $("#tabela-produtos tbody tr span").each(function() {
            const span = $(this);
            const row = span.closest('tr');
            const custoUnit = parseFloat(row.data('custo-unitario')) || 0;
            const preco = parseCurrency(span.text());

            if (preco < custoUnit && preco > 0) {
                span.attr('data-bs-toggle', 'tooltip');
                span.attr('data-bs-title', 'Preço abaixo do custo!');
            } else {
                span.removeAttr('data-bs-toggle');
                span.removeAttr('data-bs-title');
            }
        });
        $('[data-bs-toggle="tooltip"]').tooltip({ trigger: "hover" });
    }

    function showPage(page) {
        currentPage = page;
        const start = (currentPage - 1) * rowsPerPage;
        const end = start + rowsPerPage;
        
        $(allRows).hide();
        $(filteredRows.slice(start, end)).show();
        
        updatePaginationControls();
        updateTableInfo();
        updateResumo();
    }

    function updatePaginationControls() {
        const paginationContainer = $("#pagination");
        paginationContainer.empty();
        const numPages = Math.ceil(filteredRows.length / rowsPerPage);

        if (numPages <= 1) return;

        for (let i = 1; i <= numPages; i++) {
            const pageItem = $(`<li class="page-item ${i === currentPage ? 'active' : ''}"><a class="page-link" href="#">${i}</a></li>`);
            pageItem.on("click", (e) => { e.preventDefault(); showPage(i); });
            paginationContainer.append(pageItem);
        }
    }
    
    function updateTableInfo() {
        const total = filteredRows.length;
        const start = total > 0 ? (currentPage - 1) * rowsPerPage + 1 : 0;
        const end = Math.min(start + rowsPerPage - 1, total);
        $("#table-info").text(`Mostrando ${start}-${end} de ${total} produtos`);
    }

    function filterTable(searchTerm) {
        const term = searchTerm.toLowerCase().trim();
        if (!term) {
            filteredRows = [...allRows];
        } else {
            filteredRows = allRows.filter(row => {
                const codigo = $(row).find("input[name='codigo[]']").val().toLowerCase();
                const nome = $(row).find("input[name='nome[]']").val().toLowerCase();
                return codigo.includes(term) || nome.includes(term);
            });
        }
        showPage(1);
    }

    function saveChangesViaAjax() {
        const btn = $("#btn-salvar-ajax");
        const originalText = btn.html();
        const precId = btn.data('prec-id');

        btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>A Guardar...');

        const produtos = [];
        $("#tabela-produtos tbody tr").each(function() {
            const row = $(this);
            produtos.push({
                'Série NF-e': row.find('td:first').text(),
                'valor_total': row.data('valor-total'),
                'impostos': row.data('impostos'),
                'frete_total': row.data('frete-total'),
                'seguro_total': row.data('seguro-total'),
                'outros_total': row.data('outros-total'),
                'desc_total': row.data('desc-total'),
                'Código': row.find("input[name='codigo[]']").val(),
                'Nome': row.find("input[name='nome[]']").val(),
                'Qtd': parseFloat(row.find("input[name='qtd[]']").val()),
                'Custo Unitário (R$)': row.data('custo-unitario'),
                'Preço Venda Site (R$)': parseCurrency(row.find('.cell-preco-site span').text()),
                'Mercado Livre (R$)': parseCurrency(row.find('.cell-preco-ml span').text()),
                'Shopee (R$)': parseCurrency(row.find('.cell-preco-shopee span').text()),
            });
        });

        const parametros = getParametros();

        fetch(`/api/precificacao/${precId}/salvar`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ produtos, parametros }),
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                showToast(data.message, 'success');
            } else {
                showToast(data.message, 'danger');
            }
        })
        .catch((error) => {
            console.error('Error:', error);
            showToast('Erro de comunicação com o servidor.', 'danger');
        })
        .finally(() => {
            btn.prop('disabled', false).html(originalText);
        });
    }
    
    function showToast(message, category = 'info') {
        const toastHtml = `
            <div class="toast show align-items-center text-bg-${category} border-0 mb-2" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="d-flex">
                    <div class="toast-body">${message}</div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
            </div>`;
        
        if($(".toast-container").length === 0) {
             $('body').append('<div class="toast-container position-fixed top-0 end-0 p-3" style="z-index: 1060;"></div>');
        }
        const newToast = $(toastHtml);
        $(".toast-container").append(newToast);
        
        setTimeout(() => newToast.fadeOut(500, () => newToast.remove()), 5000);
    }

    function attachEventListeners() {
        $(document).on("change", ".param-global", function() {
            recalculateAllRows();
            saveParametersToLocalStorage();
        });
        $(document).on("change", ".qtd-input", function() {
            const row = $(this).closest("tr");
            recalculateRow(row);
            updateResumo();
            updatePriceAlerts();
        });
        $("#busca-produto").on("input", function() { filterTable($(this).val()); });
        $("#btn-exportar-pdf").on("click", function() {
            const { jsPDF } = window.jspdf;
            const doc = new jsPDF({ orientation: 'landscape' });
            doc.autoTable({ html: '#tabela-produtos' });
            doc.save('precificacao_xmarkup.pdf');
        });
        $("#btn-salvar-ajax").on("click", function(event) {
            event.preventDefault();
            saveChangesViaAjax();
        });
    }
    
    function attachFormValidation(formId) {
         $(document).on("submit", formId, function(event) {
            let isValid = true;
            $(this).find(".required-field").each(function() {
                const input = $(this);
                if (!input.val() || (input.is('input[type="number"]') && parseFloat(input.val()) < 0)) {
                    input.addClass("is-invalid");
                    if(!input.val()){
                         input.siblings(".invalid-feedback").text("Este campo é obrigatório.");
                    } else {
                         input.siblings(".invalid-feedback").text("O valor não pode ser negativo.");
                    }
                    isValid = false;
                } else {
                    input.removeClass("is-invalid");
                }
            });

            if (!isValid) {
                event.preventDefault();
                event.stopPropagation();
                return;
            }
            $("#spinner-overlay").css("display", "flex");
        });
    }

    function initializeResultsPage() {
        console.log("XMarkup JS: Inicializando página de resultados.");
        loadParametersFromLocalStorage();
        allRows = $("#tabela-produtos tbody tr").toArray();
        filteredRows = [...allRows];
        attachEventListeners();
        showPage(1);
        updateResumo();
        updatePriceAlerts();
    }

    let allRows = [];
    let filteredRows = [];
    let currentPage = 1;
    let rowsPerPage = 50;

    if ($("#tabela-produtos").length) {
        initializeResultsPage();
    }
    
    if ($("#form-param").length) {
        loadParametersFromLocalStorage();
        attachFormValidation("#form-param");
        $("#form-param input[name^='margem'], #form-param input[name^='comissao_'], #form-param input[name^='frete_']").on("change", saveParametersToLocalStorage);
    }
});