import base64
import sqlite3
import requests
import socket
import subprocess
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from PIL import Image
import io
import imagehash
import tldextract
import re

# Connexion à la base de données
#conn = sqlite3.connect('database.db')
#cursor = conn.cursor()

def get_db_connection():
    return sqlite3.connect('database.db')

def get_phash(screenshot_base64):
    try:
        # Décoder l'image en base64 pour obtenir les bytes
        image_data = base64.b64decode(screenshot_base64)

        # Créer une image PIL à partir des bytes
        image = Image.open(io.BytesIO(image_data))

        # Calculer le perceptual hash
        phash_value = str(imagehash.phash(image))
        return phash_value

    except Exception as e:
        #print(f"Failed to calculate phash: {e}")
        return None

def get_method(domain):
    # Tester HTTPS
    https_command = f"curl -s -X OPTIONS -I https://{domain} | grep -i 'allow:' | grep -oPi '(?<=allow: ).*'"
    https_result = subprocess.run(https_command, shell=True, capture_output=True, text=True)
    method_https = https_result.stdout.strip()

    # Tester HTTP
    http_command = f"curl -s -X OPTIONS -I http://{domain} | grep -i 'allow:' | grep -oPi '(?<=allow: ).*'"
    http_result = subprocess.run(http_command, shell=True, capture_output=True, text=True)
    method_http = http_result.stdout.strip()

    result = []

    if method_https:  # Si method_https n'est pas vide
        result.append(f"https: {method_https}")

    if method_http:  # Si method_http n'est pas vide
        result.append(f"http: {method_http}")

    return " | ".join(result) if result else "No methods found"


def get_spfdmarc(domain):

    #print(f"✔️  \033[1m{len(domains)}\033[0m domain find")
    #spf = curl -s https://dmarcly.com/server/spf_check.php?domain={domain} | grep -q --color=auto "SPF record not found" && echo -e "[!]\e[31m SPF RECORD NOT FOUND\e[0m" || echo -e "[●]\e[33m SPF RECORD VALID\e[0m"
    #dmarc = curl -s https://dmarcly.com/server/dmarc_check.php\?domain\={domain} | grep -q --color=auto "DMARC record not found" && echo -e "[!]\e[31m DMARC RECORD NOT FOUND\e[0m" || echo -e "[●]\e[33m DMARC RECORD VALID\e[0m"
    url_spf = f"https://dmarcly.com/server/spf_check.php?domain={domain}"
    response_spf = requests.get(url_spf)
    if "SPF record not found" in response_spf.text:
        #print("\033[31m[!]\033[0m SPF RECORD NOT FOUND")
        spf_result = "❌"
    else:
        #print("\033[33m[●]\033[0m SPF RECORD VALID")
        spf_result = "✔️ "

    url_dmarc = f"https://dmarcly.com/server/dmarc_check.php?domain={domain}"
    response_dmarc = requests.get(url_dmarc)
    if "DMARC record not found" in response_dmarc.text:
        #print("\033[31m[!]\033[0m DMARC RECORD NOT FOUND")
        dmarc_result = "❌"
    else:
        #print("\033[33m[●]\033[0m DMARC RECORD VALID")
        dmarc_result = "✔️ "

    return spf_result + dmarc_result

def get_ip(domain):

    try:
        ip_address = socket.gethostbyname(domain)
        return ip_address
    except socket.error as e:
        pass
        #print(f"❌ Error resolving {domain_name}: {e}")
    return None

def get_http_status(domain):

    url = f"http://{domain}"
    try:
        response = requests.get(url, timeout=10)  # Ajoute un timeout pour éviter de bloquer
        return response.status_code
    except requests.RequestException as e:
        #print(f"❌ Error fetching {url}: {e}")
        return None

def get_techno(domain):
    result = subprocess.run(f"echo {domain} | httpx --tech-detect --silent -nc | grep -oP '\\[.*?\\]'",
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True)

    if not result.stdout.strip():  # Vérifie si stdout est vide ou seulement des espaces
        return None
    clean_techs = re.findall(r'\[(.*?)\]', result.stdout.strip())
    return ", ".join(clean_techs)  # Retourne une chaîne formatée
    #return result.stdout.strip()  # Retire les espaces en trop si nécessaire

def get_title(domain):
    url = f"http://{domain}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            return soup.title.string if soup.title else 'No title found'
        else:
            return 'No title found'
    except requests.RequestException as e:
        pass
        #print(f"❌ Error fetching {url}: {e}")
        return 'No title found'

