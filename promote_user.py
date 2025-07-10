import sqlite3
import sys

DATABASE_NAME = 'database.db'

def promote_user(email):
    """Atribui privilégios de administrador a um utilizador com base no seu e-mail."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Verifica se o utilizador existe
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()

    if user:
        # Promove o utilizador a administrador
        cursor.execute("UPDATE users SET is_admin = TRUE WHERE email = ?", (email,))
        conn.commit()
        print(f"Sucesso: O utilizador '{email}' foi promovido a administrador.")
    else:
        print(f"Erro: Nenhum utilizador encontrado com o e-mail '{email}'.")

    conn.close()

if __name__ == '__main__':
    # Garante que um e-mail foi fornecido como argumento na linha de comando
    if len(sys.argv) != 2:
        print("Uso: python promote_user.py <email_do_utilizador>")
        sys.exit(1)

    user_email = sys.argv[1]
    promote_user(user_email)