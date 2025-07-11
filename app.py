import os
import xml.etree.ElementTree as ET
import io
import json
from functools import wraps
import click
from flask.cli import with_appcontext
from io import BytesIO
from flask import Flask, jsonify, render_template, request, flash, send_file, redirect, url_for, session
import pandas as pd
from database import init_app, get_db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
from flask_mail import Mail, Message
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer
from collections import Counter

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")

# --- CONFIGURAÇÃO DO FLASK-MAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = ('XMarkup', os.environ.get('MAIL_USERNAME'))

mail = Mail(app)
init_app(app)

# --- CONFIGURAÇÃO DO FLASK-LOGIN ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, faça o login para acessar esta página."
login_manager.login_message_category = "info"

NFE_NAMESPACE = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}

# --- DECORATORS E HELPERS ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
            flash("Acesso restrito a administradores.", "danger")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def get_user_usage(db, user_id, last_reset_date=None):
    start_date = datetime.now() - timedelta(days=30)
    if last_reset_date:
        if isinstance(last_reset_date, str):
            try:
                reset_date = datetime.strptime(last_reset_date, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                reset_date = datetime.strptime(last_reset_date, '%Y-%m-%d %H:%M:%S')
        else:
            reset_date = last_reset_date
        
        if reset_date and reset_date > start_date:
            start_date = reset_date
            
    count = db.execute(
        "SELECT COUNT(id) FROM precificacoes WHERE user_id = ? AND criado_em > ?",
        (user_id, start_date)
    ).fetchone()[0]
    return count

def send_price_alert_email(user_email, user_nome, items_abaixo_custo, prec_id):
    """Envia um e-mail de alerta quando produtos estão com preço abaixo do custo."""
    try:
        msg = Message(
            subject="Alerta de Precificação - Produtos Abaixo do Custo",
            recipients=[user_email]
        )
        msg.html = render_template(
            'emails/price_alert.html', 
            user_nome=user_nome,
            items=items_abaixo_custo,
            prec_id=prec_id
        )
        mail.send(msg)
    except Exception as e:
        print(f"ERRO AO ENVIAR E-MAIL DE ALERTA DE PREÇO: {e}")

# --- FILTROS DE TEMPLATE ---
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

# --- MODELO DE UTILIZADOR ---
class User(UserMixin):
    def __init__(self, id, email, password, nome_completo, is_admin=False, status_cliente='Safira', precificacao_limit=5, limit_reset_date=None):
        self.id = id
        self.email = email
        self.password = password
        self.nome_completo = nome_completo
        self.is_admin = is_admin
        self.status_cliente = status_cliente
        self.precificacao_limit = precificacao_limit
        self.limit_reset_date = limit_reset_date

    def get_reset_token(self):
        s = URLSafeTimedSerializer(app.config['SECRET_KEY'])
        return s.dumps(self.id, salt='password-reset-salt')

    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        s = URLSafeTimedSerializer(app.config['SECRET_KEY'])
        try:
            user_id = s.loads(token, salt='password-reset-salt', max_age=expires_sec)
        except:
            return None
        db = get_db()
        return db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    user_data = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if user_data:
        keys = user_data.keys()
        return User(
            id=user_data['id'],
            email=user_data['email'],
            password=user_data['password'],
            nome_completo=user_data['nome_completo'],
            is_admin=user_data['is_admin'] if 'is_admin' in keys else False,
            status_cliente=user_data['status_cliente'] if 'status_cliente' in keys else 'Safira',
            precificacao_limit=user_data['precificacao_limit'] if 'precificacao_limit' in keys else 5,
            limit_reset_date=user_data['limit_reset_date'] if 'limit_reset_date' in keys else None
        )
    return None

# --- LÓGICA DE NEGÓCIO ---
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

# --- ROTAS PRINCIPAIS E DE AUTENTICAÇÃO ---
@app.route('/')
def home():
    return render_template('home.html')
    
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        db = get_db()
        user_data = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()

        if user_data and user_data['is_deleted']:
            flash('Esta conta foi excluída e não pode ser acedida. Por favor, entre em contacto com o suporte se achar que isto é um erro.', 'danger')
            return redirect(url_for('login'))

        if not user_data or not check_password_hash(user_data['password'], password):
            flash('Email ou senha inválidos. Por favor, tente novamente.', 'danger')
            return redirect(url_for('login'))
        
        keys = user_data.keys()
        user = User(
            id=user_data['id'],
            email=user_data['email'],
            password=user_data['password'],
            nome_completo=user_data['nome_completo'],
            is_admin=user_data['is_admin'] if 'is_admin' in keys else False,
            status_cliente=user_data['status_cliente'] if 'status_cliente' in keys else 'Safira',
            precificacao_limit=user_data['precificacao_limit'] if 'precificacao_limit' in keys else 5,
            limit_reset_date=user_data['limit_reset_date'] if 'limit_reset_date' in keys else None
        )
        login_user(user)
        return redirect(url_for('dashboard'))
    return render_template('login.html')

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

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sessão terminada com sucesso.', 'info')
    return redirect(url_for('home'))

# --- ROTAS DE RECUPERAÇÃO DE SENHA ---
@app.route('/request_reset_password', methods=['GET', 'POST'])
def request_reset_password():
    if request.method == 'POST':
        email = request.form.get('email')
        db = get_db()
        user_data = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if user_data:
            user = User(id=user_data['id'], email=user_data['email'], password=user_data['password'], nome_completo=user_data['nome_completo'])
            token = user.get_reset_token()
            msg = Message('Redefinição de Senha - XMarkup',
                          recipients=[user.email])
            msg.body = f'''Para redefinir a sua senha, visite o seguinte link:
{url_for('reset_password', token=token, _external=True)}

Se não foi você que fez este pedido, ignore este e-mail. Este link é válido por 30 minutos.
'''
            try:
                mail.send(msg)
                flash('Um e-mail foi enviado com as instruções para redefinir a sua senha.', 'info')
            except Exception as e:
                flash('Ocorreu um erro ao enviar o e-mail. Por favor, tente novamente mais tarde.', 'danger')
                print(f"ERRO DE EMAIL: {e}")
        else:
            flash('Não foi encontrada nenhuma conta com esse e-mail.', 'warning')
        return redirect(url_for('login'))
    return render_template('request_reset.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user_data = User.verify_reset_token(token)
    if not user_data:
        flash('O link de redefinição é inválido ou expirou.', 'warning')
        return redirect(url_for('request_reset_password'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')
        if password != password_confirm:
            flash('As senhas não coincidem.', 'danger')
            return render_template('reset_password.html')
            
        hashed_password = generate_password_hash(password)
        db = get_db()
        db.execute('UPDATE users SET password = ? WHERE id = ?', (hashed_password, user_data['id']))
        db.commit()
        flash('A sua senha foi atualizada! Pode agora fazer o login.', 'success')
        return redirect(url_for('login'))
        
    return render_template('reset_password.html')

# --- ROTAS DA APLICAÇÃO ---
@app.route('/precificador', methods=["GET", "POST"])
@login_required
def precificador():
    db = get_db()
    contagem_recente = get_user_usage(db, current_user.id, current_user.limit_reset_date)
    limite_atingido = contagem_recente >= current_user.precificacao_limit

    if request.method == "POST":
        if limite_atingido:
            flash(f"Você atingiu o seu limite de {current_user.precificacao_limit} precificações.", "danger")
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
        contagem_recente=contagem_recente,
        limite_total=current_user.precificacao_limit
    )

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    
    query_params = [current_user.id]
    date_filter_query = ""
    
    if start_date_str and end_date_str:
        end_date_dt = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1, seconds=-1)
        date_filter_query = "AND p.criado_em BETWEEN ? AND ?"
        query_params.extend([start_date_str, end_date_dt])

    base_query = f"""
        SELECT p.id, p.criado_em, p.dados_json 
        FROM precificacoes p 
        WHERE p.user_id = ? {date_filter_query}
        ORDER BY p.criado_em DESC
    """
    all_precificacoes_raw = db.execute(base_query, tuple(query_params)).fetchall()
    
    search_nfe = request.args.get('search_nfe', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 10 
    
    filtered_precificacoes = []
    if search_nfe:
        for row in all_precificacoes_raw:
            dados = json.loads(row['dados_json'])
            if dados and any(item.get("Série NF-e", "") == search_nfe for item in dados):
                filtered_precificacoes.append(row)
    else:
        filtered_precificacoes = all_precificacoes_raw
        
    total_items = len(filtered_precificacoes)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_precificacoes = filtered_precificacoes[start:end]
    total_pages = (total_items + per_page - 1) // per_page
    
    kpis = {'custo_total': 0, 'receita_total': 0, 'lucro_total': 0, 'total_itens': 0}
    receita_por_canal = {'Meu Site': 0, 'Mercado Livre': 0, 'Shopee': 0}
    
    for row in all_precificacoes_raw:
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
    for row in paginated_precificacoes:
        dados = json.loads(row['dados_json'])
        resumo = generate_summary(dados)
        nfe_num = dados[0].get("Série NF-e", "N/A") if dados else "N/A"
        precificacoes_list.append({
            'id': row['id'],
            'criado_em': datetime.strptime(row['criado_em'], '%Y-%m-%d %H:%M:%S'),
            'nfe': nfe_num,
            'num_produtos': len(dados),
            'custo_total': resumo.get('custo_total', 0)
        })
        
    return render_template(
        'dashboard.html', 
        precificacoes=precificacoes_list, 
        kpis=kpis, 
        chart_data=chart_data,
        page=page,
        total_pages=total_pages,
        search_nfe=search_nfe,
        start_date=start_date_str,
        end_date=end_date_str
    )

@app.route('/precificacao/<int:prec_id>')
@login_required
def ver_precificacao(prec_id):
    db = get_db()
    query = "SELECT dados_json, parametros_json FROM precificacoes WHERE id = ?"
    params = (prec_id,)
    if not getattr(current_user, 'is_admin', False):
        query += " AND user_id = ?"
        params = (prec_id, current_user.id)
    prec_data = db.execute(query, params).fetchone()
    if prec_data is None:
        flash("Precificação não encontrada ou acesso não permitido.", "danger")
        return redirect(url_for('dashboard'))
    page = request.args.get('page', 1, type=int)
    per_page = 20
    produtos_todos = json.loads(prec_data['dados_json'])
    parametros = json.loads(prec_data['parametros_json']) if prec_data['parametros_json'] else {}
    resumo = generate_summary(produtos_todos)
    session['precificacao_id'] = prec_id
    total_items = len(produtos_todos)
    start = (page - 1) * per_page
    end = start + per_page
    produtos_paginados = produtos_todos[start:end]
    total_pages = (total_items + per_page - 1) // per_page
    return render_template(
        'precificador.html', 
        produtos=produtos_paginados,
        resumo=resumo, 
        parametros=parametros,
        page=page,
        total_pages=total_pages,
        prec_id=prec_id
    )

@app.route('/api/precificacao/<int:prec_id>/salvar', methods=['POST'])
@login_required
def salvar_precificacao_ajax(prec_id):
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'Nenhum dado recebido.'}), 400

    produtos_atualizados = data.get('produtos')
    parametros_atualizados = data.get('parametros')

    if not produtos_atualizados or not parametros_atualizados:
        return jsonify({'status': 'error', 'message': 'Dados da requisição estão incompletos.'}), 400

    db = get_db()

    prec_record = db.execute(
        "SELECT id FROM precificacoes WHERE id = ? AND user_id = ?",
        (prec_id, current_user.id)
    ).fetchone()

    if not prec_record:
        return jsonify({'status': 'error', 'message': 'Precificação não encontrada ou acesso não permitido.'}), 403

    items_abaixo_custo = []
    for produto in produtos_atualizados:
        custo_unitario = float(produto.get('Custo Unitário (R$)', 0))
        precos = {
            "Meu Site": float(produto.get('Preço Venda Site (R$)', 0)),
            "Mercado Livre": float(produto.get('Mercado Livre (R$)', 0)),
            "Shopee": float(produto.get('Shopee (R$)', 0))
        }
        for canal, preco_venda in precos.items():
            if preco_venda > 0 and preco_venda < custo_unitario:
                items_abaixo_custo.append({
                    "codigo": produto.get("Código"),
                    "nome": produto.get("Nome"),
                    "custo": custo_unitario,
                    "preco": preco_venda,
                    "canal": canal
                })
    
    if items_abaixo_custo:
        send_price_alert_email(current_user.email, current_user.nome_completo, items_abaixo_custo, prec_id)

    try:
        dados_json_str = json.dumps(produtos_atualizados)
        parametros_json_str = json.dumps(parametros_atualizados)

        db.execute(
            "UPDATE precificacoes SET dados_json = ?, parametros_json = ? WHERE id = ?",
            (dados_json_str, parametros_json_str, prec_id)
        )
        db.commit()

        return jsonify({'status': 'success', 'message': 'Alterações guardadas com sucesso!'})

    except Exception as e:
        print(f"ERRO AO SALVAR PRECIFICACAO (ID: {prec_id}): {e}")
        return jsonify({'status': 'error', 'message': 'Ocorreu um erro interno ao tentar guardar as alterações.'}), 500

@app.route('/perfil')
@login_required
def perfil():
    db = get_db()
    user_data = db.execute(
        'SELECT * FROM users WHERE id = ?', (current_user.id,)
    ).fetchone()
    uso_recente = get_user_usage(db, current_user.id, current_user.limit_reset_date)
    return render_template(
        'perfil.html', 
        user=user_data, 
        uso_recente=uso_recente
    )

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

@app.route('/perfil/excluir', methods=['POST'])
@login_required
def excluir_conta():
    reason = request.form.get('delete_reason')
    
    if not reason or len(reason) < 100:
        flash('É necessário fornecer um motivo com pelo menos 100 caracteres para excluir a conta.', 'danger')
        return redirect(url_for('perfil'))

    db = get_db()
    user_id = current_user.id
    user_email = current_user.email
    user_nome = current_user.nome_completo
    
    db.execute(
        'UPDATE users SET is_deleted = 1, deleted_at = ?, delete_reason = ? WHERE id = ?',
        (datetime.now(), reason, user_id)
    )
    
    db.commit()

    try:
        msg = Message(
            subject=f"Notificação: Conta Excluída - {user_email}",
            recipients=[os.environ.get('MAIL_USERNAME')]
        )
        msg.body = f"""
O utilizador abaixo excluiu a sua conta do XMarkup.

- Nome: {user_nome}
- Email: {user_email}
- Data da Exclusão: {datetime.now().strftime('%d/%m/%Y %H:%M')}

Motivo fornecido:
-----------------
{reason}
-----------------

Pode ver mais detalhes no painel de administração.
"""
        mail.send(msg)
    except Exception as e:
        print(f"ERRO AO ENVIAR E-MAIL DE NOTIFICAÇÃO DE EXCLUSÃO: {e}")

    logout_user()
    
    flash('A sua conta foi excluída com sucesso. Lamentamos vê-lo partir!', 'success')
    return redirect(url_for('home'))
    
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

# --- ROTAS DE ADMIN ---
@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    db = get_db()
    all_users_raw = db.execute("SELECT * FROM users ORDER BY nome_completo").fetchall()
    
    all_users = []
    for user_row in all_users_raw:
        user = dict(user_row)
        keys = user_row.keys()
        reset_date = user_row['limit_reset_date'] if 'limit_reset_date' in keys else None
        user['uso_recente'] = get_user_usage(db, user['id'], reset_date)
        all_users.append(user)

    all_precificacoes = db.execute("""
        SELECT p.id, p.criado_em, p.dados_json, u.nome_completo as user_nome
        FROM precificacoes p JOIN users u ON p.user_id = u.id
        ORDER BY p.criado_em DESC
        LIMIT 10
    """).fetchall()
    
    precificacoes_list = []
    for row in all_precificacoes:
        dados = json.loads(row['dados_json'])
        nfe_num = dados[0].get("Série NF-e", "N/A") if dados else "N/A"
        precificacoes_list.append({
            'id': row['id'],
            'user_nome': row['user_nome'],
            'criado_em': datetime.strptime(row['criado_em'], '%Y-%m-%d %H:%M:%S'),
            'num_produtos': len(dados),
            'nfe': nfe_num,
            'custo_total': generate_summary(dados).get('custo_total', 0)
        })

    kpis = {
        'total_users': len(all_users),
        'total_precificacoes': db.execute("SELECT COUNT(id) FROM precificacoes").fetchone()[0]
    }
    return render_template(
        'admin_dashboard.html', 
        users=all_users, 
        precificacoes=precificacoes_list,
        kpis=kpis
    )

@app.route('/admin/cliente/<int:user_id>')
@login_required
@admin_required
def ver_cliente(user_id):
    db = get_db()
    cliente_raw = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not cliente_raw:
        flash("Cliente não encontrado.", "danger")
        return redirect(url_for('admin_dashboard'))
        
    cliente = dict(cliente_raw)
    
    if cliente.get('deleted_at'):
        try:
            cliente['deleted_at'] = datetime.strptime(cliente['deleted_at'], '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            cliente['deleted_at'] = datetime.strptime(cliente['deleted_at'], '%Y-%m-%d %H:%M:%S')

    historico_raw = db.execute(
        "SELECT id, criado_em, dados_json FROM precificacoes WHERE user_id = ? ORDER BY criado_em DESC", (user_id,)
    ).fetchall()
    
    keys = cliente.keys()
    reset_date = cliente.get('limit_reset_date')
    uso_recente = get_user_usage(db, cliente['id'], reset_date)
    
    historico_list = []
    for row in historico_raw:
        dados = json.loads(row['dados_json'])
        historico_list.append({
            'id': row['id'],
            'criado_em': datetime.strptime(row['criado_em'], '%Y-%m-%d %H:%M:%S'),
            'num_produtos': len(dados)
        })

    return render_template('admin_cliente_detalhes.html', cliente=cliente, historico=historico_list, uso_recente=uso_recente)

@app.route('/admin/cliente/<int:user_id>/update_limit', methods=['POST'])
@login_required
@admin_required
def update_client_limit(user_id):
    try:
        novo_limite = int(request.form.get('novo_limite'))
        if novo_limite < 0:
            flash("O limite não pode ser negativo.", "danger")
        else:
            db = get_db()
            db.execute("UPDATE users SET precificacao_limit = ? WHERE id = ?", (novo_limite, user_id))
            db.commit()
            flash("Limite do cliente atualizado com sucesso!", "success")
    except (ValueError, TypeError):
        flash("Por favor, insira um número válido para o limite.", "danger")
    
    return redirect(url_for('ver_cliente', user_id=user_id))

@app.route('/admin/cliente/<int:user_id>/reset_usage', methods=['POST'])
@login_required
@admin_required
def reset_client_usage(user_id):
    db = get_db()
    now = datetime.now()
    db.execute("UPDATE users SET limit_reset_date = ? WHERE id = ?", (now, user_id))
    db.commit()
    flash("O contador de uso do cliente foi resetado com sucesso!", "success")
    return redirect(url_for('ver_cliente', user_id=user_id))

@app.route('/admin/cliente/<int:user_id>/reactivate', methods=['POST'])
@login_required
@admin_required
def reactivate_client(user_id):
    db = get_db()
    user = db.execute("SELECT nome_completo FROM users WHERE id = ?", (user_id,)).fetchone()

    if not user:
        flash("Cliente não encontrado.", "danger")
        return redirect(url_for('admin_dashboard'))

    db.execute(
        "UPDATE users SET is_deleted = 0, deleted_at = NULL, delete_reason = NULL WHERE id = ?",
        (user_id,)
    )
    db.commit()

    flash(f"A conta de {user['nome_completo']} foi reativada com sucesso!", "success")
    return redirect(url_for('ver_cliente', user_id=user_id))
    
@app.route('/admin/cliente/<int:user_id>/update_status', methods=['POST'])
@login_required
@admin_required
def update_client_status(user_id):
    novo_status = request.form.get('novo_status')
    if novo_status not in ['Safira', 'Esmeralda', 'Diamante']:
        flash("Status inválido selecionado.", "danger")
        return redirect(url_for('ver_cliente', user_id=user_id))

    db = get_db()
    db.execute("UPDATE users SET status_cliente = ? WHERE id = ?", (novo_status, user_id))
    db.commit()
    flash("Status do cliente atualizado com sucesso!", "success")
    return redirect(url_for('ver_cliente', user_id=user_id))

@app.route('/admin/precificacao/<int:prec_id>/resumo')
@login_required
@admin_required
def admin_ver_resumo_precificacao(prec_id):
    db = get_db()
    prec_data = db.execute("""
        SELECT p.id, p.dados_json, p.criado_em, u.nome_completo as user_nome
        FROM precificacoes p JOIN users u ON p.user_id = u.id
        WHERE p.id = ?
    """, (prec_id,)).fetchone()
    if not prec_data:
        flash("Precificação não encontrada.", "danger")
        return redirect(url_for('admin_dashboard'))
    dados = json.loads(prec_data['dados_json'])
    resumo_geral = generate_summary(dados)
    nfe_de_cada_produto = [item.get("Série NF-e", "N/A") for item in dados]
    nfe_counts = Counter(nfe_de_cada_produto)
    nfe_info = sorted(nfe_counts.items())
    criado_em_dt = datetime.strptime(prec_data['criado_em'], '%Y-%m-%d %H:%M:%S')
    return render_template(
        'admin_precificacao_resumo.html',
        prec={
            'id': prec_data['id'],
            'user_nome': prec_data['user_nome'],
            'criado_em': criado_em_dt
        },
        resumo=resumo_geral,
        nfe_info=nfe_info
    )

# --- ROTAS DE DOWNLOAD ---
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
    query = "SELECT dados_json FROM precificacoes WHERE id = ?"
    params = (prec_id,)
    if not getattr(current_user, 'is_admin', False):
        query += " AND user_id = ?"
        params = (prec_id, current_user.id)
    prec_data = db.execute(query, params).fetchone()
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
    query = "SELECT dados_json FROM precificacoes WHERE id = ?"
    params = (prec_id,)
    if not getattr(current_user, 'is_admin', False):
        query += " AND user_id = ?"
        params = (prec_id, current_user.id)
    prec_data = db.execute(query, params).fetchone()
    if prec_data is None:
        flash("Precificação não encontrada ou acesso negado.", "danger")
        return redirect(url_for('dashboard'))
    produtos = json.loads(prec_data['dados_json'])
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
    query = "SELECT dados_json FROM precificacoes WHERE id = ?"
    params = (prec_id,)
    if not getattr(current_user, 'is_admin', False):
        query += " AND user_id = ?"
        params = (prec_id, current_user.id)
    prec_data = db.execute(query, params).fetchone()
    if prec_data is None:
        flash("Precificação não encontrada ou acesso negado.", "danger")
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
    
# --- COMANDO CLI PARA PROMOVER UTILIZADOR A ADMIN ---
@app.cli.command("promote-user")
@click.argument("email")
def promote_user_command(email):
    """Atribui privilégios de administrador a um utilizador existente."""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    
    if user is None:
        print(f"Erro: Utilizador com o e-mail '{email}' não encontrado.")
        return

    if user['is_admin']:
        print(f"Aviso: O utilizador '{email}' já é um administrador.")
        return

    db.execute("UPDATE users SET is_admin = 1 WHERE email = ?", (email,))
    db.commit()
    print(f"Sucesso: O utilizador '{email}' foi promovido a administrador.")
    
if __name__ == "__main__":
    app.run(debug=True)