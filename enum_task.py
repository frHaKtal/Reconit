import base64
import sqlite3
import requests
import socket
import subprocess
from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor
import concurrent.futures
import tldextract
import re
import imagehash
import io
from PIL import Image
import json


def get_db_connection():
    return sqlite3.connect('database.db')

def execute_command(command):
    
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return result.stdout.strip().split('\n')
    except subprocess.CalledProcessError as e:
        return []

def get_spfdmarc(domain):
    
    spf_records = execute_command(["dig", "TXT", domain, "+short"])
    dmarc_records = execute_command(["dig", "TXT", f"_dmarc.{domain}", "+short"])

    spf_check = "✔️" if any("v=spf1" in record for record in spf_records) else "❌"
    dmarc_check = "✔️" if any("v=DMARC1" in record for record in dmarc_records) else "❌"

    return f"{spf_check} {dmarc_check}"

def get_method(domain):
   
    https_command = f"curl -s -X OPTIONS -I https://{domain} | grep -i 'allow:' | grep -oPi '(?<=allow: ).*'"
    https_result = subprocess.run(https_command, shell=True, capture_output=True, text=True)
    method_https = https_result.stdout.strip()


    http_command = f"curl -s -X OPTIONS -I http://{domain} | grep -i 'allow:' | grep -oPi '(?<=allow: ).*'"
    http_result = subprocess.run(http_command, shell=True, capture_output=True, text=True)
    method_http = http_result.stdout.strip()

    result = []

    if method_https:  # Si method_https n'est pas vide
        result.append(f"https: {method_https}")

    if method_http:  # Si method_http n'est pas vide
        result.append(f"http: {method_http}")

    return " | ".join(result) if result else "No methods found"


def get_httpx_data(domains):
    
    domain_results = {}
    #driver = setup_selenium_driver()
    domains_str = "\n".join(domains)
