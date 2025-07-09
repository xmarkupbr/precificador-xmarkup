import sqlite3

# Conecta ao banco de dados
conn = sqlite3.connect("database.db")  # certifique-se de estar no mesmo diretório
cursor = conn.cursor()

# Adiciona a nova coluna, se não existir
try:
    cursor.execute("ALTER TABLE precificacoes ADD COLUMN parametros_json TEXT")
    print("Coluna 'parametros_json' adicionada com sucesso.")
except sqlite3.OperationalError as e:
    print("Erro ao adicionar a coluna:", e)

# Finaliza a conexão
conn.commit()
conn.close()