def scan_naabu_fingerprint(domain):
    try:
        # Exécuter la commande avec un timeout de 10 secondes
        result = subprocess.run(
            f"naabu -host {domain} -ec -cdn -silent -s s 2>/dev/null | grep -oP '\d+(?=\s*$)' | tr '\n' ',' | sed 's/,$//'",
#f"naabu -host {domain} -ec -cdn -silent 2>/dev/null | fingerprintx",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10  # Timeout de 10 secondes
        )

        # Renvoyer la sortie de la commande (stdout)
        return result.stdout
    except subprocess.TimeoutExpired:
        #print(f"⏰ Scan {dom} Timeout")
        return "Timeout"
    except Exception as e:
        pass
        #print(f"❌ Error run {dom}: {e}")
        return None



def check_protocol(domain_name):
    """
    Vérifie si le domaine est accessible via HTTPS ou HTTP.
    Renvoie le protocole disponible.
    """
    try:
        response = requests.get(f"https://{domain_name}", timeout=5)
        if response.status_code == 200:
            return "https"
    except requests.RequestException:
        pass  # Ignore l'erreur et essaie HTTP ensuite

    try:
        response = requests.get(f"http://{domain_name}", timeout=5)
        if response.status_code == 200:
            return "http"
    except requests.RequestException:
        pass  # Si les deux échouent, retourne None

    return None

def take_screenshot(domain_name):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")
    driver = webdriver.Chrome(options=chrome_options)

    try:
        # Ouvrir la page du domaine
        protocol = check_protocol(domain_name)
        #driver.get(f"http://{domain_name}")
        driver.get(f"{protocol}://{domain_name}")
        screenshot = driver.get_screenshot_as_png()

        # Encoder en base64
        screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
        return screenshot_base64

    except Exception as e:
        #print(f"Failed to take screenshot for {domain_name}: {e}")
        return None
    finally:
        driver.quit()

def add_dom(program_name, domain):
    # Ouvrir une nouvelle connexion et un curseur pour ce thread
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    #conn = get_db_connection()
    #cursor = conn.cursor()

    try:


        cursor.execute('SELECT id FROM domains WHERE domain_name = ?', (domain,))
        existing_domain = cursor.fetchone()

        if existing_domain:
            print(f"⚠️  Domain '{domain}' already exists.")
            return

        #print(f"Adding domain: {domain} to program: {program_name}")

        # Récupérer les informations d'énumération
        ip = get_ip(domain)
        open_ports = scan_naabu_fingerprint(domain)
        #spfdmarc = get_spfdmarc(domain)
        extracted = tldextract.extract(domain)

        # Récupérer uniquement le spfdmarc si le domaine principal n'est pas déjà présent
        domain_main = f"{extracted.domain}.{extracted.suffix}"
        #cursor.execute('SELECT spfdmarc FROM domain_details JOIN domains ON domains.id = domain_details.domain_id WHERE domain_name LIKE ?', (f"%.{domain_main}",))
        #existing_main_domain = cursor.fetchone()

        #if existing_main_domain:
        #    spfdmarc = existing_main_domain[0]
        #else:
        #    spfdmarc = get_spfdmarc(domain_main)  # Récupérer spfdmarc seulement si le domaine principal n'est pas présent

        spfdmarc = get_spfdmarc(domain_main)
 #       if not ip:
 #           http_status = None
 #           techno = None
 #           open_ports = None
 #           screenshot = None
 #           title = None
 #           phash = None
 #           method = None
#        else:
        http_status = get_http_status(domain)
        techno = get_techno(domain)
        open_ports = scan_naabu_fingerprint(domain)
        screenshot = take_screenshot(domain)
        title = get_title(domain)
        phash = get_phash(screenshot)
        method = get_method(domain)
        #print(get_method(domain))

        # Récupérer l'ID du programme
        cursor.execute('SELECT id FROM programs WHERE program_name = ?', (program_name,))
        program_id = cursor.fetchone()

        if program_id:
            # Ajouter le domaine dans la table domains
            cursor.execute('''
                INSERT INTO domains (program_id, domain_name) VALUES (?, ?)
            ''', (program_id[0], domain))
            domain_id = cursor.lastrowid

            # Ajouter les détails du domaine dans la table domain_details
            cursor.execute('''
                INSERT INTO domain_details (domain_id, title, ip, http_status, techno, open_port, screen, phash, spfdmarc, method)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (domain_id, title, ip, http_status, techno, open_ports, screenshot, phash, spfdmarc, method))

            conn.commit()
            #print(f"✔️ Domain {domain} added successfully.")
        else:
            print(f"❌ Program {program_name} not found.")

    except Exception as e:
        print(f"❌ Failed to add domain {domain}: {e}")
    finally:
        cursor.close()
        conn.close()
