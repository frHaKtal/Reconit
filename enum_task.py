import base64
import sqlite3
import requests
import socket
import subprocess
from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor
from rich.progress import Progress, SpinnerColumn, BarColumn, TimeRemainingColumn
from concurrent.futures import ThreadPoolExecutor, as_completed
import concurrent.futures
import tldextract
import re
import imagehash
import io
from PIL import Image
import json

def get_db_connection():
    return sqlite3.connect('database.db')


def execute_command(command, timeout=1):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except subprocess.TimeoutExpired:
        #print(f"[⚠] Timeout : La commande {' '.join(command)} a dépassé {timeout} secondes.")
        return []  # Retourne une liste vide si timeout
    except Exception as e:
        #print(f"[⚠] Erreur : {e}")
        return []


def get_spfdmarc(domain, timeout=1):

    def get_dns_record(query):
        return execute_command(["dig", "TXT", query, "+short"], timeout=timeout)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        spf_future = executor.submit(get_dns_record, domain)
        dmarc_future = executor.submit(get_dns_record, f"_dmarc.{domain}")

        spf_records = spf_future.result()
        dmarc_records = dmarc_future.result()

    spf_check = "✔️" if any("v=spf1" in record for record in spf_records) else "❌"
    dmarc_check = "✔️" if any("v=DMARC1" in record for record in dmarc_records) else "❌"

    return f"{spf_check} {dmarc_check}"


def get_spfdmarc_parallel(domains, max_workers=20):

    print(f"✔️  Get Spf/Dmarc status")
    results = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_domain = {executor.submit(get_spfdmarc, domain): domain for domain in domains}

        for future in concurrent.futures.as_completed(future_to_domain):
            domain = future_to_domain[future]
            try:
                results[domain] = future.result()
            except Exception as e:
                results[domain] = f"Error: {e}"

    return results


def get_method(domain, timeout=1):

    def run_command(command):
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            return ""

    https_command = f"curl --max-time {timeout} -s -X OPTIONS -I https://{domain} | grep -i 'allow:' | grep -oPi '(?<=allow: ).*'"
    http_command = f"curl --max-time {timeout} -s -X OPTIONS -I http://{domain} | grep -i 'allow:' | grep -oPi '(?<=allow: ).*'"

    with concurrent.futures.ThreadPoolExecutor() as executor:
        https_future = executor.submit(run_command, https_command)
        http_future = executor.submit(run_command, http_command)

        method_https = https_future.result()
        method_http = http_future.result()

    result = []
    if method_https:
        result.append(f"https: {method_https}")
    if method_http:
        result.append(f"http: {method_http}")

    return " | ".join(result) if result else "No methods found"


def get_methods_parallel(domains, max_workers=20):
    print(f"✔️  Get http method")
    methods = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_domain = {executor.submit(get_method, domain): domain for domain in domains}

        for future in concurrent.futures.as_completed(future_to_domain):
            domain = future_to_domain[future]
            try:
                methods[domain] = future.result()
            except Exception as e:
                methods[domain] = f"Error: {e}"
    return methods


def get_httpx_data(domains):
    print(f"✔️  Get Httpx data")
    domain_results = {}
    #driver = setup_selenium_driver()
    domains_str = "\n".join(domains)
