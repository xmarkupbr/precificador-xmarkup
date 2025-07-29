import sqlite3
from datetime import datetime
import os
import sys

# Adiciona o diretório pai ao path para importar database
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def migrate():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    try:
        print("Iniciando migração do banco de dados...")
        
        # Verifica se as colunas já existem antes de adicionar
        cursor.execute("PRAGMA table_info(competitor_products)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'monitoring_frequency' not in columns:
            cursor.execute("""
                ALTER TABLE competitor_products ADD COLUMN 
                monitoring_frequency INTEGER DEFAULT 720
            """)
            print("✓ Coluna 'monitoring_frequency' adicionada")
        
        # Verifica competitor_price_history
        cursor.execute("PRAGMA table_info(competitor_price_history)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'additional_data' not in columns:
            cursor.execute("""
                ALTER TABLE competitor_price_history ADD COLUMN 
                additional_data TEXT
            """)
            print("✓ Coluna 'additional_data' adicionada")
        
        # Tabela para regras de alerta
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_alert_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_id INTEGER,
                competitor_id INTEGER,
                alert_type TEXT NOT NULL,
                threshold REAL DEFAULT 5.0,
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (product_id) REFERENCES competitor_products (id),
                FOREIGN KEY (competitor_id) REFERENCES competitors (id)
            )
        """)
        print("✓ Tabela 'price_alert_rules' criada")
        
        # Tabela para análises de ML
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                predicted_price REAL NOT NULL,
                prediction_date DATE NOT NULL,
                confidence_score REAL,
                model_version TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES competitor_products (id)
            )
        """)
        print("✓ Tabela 'price_predictions' criada")
        
        # Tabela para notificações
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                alert_type TEXT NOT NULL,
                message TEXT NOT NULL,
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (product_id) REFERENCES competitor_products (id)
            )
        """)
        print("✓ Tabela 'price_notifications' criada")
        
        conn.commit()
        print("\n✅ Migração concluída com sucesso!")
        
    except Exception as e:
        print(f"\n❌ Erro durante a migração: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()