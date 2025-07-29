print("Testando imports...")

try:
    import selenium
    print("✓ Selenium importado com sucesso")
except ImportError as e:
    print("✗ Erro ao importar Selenium:", e)

try:
    from selenium import webdriver
    print("✓ Selenium webdriver importado com sucesso")
except ImportError as e:
    print("✗ Erro ao importar webdriver:", e)

try:
    from webdriver_manager.chrome import ChromeDriverManager
    print("✓ Webdriver Manager importado com sucesso")
except ImportError as e:
    print("✗ Erro ao importar Webdriver Manager:", e)

try:
    from bs4 import BeautifulSoup
    print("✓ BeautifulSoup importado com sucesso")
except ImportError as e:
    print("✗ Erro ao importar BeautifulSoup:", e)

try:
    import lxml
    print("✓ lxml importado com sucesso")
except ImportError as e:
    print("✗ Erro ao importar lxml:", e)

print("\nTeste concluído!")