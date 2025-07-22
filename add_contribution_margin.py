import sqlite3

# Conecta ao banco de dados
conn = sqlite3.connect("database.db")
cursor = conn.cursor()

# Adiciona novas colunas para suportar Margem de Contribuição
try:
    # Coluna para armazenar o método de precificação escolhido
    cursor.execute("ALTER TABLE users ADD COLUMN default_pricing_method TEXT DEFAULT 'simple_margin'")
    print("Coluna 'default_pricing_method' adicionada com sucesso.")
except sqlite3.OperationalError as e:
    print("Erro ao adicionar 'default_pricing_method':", e)

try:
    # Coluna para armazenar os custos fixos mensais
    cursor.execute("ALTER TABLE users ADD COLUMN default_fixed_costs REAL DEFAULT 0.0")
    print("Coluna 'default_fixed_costs' adicionada com sucesso.")
except sqlite3.OperationalError as e:
    print("Erro ao adicionar 'default_fixed_costs':", e)

try:
    # Coluna para armazenar a quantidade média de vendas mensais
    cursor.execute("ALTER TABLE users ADD COLUMN default_monthly_sales_qty INTEGER DEFAULT 100")
    print("Coluna 'default_monthly_sales_qty' adicionada com sucesso.")
except sqlite3.OperationalError as e:
    print("Erro ao adicionar 'default_monthly_sales_qty':", e)

try:
    # Coluna para armazenar a margem de contribuição padrão
    cursor.execute("ALTER TABLE users ADD COLUMN default_contribution_margin REAL DEFAULT 30.0")
    print("Coluna 'default_contribution_margin' adicionada com sucesso.")
except sqlite3.OperationalError as e:
    print("Erro ao adicionar 'default_contribution_margin':", e)

# Finaliza a conexão
conn.commit()
conn.close()

print("\nMigração concluída! As novas colunas foram adicionadas para suportar a Margem de Contribuição.")