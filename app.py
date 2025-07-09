import os
import xml.etree.ElementTree as ET
import io
import json
from io import BytesIO
from flask import Flask, render_template, request, flash, send_file, redirect, url_for, session
import pandas as pd
from database import init_app, get_db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from datetime import datetime

# --- CONFIGURAÇÃO DA APLICAÇÃO ---
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "uma_chave_secreta_muito_forte_e_diferente")
init_app(app)

# --- CONFIGURAÇÃO DO FLASK-LOGIN ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, faça o login para acessar esta página."
login_manager.login_message_category = "info"

NFE_NAMESPACE = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}

# --- FILTRO E MODELO DE USUÁRIO ---
@app.template_filter("brl")
def format_as_brl(value):
    try:
        float_value = float(value)
        return f"R$ {float_value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return value

class User(UserMixin):
    def __init__(self, id, email, password, nome_completo): # Adicionar nome_completo aqui
        self.id = id
        self.email = email
        self.password = password
        self.nome_completo = nome_completo # E aqui

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    user_data = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if user_data:
        # Passar também o nome_completo ao criar o objeto User
        return User(
            id=user_data['id'], 
            email=user_data['email'], 
            password=user_data['password'],
            nome_completo=user_data['nome_completo'] # Adicionar esta linha
        )
    return None

# --- FUNÇÕES DE LÓGICA ---
def process_nfe_file(xml_file):
    try:
        xml_content = xml_file.read()
        xml_buffer = io.BytesIO(xml_content)
        tree = ET.parse(xml_buffer)
    except ET.ParseError:
        raise ValueError(f"O arquivo '{xml_file.filename}' não é um XML válido ou está corrompido.")
    root = tree.getroot()
    products_data = []
    freight_total = float(root.findtext(".//nfe:total/nfe:ICMSTot/nfe:vFrete", default="0.0", namespaces=NFE_NAMESPACE))
    insurance_total = float(root.findtext(".//nfe:total/nfe:ICMSTot/nfe:vSeg", default="0.0", namespaces=NFE_NAMESPACE))
    other_expenses_total = float(root.findtext(".//nfe:total/nfe:ICMSTot/nfe:vOutro", default="0.0", namespaces=NFE_NAMESPACE))
    discount_total = float(root.findtext(".//nfe:total/nfe:ICMSTot/nfe:vDesc", default="0.0", namespaces=NFE_NAMESPACE))
    nfe_number = root.findtext(".//nfe:ide/nfe:nNF", default="", namespaces=NFE_NAMESPACE).strip()
    nfe_series = root.findtext(".//nfe:ide/nfe:serie", default="", namespaces=NFE_NAMESPACE).strip()
    nf_id = f"{nfe_number}/{nfe_series}" if nfe_number and nfe_series else ""
    for det in root.findall(".//nfe:det", NFE_NAMESPACE):
        prod = det.find("nfe:prod", NFE_NAMESPACE)
        imposto = det.find("nfe:imposto", NFE_NAMESPACE)
        if prod is None or imposto is None: continue
        taxes = sum(float(n.text) for n in [
            imposto.find(".//nfe:ICMS//nfe:vICMS", NFE_NAMESPACE),
            imposto.find(".//nfe:PIS//nfe:vPIS", NFE_NAMESPACE),
            imposto.find(".//nfe:COFINS//nfe:vCOFINS", NFE_NAMESPACE),
        ] if n is not None and n.text is not None)
        products_data.append({
            "Série NF-e": nf_id, "Código": prod.findtext("nfe:cProd", default="N/A", namespaces=NFE_NAMESPACE),
            "Nome": prod.findtext("nfe:xProd", default="N/A", namespaces=NFE_NAMESPACE),
            "Qtd": float(prod.findtext("nfe:qCom", default="0.0", namespaces=NFE_NAMESPACE)),
            "valor_total": float(prod.findtext("nfe:vProd", default="0.0", namespaces=NFE_NAMESPACE)),
            "impostos": taxes, "frete_total": freight_total, "seguro_total": insurance_total,
            "outros_total": other_expenses_total, "desc_total": discount_total,
        })
    return products_data

