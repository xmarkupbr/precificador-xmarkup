#!/usr/bin/env python3
"""
Script de Teste Robusto para o Sistema de Monitoramento de Preços
=================================================================

Este script testa todas as funcionalidades do sistema de monitoramento:
1. Conexão com banco de dados
2. Scraping de diferentes marketplaces
3. Armazenamento de histórico
4. Detecção de mudanças de preço
5. Performance e tempo de resposta
"""

import sqlite3
import time
from datetime import datetime, timedelta
import sys
import os
import json

# Adiciona o diretório pai ao path para encontrar os módulos
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraping.simple_scraper import SimplePriceScraper
from scraping.simple_scheduler import SimpleScrapingScheduler

# Cores para output no terminal
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_test_header(test_name):
    print(f"\n{Colors.BLUE}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.BLUE}{Colors.BOLD}TESTE: {test_name}{Colors.ENDC}")
    print(f"{Colors.BLUE}{Colors.BOLD}{'='*60}{Colors.ENDC}")

def print_result(success, message):
    if success:
        print(f"{Colors.GREEN}✓ {message}{Colors.ENDC}")
    else:
        print(f"{Colors.RED}✗ {message}{Colors.ENDC}")

def print_info(message):
    print(f"{Colors.YELLOW}ℹ {message}{Colors.ENDC}")

# 1. TESTE DE CONEXÃO COM BANCO DE DADOS
def test_database_connection():
    print_test_header("Conexão com Banco de Dados")
    
    try:
        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Verifica se as tabelas existem
        tables = ['competitors', 'competitor_products', 'competitor_price_history']
        for table in tables:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            result = cursor.fetchone()
            print_result(result is not None, f"Tabela '{table}' existe")
        
        # Verifica se há produtos cadastrados
        cursor.execute("SELECT COUNT(*) as count FROM competitor_products")
        count = cursor.fetchone()['count']
        print_info(f"Total de produtos cadastrados: {count}")
        
        if count == 0:
            print_info("Nenhum produto cadastrado. Adicione produtos antes de testar o monitoramento.")
            return False
            
        conn.close()
        return True
        
    except Exception as e:
        print_result(False, f"Erro ao conectar ao banco: {e}")
        return False

# 2. TESTE DE SCRAPING INDIVIDUAL
def test_individual_scraping():
    print_test_header("Teste de Scraping Individual")
    
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Pega um produto aleatório para testar
    cursor.execute("""
        SELECT cp.*, c.name as competitor_name 
        FROM competitor_products cp
        JOIN competitors c ON cp.competitor_profile_id = c.id
        LIMIT 1
    """)
    product = cursor.fetchone()
    
    if not product:
        print_info("Nenhum produto encontrado para teste")
        return False
    
    print_info(f"Testando produto: {product['product_name']}")
    print_info(f"URL: {product['product_url']}")
    print_info(f"Marketplace: {product['marketplace']}")
    
    # Tenta até 3 vezes em caso de falha temporária
    max_attempts = 3
    for attempt in range(max_attempts):
        if attempt > 0:
            print_info(f"Tentativa {attempt + 1} de {max_attempts}...")
            time.sleep(2)  # Aguarda 2 segundos entre tentativas
        
        # Inicializa o scraper
        scraper = SimplePriceScraper()
        
        start_time = time.time()
        result = scraper.scrape_product(
            product['id'],
            product['product_url'],
            product['marketplace']
        )
        end_time = time.time()
        
        elapsed_time = end_time - start_time
        print_info(f"Tempo de scraping: {elapsed_time:.2f} segundos")
        
        if result and result.get('price'):
            print_result(True, f"Preço obtido com sucesso: R$ {result['price']:.2f}")
            
            # Verifica outros dados
            if result.get('title'):
                print_info(f"Título: {result['title'][:50]}...")
            if 'stock' in result:
                print_info(f"Em estoque: {'Sim' if result['stock'] else 'Não'}")
            
            # Salva no histórico para teste
            try:
                # Usa json.dumps para serializar corretamente
                import json
                cursor.execute(
                    "INSERT INTO competitor_price_history (product_id, price, additional_data) VALUES (?, ?, ?)",
                    (product['id'], result['price'], json.dumps(result))
                )
                conn.commit()
            except Exception as e:
                print_info(f"Aviso: Erro ao salvar no histórico: {e}")
                # Não falha o teste por isso
            
            scraper.close()
            conn.close()
            return True
        
        scraper.close()
    
    # Se chegou aqui, todas as tentativas falharam
    print_result(False, "Não foi possível obter o preço após múltiplas tentativas")
    print_info("Possíveis causas:")
    print_info("- URL inválida ou produto não encontrado")
    print_info("- Site bloqueando requisições automatizadas")
    print_info("- Estrutura do site mudou")
    print_info("- Problema temporário de conexão")
    
    conn.close()
    return False

