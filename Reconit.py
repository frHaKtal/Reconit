#!/usr/bin/python3
import sys
import time
import os
import concurrent.futures
import sqlite3
from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.shortcuts import print_formatted_text
from enum_task import *
from setup_database import setup_database
import subprocess
import base64
from tqdm import tqdm
import multiprocessing
import argparse
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text


def lolcat(text):
    os.system(f"echo '{text}' | lolcat")

# Dictionnaire contenant les commandes et leurs descriptions
commands_with_descriptions = {
    'exit': 'Exit the program',
    'add': 'Add domain1.com domain2.com or *.domain.com',
    'add_com': 'Add comment to domain or program (add_com domain/program domain.com "xx")',
    'rm': 'Remove a domain (without http) or program (rm domain/program xx)',
    'list': 'Domain of program list (list domain/ip/url/program)',
    'show': 'Show domain (list domain with screenshot)',
    'search': 'Search in domain list (search xx)',
    'clear': 'Clear screen',
}

class CommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        # Renvoyer les suggestions et descriptions des commandes
        word_before_cursor = document.get_word_before_cursor()
        for command, description in commands_with_descriptions.items():
            if command.startswith(word_before_cursor):
                yield Completion(command, start_position=-len(word_before_cursor), display_meta=description)

def setup_selenium_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")
    return webdriver.Chrome(options=chrome_options)

