/**
 * Ficheiro: static/js/script.js
 * Descrição: Script principal da página de precificação, refatorado para usar JavaScript moderno (Vanilla JS) sem jQuery.
 */

// Executa o script quando o conteúdo do HTML estiver completamente carregado.
// Equivalente a $(document).ready()
document.addEventListener('DOMContentLoaded', function() {
    console.log("XMarkup JS: Documento pronto. Iniciando script com Vanilla JS.");

    // --- VARIÁVEIS GLOBAIS ---
    let allRows = [];
    let filteredRows = [];
    let currentPage = 1;
    const rowsPerPage = 50;
    
    // --- FUNÇÕES UTILITÁRIAS ---

    function saveParametersToLocalStorage() {
        const params = getParametros();
        // O localStorage já usa JavaScript nativo.
        localStorage.setItem('xmarkup_params', JSON.stringify(params));
        console.log("Parâmetros guardados no Local Storage.");
    }

    function loadParametersFromLocalStorage() {
        const savedParams = localStorage.getItem('xmarkup_params');
        if (savedParams) {
            console.log("Parâmetros encontrados no Local Storage. A carregar...");
            const params = JSON.parse(savedParams);
            Object.keys(params).forEach(key => {
                // querySelector para selecionar o input pelo nome.
                const input = document.querySelector(`input[name="${key}"]`);
                if (input) {
                    input.value = params[key];
                }
            });
        } else {
            console.log("Nenhum parâmetro encontrado no Local Storage.");
        }
    }
    
    function formatCurrency(value) {
        if (isNaN(value)) return "R$ 0,00";
        // Intl.NumberFormat é a forma nativa e correta de formatar moeda.
        return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);
    }

    function parseCurrency(text) {
        if (typeof text !== 'string') return 0;
        return parseFloat(text.replace(/[R$\s.]/g, "").replace(",", ".")) || 0;
    }

    // --- FUNÇÕES DE CÁLCULO E ATUALIZAÇÃO ---

    function getParametros() {
        const params = {};
        // querySelectorAll para obter todos os inputs que correspondem ao seletor.
        document.querySelectorAll("input[name^='margem'], input[name^='comissao_'], input[name^='frete_']").forEach(input => {
            params[input.name] = input.value;
        });
        return params;
    }

    function recalculateRow(row) {
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

    function recalculateAllRows() {
        document.querySelectorAll("#tabela-produtos tbody tr").forEach(recalculateRow);
        updateResumo();
        updatePriceAlerts();
    }
    
    function updateResumo() {
        let totalQtd = 0;
        let custoTotal = 0;
        const totaisVenda = { site: 0, ml: 0, shopee: 0 };
        const precosMedios = { site: 0, ml: 0, shopee: 0 };
        
        const visibleRows = document.querySelectorAll("#tabela-produtos tbody tr");

        visibleRows.forEach(row => {
            const qtd = parseFloat(row.querySelector("input[name='qtd[]']").value) || 0;
            const custoUnit = parseFloat(row.dataset.custoUnitario) || 0;
            
            totalQtd += qtd;
            custoTotal += custoUnit * qtd;

            Object.keys(totaisVenda).forEach(p => {
                const span = row.querySelector(`.cell-preco-${p} span`);
                const preco = span ? parseCurrency(span.textContent) : 0;
                totaisVenda[p] += preco * qtd;
                precosMedios[p] += preco;
            });
        });

        const numTotalItens = visibleRows.length;
        document.getElementById("resumo-qtd-total").textContent = totalQtd.toFixed(0);
        document.getElementById("resumo-custo-total").textContent = formatCurrency(custoTotal);

        Object.keys(totaisVenda).forEach(p => {
            document.getElementById(`resumo-${p}-total`).textContent = formatCurrency(totaisVenda[p]);
            document.getElementById(`resumo-${p}-media`).textContent = formatCurrency(numTotalItens > 0 ? precosMedios[p] / numTotalItens : 0);
        });
        updateTableInfo();
    }

    function updatePriceAlerts() {
        document.querySelectorAll("#tabela-produtos tbody tr span").forEach(span => {
            const row = span.closest('tr');
            if (!row) return;

            const custoUnit = parseFloat(row.dataset.custoUnitario) || 0;
            const preco = parseCurrency(span.textContent);

            if (preco < custoUnit && preco > 0) {
                span.setAttribute('data-bs-toggle', 'tooltip');
                span.setAttribute('data-bs-title', 'Preço abaixo do custo!');
            } else {
                span.removeAttribute('data-bs-toggle');
                span.removeAttribute('data-bs-title');
            }
        });
        
        // Reinicializa os tooltips do Bootstrap
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl, { trigger: 'hover' });
        });
    }
    
    // --- LÓGICA DE PAGINAÇÃO E FILTRO ---
    
    function showPage(page) {
        currentPage = page;
        const start = (currentPage - 1) * rowsPerPage;
        const end = start + rowsPerPage;
        
        allRows.forEach(row => row.style.display = 'none'); // Esconde todas
        filteredRows.slice(start, end).forEach(row => row.style.display = ''); // Mostra as da página
        
        updatePaginationControls();
        updateTableInfo();
        updateResumo();
    }

    function updatePaginationControls() {
        const paginationContainer = document.getElementById("pagination");
        paginationContainer.innerHTML = ''; // Limpa a paginação
        const numPages = Math.ceil(filteredRows.length / rowsPerPage);

        if (numPages <= 1) return;

        for (let i = 1; i <= numPages; i++) {
            const pageItem = document.createElement('li');
            pageItem.className = `page-item ${i === currentPage ? 'active' : ''}`;
            pageItem.innerHTML = `<a class="page-link" href="#">${i}</a>`;
            pageItem.addEventListener('click', (e) => {
                e.preventDefault();
                showPage(i);
            });
            paginationContainer.appendChild(pageItem);
        }
    }
    
    function updateTableInfo() {
        const totalRows = document.querySelectorAll("#tabela-produtos tbody tr").length;
        document.getElementById("table-info").textContent = `Mostrando ${totalRows} de ${totalRows} produtos`;
    }

    function filterTable(searchTerm) {
        const term = searchTerm.toLowerCase().trim();
        if (!term) {
            filteredRows = [...allRows];
        } else {
            filteredRows = allRows.filter(row => {
                const codigo = row.querySelector("input[name='codigo[]']").value.toLowerCase();
                const nome = row.querySelector("input[name='nome[]']").value.toLowerCase();
                return codigo.includes(term) || nome.includes(term);
            });
        }
        showPage(1); // Volta para a primeira página após o filtro
    }

    // --- AJAX E TOASTS ---
    
    function saveChangesViaAjax() {
        const btn = document.getElementById("btn-salvar-ajax");
        const originalText = btn.innerHTML;
        const precId = btn.dataset.precId;

        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>A Guardar...';

        const produtos = [];
        document.querySelectorAll("#tabela-produtos tbody tr").forEach(row => {
            produtos.push({
                'Série NF-e': row.cells[0].textContent,
                'valor_total': row.dataset.valorTotal,
                'impostos': row.dataset.impostos,
                'frete_total': row.dataset.freteTotal,
                'seguro_total': row.dataset.seguroTotal,
                'outros_total': row.dataset.outrosTotal,
                'desc_total': row.dataset.descTotal,
                'Código': row.querySelector("input[name='codigo[]']").value,
                'Nome': row.querySelector("input[name='nome[]']").value,
                'Qtd': parseFloat(row.querySelector("input[name='qtd[]']").value),
                'Custo Unitário (R$)': parseFloat(row.dataset.custoUnitario),
                'Preço Venda Site (R$)': parseCurrency(row.querySelector('.cell-preco-site span').textContent),
                'Mercado Livre (R$)': parseCurrency(row.querySelector('.cell-preco-ml span').textContent),
                'Shopee (R$)': parseCurrency(row.querySelector('.cell-preco-shopee span').textContent),
            });
        });

        const parametros = getParametros();

        // fetch já é JavaScript nativo.
        fetch(`/api/precificacao/${precId}/salvar`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ produtos, parametros }),
        })
        .then(response => response.json())
        .then(data => {
            showToast(data.message, data.status === 'success' ? 'success' : 'danger');
        })
        .catch(error => {
            console.error('Erro:', error);
            showToast('Erro de comunicação com o servidor.', 'danger');
        })
        .finally(() => {
            btn.disabled = false;
            btn.innerHTML = originalText;
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
        
        let toastContainer = document.querySelector(".toast-container");
        if (!toastContainer) {
             toastContainer = document.createElement('div');
             toastContainer.className = "toast-container position-fixed top-0 end-0 p-3";
             toastContainer.style.zIndex = "1060";
             document.body.appendChild(toastContainer);
        }
        
        // Adiciona o novo toast no container.
        toastContainer.insertAdjacentHTML('beforeend', toastHtml);
        const newToast = toastContainer.lastElementChild;

        // Garante que o toast seja removido após um tempo
        setTimeout(() => {
            const toastInstance = bootstrap.Toast.getInstance(newToast);
            if(toastInstance) {
                toastInstance.hide();
            } else {
                newToast.remove();
            }
        }, 5000);
    }

    // --- INICIALIZAÇÃO E EVENT LISTENERS ---

    function attachEventListeners() {
        // Usa delegação de eventos para inputs dinâmicos
        document.body.addEventListener('change', function(event) {
            // Recálculo ao mudar parâmetros globais
            if (event.target.matches('.param-global')) {
                recalculateAllRows();
                saveParametersToLocalStorage();
            }
            // Recálculo ao mudar quantidade de um item
            if (event.target.matches('.qtd-input')) {
                const row = event.target.closest("tr");
                recalculateRow(row);
                updateResumo();
                updatePriceAlerts();
            }
        });
        document.body.addEventListener('click', function(event) {
            const deleteButton = event.target.closest('.btn-excluir-item');
            if (deleteButton) {
                const row = deleteButton.closest('tr');
                // Adiciona uma animação de fade-out para suavidade
                row.style.transition = 'opacity 0.3s ease-out';
                row.style.opacity = '0';
                setTimeout(() => {
                    row.remove();
                    recalculateAllRows(); // Recalcula tudo após remover o item
                }, 300);
            }
        });
        
        // Busca
        const buscaInput = document.getElementById("busca-produto");
        if(buscaInput) {
            buscaInput.addEventListener("input", () => filterTable(buscaInput.value));
        }

        // Exportar para PDF
        const btnExportarPdf = document.getElementById("btn-exportar-pdf");
        if(btnExportarPdf) {
            btnExportarPdf.addEventListener("click", function() {
                // A biblioteca jsPDF precisa ser carregada na página
                const { jsPDF } = window.jspdf;
                const doc = new jsPDF({ orientation: 'landscape' });
                doc.autoTable({ html: '#tabela-produtos' });
                doc.save('precificacao_xmarkup.pdf');
            });
        }
        
        // Guardar alterações via AJAX
        const btnSalvarAjax = document.getElementById("btn-salvar-ajax");
        if(btnSalvarAjax) {
            btnSalvarAjax.addEventListener("click", function(event) {
                event.preventDefault();
                saveChangesViaAjax();
            });
        }
    }
    
    function initializeResultsPage() {
        console.log("XMarkup JS: Inicializando página de resultados.");
        loadParametersFromLocalStorage();
        // Converte NodeList para Array para usar métodos como slice() e filter()
        allRows = Array.from(document.querySelectorAll("#tabela-produtos tbody tr"));
        filteredRows = [...allRows];
        attachEventListeners();
        showPage(1); // Exibe a primeira página
        updateResumo();
        updatePriceAlerts();
    }
    
    // --- PONTO DE ENTRADA ---
    
    // Verifica se estamos na página de resultados (se a tabela existe)
    if (document.getElementById("tabela-produtos")) {
        initializeResultsPage();
    }
    
    // Se estiver na página inicial (formulário de parâmetros)
    const formParam = document.getElementById("form-param");
    if (formParam) {
        loadParametersToLocalStorage();
        // Adiciona listener para guardar os parâmetros ao alterá-los.
        formParam.querySelectorAll("input[name^='margem'], input[name^='comissao_'], input[name^='frete_']").forEach(input => {
            input.addEventListener("change", saveParametersToLocalStorage);
        });
    }
});
document.addEventListener('DOMContentLoaded', function() {
    // ... (todo o seu código JS existente)

    // --- LÓGICA PARA O MODAL DE EXCLUSÃO DE CONTA ---
    const deleteModal = document.getElementById('deleteAccountModal');
    if (deleteModal) {
        const reasonTextarea = document.getElementById('delete_reason');
        const confirmDeleteBtn = document.getElementById('confirmDeleteBtn');
        const charCounter = document.getElementById('charCounter');
        const minChars = 100;

        reasonTextarea.addEventListener('input', function() {
            const currentLength = reasonTextarea.value.length;
            
            // Atualiza o contador de caracteres
            charCounter.textContent = `${currentLength} / ${minChars} caracteres`;

            // Ativa ou desativa o botão de exclusão
            if (currentLength >= minChars) {
                confirmDeleteBtn.disabled = false;
                charCounter.classList.remove('text-muted');
                charCounter.classList.add('text-success');
            } else {
                confirmDeleteBtn.disabled = true;
                charCounter.classList.remove('text-success');
                charCounter.classList.add('text-muted');
            }
        });
    }
    const formRegistro = document.getElementById('form-registro');
    if (formRegistro) {
        const passwordInput = document.getElementById('password');
        const passwordConfirmInput = document.getElementById('password_confirm');
        const passwordFeedback = document.getElementById('password-feedback');
        const submitButton = document.getElementById('btn-criar-conta');

        const validatePasswords = () => {
            const pass = passwordInput.value;
            const confirmPass = passwordConfirmInput.value;
            
            // Requisitos da senha: mínimo 8 caracteres, 1 letra, 1 número, 1 símbolo
            const passwordRegex = /^(?=.*[A-Za-z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$/;

            let isValid = true;

            // 1. Validar a força da senha principal
            if (!passwordRegex.test(pass)) {
                passwordInput.classList.remove('is-valid');
                passwordInput.classList.add('is-invalid');
                isValid = false;
            } else {
                passwordInput.classList.remove('is-invalid');
                passwordInput.classList.add('is-valid');
            }

            // 2. Validar se a confirmação está preenchida e coincide
            if (confirmPass === "") {
                passwordConfirmInput.classList.remove('is-valid', 'is-invalid');
                passwordFeedback.textContent = '';
                isValid = false;
            } else if (pass !== confirmPass) {
                passwordConfirmInput.classList.remove('is-valid');
                passwordConfirmInput.classList.add('is-invalid');
                passwordFeedback.textContent = 'As senhas não coincidem.';
                isValid = false;
            } else {
                passwordConfirmInput.classList.remove('is-invalid');
                passwordConfirmInput.classList.add('is-valid');
            }

            // Ativa ou desativa o botão de submissão
            submitButton.disabled = !isValid;
        };

        passwordInput.addEventListener('input', validatePasswords);
        passwordConfirmInput.addEventListener('input', validatePasswords);
    }
});