#f"echo \"{domains_str}\" > file.txt | httpx --tech-detect --silent -nc -timeout 3 -l file.txt"

    result = subprocess.run(
        f"echo \"{domains_str}\" > file.txt | httpx -ip -title -method -sc -td --tech-detect --silent -nc -timeout 3 -l file.txt",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if not result.stdout.strip():
        return {domain: None for domain in domains}

    screenshots=take_screenshots_parallel(domains, max_workers=20)
    for line in result.stdout.split("\n"):
        match = re.search(r"(https?:\/\/[^\s]+) \[(\d+)\] \[(\w+)\] \[(.*?)\] \[(.*?)\] \[(.*?)\]", line)
        if match:
            full_url = match.group(1)
            domain = match.group(1).replace("https://", "").replace("http://", "")
            http_status = match.group(2)
            #method = match.group(3)
            method = get_method(domain)
            title = match.group(4)
            ip = match.group(5)
            tech_list = match.group(6).split(", ") if match.group(6) else []

            domain_principal = re.search(r"([a-zA-Z0-9-]+\.[a-zA-Z]{2,})$", full_url)
            #screenshot=take_screenshots_parallel(domain, max_workers=20)
            screenshot = screenshots.get(domain, None)
            domain_results[domain] = {
                "http_status": http_status,
                "method": method,
                "title": title,
                "ip": ip,
                "tech_list": tech_list,
                #"open_port": scan_naabu_fingerprint(domain),  # Scan des ports ouverts
                "open_port": "xx",  # Scan des ports ouverts
                "screen": screenshot,  # Capture d'écran
                "phash": get_phash(screenshot),  # Perceptual hash de l'image
                "spfdmarc": get_spfdmarc(domain_principal.group(1))  # SPF/DMARC info
            }

    result = subprocess.run(
        f"rm file.txt",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    return domain_results



def take_screenshot_base64(url):
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            #print(url)
            page.goto(f"http://{url}", timeout=5000)  # Timeout max de 10s
            screenshot = page.screenshot()
            browser.close()
            return base64.b64encode(screenshot).decode('utf-8')
    except Exception as e:
        #print(f"[✘] Failed: {url} -> {e}")
        return None


def take_screenshots_parallel(urls, max_workers=20):
    

   
    if isinstance(urls, str):
        urls = [urls]  # Convertit une chaîne en liste

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for url, screenshot in zip(urls, executor.map(take_screenshot_base64, urls)):
            if screenshot:
                results[url] = screenshot #modifier ici
                #domain_results[domain_name]['screen'].append(screenshot_base64)

    return results


def update_db(program_name, domain_data):
    

    with sqlite3.connect("database.db") as conn:
        cursor = conn.cursor()

        
        cursor.execute("SELECT id FROM programs WHERE program_name = ?", (program_name,))
        program_id = cursor.fetchone()

        if not program_id:
            print(f"⚠️ Erreur : Aucun programme trouvé pour '{program_name}'.")
            return

        program_id = program_id[0]

        
        for domain, data in domain_data.items():
            if data is None:
                continue  # Si aucune donnée, on passe

            
            cursor.execute(
                'INSERT OR IGNORE INTO domains (program_id, domain_name) VALUES (?, ?)',
                (program_id, domain)
            )

            
            cursor.execute(
                'SELECT id FROM domains WHERE program_id = ? AND domain_name = ?',
                (program_id, domain)
            )
            domain_id = cursor.fetchone()[0]

           
            cursor.execute('''
                INSERT INTO domain_details
                (domain_id, http_status, method, title, ip, techno, open_port, screen, phash, spfdmarc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                domain_id,
                data["http_status"] if data["http_status"] else None,
                data["method"] if data["method"] else None,
                data["title"] if data["title"] else None,
                data["ip"] if data["ip"] else None,
                ", ".join(data["tech_list"]) if data["tech_list"] else None,
                str(data["open_port"]) if data["open_port"] else None,
                str(data["screen"]) if data["screen"] else None,
                str(data["phash"]) if data["phash"] else None,
                str(data["spfdmarc"]) if data["spfdmarc"] else None
            ))

        conn.commit()

def update_dbb(program_name, domain_data):
    
    with sqlite3.connect("database.db") as conn:
        cursor = conn.cursor()

        
        cursor.execute("SELECT id FROM programs WHERE program_name = ?", (program_name,))
        program_id = cursor.fetchone()

        if not program_id:
            print(f"⚠️ Erreur : Aucun programme trouvé pour '{program_name}'.")
            return

        program_id = program_id[0]

        
        for domain, data in domain_data.items():
            if data is None:
                continue  

            cursor.execute(
                'INSERT OR IGNORE INTO domains (program_id, domain_name) VALUES (?, ?)',
                (program_id, domain)
            )
            domain_id = cursor.lastrowid  # ID du domaine inséré

     
            cursor.execute('''
                INSERT INTO domain_details
                (domain_id, http_status, method, title, ip, techno, open_port, screen, phash, spfdmarc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                domain_id,
                data["http_status"],
                data["method"],
                data["title"],
                data["ip"],
                ", ".join(data["tech_list"]) if data["tech_list"] else None,
                #", ".join(map(str, data["open_port"])) if data["open_port"] else None,
                str(data["open_port"]) if data["open_port"] else None,
                str(data["screen"]) if data["screen"] else None,
                str(data["phash"]) if data["phash"] else None,
                str(data["spfdmarc"]) if data["spfdmarc"] else None
            ))

        conn.commit()


def scan_naabu_fingerprint(domain):
    try:
        
        result = subprocess.run(
            f"naabu -host {domain} -retries 1 -ec -silent -s s 2>/dev/null | grep -oP '\d+(?=\s*$)' | tr '\n' ',' | sed 's/,$//'",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5  # Timeout de 10 secondes
        )

        
        return result.stdout
    except subprocess.TimeoutExpired:
        #print(f"⏰ Scan {dom} Timeout")
        return "Timeout"
    except Exception as e:
        pass
        #print(f"❌ Error run {dom}: {e}")
        return None


def get_phash(screenshot_base64):
    try:
        
        image_data = base64.b64decode(screenshot_base64)
        image = Image.open(io.BytesIO(image_data))
        phash_value = str(imagehash.phash(image))
        return phash_value

    except Exception as e:
        
        return None


def maintest(domains, program_name):
    end=get_httpx_data(domains)
    update_db(program_name,end)