def enum_domain(domain_name, method):
    result_lines = []  # Liste pour stocker les résultats ligne par ligne

    if method == "passive":
        print(f"❗️ Enumeration passive for domain: \033[1m{domain_name}\033[0m")

        print(f"✔️  Subfinder")
        subfinder_result = subprocess.run(f"subfinder -d {domain_name} -silent -all -recursive",
                                          shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        result_lines.extend(subfinder_result.stdout.splitlines())

        print(f"✔️  Amass")
        amass_result = subprocess.run(f"amass enum -passive -d {domain_name}",
                                      shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        result_lines.extend(amass_result.stdout.splitlines())

        print(f"✔️  Crt.sh")
        crt_result = subprocess.run(f"curl -s 'https://crt.sh/?q=%25.{domain_name}&output=json' | jq -r '.[].name_value' | sed 's/\*\.//g'",
                                    shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        result_lines.extend(crt_result.stdout.splitlines())

    else:
        print(f"✔️  Enumeration active for domain: \033[1m{domain_name}\033[0m")
        print(f"✔️  Shuffledns")
        active_result = subprocess.run(f"shuffledns -d {domain_name} -list all.txt -r resolvers.txt",
                                       shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        result_lines.extend(active_result.stdout.splitlines())

    # Suppression des doublons et tri des résultats
    unique_sorted_result = sorted(set(result_lines))

    return "\n".join(unique_sorted_result)
def get_domains():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, domain_name FROM domains")
    domains = [{"id": row[0], "domain_name": row[1]} for row in cursor.fetchall()]
    conn.close()
    return domains

def add_domains_in_parallel_multithread(program_name, domains):
    print("✔️  Processing domains recon...")

    def safe_add_dom(domain):
        try:
            return add_dom(setup_selenium_driver(), program_name, domain)
        except Exception as e:
            print(f"Error during domain addition ({domain}): {e}")
            return None  # Retourne None en cas d'erreur

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        list(executor.map(safe_add_dom, domains))

    print("✔️  Processing complete.")

def add_url(program_name, new_url):

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM programs WHERE program_name = ?", (program_name,))
    result = cursor.fetchone()

    if not result:
        print(f"❌ Program '{program_name}' not found.")
    else:
        current_url = result[0]
        if current_url:
            # Ajouter la nouvelle URL à l'URL existante (séparée par un espace ou autre délimiteur)
            new_combined_url = current_url + "\n" + new_url
            cursor.execute("UPDATE programs SET url = ? WHERE program_name = ?", (new_combined_url, program_name))
            print(f"✅ URL added to program '{program_name}': {new_combined_url}")
        else:
            # Si l'URL est vide, on peut simplement l'ajouter
            cursor.execute("UPDATE programs SET url = ? WHERE program_name = ?", (new_url, program_name))
            print(f"✅ URL added for program '{program_name}': {new_url}")

    conn.commit()
    cursor.close()
    conn.close()


def enum_url(domain_name):

        result_lines = []

        print(f"❗ Finding url for domain: \033[1m{domain_name}\033[0m")
        print(f"✔️  Gau")
        gau_result = subprocess.run(f"gau {domain_name}",
                                      shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        result_lines.extend(gau_result.stdout.splitlines())

        print(f"✔️  Katana")
        katana_result = subprocess.run(f"katana -u {domain_name} -jc -silent",
                                      shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        result_lines.extend(katana_result.stdout.splitlines())

        print(f"✔️  Gospider")
        gospider_result = subprocess.run(f"gospider -s https://{domain_name}",
                                      shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        result_lines.extend(gospider_result.stdout.splitlines())

        print(f"✔️  Hakrawler")
        hakrawler_result = subprocess.run(f"echo 'https://{domain_name}' | hakrawler",
                                      shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        result_lines.extend(hakrawler_result.stdout.splitlines())


def display_screenshot_with_imgcat(screenshot_data):
    #print(screenshot_data)
    image_data = base64.b64decode(screenshot_data)

    temp_image_path = "/tmp/temp_screenshot.png"
    with open(temp_image_path, "wb") as img_file:
        img_file.write(image_data)

    os.system(f"imgcat {temp_image_path}")
    os.remove(temp_image_path)


def rm(entity_type, *entity_names):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    try:
        if entity_type == 'program':
            for entity_name in entity_names:
                cursor.execute('SELECT id FROM programs WHERE program_name = ?', (entity_name,))
                program = cursor.fetchone()

                if program:
                    program_id = program[0]
                    cursor.execute('DELETE FROM domains WHERE program_id = ?', (program_id,))
                    cursor.execute('DELETE FROM programs WHERE id = ?', (program_id,))
                    conn.commit()
                    print(f"✔️ Program \033[1m'{entity_name}'\033[0m and its associated domains have been deleted.")
                else:
                    print(f"❌ Program \033[1m'{entity_name}'\033[0m not found.")

        elif entity_type == 'domain':
            for entity_name in entity_names:
                if '*' in entity_name:
                    # Gestion du wildcard (*.example.com)
                    domain_pattern = entity_name.replace('*.', '')  # Supprimer le '*.'
                    cursor.execute('SELECT id, domain_name FROM domains WHERE domain_name LIKE ?', (f'%.{domain_pattern}',))
                    domains = cursor.fetchall()

                    if domains:
                        cursor.executemany('DELETE FROM domains WHERE id = ?', [(d[0],) for d in domains])
                        conn.commit()
                        print(f"✔️ All domains matching \033[1m'{entity_name}'\033[0m have been deleted.")
                    else:
                        print(f"❌ No domains found matching \033[1m'{entity_name}'\033[0m.")
                else:
                    # Suppression d'un domaine unique
                    cursor.execute('SELECT id FROM domains WHERE domain_name = ?', (entity_name,))
                    domain = cursor.fetchone()

                    if domain:
                        cursor.execute('DELETE FROM domains WHERE id = ?', (domain[0],))
                        conn.commit()
                        print(f"✔️ Domain \033[1m'{entity_name}'\033[0m has been deleted.")
                    else:
                        print(f"❌ Domain \033[1m'{entity_name}'\033[0m not found.")
        else:
            print("❌ Invalid entity type. Use 'program' or 'domain'.")
    finally:
        cursor.close()
        conn.close()


def add_com(target_type, target_name, comment):

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    try:
        if target_type == 'program':
            cursor.execute('SELECT id FROM programs WHERE program_name = ?', (target_name,))
            program = cursor.fetchone()

            if program:
                program_id = program[0]
                cursor.execute('UPDATE programs SET com = ? WHERE id = ?', (comment, program_id))
                conn.commit()
                print(f"✔️ Comment added to program '{target_name}'")
            else:
                print(f"❌ Program '{target_name}' not found.")
        elif target_type == 'domain':
           
            cursor.execute('SELECT id FROM domains WHERE domain_name = ?', (target_name,))
            domain = cursor.fetchone()

            if domain:
                domain_id = domain[0]
                cursor.execute('UPDATE domain_details SET com = ? WHERE domain_id = ?', (comment, domain_id))
                conn.commit()
                print(f"✔️ Comment added to domain '{target_name}'")
            else:
                print(f"❌ Domain '{target_name}' not found.")
        else:
            print(f"❌ Invalid target type. Use 'program' or 'domain'.")

    finally:

        cursor.close()
        conn.close()

def show(program_name=None):

    console = Console()
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    if program_name:
        cursor.execute('SELECT id FROM programs WHERE program_name = ?', (program_name,))
        program = cursor.fetchone()

        if program:
            program_id = program[0]
            cursor.execute('''
                SELECT COUNT(*) FROM domains
                WHERE program_id = ?
            ''', (program_id,))
            domain_count = cursor.fetchone()[0]

            print(f"📝 Number of domains for program \033[1m{program_name}\033[0m: \033[1m{domain_count}\033[0m")

            # Récupérer les domaines du programme avec le phash
            cursor.execute('''
                SELECT domains.domain_name, domain_details.http_status, domain_details.ip, domain_details.title,
                       domain_details.techno, domain_details.open_port, domain_details.screen, domain_details.phash, domain_details.spfdmarc,
                       domain_details.method, domain_details.com, domain_details.phash
                FROM domains
                INNER JOIN domain_details ON domains.id = domain_details.domain_id
                WHERE domains.program_id = ?
                ORDER BY domain_details.screen IS NOT NULL DESC,
                         CASE
                            WHEN domain_details.http_status = 200 THEN 1
                            WHEN domain_details.http_status IS NULL THEN 3
                            ELSE 2
                         END
            ''', (program_id,))
            domains = cursor.fetchall()

            if domains:
                print(f"\n📄 List of domains for program \033[1m{program_name}\033[0m:")

                grouped_domains = {}

                for domain in domains:
                    domain_name, http_status, ip, title, techno, open_port, screen, phash, spfdmarc, method, comment, phash = domain
                    if phash not in grouped_domains:
                        grouped_domains[phash] = []
                    grouped_domains[phash].append(domain)

                for phash, group in grouped_domains.items():
                    if len(group) > 1:
                        print(f"⚠️  Domains with identical phash \033[1m{phash}\033[0m:")

                    for domain in group:
                        domain_name, http_status, ip, title, techno, open_port, screen, phash, spfdmarc, method, comment, phash = domain
                        console.rule(f"[bold grey][ {domain_name} ][/bold grey]", style="grey")
                        console.print(f"[dim]🌐 Domain:[/dim] [bold][link=https://{domain_name}]{domain_name}[/link][/bold]")
                        console.print(f"[dim]✅ Http status:[/dim] [bold]{http_status}[/bold]")
                        console.print(f"[dim]🔄 Http method:[/dim] [bold]{method}[/bold]")
                        console.print(f"[dim]🖥️ IP:[/dim] [bold]{ip}[/bold]")
                        console.print(f"[dim]🏷️ Title:[/dim] [bold]{title}[/bold]")
                        console.print(f"[dim]🛠️ Tech:[/dim]", end=" ")
                        tech=str(techno)

                        for index, techsplit in enumerate(tech.split(",")):
                            console.print(f"[black on grey100]{techsplit}[/black on grey100]", end=" " if index < len(tech.split(",")) - 1 else "\n")

                        #console.print(f"[dim]Open port:[/dim] [bold]{open_port}[/bold]")
                        console.print("[dim]🔓 Open port:[/dim]", end=" ")
                        open_ports=str(open_port)
                        #print(f"{open_ports}")
                        for index, port in enumerate(open_ports.split(",")):
                            console.print(f"[black on grey100]{port}[/black on grey100]", end=" " if index < len(open_ports.split(",")) - 1 else "\n")
                        console.print(f"[dim]✉️ Spf/Dmarc:[/dim] [bold]{spfdmarc}[/bold]")

                        if comment:
                            console.print(f"[dim]📝 Comment:[/dim] [bold]{comment}[/bold]")
                        if screen:
                            #screenshot_panel = Panel("Screenshot available", title="Screenshot", border_style="green")
                            #console.print(screenshot_panel)
                            display_screenshot_with_imgcat(screen)
                            print("\n")
                        else:
                            print("No screenshot available.")
                            print("\n")

            else:
                print(f"❌ No domains found for program \033[1m{program_name}\033[0m.")
        else:
            print(f"❌ Program \033[1m{program_name}\033[0m not found.")
    else:
        print("❌ No program name provided.")

    cursor.close()
    conn.close()

def search(search_text, program_name):
    console = Console()
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM programs WHERE program_name = ?', (program_name,))
    program = cursor.fetchone()

    if not program:
        console.print(f"[bold red]❌ Program '{program_name}' not found.[/bold red]")
        cursor.close()
        conn.close()
        return

    program_id = program[0]

    query = '''
        SELECT domains.domain_name, domain_details.http_status, domain_details.ip, domain_details.title,
               domain_details.techno, domain_details.open_port, domain_details.screen, domain_details.spfdmarc,
               domain_details.method, domain_details.com
        FROM domains
        INNER JOIN domain_details ON domains.id = domain_details.domain_id
        WHERE domains.program_id = ?
        AND (
            domains.domain_name LIKE ?
            OR domain_details.http_status LIKE ?
            OR domain_details.ip LIKE ?
            OR domain_details.title LIKE ?
            OR domain_details.techno LIKE ?
            OR domain_details.open_port LIKE ?
            OR domain_details.screen LIKE ?
            OR domain_details.spfdmarc LIKE ?
            OR domain_details.method LIKE ?
            OR domain_details.com LIKE ?
        )
        ORDER BY domain_details.screen IS NOT NULL DESC,  -- D'abord ceux avec un screenshot
                 domain_details.ip IS NOT NULL DESC      -- Puis ceux avec une IP
    '''

    search_wildcard = f'%{search_text}%'
    cursor.execute(query, (
        program_id, search_wildcard, search_wildcard, search_wildcard, search_wildcard,
        search_wildcard, search_wildcard, search_wildcard, search_wildcard, search_wildcard, search_wildcard
    ))

    domains = cursor.fetchall()

    if domains:
        console.print(f"[bold green]📄 List of domains matching '{search_text}' in program '{program_name}':[/bold green]")
        for domain in domains:
            domain_name, http_status, ip, title, techno, open_port, screen, spfdmarc, method, com = domain
            console.rule(f"[bold grey][ {domain_name} ][/bold grey]", style="grey")
            console.print(f"[dim]🌐 Domain:[/dim] [bold][link=https://{domain_name}]{domain_name}[/link][/bold]")
            console.print(f"[dim]✅ Http status:[/dim] [bold]{http_status}[/bold]")
            console.print(f"[dim]🔄 Http method:[/dim] [bold]{method}[/bold]")
            console.print(f"[dim]🖥️ IP:[/dim] [bold]{ip}[/bold]")
            console.print(f"[dim]🏷️ Title:[/dim] [bold]{title}[/bold]")
            #console.print(f"[dim]Tech:[/dim] [bold]{techno}[/bold]")
            #console.print(f"[dim]Open port:[/dim] [bold]{open_port}[/bold]")
            console.print(f"[dim]🛠️ Tech:[/dim]", end=" ")
            tech=str(techno)
            for index, techsplit in enumerate(tech.split(",")):
                console.print(f"[black on grey100]{techsplit}[/black on grey100]", end=" " if index < len(tech.split(",")) - 1 else "\n")

            #console.print(f"[dim]Open port:[/dim] [bold]{open_port}[/bold]")
            console.print("[dim]🔓 Open port:[/dim]", end=" ")
            open_ports=str(open_port)
            for index, port in enumerate(open_ports.split(",")):
                console.print(f"[black on grey100]{port}[/black on grey100]", end=" " if index < len(open_ports.split(",")) - 1 else "\n")

            console.print(f"[dim]✉️ Spf/Dmarc:[/dim] [bold]{spfdmarc}[/bold]")

            if com:
                console.print(f"[dim]📝 Comment:[/dim] [bold]{com}[/bold]")

            if screen:
                display_screenshot_with_imgcat(screen)
                console.print("\n")
            else:
                console.print("[bold red]No screenshot available.[/bold red]")
                console.print("\n")
    else:
        console.print(f"[bold red]❌ No domains found containing '{search_text}' in any field in program '{program_name}'.[/bold red]")

    cursor.close()
    conn.close()


def llist(entity_type, program_name=None):

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    if entity_type == 'program':
        cursor.execute('''
            SELECT id, program_name, com FROM programs
        ''')
        programs = cursor.fetchall()

        if programs:
            print("\n📄 List of programs:")
            for program in programs:
                print(f"Program: \033[1m{program[1]}\033[0m - Comment: \033[1m{program[2]}\033[0m")
        else:
            print("❌ No programs found.")

    elif entity_type == 'domain':
        if program_name:
            cursor.execute('''
                SELECT id FROM programs WHERE program_name = ?
            ''', (program_name,))
            program = cursor.fetchone()

            if program:
                program_id = program[0]
                cursor.execute('''
                    SELECT domain_name FROM domains
                    WHERE program_id = ?
                    ORDER BY domain_name
                ''', (program_id,))
                domains = cursor.fetchall()

                if domains:
                    print(f"\n📄 List of domains for program '{program_name}':")
                    for domain in domains:
                        print(f"\033[1m{domain[0]}\033[0m")
                else:
                    print(f"❌ No domains found for program '{program_name}'.")
            else:
                print(f"❌ Program '{program_name}' not found.")
        else:
            print("❌ Please specify a program name to list domains.")

    elif entity_type == 'ip':
        if program_name:
            cursor.execute('''
                SELECT id FROM programs WHERE program_name = ?
            ''', (program_name,))
            program = cursor.fetchone()

            if program:
                program_id = program[0]
                cursor.execute('''
                    SELECT DISTINCT domain_details.ip FROM domain_details
                    JOIN domains ON domains.id = domain_details.domain_id
                    WHERE domains.program_id = ? AND domain_details.ip IS NOT NULL
                    ORDER BY domain_details.ip
                ''', (program_id,))
                ips = cursor.fetchall()

                if ips:
                    print(f"\n📄 List of IP addresses for program '{program_name}':")
                    for ip in ips:
                        print(f"\033[1m{ip[0]}\033[0m")
                else:
                    print(f"❌ No IP addresses found for program '{program_name}'.")
            else:
                print(f"❌ Program '{program_name}' not found.")
        else:
            print("❌ Please specify a program name to list IP addresses.")

    elif entity_type == 'url':
        if program_name:
            cursor.execute('''
                SELECT id FROM programs WHERE program_name = ?
            ''', (program_name,))
            program = cursor.fetchone()

            if program:
                program_id = program[0]
                cursor.execute('''
                    SELECT url FROM programs
                    WHERE id = ?
                ''', (program_id,))
                urls = cursor.fetchall()

                if urls:
                    print(f"\n📄 List of URLs for program '{program_name}':")
                    for url in urls:
                        print(f"\033[0m{url[0]}\033[0m")
                else:
                    print(f"❌ No URLs found for program '{program_name}'.")
            else:
                print(f"❌ Program '{program_name}' not found.")
        else:
            print("❌ Please specify a program name to list URLs.")

    else:
        print("❌ Invalid entity type. Use 'program', 'domain', 'ip', or 'url'.")

    cursor.close()
    conn.close()

def add_program(program_name):
    #conn = get_db_connection()
    #cursor = conn.cursor()
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT id FROM programs WHERE program_name = ?', (program_name,))
        existing_program = cursor.fetchone()

        if existing_program:
            print(f"⚠️  Program '{program_name}' already exists.")
        else:
            cursor.execute('INSERT INTO programs (program_name) VALUES (?)', (program_name,))
            conn.commit()
            print(f"✔️  Program '{program_name}' added successfully.")
    except Exception as e:
        print(f"❌ Failed to add program '{program_name}': {e}")
    finally:
        cursor.close()
        conn.close()

def main():

    if len(sys.argv) > 1:
        session = PromptSession()
        #print_formatted_text("\n【Welcome to ReconNinja v1.0 by _frHaKtal_】")
        #print_formatted_text("‼️ Press tab for autocompletion and available commands\n")
        lolcat("\n【Welcome to Recon-it v1.0 by _frHaKtal_】")
        lolcat("‼️ Press tab for autocompletion and available commands\n")

        setup_database()

        program_name = sys.argv[1]
        command_completer = CommandCompleter()

        add_program(program_name)
        while True:
            try:
                user_input = session.prompt(f'{program_name} ▶︎ ', completer=command_completer)
                parts = user_input.split()
                if parts:
                    command = parts[0]
                    args = parts[1:]

                    if command == 'add':
                        domains = []
                        for domain in args:
                            if '*.' in domain:
                                domain_enum = enum_domain(domain.lstrip('*.'),"passive")
                                domains.extend(domain_enum.splitlines())
                                print(f"✔️  \033[1m{len(domain_enum.splitlines())}\033[0m domain find")
                            else:
                                domains.append(domain)
                        maintest(domains, program_name)
                        #add_domains_in_parallel_multithread(program_name, domains)
                        #process_domains(domains)
                    elif command == 'show':
                        show(sys.argv[1])
                        #print(args[0])
                    elif command == 'add_url':
                        add_url(args[0], args[1])
                    elif command == 'search':
                        search(args[0],sys.argv[1])
                    elif command == 'list':
                        if args:
                            llist(args[0], sys.argv[1])
                            #print(args[0], sys.argv[1])
                        else:
                            print("❌ Usage: list [domain|program|ip|url]")
                    elif command == 'clear':
                        os.system('clear')
                    elif command == 'add_com':
                        if len(args) >= 3:
                            target_type = args[0]
                            target_name = args[1]
                            comment = " ".join(args[2:]) 
                            add_com(target_type, target_name, comment)
                        else:
                            print("❌ Usage: add_com [program|domain] [name] [comment]")
                    elif command == 'rm':
                        rm(args[0], args[1])
                    elif command == 'exit':
                        print("Exiting...")
                        break
            except (KeyboardInterrupt, EOFError):
                print("Exiting...")
                break
    else:

        llist('program')

if __name__ == "__main__":
    main()
