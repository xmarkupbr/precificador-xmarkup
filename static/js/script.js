// ===== VARIÁVEIS GLOBAIS =====
let allRows = [];
let filteredRows = [];
let currentPage = 1;
let rowsPerPage = 15;
let tableSort = null;

// ===== FUNÇÕES UTILITÁRIAS =====
function formatCurrency(value) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);
}

function parseCurrency(text) {
  return parseFloat(text.replace(/[R$\s.]/g, "").replace(",", ".")) || 0;
}

function isValidNumber(value) {
  return !isNaN(value) && isFinite(value) && value >= 0;
}

// ===== CÁLCULOS DE PREÇOS =====
function getParametros() {
  return {
    margem: parseFloat($("input[name=\"margem\"]").val()) / 100 || 0,
    comissoes: {
      site: parseFloat($("input[name=\"comissao_site\"]").val()) / 100 || 0,
      ml: parseFloat($("input[name=\"comissao_ml\"]").val()) / 100 || 0,
      shopee: parseFloat($("input[name=\"comissao_shopee\"]").val()) / 100 || 0,
      magalu: parseFloat($("input[name=\"comissao_magalu\"]").val()) / 100 || 0,
    },
    fretes: {
      site: parseFloat($("input[name=\"frete_site\"]").val()) || 0,
      ml: parseFloat($("input[name=\"frete_ml\"]").val()) || 0,
      shopee: parseFloat($("input[name=\"frete_shopee\"]").val()) || 0,
      magalu: parseFloat($("input[name=\"frete_magalu\"]").val()) || 0,
    }
  };
}