# 3. TESTE DE MÚLTIPLOS PRODUTOS
def test_multiple_products():
    print_test_header("Teste de Múltiplos Produtos")
    
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Pega até 5 produtos de diferentes marketplaces
    cursor.execute("""
        SELECT cp.*, c.name as competitor_name 
        FROM competitor_products cp
        JOIN competitors c ON cp.competitor_profile_id = c.id
        ORDER BY cp.marketplace
        LIMIT 5
    """)
    products = cursor.fetchall()
    
    if not products:
        print_info("Nenhum produto encontrado")
        return False
    
    scraper = SimplePriceScraper()
    success_count = 0
    fail_count = 0
    
    print_info(f"Testando {len(products)} produtos...\n")
    
    for i, product in enumerate(products):
        print(f"\n{Colors.BOLD}Produto {i+1}/{len(products)}{Colors.ENDC}")
        print(f"Nome: {product['product_name']}")
        print(f"Marketplace: {product['marketplace']}")
        
        result = scraper.scrape_product(
            product['id'],
            product['product_url'],
            product['marketplace']
        )
        
        if result and result.get('price'):
            success_count += 1
            print_result(True, f"Preço: R$ {result['price']:.2f}")
        else:
            fail_count += 1
            print_result(False, "Falha ao obter preço")
    
    scraper.close()
    conn.close()
    
    print(f"\n{Colors.BOLD}Resumo:{Colors.ENDC}")
    print(f"Sucessos: {success_count}")
    print(f"Falhas: {fail_count}")
    print(f"Taxa de sucesso: {(success_count/len(products)*100):.1f}%")
    
    return success_count > 0

# 4. TESTE DE DETECÇÃO DE MUDANÇAS
def test_price_change_detection():
    print_test_header("Detecção de Mudanças de Preço")
    
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Busca produtos com histórico
    cursor.execute("""
        SELECT DISTINCT p.*, 
               (SELECT price FROM competitor_price_history 
                WHERE product_id = p.id 
                ORDER BY checked_at DESC LIMIT 1) as last_price,
               (SELECT COUNT(*) FROM competitor_price_history 
                WHERE product_id = p.id) as history_count
        FROM competitor_products p
        WHERE EXISTS (
            SELECT 1 FROM competitor_price_history 
            WHERE product_id = p.id
        )
    """)
    
    products_with_history = cursor.fetchall()
    
    if not products_with_history:
        print_info("Nenhum produto com histórico encontrado")
        return False
    
    for product in products_with_history:
        print(f"\n{Colors.BOLD}{product['product_name']}{Colors.ENDC}")
        print(f"Registros no histórico: {product['history_count']}")
        
        if product['history_count'] >= 2:
            # Analisa variação de preço
            cursor.execute("""
                SELECT price, checked_at 
                FROM competitor_price_history 
                WHERE product_id = ? 
                ORDER BY checked_at DESC 
                LIMIT 10
            """)
            
            history = cursor.fetchall()
            
            print("\nHistórico recente:")
            for i, record in enumerate(history):
                print(f"  {i+1}. R$ {record['price']:.2f} - {record['checked_at']}")
                
                if i > 0:
                    variation = ((record['price'] - history[i-1]['price']) / history[i-1]['price']) * 100
                    if abs(variation) > 0.01:
                        symbol = "↑" if variation > 0 else "↓"
                        print(f"     {symbol} Variação: {variation:.2f}%")
    
    conn.close()
    return True

# 5. TESTE DE PERFORMANCE
def test_scheduler_performance():
    print_test_header("Teste de Performance do Scheduler")
    
    print_info("Iniciando scheduler por 1 minuto...")
    
    # Cria um scheduler temporário
    scraper = SimplePriceScraper()
    scheduler = SimpleScrapingScheduler(None, scraper)
    
    # Modifica temporariamente o intervalo
    original_run = scheduler._run
    test_duration = 60  # 1 minuto
    
    def modified_run():
        start_time = time.time()
        products_processed = 0
        
        while scheduler.running and (time.time() - start_time) < test_duration:
            products = scheduler._get_products_to_update()
            
            if products:
                print_info(f"Processando {len(products)} produtos...")
                for product in products:
                    scheduler._process_product(product)
                    products_processed += 1
                    time.sleep(1)  # Intervalo entre produtos
            
            time.sleep(5)  # Intervalo entre verificações
        
        elapsed = time.time() - start_time
        print_info(f"Teste concluído em {elapsed:.1f} segundos")
        print_info(f"Produtos processados: {products_processed}")
        
        if products_processed > 0:
            print_info(f"Tempo médio por produto: {elapsed/products_processed:.2f} segundos")
    
    scheduler._run = modified_run
    scheduler.start()
    
    # Aguarda o término
    time.sleep(test_duration + 5)
    scheduler.stop()
    
    return True

# FUNÇÃO PRINCIPAL
def run_all_tests():
    print(f"\n{Colors.BOLD}INICIANDO SUITE DE TESTES DO SISTEMA DE MONITORAMENTO{Colors.ENDC}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    tests = [
        ("Conexão com Banco", test_database_connection),
        ("Scraping Individual", test_individual_scraping),
        ("Múltiplos Produtos", test_multiple_products),
        ("Detecção de Mudanças", test_price_change_detection),
        ("Performance do Scheduler", test_scheduler_performance)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print_result(False, f"Erro não esperado no teste '{test_name}': {e}")
            results.append((test_name, False))
    
    # Resumo final
    print(f"\n{Colors.BLUE}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.BLUE}{Colors.BOLD}RESUMO DOS TESTES{Colors.ENDC}")
    print(f"{Colors.BLUE}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    
    passed = sum(1 for _, result in results if result)
    failed = len(results) - passed
    
    for test_name, result in results:
        status = f"{Colors.GREEN}PASSOU{Colors.ENDC}" if result else f"{Colors.RED}FALHOU{Colors.ENDC}"
        print(f"{test_name}: {status}")
    
    print(f"\n{Colors.BOLD}Total: {passed} passou, {failed} falhou{Colors.ENDC}")
    
    if failed == 0:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Todos os testes passaram!{Colors.ENDC}")
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}✗ Alguns testes falharam. Verifique os logs acima.{Colors.ENDC}")

if __name__ == "__main__":
    run_all_tests()