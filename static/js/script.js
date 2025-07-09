// A função principal agora espera pelo evento 'load' da janela,
// que acontece depois que todos os scripts são carregados e processados.
$(window).on('load', function() {
    console.log("XMarkup JS: Janela completamente carregada. Iniciando script.");

    // Inicialização de plugins do Bootstrap
    try {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function(tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl, { trigger: "hover" });
        });
    } catch (e) { console.error("Erro ao inicializar tooltips:", e); }

    // Inicialização da Tabela
    if (document.getElementById("tabela-produtos")) {
        try {
            if (typeof Tablesort !== 'undefined') {
                new Tablesort(document.getElementById("tabela-produtos"));
                console.log("XMarkup JS: Tablesort inicializado.");
            }
            initPagination();
        } catch(e) { console.error("Erro ao inicializar tabela:", e); }
    }

    // ===== EVENT LISTENERS =====

    // Validação de formulário ao enviar
    $(document).on("submit", "form", function(event) {
        if ($(this).attr('id') === 'form-param' || $(this).attr('id') === 'form-editar') {
            let isValid = true;
            $(this).find(".required-field").each(function() {
                const input = $(this);
                if (!input.val().trim()) {
                    input.addClass("is-invalid");
                    input.siblings(".invalid-feedback").text("Este campo é obrigatório.");
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
            
            const submitter = event.originalEvent.submitter;
            if (submitter && submitter.name === 'acao' && submitter.value === 'baixar') {
                // Não mostra o spinner para download de Excel
            } else {
                $("#spinner-overlay").css("display", "flex");
            }
        }
    });

    // Listener para o botão de exportar PDF
    $(document).on("click", "#btn-exportar-pdf", function() {
        console.log("XMarkup JS: Botão Exportar PDF clicado!");

        if (typeof jspdf === 'undefined' || typeof jspdf.jsPDF.autoTable === 'undefined') {
            alert("Erro: A biblioteca para gerar PDF (jsPDF) não foi carregada. Verifique o console para erros de rede.");
            console.error("Erro: A variável 'jspdf' ou 'jspdf.jsPDF.autoTable' não está definida.");
            return;
        }

        try {
            const { jsPDF } = window.jspdf;
            const doc = new jsPDF({ orientation: 'landscape' });

            doc.setFontSize(18);
            doc.text("Relatório de Precificação - XMarkup", 14, 22);

            const head = [['NF-e', 'Código', 'Nome', 'Qtd', 'Custo Unit.', 'Meu Site', 'Merc. Livre', 'Shopee', 'Magalu']];
            const body = [];
            $("#tabela-produtos tbody tr:visible").each(function() {
                const row = $(this);
                body.push([
                    row.find("td:eq(0)").text().trim(),
                    row.find("td:eq(1) input").val(),
                    row.find("td:eq(2) input").val(),
                    row.find("td:eq(3) input").val(),
                    row.find("td:eq(4)").text().trim(),
                    row.find("td:eq(5) span").text().trim(),
                    row.find("td:eq(6) span").text().trim(),
                    row.find("td:eq(7) span").text().trim(),
                    row.find("td:eq(8) span").text().trim(),
                ]);
            });

            doc.autoTable({
                head: head, body: body, startY: 35, theme: 'grid',
                headStyles: { fillColor: [41, 128, 185], textColor: 255, fontStyle: 'bold' },
                styles: { fontSize: 8, cellPadding: 2 },
                alternateRowStyles: { fillColor: [240, 240, 240] }
            });

            doc.save("precificacao_xmarkup.pdf");
            console.log("XMarkup JS: PDF gerado e download iniciado.");
        } catch (error) {
            console.error("XMarkup JS: Ocorreu um erro ao tentar gerar o PDF:", error);
            alert("Ocorreu um erro ao gerar o PDF. Verifique o console (F12) para mais detalhes.");
        }
    });

    // Outros listeners
    $("#busca-produto").on("input", function() { filterTable($(this).val()); });
    $(".btn-clear-busca").on("click", function() { $("#busca-produto").val("").trigger("input"); });
    $(document).on("change", ".param-global", recalculateAllRows);
    $(document).on("change", ".qtd-input", function() {
        const row = $(this).closest("tr");
        recalculateRow(row);
        updateResumo();
    });
});

// ===== FUNÇÕES DE LÓGICA DA PÁGINA =====
let allRows = [];
let filteredRows = [];
let currentPage = 1;
let rowsPerPage = 15;

function formatCurrency(value) {
    return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);
}

function parseCurrency(text) {
    if (typeof text !== 'string') return 0;
    return parseFloat(text.replace(/[R$\s.]/g, "").replace(",", ".")) || 0;
}

function getParametros() {
    return {
        margem: parseFloat($("input[name='margem']").val()) / 100 || 0,
        comissoes: {
            site: parseFloat($("input[name='comissao_site']").val()) / 100 || 0,
            ml: parseFloat($("input[name='comissao_ml']").val()) / 100 || 0,
            shopee: parseFloat($("input[name='comissao_shopee']").val()) / 100 || 0,
            magalu: parseFloat($("input[name='comissao_magalu']").val()) / 100 || 0,
        },
        fretes: {
            site: parseFloat($("input[name='frete_site']").val()) || 0,
            ml: parseFloat($("input[name='frete_ml']").val()) || 0,
            shopee: parseFloat($("input[name='frete_shopee']").val()) || 0,
            magalu: parseFloat($("input[name='frete_magalu']").val()) || 0,
        }
    };
}