def calculate_product_prices(products_raw, margin, commissions, shipping_costs):
    total_items_value = sum(item["valor_total"] for item in products_raw)
    if not products_raw: return []
    total_freight_nfe = products_raw[0].get('frete_total', 0.0)
    total_insurance_nfe = products_raw[0].get('seguro_total', 0.0)
    total_other_nfe = products_raw[0].get('outros_total', 0.0)
    total_discount_nfe = products_raw[0].get('desc_total', 0.0)
    final_products = []
    for item in products_raw:
        proportion = item["valor_total"] / total_items_value if total_items_value > 0 else 0
        item_freight = proportion * total_freight_nfe
        item_insurance = proportion * total_insurance_nfe
        item_other = proportion * total_other_nfe
        item_discount = proportion * total_discount_nfe
        total_cost = (item["valor_total"] + item["impostos"] + item_freight + item_insurance + item_other - item_discount)
        unit_cost = total_cost / item["Qtd"] if item["Qtd"] > 0 else 0
        cost_with_margin = unit_cost * (1 + margin)
        prices = {channel: (cost_with_margin + shipping_costs.get(channel, 0)) / (1 - commission) if (1 - commission) != 0 else 0
                  for channel, commission in commissions.items()}
        item.update({
            "Custo Unitário (R$)": unit_cost, "Preço Venda Site (R$)": prices.get("site", 0),
            "Mercado Livre (R$)": prices.get("ml", 0), "Shopee (R$)": prices.get("shopee", 0),
            "Magalu (R$)": prices.get("magalu", 0),
        })
        final_products.append(item)
    return final_products

def generate_summary(products):
    if not products: return {}
    summary = {
        "total_qtd": sum(p.get("Qtd", 0) for p in products),
        "custo_total": sum(p.get("Custo Unitário (R$)", 0) * p.get("Qtd", 0) for p in products),
    }
    channels = ["Preço Venda Site (R$)", "Mercado Livre (R$)", "Shopee (R$)", "Magalu (R$)"]
    num_products = len(products)
    for channel in channels:
        total_channel_price = sum(p.get(channel, 0) * p.get("Qtd", 0) for p in products)
        summary[f"{channel}_total"] = total_channel_price
        summary[f"{channel}_media"] = sum(p.get(channel, 0) for p in products) / num_products if num_products > 0 else 0
    return summary

