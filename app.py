import os
import xml.etree.ElementTree as ET
import io
import json
from flask import jsonify
from io import BytesIO
from flask import Flask, render_template, request, flash, send_file, redirect, url_for, session
import pandas as pd
from database import init_app, get_db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
from flask_mail import Mail, Message
# =======================================================
# CORREÇÃO: IMPORTAR E CARREGAR O .ENV PRIMEIRO DE TUDO
# =======================================================
from dotenv import load_dotenv
load_dotenv() 
# =======================================================

# --- CONFIGURAÇÃO DA APLICAÇÃO ---
app = Flask(__name__)
# Agora, ao criar o app, as variáveis do .env já estão disponíveis
app.secret_key = os.environ.get("SECRET_KEY")

# --- CONFIGURAÇÃO DO FLASK-MAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = ('XMarkup Feedback', os.environ.get('MAIL_USERNAME'))

mail = Mail(app)

init_app(app)

# --- CONFIGURAÇÃO DO FLASK-LOGIN ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, faça o login para acessar esta página."
login_manager.login_message_category = "info"

NFE_NAMESPACE = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}

# --- FILTROS E MODELO DE USUÁRIO ---
@app.template_filter("brl")
def format_as_brl(value):
    try:
        float_value = float(value)
        return f"R$ {float_value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return value

@app.template_filter("input_num")
def format_for_input_filter(value):
    try:
        return f"{float(value):.2f}"
    except (ValueError, TypeError):
        return value

class User(UserMixin):
    def __init__(self, id, email, password, nome_completo):
        self.id = id
        self.email = email
        self.password = password
        self.nome_completo = nome_completo

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    user_data = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if user_data:
        return User(
            id=user_data['id'],
            email=user_data['email'],
            password=user_data['password'],
            nome_completo=user_data['nome_completo']
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
            "Mercado Livre (R$)": prices.get("ml", 0), "Shopee (R$)": prices.get("shopee", 0)
        })
        final_products.append(item)
    return final_products

def generate_summary(products):
    if not products: return {}
    summary = {
        "total_qtd": sum(p.get("Qtd", 0) for p in products),
        "custo_total": sum(p.get("Custo Unitário (R$)", 0) * p.get("Qtd", 0) for p in products),
    }
    channels = ["Preço Venda Site (R$)", "Mercado Livre (R$)", "Shopee (R$)"]
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
        email = request.form.get('email')
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')
        nome_completo = request.form.get('nome_completo')
        empresa = request.form.get('empresa')
        telefone = request.form.get('telefone')
        ramo_atividade = request.form.get('ramo_atividade')
        marketplaces_list = request.form.getlist('marketplaces')
        marketplaces = ','.join(marketplaces_list)
        if password != password_confirm:
            flash('As senhas não coincidem. Por favor, tente novamente.', 'danger')
            return redirect(url_for('register'))
        db = get_db()
        user_exists = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if user_exists:
            flash('Este email já está cadastrado. Por favor, faça o login.', 'warning')
            return redirect(url_for('login'))
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        sql_query = '''
            INSERT INTO users (email, password, nome_completo, empresa, telefone, ramo_atividade, marketplaces)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        '''
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
    db = get_db()
    thirty_days_ago = datetime.now() - timedelta(days=30)
    contagem_recente = db.execute(
        "SELECT COUNT(id) FROM precificacoes WHERE user_id = ? AND criado_em > ?",
        (current_user.id, thirty_days_ago)
    ).fetchone()[0]
    limite_atingido = contagem_recente >= 5

    if request.method == "POST":
        if limite_atingido:
            flash("Você atingiu o limite de 5 precificações nos últimos 30 dias.", "danger")
            return redirect(url_for('dashboard'))

        form_params = request.form.to_dict()
        try:
            xml_files = request.files.getlist("xmlfiles")
            if not xml_files or xml_files[0].filename == '':
                flash("Por favor, selecione ao menos um arquivo XML.", "danger")
                return redirect(url_for('precificador'))

            plataformas = ['site', 'ml', 'shopee']
            margem = float(form_params.get("margem", "0").replace(',', '.')) / 100
            comissoes = {p: float(form_params.get(f"comissao_{p}", "0").replace(',', '.')) / 100 for p in plataformas}
            fretes = {p: float(form_params.get(f"frete_{p}", "0").replace(',', '.')) for p in plataformas}
            raw_products = [prod for xml_file in xml_files for prod in process_nfe_file(xml_file)]
            final_products = calculate_product_prices(raw_products, margem, comissoes, fretes)
            
            dados_json = json.dumps(final_products)
            parametros_json = json.dumps(form_params)
            
            cursor = db.cursor()
            cursor.execute("INSERT INTO precificacoes (user_id, dados_json, parametros_json) VALUES (?, ?, ?)",
                           (current_user.id, dados_json, parametros_json))
            new_id = cursor.lastrowid
            db.commit()
            return redirect(url_for('ver_precificacao', prec_id=new_id))
        except ValueError as e:
            flash(f"Erro nos dados enviados: {e}", "danger")
            return redirect(url_for('precificador'))
        except Exception as e:
            flash(f"Ocorreu um erro inesperado: {e}", "danger")
            return redirect(url_for('precificador'))

    user_settings = db.execute('SELECT * FROM users WHERE id = ?', (current_user.id,)).fetchone()
    parametros = {
        'margem': user_settings['default_margem'],
        'comissao_site': user_settings['default_comissao_site'],
        'frete_site': user_settings['default_frete_site'],
        'comissao_ml': user_settings['default_comissao_ml'],
        'frete_ml': user_settings['default_frete_ml'],
        'comissao_shopee': user_settings['default_comissao_shopee'],
        'frete_shopee': user_settings['default_frete_shopee'],
    }
    return render_template(
        "precificador.html", 
        parametros=parametros,
        limite_atingido=limite_atingido, 
        contagem_recente=contagem_recente
    )

