import sqlite3

# Conecta ao banco de dados
conn = sqlite3.connect("database.db")
cursor = conn.cursor()

# Verifica se a coluna já existe
cursor.execute("PRAGMA table_info(competitor_price_history)")
columns = [column[1] for column in cursor.fetchall()]

if 'additional_data' not in columns:
    try:
        cursor.execute("ALTER TABLE competitor_price_history ADD COLUMN additional_data TEXT")
        print("✓ Coluna 'additional_data' adicionada com sucesso à tabela competitor_price_history.")
    except sqlite3.OperationalError as e:
        print("Erro ao adicionar a coluna:", e)
else:
    print("A coluna 'additional_data' já existe.")

# Finaliza a conexão
conn.commit()
conn.close()

print("\nMigração concluída!")