function recalculateRow(row) {
  const params = getParametros();
  const qtd = parseFloat(row.find("input[name=\"qtd[]\"]").val()) || 0;
  
  if (qtd <= 0) return;

  const valorTotal = parseFloat(row.data("valor-total")) || 0;
  const impostos = parseFloat(row.data("impostos")) || 0;
  const freteTotal = parseFloat(row.data("frete-total")) || 0;
  const seguroTotal = parseFloat(row.data("seguro-total")) || 0;
  const outrosTotal = parseFloat(row.data("outros-total")) || 0;
  const descTotal = parseFloat(row.data("desc-total")) || 0;

  const custoTotal = valorTotal + impostos + freteTotal + seguroTotal + outrosTotal - descTotal;
  const custoUnit = custoTotal / qtd;

  // Atualiza o data attribute e a célula de custo unitário
  row.data("custo-unitario", custoUnit);
  row.find(".cell-custo-unitario").text(formatCurrency(custoUnit));

  const custoUnitComMargem = custoUnit * (1 + params.margem);

  const precos = {
    site: (1 - params.comissoes.site) !== 0 ? (custoUnitComMargem + params.fretes.site) / (1 - params.comissoes.site) : 0,
    ml: (1 - params.comissoes.ml) !== 0 ? (custoUnitComMargem + params.fretes.ml) / (1 - params.comissoes.ml) : 0,
    shopee: (1 - params.comissoes.shopee) !== 0 ? (custoUnitComMargem + params.fretes.shopee) / (1 - params.comissoes.shopee) : 0,
    magalu: (1 - params.comissoes.magalu) !== 0 ? (custoUnitComMargem + params.fretes.magalu) / (1 - params.comissoes.magalu) : 0,
  };

  // Atualiza as células de preço
  Object.keys(precos).forEach(plataforma => {
    const cell = row.find(`.cell-preco-${plataforma}`);
    const span = cell.find("span");
    span.text(formatCurrency(precos[plataforma]));

    // Remove tooltip existente
    const tooltip = bootstrap.Tooltip.getInstance(span[0]);
    if (tooltip) {
      tooltip.dispose();
    }

    // Atualiza a classe de alerta de preço
    if (precos[plataforma] < custoUnit) {
      span.removeClass().addClass("bg-danger text-white fw-bold alerta-preco");
      span.attr("data-bs-toggle", "tooltip");
      span.attr("data-bs-title", "Preço abaixo do custo!");
      // Reinicializa o tooltip
      new bootstrap.Tooltip(span[0], { trigger: "hover" });
    } else {
      span.removeClass().addClass("");
      span.removeAttr("data-bs-toggle");
      span.removeAttr("data-bs-title");
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
  let totalQtd = 0;
  let custoTotal = 0;
  let totais = { site: 0, ml: 0, shopee: 0, magalu: 0 };
  let count = 0;

  $("#tabela-produtos tbody tr:visible").each(function() {
    const row = $(this);
    const qtd = parseFloat(row.find("input[name=\"qtd[]\"]").val()) || 0;
    const custoUnit = parseFloat(row.data("custo-unitario")) || 0;
    
    totalQtd += qtd;
    custoTotal += custoUnit * qtd;

    count++;

    // Calcula totais por plataforma
    ["site", "ml", "shopee", "magalu"].forEach(plataforma => {
      const precoText = row.find(`.cell-preco-${plataforma} span`).text();
      const preco = parseCurrency(precoText);
      totais[plataforma] += preco * qtd;
    });
  });

  // Atualiza o resumo na interface
  $("#resumo-qtd-total").text(totalQtd.toFixed(0));
  $("#resumo-custo-total").text(formatCurrency(custoTotal));
  
  $("#resumo-site-total").text(formatCurrency(totais.site));
  $("#resumo-site-media").text(formatCurrency(count > 0 ? totais.site / totalQtd : 0));
  
  $("#resumo-ml-total").text(formatCurrency(totais.ml));
  $("#resumo-ml-media").text(formatCurrency(count > 0 ? totais.ml / totalQtd : 0));
  
  $("#resumo-shopee-total").text(formatCurrency(totais.shopee));
  $("#resumo-shopee-media").text(formatCurrency(count > 0 ? totais.shopee / totalQtd : 0));
  
  $("#resumo-magalu-total").text(formatCurrency(totais.magalu));
  $("#resumo-magalu-media").text(formatCurrency(count > 0 ? totais.magalu / totalQtd : 0));
}

// ===== PAGINAÇÃO =====
function initPagination() {
  allRows = $("#tabela-produtos tbody tr").toArray();
  filteredRows = [...allRows];
  updatePagination();
  showPage(1);
  console.log("Paginação inicializada com", allRows.length, "linhas");
}

function updatePagination() {
  const numPages = Math.ceil(filteredRows.length / rowsPerPage);
  const paginationContainer = $("#pagination");
  paginationContainer.empty();

  if (numPages <= 1) {
    updateTableInfo();
    return;
  }

  // Botão anterior
  paginationContainer.append(`
    <li class="page-item ${currentPage === 1 ? "disabled" : ""}">
      <a class="page-link" href="#" data-page="${currentPage - 1}">Anterior</a>
    </li>
  `);

  // Páginas numeradas
  for (let i = 1; i <= numPages; i++) {
    if (i === 1 || i === numPages || (i >= currentPage - 2 && i <= currentPage + 2)) {
      paginationContainer.append(`
        <li class="page-item ${i === currentPage ? "active" : ""}">
          <a class="page-link" href="#" data-page="${i}">${i}</a>
        </li>
      `);
    } else if (i === currentPage - 3 || i === currentPage + 3) {
      paginationContainer.append("<li class=\"page-item disabled\"><span class=\"page-link\">...</span></li>");
    }
  }

  // Botão próximo
  paginationContainer.append(`
    <li class="page-item ${currentPage === numPages ? "disabled" : ""}">
      <a class="page-link" href="#" data-page="${currentPage + 1}">Próximo</a>
    </li>
  `);

  updateTableInfo();
}

function showPage(page) {
  const numPages = Math.ceil(filteredRows.length / rowsPerPage);
  if (page < 1 || page > numPages) return;

  currentPage = page;
  const start = (page - 1) * rowsPerPage;
  const end = start + rowsPerPage;

  // Esconde todas as linhas
  $(allRows).hide();
  
  // Mostra apenas as linhas da página atual
  filteredRows.slice(start, end).forEach(row => {
    $(row).show();
  });

  updatePagination();
  console.log(`Mostrando página ${page}: linhas ${start} a ${end-1} de ${filteredRows.length} filtradas`);
}

function updateTableInfo() {
  const start = (currentPage - 1) * rowsPerPage + 1;
  const end = Math.min(currentPage * rowsPerPage, filteredRows.length);
  const total = filteredRows.length;
  
  $("#table-info").text(`Mostrando ${start}-${end} de ${total} produtos`);
}

// ===== BUSCA =====
function filterTable(searchTerm) {
  console.log("Função filterTable chamada com termo:", searchTerm);
  
  const term = searchTerm.toLowerCase().trim();
  
  if (!term) {
    console.log("Termo vazio, mostrando todas as linhas");
    filteredRows = [...allRows];
  } else {
    console.log("Filtrando linhas com termo:", term);
    filteredRows = allRows.filter(row => {
      // Busca no código (input)
      const codigo = $(row).find("input[name='codigo[]']").val().toLowerCase();
      // Busca no nome (input)
      const nome = $(row).find("input[name='nome[]']").val().toLowerCase();
      // Busca na série NF-e (texto da célula)
      const nfe = $(row).find("td:first").text().toLowerCase();
      
      const match = codigo.includes(term) || nome.includes(term) || nfe.includes(term);
      console.log(`Linha: código="${codigo}", nome="${nome}", nfe="${nfe}", match=${match}`);
      return match;
    });
  }
  
  console.log(`Filtro resultou em ${filteredRows.length} de ${allRows.length} linhas`);
  
  currentPage = 1;
  showPage(1);
  updateResumo();
}

// ===== VALIDAÇÃO =====
function validateNumericInput(input) {
  const value = parseFloat(input.val());
  const min = parseFloat(input.attr("min")) || 0;
  const max = parseFloat(input.attr("max")) || Infinity;
  
  if (!isValidNumber(value) || value < min || value > max) {
    input.addClass("is-invalid");
    input.siblings(".invalid-feedback").text(`Valor deve ser um número entre ${min} e ${max}`);
    return false;
  } else {
    input.removeClass("is-invalid");
    return true;
  }
}

// ===== INICIALIZAÇÃO =====
$(document).ready(function() {
  console.log("Inicializando aplicação...");
  
  // Verificação de dependências
  if (typeof $ === 'undefined') {
    console.error("jQuery não foi carregado!");
    alert("Erro: jQuery não foi carregado. Recarregue a página.");
    return;
  }
  
  if (typeof html2canvas === 'undefined') {
    console.error("html2canvas não foi carregado!");
  }
  
  if (typeof jspdf === 'undefined') {
    console.error("jsPDF não foi carregado!");
  }
  
  // Inicialização de plugins
  if (document.getElementById("tabela-produtos")) {
    if (typeof Tablesort !== 'undefined') {
      tableSort = new Tablesort(document.getElementById("tabela-produtos"));
      console.log("Tablesort inicializado com sucesso");
    } else {
      console.error("Tablesort não foi carregado!");
    }
    initPagination();
  }

  // Tooltips
  const tooltipTriggerList = [].slice.call(document.querySelectorAll("[data-bs-toggle=\"tooltip\"]"));
  tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl, { trigger: "hover" });
  });

  // Toasts
  const toastElList = [].slice.call(document.querySelectorAll(".toast"));
  const toastList = toastElList.map(function (toastEl) {
    return new bootstrap.Toast(toastEl, { autohide: true, delay: 5000 });
  });
  toastList.forEach(toast => toast.show());

  // ===== EVENT LISTENERS =====

  // Paginação
  $(document).on("click", "#pagination a", function(e) {
    e.preventDefault();
    const page = parseInt($(this).data("page"));
    if (!isNaN(page)) {
      showPage(page);
    }
  });

  // Busca
  $("#busca-produto").on("input", function() {
    console.log("Event listener de busca disparado");
    const searchTerm = $(this).val();
    console.log("Valor do campo de busca:", searchTerm);
    filterTable(searchTerm);
  });

  $("#btn-clear-busca").on("click", function() {
    console.log("Botão limpar busca clicado");
    $("#busca-produto").val("");
    filterTable("");
  });

  // Edição in-place
  $(document).on("change", ".editable-cell", function() {
    const input = $(this);
    const row = input.closest("tr");
    
    if (input.hasClass("qtd-input")) {
      if (validateNumericInput(input)) {
        input.addClass("cell-edited");
        recalculateRow(row);
        updateResumo();
      }
    } else {
      input.addClass("cell-edited");
    }
  });

  // Parâmetros globais
  $(document).on("change", ".param-global", function() {
    const input = $(this);
    if (validateNumericInput(input)) {
      recalculateAllRows();
    }
  });

  // Validação em tempo real
  $(document).on("input", ".required-field", function() {
    const input = $(this);
    if (input.attr("type") === "number") {
      validateNumericInput(input);
    } else if (input.val().trim()) {
      input.removeClass("is-invalid");
    }
  });

  // Validação de formulário
  $("form").on("submit", function(event) {
    let isValid = true;
    
    $(this).find(".required-field").each(function() {
      const input = $(this);
      
      if (!input.val().trim()) {
        input.addClass("is-invalid");
        input.siblings(".invalid-feedback").text("Este campo é obrigatório.");
        isValid = false;
      } else if (input.attr("type") === "number") {
        if (!validateNumericInput(input)) {
          isValid = false;
        }
      } else {
        input.removeClass("is-invalid");
      }
    });

    if (!isValid) {
      event.preventDefault();
      event.stopPropagation();
    } else {
      // Mostra spinner para operações que recarregam a página
      if (event.originalEvent.submitter && 
          (event.originalEvent.submitter.id === "btn-processar" || 
           (event.originalEvent.submitter.name === "acao" && event.originalEvent.submitter.value === "atualizar"))) {
        $("#spinner-overlay").css("display", "flex");
      }
    }
  });

  // Exportação PDF
  $("#btn-exportar-pdf").on("click", function() {
    console.log("Botão PDF clicado");
    
    // Verificação de dependências
    if (typeof html2canvas === 'undefined') {
      alert("Erro: Biblioteca html2canvas não foi carregada. Recarregue a página e tente novamente.");
      return;
    }
    
    if (typeof jspdf === 'undefined') {
      alert("Erro: Biblioteca jsPDF não foi carregada. Recarregue a página e tente novamente.");
      return;
    }
    
    const areaPdf = document.getElementById("area-pdf");
    if (!areaPdf) {
      alert("Erro: Área de PDF não encontrada.");
      return;
    }
    
    console.log("Iniciando captura da tela...");
    areaPdf.classList.add("exportando-pdf");
    
    html2canvas(areaPdf, { 
      scrollY: -window.scrollY, 
      scale: 2,
      useCORS: true,
      allowTaint: true,
      logging: true
    }).then(function(canvas) {
      console.log("Captura concluída, gerando PDF...");
      
      const imgData = canvas.toDataURL("image/png");
      const pdf = new jspdf.jsPDF({ orientation: "landscape", unit: "mm", format: "a4" });
      const pageWidth = pdf.internal.pageSize.getWidth();
      const pageHeight = pdf.internal.pageSize.getHeight();
      
      let imgWidth = pageWidth;
      let imgHeight = (canvas.height * pageWidth) / canvas.width;
      
      if (imgHeight > pageHeight) {
        imgHeight = pageHeight;
        imgWidth = (canvas.width * pageHeight) / canvas.height;
      }
      
      pdf.addImage(imgData, "PNG", 0, 0, imgWidth, imgHeight);
      pdf.save("precos_calculados.pdf");
      
      console.log("PDF gerado com sucesso!");
      areaPdf.classList.remove("exportando-pdf");
    }).catch(function(error) {
      console.error("Erro ao gerar PDF:", error);
      areaPdf.classList.remove("exportando-pdf");
      alert("Erro ao gerar PDF: " + error.message + ". Tente novamente.");
    });
  });

  // Inicialização do resumo se existir
  if ($("#resumo-section").length) {
    updateResumo();
  }
  
  console.log("Aplicação inicializada com sucesso!");
  
  // Teste da busca após inicialização
  setTimeout(function() {
    console.log("Testando campo de busca...");
    const campoBusca = $("#busca-produto");
    console.log("Campo de busca encontrado:", campoBusca.length > 0);
    console.log("Valor atual do campo:", campoBusca.val());
  }, 1000);
});