# --- ROTAS DE AUTENTICAÇÃO ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Capturar os dados do formulário (antigos e novos)
        email = request.form.get('email')
        password = request.form.get('password')
        nome_completo = request.form.get('nome_completo')
        empresa = request.form.get('empresa')
        telefone = request.form.get('telefone')
        ramo_atividade = request.form.get('ramo_atividade')
        
        # Para os checkboxes, pegamos uma lista e juntamos com vírgulas
        marketplaces_list = request.form.getlist('marketplaces')
        marketplaces = ','.join(marketplaces_list)

        db = get_db()
        user_exists = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if user_exists:
            flash('Este email já está cadastrado. Por favor, faça o login.', 'warning')
            return redirect(url_for('login'))
            
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        
        # Nova instrução SQL com todas as colunas
        sql_query = '''
            INSERT INTO users (email, password, nome_completo, empresa, telefone, ramo_atividade, marketplaces)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        '''
        # Tupla com os valores na ordem correta
        values = (email, hashed_password, nome_completo, empresa, telefone, ramo_atividade, marketplaces)
        
        db.execute(sql_query, values)
        db.commit()

        flash('Conta criada com sucesso! Por favor, faça o login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        db = get_db()
        user_data = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if not user_data or not check_password_hash(user_data['password'], password):
            flash('Email ou senha inválidos. Por favor, tente novamente.', 'danger')
            return redirect(url_for('login'))
        
        # CORREÇÃO: Passar todos os dados necessários ao criar o objeto User
        user = User(
            id=user_data['id'], 
            email=user_data['email'], 
            password=user_data['password'],
            nome_completo=user_data['nome_completo']
        )
        login_user(user)
        return redirect(url_for('dashboard'))
        
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sessão terminada com sucesso.', 'info')
    return redirect(url_for('home'))

# --- ROTAS PRINCIPAIS DA APLICAÇÃO ---
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/precificador', methods=["GET", "POST"])
@login_required
def precificador():
    if request.method == "POST":
        form_params = request.form.to_dict()
        try:
            xml_files = request.files.getlist("xmlfiles")
            if not xml_files or xml_files[0].filename == '':
                flash("Por favor, selecione ao menos um arquivo XML.", "danger")
                return render_template("precificador.html", parametros=form_params)
            margem = float(form_params.get("margem", "0").replace(',', '.')) / 100
            comissoes = {p: float(form_params.get(f"comissao_{p}", "0").replace(',', '.')) / 100 for p in ['site', 'ml', 'shopee', 'magalu']}
            fretes = {p: float(form_params.get(f"frete_{p}", "0").replace(',', '.')) for p in ['site', 'ml', 'shopee', 'magalu']}
            raw_products = [prod for xml_file in xml_files for prod in process_nfe_file(xml_file)]
            final_products = calculate_product_prices(raw_products, margem, comissoes, fretes)
            dados_json = json.dumps(final_products)
            parametros_json = json.dumps(form_params)
            db = get_db()
            cursor = db.cursor()
            cursor.execute("INSERT INTO precificacoes (user_id, dados_json, parametros_json) VALUES (?, ?, ?)",
                           (current_user.id, dados_json, parametros_json))
            new_id = cursor.lastrowid
            db.commit()
            return redirect(url_for('ver_precificacao', prec_id=new_id))
        except ValueError as e:
            flash(f"Erro nos dados enviados: {e}", "danger")
            return render_template("precificador.html", parametros=form_params)
        except Exception as e:
            flash(f"Ocorreu um erro inesperado: {e}", "danger")
            return render_template("precificador.html", parametros=form_params)

    db = get_db()
    user_settings = db.execute('SELECT * FROM users WHERE id = ?', (current_user.id,)).fetchone()
    parametros = {
        'margem': user_settings['default_margem'],
        'comissao_site': user_settings['default_comissao_site'],
        'frete_site': user_settings['default_frete_site'],
        'comissao_ml': user_settings['default_comissao_ml'],
        'frete_ml': user_settings['default_frete_ml'],
        'comissao_shopee': user_settings['default_comissao_shopee'],
        'frete_shopee': user_settings['default_frete_shopee'],
        'comissao_magalu': user_settings['default_comissao_magalu'],
        'frete_magalu': user_settings['default_frete_magalu']
    }
    return render_template("precificador.html", parametros=parametros)

@app.route('/editar', methods=["POST"])
@login_required
def editar():
    precificacao_id = session.get('precificacao_id')
    if not precificacao_id:
        flash("Sessão expirada. Por favor, processe um XML novamente.", "danger")
        return redirect(url_for('precificador'))

    db = get_db()
    dados_originais_db = db.execute("SELECT dados_json FROM precificacoes WHERE id = ? AND user_id = ?", (precificacao_id, current_user.id)).fetchone()
    if dados_originais_db is None:
        flash("Precificação não encontrada ou não pertence a este usuário.", "danger")
        return redirect(url_for('precificador'))
        
    produtos_originais = json.loads(dados_originais_db['dados_json'])
    form_data = request.form
    form_params = form_data.to_dict()
    try:
        updated_raw_products = []
        codigos, nomes, qtds = form_data.getlist("codigo[]"), form_data.getlist("nome[]"), form_data.getlist("qtd[]")
        for i, row in enumerate(produtos_originais):
            if i < len(codigos):
                row.update({'Código': codigos[i], 'Nome': nomes[i], 'Qtd': float(qtds[i])})
                updated_raw_products.append(row)
        margem = float(form_params.get("margem", "0").replace(',', '.')) / 100
        comissoes = {p: float(form_params.get(f"comissao_{p}", "0").replace(',', '.')) / 100 for p in ['site', 'ml', 'shopee', 'magalu']}
        fretes = {p: float(form_params.get(f"frete_{p}", "0").replace(',', '.')) for p in ['site', 'ml', 'shopee', 'magalu']}
        final_products = calculate_product_prices(updated_raw_products, margem, comissoes, fretes)
        resumo = generate_summary(final_products)
        dados_atualizados_json = json.dumps(final_products)
        parametros_atualizados_json = json.dumps(form_params)
        db.execute("UPDATE precificacoes SET dados_json = ?, parametros_json = ? WHERE id = ?", (dados_atualizados_json, parametros_atualizados_json, precificacao_id))
        db.commit()

        # O bloco de código para "baixar" foi removido daqui, 
        # pois agora ele vive na sua própria rota /baixar/completo/<id>

        flash("Valores atualizados com sucesso!", "success")
        return render_template("precificador.html", produtos=final_products, parametros=form_params, resumo=resumo)
    
    except ValueError:
        flash("Erro de Validação: Verifique se todos os campos contêm apenas números válidos.", "danger")
        return render_template("precificador.html", produtos=produtos_originais, parametros=form_params, resumo=generate_summary(produtos_originais))
    except Exception as e:
        flash(f"Ocorreu um erro inesperado: {e}", "danger")
        return redirect(url_for('precificador'))
    

# --- ROTA DO DASHBOARD ATUALIZADA ---
@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    db_precificacoes = db.execute(
        'SELECT id, criado_em, dados_json FROM precificacoes WHERE user_id = ? ORDER BY criado_em DESC',
        (current_user.id,)
    ).fetchall()
    kpis = {'custo_total': 0, 'receita_total': 0, 'lucro_total': 0, 'total_itens': 0}
    receita_por_canal = {'Meu Site': 0, 'Mercado Livre': 0, 'Shopee': 0, 'Magalu': 0}
    for row in db_precificacoes:
        dados = json.loads(row['dados_json'])
        for produto in dados:
            custo = produto.get('Custo Unitário (R$)', 0) * produto.get('Qtd', 0)
            kpis['custo_total'] += custo
            kpis['total_itens'] += produto.get('Qtd', 0)
            receita_site = produto.get('Preço Venda Site (R$)', 0) * produto.get('Qtd', 0)
            receita_ml = produto.get('Mercado Livre (R$)', 0) * produto.get('Qtd', 0)
            receita_shopee = produto.get('Shopee (R$)', 0) * produto.get('Qtd', 0)
            receita_magalu = produto.get('Magalu (R$)', 0) * produto.get('Qtd', 0)
            receita_por_canal['Meu Site'] += receita_site
            receita_por_canal['Mercado Livre'] += receita_ml
            receita_por_canal['Shopee'] += receita_shopee
            receita_por_canal['Magalu'] += receita_magalu
    kpis['receita_total'] = sum(receita_por_canal.values())
    kpis['lucro_total'] = kpis['receita_total'] - kpis['custo_total']
    chart_data = {
        'labels': list(receita_por_canal.keys()),
        'data': list(receita_por_canal.values())
    }
    precificacoes_list = []
    for row in db_precificacoes[:5]:
        dados = json.loads(row['dados_json'])
        resumo = generate_summary(dados)
        precificacoes_list.append({
            'id': row['id'],
            'criado_em': datetime.strptime(row['criado_em'], '%Y-%m-%d %H:%M:%S'),
            'num_produtos': len(dados),
            'custo_total': resumo.get('custo_total', 0)
        })
    return render_template('dashboard.html', precificacoes=precificacoes_list, kpis=kpis, chart_data=chart_data)
@app.route('/perfil')
@login_required
def perfil():
    # O objeto 'current_user' do Flask-Login já tem o ID do utilizador logado.
    # Usamos esse ID para buscar todos os dados dele no banco de dados.
    db = get_db()
    user_data = db.execute(
        'SELECT * FROM users WHERE id = ?', (current_user.id,)
    ).fetchone()

    # Enviamos o objeto 'user_data' para o template 'perfil.html'
    return render_template('perfil.html', user=user_data)


@app.route('/perfil/editar', methods=['GET', 'POST'])
@login_required
def editar_perfil():
    db = get_db()
    
    # --- LÓGICA PARA SALVAR OS DADOS (MÉTODO POST) ---
    if request.method == 'POST':
        # 1. Capturar os dados do formulário de edição
        nome_completo = request.form.get('nome_completo')
        empresa = request.form.get('empresa')
        telefone = request.form.get('telefone')
        ramo_atividade = request.form.get('ramo_atividade')
        marketplaces_list = request.form.getlist('marketplaces')
        marketplaces = ','.join(marketplaces_list)

        # 2. Escrever e executar a instrução SQL UPDATE para o utilizador atual
        db.execute(
            '''UPDATE users SET 
               nome_completo = ?, empresa = ?, telefone = ?, ramo_atividade = ?, marketplaces = ?
               WHERE id = ?''',
            (nome_completo, empresa, telefone, ramo_atividade, marketplaces, current_user.id)
        )
        db.commit()

        # 3. Enviar uma mensagem de sucesso e redirecionar para a página de perfil
        flash('Perfil atualizado com sucesso!', 'success')
        return redirect(url_for('perfil'))

    # --- LÓGICA PARA MOSTRAR O FORMULÁRIO (MÉTODO GET) ---
    # (Esta parte já existia e continua igual)
    user_data = db.execute(
        'SELECT * FROM users WHERE id = ?', (current_user.id,)
    ).fetchone()
    
    return render_template('editar_perfil.html', user=user_data)

@app.route('/precificacao/<int:prec_id>')
@login_required
def ver_precificacao(prec_id):
    db = get_db()
    prec_data = db.execute(
        'SELECT dados_json, parametros_json FROM precificacoes WHERE id = ? AND user_id = ?',
        (prec_id, current_user.id)
    ).fetchone()
    if prec_data is None:
        flash("Precificação não encontrada ou não pertence a este usuário.", "danger")
        return redirect(url_for('dashboard'))
    produtos = json.loads(prec_data['dados_json'])
    print(f"DEBUG: Carregados {len(produtos)} produtos do banco de dados para o ID de precificação {prec_id}.")
    parametros = json.loads(prec_data['parametros_json']) if prec_data['parametros_json'] else {}
    resumo = generate_summary(produtos)
    session['precificacao_id'] = prec_id
    return render_template('precificador.html', produtos=produtos, resumo=resumo, parametros=parametros)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    db = get_db()
    if request.method == 'POST':
        try:
            params_to_update = {
                'default_margem': float(request.form.get('default_margem', 0)),
                'default_comissao_site': float(request.form.get('default_comissao_site', 0)),
                'default_frete_site': float(request.form.get('default_frete_site', 0)),
                'default_comissao_ml': float(request.form.get('default_comissao_ml', 0)),
                'default_frete_ml': float(request.form.get('default_frete_ml', 0)),
                'default_comissao_shopee': float(request.form.get('default_comissao_shopee', 0)),
                'default_frete_shopee': float(request.form.get('default_frete_shopee', 0)),
                'default_comissao_magalu': float(request.form.get('default_comissao_magalu', 0)),
                'default_frete_magalu': float(request.form.get('default_frete_magalu', 0))
            }
            query = "UPDATE users SET " + ", ".join([f"{key} = ?" for key in params_to_update.keys()]) + " WHERE id = ?"
            values = list(params_to_update.values()) + [current_user.id]
            db.execute(query, tuple(values))
            db.commit()
            flash('Configurações salvas com sucesso!', 'success')
        except ValueError:
            flash('Erro: Por favor, insira apenas números válidos.', 'danger')
        return redirect(url_for('settings'))

    user_settings = db.execute('SELECT * FROM users WHERE id = ?', (current_user.id,)).fetchone()
    return render_template('settings.html', user_settings=user_settings)

@app.route('/status')
def status():
    return render_template('status.html')

@app.route('/feedback', methods=["POST"])
def feedback():
    email = request.form.get('email')
    message = request.form.get('feedback_message')
    print(f"--- NOVO FEEDBACK RECEBIDO ---\nEmail: {email}\nMensagem: {message}\n----------------------------")
    flash("Obrigado pelo seu feedback!", "success")
    return redirect(url_for('status'))

def mapear_para_shopee(produtos):
    """Converte a lista de produtos para o formato da planilha da Shopee."""
    produtos_shopee = []
    for prod in produtos:
        produto_mapeado = {
            '*Nome do Produto': prod.get('Nome'),
            '*Descrição do Produto': prod.get('Nome'),
            '*SKU Principal': prod.get('Código'),
            # --- LINHA CORRIGIDA ABAIXO ---
            'Preço': f"{prod.get('Shopee (R$)', 0):.2f}",
            'Estoque': 100,
            '*Código da Categoria': '',
            '*Marca': 'Marca Padrão',
            '*Material': '',
            '*Peso (kg)': '1',
            '*Canal de Envio': ''
        }
        produtos_shopee.append(produto_mapeado)
    return produtos_shopee

@app.route('/baixar/shopee/<int:prec_id>')
@login_required
def baixar_planilha_shopee(prec_id):
    """Gera e envia a planilha no formato da Shopee."""
    db = get_db()
    prec_data = db.execute(
        'SELECT dados_json FROM precificacoes WHERE id = ? AND user_id = ?',
        (prec_id, current_user.id)
    ).fetchone()

    if prec_data is None:
        flash("Precificação não encontrada.", "danger")
        return redirect(url_for('dashboard'))

    produtos_originais = json.loads(prec_data['dados_json'])
    produtos_mapeados = mapear_para_shopee(produtos_originais)

    df = pd.DataFrame(produtos_mapeados)
    
    output = BytesIO()
    df.to_excel(output, index=False, sheet_name='Anuncios Shopee')
    output.seek(0)
    
    return send_file(
        output,
        download_name="planilha_shopee.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route('/baixar/completo/<int:prec_id>')
@login_required
def baixar_planilha_completa(prec_id):
    """Gera e envia a planilha completa com todos os dados calculados."""
    db = get_db()
    prec_data = db.execute(
        'SELECT dados_json FROM precificacoes WHERE id = ? AND user_id = ?',
        (prec_id, current_user.id)
    ).fetchone()

    if prec_data is None:
        flash("Precificação não encontrada.", "danger")
        return redirect(url_for('dashboard'))

    produtos = json.loads(prec_data['dados_json'])

    # --- NOVO BLOCO PARA FORMATAR OS PREÇOS ---
    # Lista de todas as colunas que contêm valores monetários
    colunas_para_formatar = [
        'Custo Unitário (R$)',
        'Preço Venda Site (R$)',
        'Mercado Livre (R$)',
        'Shopee (R$)',
        'Magalu (R$)'
    ]
    # Percorre cada produto na lista
    for produto in produtos:
        # Para cada produto, percorre as colunas que queremos formatar
        for coluna in colunas_para_formatar:
            if coluna in produto:
                # Arredonda o valor para 2 casas decimais
                produto[coluna] = round(produto[coluna], 2)
    # --- FIM DO NOVO BLOCO ---

    df = pd.DataFrame(produtos)
    
    output = BytesIO()
    df.to_excel(output, index=False, sheet_name='Precificação Completa')
    output.seek(0)
    
    return send_file(
        output,
        download_name="precificacao_completa.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
def mapear_para_ml(produtos):
    """Converte a lista de produtos para o formato da planilha do Mercado Livre."""
    produtos_ml = []
    for prod in produtos:
        produto_mapeado = {
            'Título': prod.get('Nome'),
            # --- LINHA CORRIGIDA ABAIXO ---
            'Preço': f"{prod.get('Mercado Livre (R$)', 0):.2f}",
            'SKU': prod.get('Código'),
            'Estoque': 100,
            'Tipo de anúncio': 'Clássico',
            'Descrição': prod.get('Nome'),
            'GTIN': ''
        }
        produtos_ml.append(produto_mapeado)
    return produtos_ml


@app.route('/baixar/ml/<int:prec_id>')
@login_required
def baixar_planilha_ml(prec_id):
    """Gera e envia a planilha no formato do Mercado Livre."""
    db = get_db()
    prec_data = db.execute(
        'SELECT dados_json FROM precificacoes WHERE id = ? AND user_id = ?',
        (prec_id, current_user.id)
    ).fetchone()

    if prec_data is None:
        flash("Precificação não encontrada.", "danger")
        return redirect(url_for('dashboard'))

    produtos_originais = json.loads(prec_data['dados_json'])
    produtos_mapeados = mapear_para_ml(produtos_originais)

    df = pd.DataFrame(produtos_mapeados)
    
    output = BytesIO()
    # Usamos o encoding 'utf-8-sig' para garantir compatibilidade com acentos no Excel
    df.to_csv(output, index=False, sep=';', encoding='utf-8-sig')
    output.seek(0)
    
    return send_file(
        output,
        download_name="planilha_mercado_livre.csv",
        as_attachment=True,
        mimetype="text/csv"
    ) 

if __name__ == "__main__":
    app.run(debug=True)