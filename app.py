import os
import xml.etree.ElementTree as ET
import io
from io import BytesIO
from flask import Flask, render_template, request, flash, send_file, redirect, url_for
import pandas as pd

# --- CONFIGURAÇÃO DA APLICAÇÃO ---
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "uma_chave_secreta_muito_forte")
NFE_NAMESPACE = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}

# --- FILTRO PARA FORMATAR MOEDA (JINJA2) ---
@app.template_filter("brl")
def format_as_brl(value):
    try:
        float_value = float(value)
        return f"R$ {float_value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return value

# --- FUNÇÃO PARA PROCESSAR O ARQUIVO XML DA NFe ---
def process_nfe_file(xml_file):
    try:
        # Lê o conteúdo do arquivo para a memória para garantir a leitura correta
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

        if prod is None or imposto is None:
            continue

        taxes = sum(float(n.text) for n in [
            imposto.find(".//nfe:ICMS//nfe:vICMS", NFE_NAMESPACE),
            imposto.find(".//nfe:PIS//nfe:vPIS", NFE_NAMESPACE),
            imposto.find(".//nfe:COFINS//nfe:vCOFINS", NFE_NAMESPACE),
        ] if n is not None and n.text is not None)

        products_data.append({
            "Série NF-e": nf_id,
            "Código": prod.findtext("nfe:cProd", default="N/A", namespaces=NFE_NAMESPACE),
            "Nome": prod.findtext("nfe:xProd", default="N/A", namespaces=NFE_NAMESPACE),
            "Qtd": float(prod.findtext("nfe:qCom", default="0.0", namespaces=NFE_NAMESPACE)),
            "valor_total": float(prod.findtext("nfe:vProd", default="0.0", namespaces=NFE_NAMESPACE)),
            "impostos": taxes,
            "frete_total": freight_total,
            "seguro_total": insurance_total,
            "outros_total": other_expenses_total,
            "desc_total": discount_total,
        })
    return products_data

# --- FUNÇÃO PARA CALCULAR OS PREÇOS DE VENDA ---
def calculate_product_prices(products_raw, margin, commissions, shipping_costs):
    total_items_value = sum(item["valor_total"] for item in products_raw)
    total_freight_nfe = products_raw[0].get('frete_total', 0.0) if products_raw else 0.0
    total_insurance_nfe = products_raw[0].get('seguro_total', 0.0) if products_raw else 0.0
    total_other_nfe = products_raw[0].get('outros_total', 0.0) if products_raw else 0.0
    total_discount_nfe = products_raw[0].get('desc_total', 0.0) if products_raw else 0.0

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

        prices = {}
        for channel, commission in commissions.items():
            shipping = shipping_costs.get(channel, 0)
            denominator = 1 - commission
            prices[channel] = (cost_with_margin + shipping) / denominator if denominator != 0 else 0
        
        item.update({
            "Custo Unitário (R$)": unit_cost,
            "Preço Venda Site (R$)": prices.get("site", 0),
            "Mercado Livre (R$)": prices.get("ml", 0),
            "Shopee (R$)": prices.get("shopee", 0),
            "Magalu (R$)": prices.get("magalu", 0),
        })
        final_products.append(item)
        
    return final_products

# --- FUNÇÃO PARA GERAR O RESUMO DOS TOTAIS ---
def generate_summary(products):
    if not products:
        return {}
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


