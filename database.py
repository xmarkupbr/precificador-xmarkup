import sqlite3
import click
from flask import g
from flask.cli import with_appcontext

DATABASE_NAME = 'database.db'

def get_db():
    """Cria e retorna uma conexão com o banco de dados para a requisição atual."""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE_NAME)
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    """Fecha a conexão com o banco de dados, se ela existir."""
    db = g.pop('db', None)
    if db is not None:
        db.close()

# ...
def init_db_script():
    """Cria ou atualiza as tabelas do banco de dados."""
    db = get_db() 
    cursor = db.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            
            -- NOVAS COLUNAS DE PERFIL --
            nome_completo TEXT,
            empresa TEXT,
            telefone TEXT,
            ramo_atividade TEXT,
            marketplaces TEXT,
            
            -- COLUNAS DE CONFIGURAÇÃO --
            default_margem REAL DEFAULT 0.0,
            default_comissao_site REAL DEFAULT 0.0,
            default_frete_site REAL DEFAULT 0.0,
            default_comissao_ml REAL DEFAULT 0.0,
            default_frete_ml REAL DEFAULT 0.0,
            default_comissao_shopee REAL DEFAULT 0.0,
            default_frete_shopee REAL DEFAULT 0.0,
            default_comissao_magalu REAL DEFAULT 0.0,
            default_frete_magalu REAL DEFAULT 0.0
        );
    ''')
# ...
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS precificacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            dados_json TEXT NOT NULL,
            parametros_json TEXT, -- Coluna adicionada pelo script add_column.py
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
    ''')
    
    db.commit()
    # Não há db.close() aqui.

@click.command('init-db')
@with_appcontext
def init_db_command():
    """Limpa os dados existentes e cria novas tabelas."""
    init_db_script()
    click.echo('Banco de dados inicializado com sucesso.')

def init_app(app):
    """Regista o comando e a função de limpeza com a aplicação Flask."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)