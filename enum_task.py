import ssl
import base64
import sqlite3
import subprocess
import concurrent.futures
import re
import socket
from PIL import Image
import imagehash
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright
from rich.progress import Progress, SpinnerColumn, BarColumn, TimeRemainingColumn
import logging


spfdmarc_cache = {}
ssltls_cache = {}

TLS_VULN_VERSION = {"TLSv1.0", "TLSv1.1", "SSLv2", "SSLv3"}

def get_db_connection():
    return sqlite3.connect('database.db', check_same_thread=False)

def execute_command(command, timeout=1):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except (subprocess.TimeoutExpired, Exception):
        return []

def get_main_domain(domain: str) -> str:
    """
    Extrait le domaine principal à partir d'un sous-domaine.
    Exemple : "sub.example.com" -> "example.com"
    """
    parts = domain.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])  # Retourne les deux dernières parties
    return domain  # Si le domaine est déjà un domaine principal (ex: "example.com")


def get_spfdmarc(domain, timeout=1):
    """Récupère les enregistrements SPF/DMARC pour un domaine."""
    #print(f"✔️  Get Spf/Dmarc status")
    main_domain = get_main_domain(domain)
    if main_domain in spfdmarc_cache:
        return spfdmarc_cache[main_domain]

    def get_dns_record(query):
        return execute_command(["dig", "TXT", query, "+short"], timeout=timeout)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        spf_future = executor.submit(get_dns_record, main_domain)
        dmarc_future = executor.submit(get_dns_record, f"_dmarc.{main_domain}")

        spf_records = spf_future.result()
        dmarc_records = dmarc_future.result()

    spf_check = "✔️" if any("v=spf1" in record for record in spf_records) else "❌"
    dmarc_check = "✔️" if any("v=DMARC1" in record for record in dmarc_records) else "❌"

    result = f"{spf_check} {dmarc_check}"
    spfdmarc_cache[main_domain] = result  # Mettre en cache le résultat
    return result

def get_spfdmarc_parallel(domains, max_workers=20):
    print(f"✔️  Get Spf/Dmarc status")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_domain = {executor.submit(get_spfdmarc, domain): domain for domain in domains}
        return {future_to_domain[future]: future.result() for future in concurrent.futures.as_completed(future_to_domain)}

def get_ssl(domain: str, port: int = 443):
    """Retourne les informations SSL/TLS d'un domaine."""
    #print(f"✔️  Get SSL/TLS version")
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, port), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                tls_version = ssock.version()
                if tls_version in TLS_VULN_VERSION:
                    return f"❌ ({tls_version})"
                else:
                    #print(tls_version)
                    return tls_version
    except Exception:
        return None  # Retourne None en cas d'erreur

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
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_domain = {executor.submit(get_method, domain): domain for domain in domains}
        return {future_to_domain[future]: future.result() for future in concurrent.futures.as_completed(future_to_domain)}