# --- ROTA PRINCIPAL DA APLICAÇÃO ---
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        try:
            xml_files = request.files.getlist("xmlfiles")
            if not xml_files or xml_files[0].filename == '':
                flash("Por favor, selecione ao menos um arquivo XML.", "danger")
                return render_template("index.html")

            form_params = request.form.to_dict()
            margem = float(form_params.get("margem", "0")) / 100
            comissoes = {
                'site': float(form_params.get("comissao_site", "0")) / 100,
                'ml': float(form_params.get("comissao_ml", "0")) / 100,
                'shopee': float(form_params.get("comissao_shopee", "0")) / 100,
                'magalu': float(form_params.get("comissao_magalu", "0")) / 100,
            }
            fretes = {
                'site': float(form_params.get("frete_site", "0")),
                'ml': float(form_params.get("frete_ml", "0")),
                'shopee': float(form_params.get("frete_shopee", "0")),
                'magalu': float(form_params.get("frete_magalu", "0")),
            }

            raw_products = []
            for xml_file in xml_files:
                xml_file.seek(0)
                raw_products.extend(process_nfe_file(xml_file))

            final_products = calculate_product_prices(raw_products, margem, comissoes, fretes)
            resumo = generate_summary(final_products)
            
            # Salva os resultados em um arquivo temporário para edição
            pd.DataFrame(final_products).to_pickle("resultados.pkl")

            flash("XMLs processados com sucesso!", "success")
            return render_template("index.html", produtos=final_products, parametros=form_params, resumo=resumo)

        except (ValueError, TypeError) as e:
            flash(f"Erro nos dados enviados: {e}", "danger")
        except Exception as e:
            flash(f"Ocorreu um erro inesperado: {e}", "danger")
            
        return render_template("index.html")

    return render_template("index.html")

# --- ROTA PARA EDIÇÃO E DOWNLOAD ---
@app.route("/editar", methods=["POST"])
def editar():
    if not os.path.exists("resultados.pkl"):
        flash("Não há dados para editar. Por favor, processe um XML primeiro.", "danger")
        return redirect(url_for("index"))
    
    df_original = pd.read_pickle("resultados.pkl")
    form_data = request.form
    
    # Recria a lista de produtos com os dados editados do formulário
    updated_raw_products = []
    codigos = form_data.getlist("codigo[]")
    nomes = form_data.getlist("nome[]")
    qtds = form_data.getlist("qtd[]")
    
    for i, row in df_original.iterrows():
        if i < len(codigos):
            new_row = row.to_dict()
            new_row['Código'] = codigos[i]
            new_row['Nome'] = nomes[i]
            new_row['Qtd'] = float(qtds[i])
            updated_raw_products.append(new_row)

    # Recalcula os preços com os novos parâmetros
    form_params = form_data.to_dict()
    margem = float(form_params.get("margem", "0")) / 100
    comissoes = { 'site': float(form_params.get("comissao_site", "0")) / 100, 'ml': float(form_params.get("comissao_ml", "0")) / 100, 'shopee': float(form_params.get("comissao_shopee", "0")) / 100, 'magalu': float(form_params.get("comissao_magalu", "0")) / 100 }
    fretes = { 'site': float(form_params.get("frete_site", "0")), 'ml': float(form_params.get("frete_ml", "0")), 'shopee': float(form_params.get("frete_shopee", "0")), 'magalu': float(form_params.get("frete_magalu", "0")) }

    final_products = calculate_product_prices(updated_raw_products, margem, comissoes, fretes)
    resumo = generate_summary(final_products)
    
    # Atualiza o arquivo temporário
    pd.DataFrame(final_products).to_pickle("resultados.pkl")

    acao = form_data.get("acao")
    if acao == "baixar":
        output_df = pd.DataFrame(final_products).drop(columns=[col for col in ['valor_total', 'impostos', 'frete_total', 'seguro_total', 'outros_total', 'desc_total'] if col in final_products[0]])
        output = BytesIO()
        output_df.to_excel(output, index=False, sheet_name='Precificação')
        output.seek(0)
        return send_file(output, download_name="precos_calculados.xlsx", as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else: # Ação padrão é "atualizar"
        flash("Valores atualizados com sucesso!", "success")
        return render_template("index.html", produtos=final_products, parametros=form_params, resumo=resumo)

# --- INICIA A APLICAÇÃO ---
if __name__ == "__main__":
    app.run(debug=True)