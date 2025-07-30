#!/usr/bin/env python3
"""
Simulador de Mudanças de Preço
===============================

Este script simula mudanças de preço inserindo dados fake no histórico
para testar alertas e visualizações.
"""

import sqlite3
import random
from datetime import datetime, timedelta

def simulate_price_history():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    # Pega todos os produtos
    cursor.execute("SELECT id, product_name FROM competitor_products")
    products = cursor.fetchall()
    
    if not products:
        print("Nenhum produto encontrado!")
        return
    
    print(f"Simulando histórico de preços para {len(products)} produtos...")
    
    for product in products:
        product_id = product[0]
        product_name = product[1]
        
        # Gera preço base aleatório
        base_price = random.uniform(10, 500)
        
        # Gera 30 dias de histórico
        for days_ago in range(30, -1, -1):
            timestamp = datetime.now() - timedelta(days=days_ago, hours=random.randint(0, 23))
            
            # Adiciona variação aleatória
            variation = random.uniform(-0.15, 0.15)  # ±15%
            price = base_price * (1 + variation)
            
            # Ocasionalmente faz uma mudança grande
            if random.random() < 0.1:  # 10% de chance
                price *= random.choice([0.7, 1.3])  # 30% para cima ou para baixo
            
            cursor.execute("""
                INSERT INTO competitor_price_history (product_id, price, checked_at, additional_data)
                VALUES (?, ?, ?, ?)
            """, (
                product_id,
                round(price, 2),
                timestamp.strftime('%Y-%m-%d %H:%M:%S.%f'),
                '{"simulated": true, "stock": true}'
            ))
            
            # Atualiza o preço base para próxima iteração
            base_price = price
        
        # Atualiza last_checked_at
        cursor.execute(
            "UPDATE competitor_products SET last_checked_at = ? WHERE id = ?",
            (datetime.now(), product_id)
        )
        
        print(f"✓ {product_name}: 30 dias de histórico criados")
    
    conn.commit()
    conn.close()
    print("\nSimulação concluída!")

if __name__ == "__main__":
    response = input("Isso vai adicionar dados simulados ao histórico. Continuar? (s/n): ")
    if response.lower() == 's':
        simulate_price_history()
    else:
        print("Operação cancelada.")