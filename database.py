import sqlite3
import click
from flask import g
from flask.cli import with_appcontext

DATABASE_NAME = 'database.db'

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE_NAME)
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db_script():
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("DROP TABLE IF EXISTS users")
    cursor.execute("DROP TABLE IF EXISTS precificacoes")
    cursor.execute("DROP TABLE IF EXISTS competitor_price_history")
    cursor.execute("DROP TABLE IF EXISTS competitor_products")
    # ADICIONADO: Drop da nova tabela de concorrentes
    cursor.execute("DROP TABLE IF EXISTS competitors")
    
    cursor.execute('''
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            nome_completo TEXT,
            empresa TEXT,
            telefone TEXT,
            ramo_atividade TEXT,
            marketplaces TEXT,
            is_admin BOOLEAN NOT NULL DEFAULT 0,
            
            -- COLUNAS DE GESTÃO DE CLIENTES --
            status_cliente TEXT NOT NULL DEFAULT 'Safira',
            precificacao_limit INTEGER NOT NULL DEFAULT 5,
            limit_reset_date TIMESTAMP,

            -- COLUNAS DE CONFIGURAÇÃO --
            default_margem REAL DEFAULT 0.0,
            default_comissao_site REAL DEFAULT 0.0,
            default_frete_site REAL DEFAULT 0.0,
            default_comissao_ml REAL DEFAULT 0.0,
            default_frete_ml REAL DEFAULT 0.0,
            default_comissao_shopee REAL DEFAULT 0.0,
            default_frete_shopee REAL DEFAULT 0.0,
            
            -- NOVAS COLUNAS PARA EXCLUSÃO DE CONTA --
            is_deleted BOOLEAN NOT NULL DEFAULT 0,
            deleted_at TIMESTAMP,
            delete_reason TEXT
        );
    ''')
    
    cursor.execute('''
        CREATE TABLE precificacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            dados_json TEXT NOT NULL,
            parametros_json TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
    ''')
    
    # ADICIONADO: Nova tabela para perfis de concorrentes
    cursor.execute('''
        CREATE TABLE competitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            website_url TEXT,
            ml_url TEXT,
            shopee_url TEXT,
            amazon_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE(user_id, name) -- Garante que um utilizador não tenha concorrentes com o mesmo nome
        );
    ''')

    # MODIFICADO: Tabela competitor_products para usar competitor_profile_id
    # Remove competitor_name (será obtido via JOIN)
    # Adiciona competitor_profile_id que referencia a nova tabela competitors
    cursor.execute("DROP TABLE IF EXISTS competitor_products") # Remova a tabela antiga antes de recriar
    cursor.execute('''
        CREATE TABLE competitor_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            competitor_profile_id INTEGER NOT NULL, -- REFERENCIA A NOVA TABELA
            product_name TEXT NOT NULL,
            product_url TEXT NOT NULL UNIQUE,
            marketplace TEXT, -- Ex: Mercado Livre, Shopee, Amazon, Site Próprio
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (competitor_profile_id) REFERENCES competitors (id) ON DELETE CASCADE
        );
    ''')

    # Tabela competitor_price_history permanece a mesma
    cursor.execute('''
        CREATE TABLE competitor_price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            price REAL NOT NULL,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES competitor_products (id) ON DELETE CASCADE
        );
    ''')
    
    db.commit()

@click.command('init-db')
@with_appcontext
def init_db_command():
    init_db_script()
    click.echo('Banco de dados foi recriado do zero com sucesso!')

def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)