def get_httpx_data(domains):
    print(f"✔️  Get Httpx data")
    with open("file.txt", "w") as f:
        f.write("\n".join(domains))

    result = subprocess.run(
        "httpx -ip -title -method -sc -td --tech-detect --silent -nc -timeout 3 -l file.txt",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False
    )
    subprocess.run("rm file.txt", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

# Decode output with error handling
    try:
        output = result.stdout.decode('utf-8')
    except UnicodeDecodeError:
        # Replace invalid bytes with a placeholder (e.g., �)
        output = result.stdout.decode('utf-8', errors='replace')
        # Alternatively, try a fallback encoding like 'latin1'
        # output = result.stdout.decode('latin1')

    if not output.strip():
#    if not result.stdout.strip():
        return {domain: {
            "http_status": "N/A",
            "method": "N/A",
            "title": "N/A",
            "ip": "N/A",
            "tech_list": [],
            "open_port": "N/A",
            "screen": None,
            "phash": None,
            "spfdmarc": "N/A",
            "ssltls": "N/A"
        } for domain in domains}


    # Récupérer les résultats SPF/DMARC pour tous les domaines principaux
    main_domains = set(get_main_domain(domain) for domain in domains)
    print(f"✔️  Get Spf/Dmarc status")
    print(f"✔️  Get SSL/TLS version")
    for main_domain in main_domains:
        if main_domain not in spfdmarc_cache:
            spfdmarc_cache[main_domain] = get_spfdmarc(main_domain)
            ssltls_cache[main_domain] = get_ssl(main_domain)

    method = get_methods_parallel(domains, max_workers=20)
    #spfdmarc = get_spfdmarc_parallel(domains, max_workers=20)
    screenshots = take_screenshots_parallel(domains, max_workers=20)

    regex = re.compile(
        r"^(https?:\/\/[^\s]+)"  # URL obligatoire
        r"(?: \[(\d{3})\])?"  # Code statut HTTP (optionnel)
        r"(?: \[(\w+)\])?"  # Méthode HTTP (optionnel)
        r"(?: \[([^\[\]]+)\])?"  # Titre ou IP si erreur de position (optionnel)
        r"(?: \[([\d\.]+)\])?"  # IP si bien placée (optionnel)
        r"(?: \[([^\[\]]+)\])?$"  # Technologies (optionnel)
    )

    domain_results = {}
    for line in output.split("\n"):
    #for line in result.stdout.split("\n"):
        match = regex.search(line)
        if match:
            full_url = match.group(1)
            if not full_url:
                continue

            domain = full_url.replace("https://", "").replace("http://", "").strip()
            http_status = match.group(2) or None
            http_method = match.group(3) or None
            title_or_ip = match.group(4) or None
            ip = match.group(5) or None
            tech_list = match.group(6).split(", ") if match.group(6) else []

            if title_or_ip and not ip:
                try:
                    socket.inet_aton(title_or_ip)
                    ip = title_or_ip
                    title = None
                except socket.error:
                    title = title_or_ip
            else:
                title = title_or_ip

            screenshot = screenshots.get(domain, None)
            main_domain = get_main_domain(domain)

            spfdmarc = spfdmarc_cache.get(main_domain, "N/A")
            ssltls = ssltls_cache.get(main_domain, "N/A")
            domain_results[domain] = {
                "http_status": http_status,
                "method": method.get(domain, http_method),
                "title": title,
                "ip": ip,
                "tech_list": tech_list,
                "open_port": "xx",
                "screen": screenshot,
                "phash": get_phash(screenshot),
                "spfdmarc": spfdmarc,
                "ssltls": ssltls
            }

    return domain_results





def take_screenshot_base64(url):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(f"https://{url}", timeout=10000)
            except Exception:
                page.goto(f"http://{url}", timeout=10000)
            screenshot = page.screenshot()
            browser.close()
            return base64.b64encode(screenshot).decode('utf-8')
    except Exception as e:
        print(f"⚠️ Error capturing screenshot for {url}: {e}")
        return None

def take_screenshots_parallel(urls, max_workers=10):
    if isinstance(urls, str):
        urls = [urls]

    results = {}
    with Progress(SpinnerColumn(), "[progress.description]{task.description}", BarColumn(), TimeRemainingColumn()) as progress:
        task = progress.add_task("Capturing Screenshots", total=len(urls))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(take_screenshot_base64, url): url for url in urls}
            for future in concurrent.futures.as_completed(futures):
                url = futures[future]
                try:
                    screenshot = future.result()
                    if screenshot:
                        results[url] = screenshot
                except Exception:
                    results[url] = "Error"
                progress.update(task, advance=1)
    return results

def update_db(program_name, domain_data, naabu_results):
    print(f"✔️  Update db")
    with get_db_connection() as conn:
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

            if result is None:
                print(f"⚠️ Erreur : Aucun domaine trouvé pour {domain} dans le programme {program_name}.")
                continue

            domain_id = result[0]
            ip = data["ip"] if data["ip"] else None
            open_ports = ",".join(map(str, naabu_results.get(str(ip), []))) if ip else None
            data["open_port"] = open_ports

            cursor.execute('''
                INSERT INTO domain_details
                (domain_id, http_status, method, title, ip, techno, open_port, screen, phash, spfdmarc,ssltls)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,?)
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
                str(data["spfdmarc"]) if data["spfdmarc"] else None,
                str(data["ssltls"]) if data["spfdmarc"] else None
            ))

        conn.commit()

def scan_naabu_fingerprint(domains_ips):
    print(f"✔️  Portscan with Naabu")
    with open("ips.txt", "w") as f:
        f.write("\n".join(domains_ips) + "\n")

    try:
        result = subprocess.run(
            "naabu -l ips.txt -retries 1 -ec -silent -tp 1000 -s s 2>/dev/null",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        ip_ports = {}
        for line in result.stdout.splitlines():
            match = re.match(r"(\d+\.\d+\.\d+\.\d+):(\d+)", line)
            if match:
                ip, port = match.groups()
                if ip not in ip_ports:
                    ip_ports[ip] = []
                ip_ports[ip].append(int(port))

        subprocess.run("rm ips.txt", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return ip_ports

    except (subprocess.TimeoutExpired, Exception):
        return {}

def get_phash(screenshot_base64):
    try:
        image_data = base64.b64decode(screenshot_base64)
        image = Image.open(io.BytesIO(image_data))
        phash_value = str(imagehash.phash(image))
        return phash_value
    except Exception:
        return None

def maintest(domains, program_name):
    end = get_httpx_data(domains)
    all_ips = list(set(entry["ip"] for entry in end.values() if entry and entry["ip"]))
    naabu = scan_naabu_fingerprint(all_ips)
    #print(end)
    update_db(program_name, end, naabu)
