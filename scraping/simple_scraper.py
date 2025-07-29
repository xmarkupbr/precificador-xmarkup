import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import re
from typing import Dict, Optional
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

class SimplePriceScraper:
    def __init__(self, db_connection):
        self.db = db_connection
        self.driver = None
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
    def initialize_selenium(self):
        """Inicializa o Selenium apenas quando necessário"""
        if not self.driver:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
    
    def scrape_product(self, product_id: int, url: str, marketplace: str) -> Optional[Dict]:
        """Tenta scraping com requests primeiro, depois Selenium se necessário"""
        result = self._scrape_with_requests(url, marketplace)
        
        if not result and marketplace in ['Shopee', 'Amazon']:
            self.initialize_selenium()
            result = self._scrape_with_selenium(url, marketplace)
        
        return result
    
    def _scrape_with_requests(self, url: str, marketplace: str) -> Optional[Dict]:
        """Scraping simples usando requests"""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            if 'mercadolivre' in url:
                return self._parse_mercadolivre(soup)
            else:
                return self._parse_generic(soup)
                
        except Exception as e:
            print(f"Erro com requests em {url}: {e}")
            return None
    
    def _scrape_with_selenium(self, url: str, marketplace: str) -> Optional[Dict]:
        """Scraping usando Selenium para sites com JavaScript"""
        try:
            self.driver.get(url)
            time.sleep(3)
            
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            if 'shopee' in url:
                return self._parse_shopee(soup)
            else:
                return self._parse_generic(soup)
                
        except Exception as e:
            print(f"Erro com Selenium em {url}: {e}")
            return None
    
    def _parse_mercadolivre(self, soup: BeautifulSoup) -> Optional[Dict]:
        """Parser específico para Mercado Livre"""
        try:
            price = None
            price_element = soup.find('span', class_='andes-money-amount__fraction')
            if price_element:
                price_text = price_element.text.strip()
                price = float(price_text.replace('.', '').replace(',', '.'))
            
            title = ""
            title_element = soup.find('h1', class_='ui-pdp-title')
            if title_element:
                title = title_element.text.strip()
            
            if price:
                return {
                    'price': price,
                    'stock': True,
                    'title': title,
                    'timestamp': datetime.now().isoformat()
                }
                
        except Exception as e:
            print(f"Erro ao parsear Mercado Livre: {e}")
            
        return None
    
    def _parse_shopee(self, soup: BeautifulSoup) -> Optional[Dict]:
        """Parser específico para Shopee"""
        try:
            price = None
            # Busca por elementos com classe contendo 'price'
            for element in soup.find_all(attrs={'class': re.compile('price', re.I)}):
                text = element.get_text()
                match = re.search(r'R\$\s*([\d.,]+)', text)
                if match:
                    price = float(match.group(1).replace('.', '').replace(',', '.'))
                    break
            
            if price:
                return {
                    'price': price,
                    'stock': True,
                    'title': 'Produto Shopee',
                    'timestamp': datetime.now().isoformat()
                }
                
        except Exception as e:
            print(f"Erro ao parsear Shopee: {e}")
            
        return None
    
    def _parse_generic(self, soup: BeautifulSoup) -> Optional[Dict]:
        """Parser genérico para qualquer site"""
        try:
            # Busca por dados estruturados
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and data.get('@type') in ['Product', 'Offer']:
                        price = None
                        if 'offers' in data:
                            price = float(data['offers'].get('price', 0))
                        
                        if price:
                            return {
                                'price': price,
                                'stock': True,
                                'title': data.get('name', ''),
                                'timestamp': datetime.now().isoformat()
                            }
                except:
                    continue
            
            # Busca por padrões de preço
            text = soup.get_text()
            patterns = [
                r'R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})?)',
                r'([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})?)\s*(?:reais|R\$)',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, text)
                if matches:
                    try:
                        price_str = matches[0].replace('.', '').replace(',', '.')
                        price = float(price_str)
                        if 0 < price < 1000000:
                            return {
                                'price': price,
                                'stock': True,
                                'title': soup.find('title').text if soup.find('title') else '',
                                'timestamp': datetime.now().isoformat()
                            }
                    except:
                        continue
                        
        except Exception as e:
            print(f"Erro no parser genérico: {e}")
            
        return None
    
    def close(self):
        """Fecha o navegador se estiver aberto"""
        if self.driver:
            self.driver.quit()