function recalculateRow(row) {
    const params = getParametros();
    const qtd = parseFloat(row.find("input[name='qtd[]']").val()) || 0;
    if (qtd <= 0) return;
    const valorTotal = parseFloat(row.data("valor-total")) || 0;
    const impostos = parseFloat(row.data("impostos")) || 0;
    const freteTotal = parseFloat(row.data("frete-total")) || 0;
    const seguroTotal = parseFloat(row.data("seguro-total")) || 0;
    const outrosTotal = parseFloat(row.data("outros-total")) || 0;
    const descTotal = parseFloat(row.data("desc-total")) || 0;
    const totalValorItensNFe = Array.from($("#tabela-produtos tbody tr"))
                                   .reduce((sum, el) => sum + parseFloat($(el).data("valor-total")), 0);
    const proporcao = totalValorItensNFe > 0 ? valorTotal / totalValorItensNFe : 0;
    const freteItem = proporcao * freteTotal;
    const seguroItem = proporcao * seguroTotal;
    const outrosItem = proporcao * outrosTotal;
    const descItem = proporcao * descTotal;
    const custoTotal = (valorTotal + impostos + freteItem + seguroItem + outrosItem - descItem);
    const custoUnit = custoTotal / qtd;
    row.data("custo-unitario", custoUnit);
    row.find(".cell-custo-unitario").text(formatCurrency(custoUnit));
    const custoUnitComMargem = custoUnit * (1 + params.margem);
    const precos = {
        site: (1 - params.comissoes.site) !== 0 ? (custoUnitComMargem + params.fretes.site) / (1 - params.comissoes.site) : 0,
        ml: (1 - params.comissoes.ml) !== 0 ? (custoUnitComMargem + params.fretes.ml) / (1 - params.comissoes.ml) : 0,
        shopee: (1 - params.comissoes.shopee) !== 0 ? (custoUnitComMargem + params.fretes.shopee) / (1 - params.comissoes.shopee) : 0,
        magalu: (1 - params.comissoes.magalu) !== 0 ? (custoUnitComMargem + params.fretes.magalu) / (1 - params.comissoes.magalu) : 0,
    };
    Object.keys(precos).forEach(plataforma => {
        const cell = row.find(`.cell-preco-${plataforma}`);
        const span = cell.find("span");
        span.text(formatCurrency(precos[plataforma]));
        const tooltip = bootstrap.Tooltip.getInstance(span[0]);
        if (tooltip) tooltip.dispose();
        if (precos[plataforma] < custoUnit) {
            span.addClass("bg-danger text-white fw-bold alerta-preco");
            new bootstrap.Tooltip(span[0], { title: "Preço abaixo do custo!", trigger: "hover" });
        } else {
            span.removeClass("bg-danger text-white fw-bold alerta-preco");
        }
    });
}

function recalculateAllRows() {
    $("#tabela-produtos tbody tr").each(function() {
        recalculateRow($(this));
    });
    updateResumo();
}

function updateResumo() {
    let totalQtd = 0, custoTotal = 0;
    const totais = { site: 0, ml: 0, shopee: 0, magalu: 0 };
    const medias = { site: 0, ml: 0, shopee: 0, magalu: 0 };
    let visibleRows = 0;
    $("#tabela-produtos tbody tr:visible").each(function() {
        const row = $(this);
        const qtd = parseFloat(row.find("input[name='qtd[]']").val()) || 0;
        const custoUnit = parseFloat(row.data("custo-unitario")) || 0;
        totalQtd += qtd;
        custoTotal += custoUnit * qtd;
        visibleRows++;
        Object.keys(totais).forEach(plataforma => {
            const preco = parseCurrency(row.find(`.cell-preco-${plataforma} span`).text());
            totais[plataforma] += preco * qtd;
            medias[plataforma] += preco;
        });
    });
    $("#resumo-qtd-total").text(totalQtd.toFixed(0));
    $("#resumo-custo-total").text(formatCurrency(custoTotal));
    Object.keys(totais).forEach(plataforma => {
        $(`#resumo-${plataforma}-total`).text(formatCurrency(totais[plataforma]));
        $(`#resumo-${plataforma}-media`).text(formatCurrency(visibleRows > 0 ? medias[plataforma] / visibleRows : 0));
    });
}

function initPagination() {
    allRows = $("#tabela-produtos tbody tr").get();
    filteredRows = [...allRows];
    showPage(1);
}

function showPage(page) {
    const numPages = Math.ceil(filteredRows.length / rowsPerPage);
    currentPage = Math.max(1, Math.min(page, numPages));
    const start = (currentPage - 1) * rowsPerPage;
    const end = start + rowsPerPage;
    $(allRows).hide();
    $(filteredRows.slice(start, end)).show();
    updatePaginationControls(numPages);
    updateTableInfo();
}

function updatePaginationControls(numPages) {
    const paginationContainer = $("#pagination");
    paginationContainer.empty();
    if (numPages <= 1) return;
    for (let i = 1; i <= numPages; i++) {
        const pageItem = $(`<li class="page-item ${i === currentPage ? 'active' : ''}"><a class="page-link" href="#">${i}</a></li>`);
        pageItem.on("click", (e) => {
            e.preventDefault();
            showPage(i);
        });
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
    updateResumo();
}
