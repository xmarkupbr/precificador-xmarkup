#!/usr/bin/env python3
"""
Debug detalhado do Scraping
===========================
"""

import sqlite3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraping.simple_scraper import SimplePriceScraper
import requests
from bs4 import BeautifulSoup

def debug_scraping():
    print("=== DEBUG DE SCRAPING ===\n")
    
    # 1. Pega o primeiro produto
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT cp.*, c.name as competitor_name 
        FROM competitor_products cp
        JOIN competitors c ON cp.competitor_profile_id = c.id
        LIMIT 1
    """)
    product = cursor.fetchone()
    
    if not product:
        print("Nenhum produto encontrado!")
        return
    
    print(f"Produto: {product['product_name']}")
    print(f"URL: {product['product_url']}")
    print(f"Marketplace: {product['marketplace']}")
    print("-" * 50)
    
    # 2. Testa conexão básica
    print("\n1. Testando conexão com a URL...")
    try:
        response = requests.get(product['product_url'], timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        print(f"✓ Status Code: {response.status_code}")
        print(f"✓ Tamanho da resposta: {len(response.text)} caracteres")
    except Exception as e:
        print(f"✗ Erro na conexão: {e}")
        return
    
    # 3. Analisa o HTML
    print("\n2. Analisando HTML...")
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Procura por padrões de preço comuns
    price_patterns = [
        {'tag': 'meta', 'attr': 'itemprop', 'value': 'price'},
        {'tag': 'span', 'class_contains': 'price'},
        {'tag': 'div', 'class_contains': 'price'},
        {'tag': 'span', 'class_contains': 'andes-money-amount__fraction'},  # Mercado Livre
        {'tag': None, 'text_pattern': r'R\$\s*[\d.,]+'},
    ]
    
    for pattern in price_patterns:
        if pattern.get('tag') and pattern.get('attr'):
            # Busca por meta tags
            element = soup.find(pattern['tag'], attrs={pattern['attr']: pattern['value']})
            if element:
                print(f"✓ Encontrado: <{pattern['tag']} {pattern['attr']}='{pattern['value']}'>")
                if element.get('content'):
                    print(f"  Valor: {element['content']}")
                    
        elif pattern.get('tag') and pattern.get('class_contains'):
            # Busca por classes
            elements = soup.find_all(pattern['tag'], class_=lambda x: x and pattern['class_contains'] in x.lower() if x else False)
            if elements:
                print(f"✓ Encontrado {len(elements)} elementos com classe contendo '{pattern['class_contains']}'")
                for i, elem in enumerate(elements[:3]):  # Mostra até 3
                    text = elem.get_text(strip=True)
                    if text:
                        print(f"  [{i+1}] {text[:50]}...")
    
    # 4. Testa o scraper
    print("\n3. Testando SimplePriceScraper...")
    scraper = SimplePriceScraper()
    
    result = scraper.scrape_product(
        product['id'],
        product['product_url'],
        product['marketplace']
    )
    
    if result:
        print("✓ Scraping bem-sucedido!")
        print(f"Resultado: {result}")
    else:
        print("✗ Scraping falhou")
        
        # Tenta identificar o problema
        print("\n4. Possíveis causas:")
        if 'mercadolivre' in product['product_url']:
            print("- Site do Mercado Livre pode ter mudado a estrutura")
            print("- Tente verificar se a classe 'andes-money-amount__fraction' ainda existe")
        elif 'shopee' in product['product_url']:
            print("- Shopee geralmente requer Selenium (JavaScript)")
        else:
            print("- Site pode estar usando JavaScript para carregar preços")
            print("- Estrutura HTML pode ter mudado")
            print("- Site pode estar bloqueando bots")
    
    # 5. Mostra trecho do HTML para análise
    print("\n5. Trecho do HTML (primeiros 2000 caracteres):")
    print("-" * 50)
    print(response.text[:2000])
    print("-" * 50)
    
    scraper.close()
    conn.close()

if __name__ == "__main__":
    debug_scraping()