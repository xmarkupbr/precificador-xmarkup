import time
from datetime import datetime, timedelta
import json
import threading
import sqlite3

class SimpleScrapingScheduler:
    def __init__(self, db_connection, scraper):
        self.db_connection_string = 'database.db'  # Armazena o caminho do banco em vez da conexão
        self.scraper = scraper
        self.running = False
        self.thread = None
        
    def start(self):
        """Inicia o scheduler em uma thread separada"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run)
            self.thread.daemon = True
            self.thread.start()
            print("Scheduler de monitoramento iniciado!")
    
    def stop(self):
        """Para o scheduler"""
        self.running = False
        if self.thread:
            self.thread.join()
        self.scraper.close()
        print("Scheduler de monitoramento parado!")
    
    def _get_db_connection(self):
        """Cria uma nova conexão com o banco de dados para a thread atual"""
        conn = sqlite3.connect(self.db_connection_string)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _run(self):
        """Loop principal do scheduler"""
        while self.running:
            try:
                products = self._get_products_to_update()
                
                if products:
                    print(f"Processando {len(products)} produtos...")
                    for product in products:
                        if not self.running:
                            break
                        self._process_product(product)
                        time.sleep(2)
                
                time.sleep(60)  # Verifica a cada 1 minuto em vez de 5 minutos
                
            except Exception as e:
                print(f"Erro no scheduler: {e}")
                time.sleep(60)
    
    def _get_products_to_update(self):
        """Busca produtos que precisam ser atualizados"""
        try:
            # Cria uma nova conexão para esta thread
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            one_hour_ago = datetime.now() - timedelta(minutes=1)  # Reduzido para 1 minuto para testes
            
            query = """
                SELECT cp.*, c.name as competitor_name
                FROM competitor_products cp
                JOIN competitors c ON cp.competitor_profile_id = c.id
                WHERE cp.last_checked_at < ? OR cp.last_checked_at IS NULL
                ORDER BY cp.last_checked_at ASC
                LIMIT 10
            """
            
            cursor.execute(query, (one_hour_ago,))
            products = [dict(row) for row in cursor.fetchall()]
            
            conn.close()
            return products
            
        except Exception as e:
            print(f"Erro ao buscar produtos: {e}")
            return []
    
    def _process_product(self, product):
        """Processa um produto individual"""
        conn = None
        try:
            print(f"Processando: {product['product_name']} - {product['competitor_name']}")
            
            result = self.scraper.scrape_product(
                product['id'],
                product['product_url'],
                product['marketplace']
            )
            
            if result and result.get('price'):
                # Cria uma nova conexão para esta thread
                conn = self._get_db_connection()
                cursor = conn.cursor()
                
                cursor.execute(
                    "INSERT INTO competitor_price_history (product_id, price, additional_data) VALUES (?, ?, ?)",
                    (product['id'], result['price'], json.dumps(result))
                )
                
                cursor.execute(
                    "UPDATE competitor_products SET last_checked_at = ? WHERE id = ?",
                    (datetime.now(), product['id'])
                )
                
                conn.commit()
                
                print(f"✓ Preço atualizado: R$ {result['price']:.2f}")
                
                self._check_alerts(product, result['price'])
            else:
                print(f"✗ Não foi possível obter o preço")
                
        except Exception as e:
            print(f"Erro ao processar produto {product['id']}: {e}")
        finally:
            if conn:
                conn.close()
    
    def _check_alerts(self, product, new_price):
        """Verifica se deve disparar alertas"""
        conn = None
        try:
            # Cria uma nova conexão para esta thread
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                """SELECT price FROM competitor_price_history 
                   WHERE product_id = ? AND price != ?
                   ORDER BY checked_at DESC LIMIT 1""",
                (product['id'], new_price)
            )
            
            previous = cursor.fetchone()
            
            if previous:
                old_price = previous['price']
                change_percent = ((new_price - old_price) / old_price) * 100
                
                if abs(change_percent) > 5:
                    alert_type = 'price_drop' if change_percent < 0 else 'price_increase'
                    print(f"⚠️  ALERTA: {product['product_name']} - Preço {alert_type}: {change_percent:.1f}%")
                    
        except Exception as e:
            print(f"Erro ao verificar alertas: {e}")
        finally:
            if conn:
                conn.close()