@app.route('/editar', methods=["POST"])
@login_required
def editar():
    precificacao_id = session.get('precificacao_id')
    if not precificacao_id:
        flash("Sessão expirada. Por favor, processe um XML novamente.", "danger")
        return redirect(url_for('precificador'))
    flash("Ação não suportada. Use o botão 'Guardar Alterações'.", "warning")
    return redirect(url_for('ver_precificacao', prec_id=precificacao_id))

@app.route('/api/precificacao/<int:prec_id>/salvar', methods=['POST'])
@login_required
def salvar_precificacao(prec_id):
    db = get_db()
    prec_data = db.execute(
        'SELECT id FROM precificacoes WHERE id = ? AND user_id = ?',
        (prec_id, current_user.id)
    ).fetchone()
    if prec_data is None:
        return jsonify({'status': 'error', 'message': 'Precificação não encontrada ou acesso negado.'}), 404
    data = request.json
    produtos_enviados = data.get('produtos')
    parametros_enviados = data.get('parametros')
    if not produtos_enviados or not parametros_enviados:
        return jsonify({'status': 'error', 'message': 'Dados incompletos.'}), 400
    try:
        dados_atualizados_json = json.dumps(produtos_enviados)
        parametros_atualizados_json = json.dumps(parametros_enviados)
        db.execute("UPDATE precificacoes SET dados_json = ?, parametros_json = ? WHERE id = ?", 
                   (dados_atualizados_json, parametros_atualizados_json, prec_id))
        db.commit()
        return jsonify({'status': 'success', 'message': 'Alterações guardadas com sucesso!'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Ocorreu um erro: {str(e)}'}), 500

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    db_precificacoes = db.execute(
        'SELECT id, criado_em, dados_json FROM precificacoes WHERE user_id = ? ORDER BY criado_em DESC',
        (current_user.id,)
    ).fetchall()
    kpis = {'custo_total': 0, 'receita_total': 0, 'lucro_total': 0, 'total_itens': 0}
    receita_por_canal = {'Meu Site': 0, 'Mercado Livre': 0, 'Shopee': 0}
    for row in db_precificacoes:
        dados = json.loads(row['dados_json'])
        for produto in dados:
            custo = produto.get('Custo Unitário (R$)', 0) * produto.get('Qtd', 0)
            kpis['custo_total'] += custo
            kpis['total_itens'] += produto.get('Qtd', 0)
            receita_site = produto.get('Preço Venda Site (R$)', 0) * produto.get('Qtd', 0)
            receita_ml = produto.get('Mercado Livre (R$)', 0) * produto.get('Qtd', 0)
            receita_shopee = produto.get('Shopee (R$)', 0) * produto.get('Qtd', 0)
            receita_por_canal['Meu Site'] += receita_site
            receita_por_canal['Mercado Livre'] += receita_ml
            receita_por_canal['Shopee'] += receita_shopee
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
    db = get_db()
    user_data = db.execute(
        'SELECT * FROM users WHERE id = ?', (current_user.id,)
    ).fetchone()
    return render_template('perfil.html', user=user_data)

@app.route('/perfil/editar', methods=['GET', 'POST'])
@login_required
def editar_perfil():
    db = get_db()
    if request.method == 'POST':
        nome_completo = request.form.get('nome_completo')
        empresa = request.form.get('empresa')
        telefone = request.form.get('telefone')
        ramo_atividade = request.form.get('ramo_atividade')
        marketplaces_list = request.form.getlist('marketplaces')
        marketplaces = ','.join(marketplaces_list)
        db.execute(
            '''UPDATE users SET 
               nome_completo = ?, empresa = ?, telefone = ?, ramo_atividade = ?, marketplaces = ?
               WHERE id = ?''',
            (nome_completo, empresa, telefone, ramo_atividade, marketplaces, current_user.id)
        )
        db.commit()
        flash('Perfil atualizado com sucesso!', 'success')
        return redirect(url_for('perfil'))
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
    msg = Message(
        subject=f"Novo Feedback de {email or 'Anônimo'}",
        recipients=[os.environ.get('MAIL_USERNAME')]
    )
    msg.body = f"""
    Um novo feedback foi enviado através do XMarkup.
    
    De: {email or 'Não informado'}
    Mensagem:
    -----------------
    {message}
    -----------------
    """
    try:
        mail.send(msg)
        flash("Obrigado pelo seu feedback! A sua mensagem foi enviada.", "success")
    except Exception as e:
        print(f"ERRO AO ENVIAR E-MAIL DE FEEDBACK: {e}")
        flash("Ocorreu um erro ao tentar enviar a sua mensagem. Por favor, tente novamente mais tarde.", "danger")
    return redirect(url_for('status'))

def mapear_para_shopee(produtos):
    produtos_shopee = []
    for prod in produtos:
        produto_mapeado = {
            '*Nome do Produto': prod.get('Nome'),
            '*Descrição do Produto': prod.get('Nome'),
            '*SKU Principal': prod.get('Código'),
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
    db = get_db()
    prec_data = db.execute(
        'SELECT dados_json FROM precificacoes WHERE id = ? AND user_id = ?',
        (prec_id, current_user.id)
    ).fetchone()
    if prec_data is None:
        flash("Precificação não encontrada.", "danger")
        return redirect(url_for('dashboard'))
    produtos = json.loads(prec_data['dados_json'])
    colunas_para_formatar = [
        'Custo Unitário (R$)', 'Preço Venda Site (R$)', 'Mercado Livre (R$)',
        'Shopee (R$)'
    ]
    for produto in produtos:
        for coluna in colunas_para_formatar:
            if coluna in produto:
                produto[coluna] = round(produto[coluna], 2)
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
    produtos_ml = []
    for prod in produtos:
        produto_mapeado = {
            'Título': prod.get('Nome'),
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
    df.to_csv(output, index=False, sep=';', encoding='utf-8-sig')
    output.seek(0)
    return send_file(
        output,
        download_name="planilha_mercado_livre.csv",
        as_attachment=True,
        mimetype="text/csv"
    )

@app.route('/baixar/historico_completo')
@login_required
def baixar_historico_completo():
    """Gera e envia uma planilha Excel com todas as precificações do usuário."""
    db = get_db()
    db_precificacoes = db.execute(
        'SELECT id, criado_em, dados_json FROM precificacoes WHERE user_id = ? ORDER BY criado_em DESC',
        (current_user.id,)
    ).fetchall()
    if not db_precificacoes:
        flash("Você não possui nenhum histórico para baixar.", "info")
        return redirect(url_for('dashboard'))
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for prec in db_precificacoes:
            prec_id = prec['id']
            criado_em = datetime.strptime(prec['criado_em'], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
            dados = json.loads(prec['dados_json'])
            df = pd.DataFrame(dados)
            sheet_name = f"ID_{prec_id}_{criado_em}"
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    output.seek(0)
    return send_file(
        output,
        download_name="historico_completo_xmarkup.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

if __name__ == "__main__":
    app.run(debug=True)