#f"echo \"{domains_str}\" > file.txt | httpx --tech-detect --silent -nc -timeout 3 -l file.txt"
    with open("file.txt", "w") as f:
        f.write("\n".join(domains))

    result = subprocess.run(
        f"httpx -ip -title -method -sc -td --tech-detect --silent -nc -timeout 3 -l file.txt",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if not result.stdout.strip():
        return {domain: None for domain in domains}

    method = get_methods_parallel(domains, max_workers=20)
    spfdmarc = get_spfdmarc_parallel(domains, max_workers=20)
    #naabu = scan_naabu_fingerprint(domains, None)
    screenshots=take_screenshots_parallel(domains, max_workers=20)
    for line in result.stdout.split("\n"):
        match = re.search(r"(https?:\/\/[^\s]+) \[(\d+)\] \[(\w+)\] \[(.*?)\] \[(.*?)\] \[(.*?)\]", line)
        if match:
            full_url = match.group(1)
            domain = match.group(1).replace("https://", "").replace("http://", "")
            http_status = match.group(2)
            #method = match.group(3)
            #method = get_methods_parallel()
            methods = method.get(domain, None)
            title = match.group(4)
            ip = match.group(5)
            tech_list = match.group(6).split(", ") if match.group(6) else []

            domain_principal = re.search(r"([a-zA-Z0-9-]+\.[a-zA-Z]{2,})$", full_url)
            #screenshot=take_screenshots_parallel(domain, max_workers=20)
            screenshot = screenshots.get(domain, None)
            domain_results[domain] = {
                "http_status": http_status,
                "method": methods,
                "title": title,
                "ip": ip,
                "tech_list": tech_list,
                #"open_port": naabu.get(domain,None),  # Scan des ports ouverts
                "open_port": "xx",  # Scan des ports ouverts
                "screen": screenshot,  # Capture d'écran
                "phash": get_phash(screenshot),  # Perceptual hash de l'image
                #"spfdmarc": get_spfdmarc(domain_principal.group(1))  # SPF/DMARC info
                "spfdmarc": spfdmarc.get(domain, None)
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
    #print(f"screenshot {url}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            #print(url)
            page.goto(f"http://{url}", timeout=2000)  # Timeout max de 2s
            screenshot = page.screenshot()
            browser.close()
            return base64.b64encode(screenshot).decode('utf-8')
    except Exception as e:
        #print(f"[✘] Failed: {url} -> {e}")
        return None



def take_screenshots_parallel(urls, max_workers=20):
    if isinstance(urls, str):
        urls = [urls]

    results = {}

    with Progress(
        SpinnerColumn(),  # Petit spinner
        "[progress.description]{task.description}",  # Description de la tâche
        BarColumn(),  # Barre de progression
        TimeRemainingColumn(),  # Temps restant estimé
    ) as progress:
        task = progress.add_task("Capturing Screenshots", total=len(urls))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(take_screenshot_base64, url): url for url in urls}

            for future in as_completed(futures):
                url = futures[future]
                try:
                    screenshot = future.result()
                    if screenshot:
                        results[url] = screenshot
                except Exception as e:
                    results[url] = f"Error: {e}"  # Garde l'erreur dans le dict

                progress.update(task, advance=1)  # ✅ Indentation correcte ici

    return results


def update_db(program_name, domain_data, naabu_results):
    print(f"✔️  Update db")
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

            cursor.execute(
                'SELECT id FROM domains WHERE program_id = ? AND domain_name = ?',
                (program_id, domain)
            )
            result = cursor.fetchone()
            #domain_id = cursor.fetchone()[0]
            if result is None:
                print(f"⚠️ Erreur : Aucun domaine trouvé pour {domain} dans le programme {program_name}.")
                continue  # Passer au domaine suivant

            domain_id = result[0]

            # Récupérer l'IP associée au domaine
            ip = data["ip"] if data["ip"] else None
            #print(ip)
            # Récupérer les ports ouverts pour cette IP via Naabu
            #open_ports = ",".join(map(str, naabu_results.get(ip, []))) if ip else None
            open_ports = ",".join(map(str, naabu_results.get(str(ip), []))) if ip else None

            data["open_port"] = open_ports

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


def scan_naabu_fingerprint(domains_ips):
    print(f"✔️  Portscan with Naabu")
    domains_str = "\n".join(domains_ips)
    with open("ips.txt", "w") as f:
        f.write("\n".join(domains_ips) + "\n")

    try:
        result = subprocess.run(
            f"naabu -l ips.txt -retries 1 -ec -silent -s s 2>/dev/null",
#f"echo {domains_str} > ips.txt | naabu -l ips.txt -retries 1 -ec -silent -s s 2>/dev/null | grep -oP '\d+(?=\s*$)' | tr '\n' ',' | sed 's/,$//'",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        ip_ports = {}
        for line in result.stdout.splitlines():
            match = re.match(r"(\d+\.\d+\.\d+\.\d+):(\d+)", line)  # Extraction IP:PORT
            if match:
                ip, port = match.groups()
                if ip not in ip_ports:
                    ip_ports[ip] = []
                ip_ports[ip].append(int(port))

        result = subprocess.run(
            f"rm ips.txt",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return ip_ports

    except subprocess.TimeoutExpired:
        return {}  # Timeout, retourne un dict vide
    except Exception as e:
        return None  # Erreur, retourne None


def get_phash(screenshot_base64):
    try:
        image_data = base64.b64decode(screenshot_base64)
        image = Image.open(io.BytesIO(image_data))
        phash_value = str(imagehash.phash(image))
        return phash_value

    except Exception as e:
        #print(f"Failed to calculate phash: {e}")
        return None


def maintest(domains, program_name):
    end=get_httpx_data(domains)
    all_ips = list(set(entry["ip"] for entry in end.values() if entry and entry["ip"]))
    naabu = scan_naabu_fingerprint(all_ips)
    update_db(program_name,end,naabu)
