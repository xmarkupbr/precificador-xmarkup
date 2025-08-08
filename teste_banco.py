import sqlite3

# Conecta ao banco de dados
conn = sqlite3.connect('database.db')
cursor = conn.cursor()

# Mostra TODOS os usuários para você escolher
print("=== USUÁRIOS NO SISTEMA ===")
cursor.execute("SELECT id, email, nome_completo FROM users")
usuarios = cursor.fetchall()

for usuario in usuarios:
    print(f"ID: {usuario[0]} - Email: {usuario[1]} - Nome: {usuario[2]}")

print("\n" + "="*50 + "\n")

# Pega o ID do usuário que você quer verificar
user_id = input("Digite o ID do usuário que você quer verificar: ")

# Busca os dados do usuário
cursor.execute("""
    SELECT 
        email,
        default_pricing_method,
        default_contribution_margin,
        default_fixed_costs,
        default_monthly_sales_qty,
        default_margem
    FROM users 
    WHERE id = ?
""", (user_id,))

result = cursor.fetchone()

if result:
    print(f"\n=== CONFIGURAÇÕES DO USUÁRIO: {result[0]} ===")
    print(f"Método Padrão: {result[1]}")
    print(f"Margem Contribuição: {result[2]}%")
    print(f"Custos Fixos: R$ {result[3]}")
    print(f"Vendas Mensais: {result[4]} unidades")
    print(f"Margem Simples: {result[5]}%")
else:
    print("Usuário não encontrado")

conn.close()