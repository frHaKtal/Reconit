#!/usr/bin/python3
import time
import sys
import os
import sqlite3
import subprocess
import base64
from enum_task import *
from setup_database import setup_database
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.box import MINIMAL
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse
import socketserver
import platform
import threading

# Configuration
DATABASE = 'database.db'
MAX_THREADS = 20

# Initialisation de la console Rich
console = Console()

# Dictionnaire contenant les commandes et leurs descriptions
commands_with_descriptions = {
    'exit': 'Exit the program',
    'add': 'Add domain1.com domain2.com or *.domain.com',
    'add_com': 'Add comment to domain or program (add_com domain/program domain.com "xx")',
    'rm': 'Remove a domain (without http) or program (rm domain/program xx)',
    'list': 'Domain of program list [domain|program|ip] [http_status:|techno:..]',
    'show': 'Show domain (list domain with screenshot)',
    'search': 'Search in domain list (search xx)',
    'clear': 'Clear screen',
}

class CommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        word_before_cursor = document.get_word_before_cursor()
        for command, description in commands_with_descriptions.items():
            if command.startswith(word_before_cursor):
                yield Completion(command, start_position=-len(word_before_cursor), display_meta=description)

@contextmanager
def get_db_connection():
    """Gère la connexion à la base de données."""
    conn = sqlite3.connect(DATABASE)
    try:
        yield conn
    finally:
        conn.close()

def run_command(command):
    """Exécute une commande shell et retourne la sortie."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout.splitlines()

def lolcat(text):
    """Affiche du texte avec lolcat."""
    os.system(f"echo '{text}' | lolcat")

def rm(entity_type, *entity_names):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    try:
        if entity_type == 'program':
            # Supprimer plusieurs programmes
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


def generate_html_report(domains_data, program_name):
    """Génère un rapport HTML avec les informations et les captures d'écran en colonnes, style Executive Suite."""
    # Liste des méthodes HTTP valides selon les standards
    VALID_HTTP_METHODS = {"GET", "POST", "HEAD", "OPTIONS", "TRACE", "PUT", "DELETE", "PATCH", "CONNECT"}

    style = """
        body {
            font-family: 'Inter', sans-serif;
            margin: 0;
            padding: 30px;
            background: linear-gradient(135deg, #e5e7eb 0%, #d1d5db 100%);
            color: #1f2a44;
            transition: background 0.3s ease, color 0.3s ease;
        }
        body.dark-mode {
            background: linear-gradient(135deg, #1f2a44 0%, #111827 100%);
            color: #e5e7eb;
        }
        h1 {
            color: #1e3a8a;
            text-align: center;
            font-size: 2.2em;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #1e3a8a;
            position: relative;
        }
        h1::after {
            content: '';
            position: absolute;
            bottom: -2px;
            left: 50%;
            transform: translateX(-50%);
            width: 40px;
            height: 2px;
            background: #2563eb;
        }
        body.dark-mode h1 {
            color: #60a5fa;
            border-bottom: 2px solid #60a5fa;
        }
        body.dark-mode h1::after {
            background: #93c5fd;
        }
        .container {
            max-width: 2200px;
            margin: 0 auto;
        }
        .header {
            position: sticky;
            top: 0;
            background: rgba(249, 250, 251, 0.9);
            backdrop-filter: blur(10px);
            z-index: 10;
            padding: 10px 0;
            transition: background 0.3s ease;
        }
        body.dark-mode .header {
            background: rgba(31, 41, 68, 0.9);
        }
        .tabs {
            display: flex;
            border-bottom: 2px solid #e5e7eb;
            margin-bottom: 10px;
        }
        body.dark-mode .tabs {
            border-bottom: 2px solid #4b5563;
        }
        .tab {
            padding: 8px 15px;
            background-color: #e5e7eb;
            color: #4b5563;
            border-radius: 5px 5px 0 0;
            margin-right: 5px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        .tab.active {
            background-color: #1e3a8a;
            color: #fff;
        }
        body.dark-mode .tab {
            background-color: #4b5563;
            color: #e5e7eb;
        }
        body.dark-mode .tab.active {
            background-color: #60a5fa;
            color: #1f2a44;
        }
        .search-bar {
            margin-bottom: 15px;
            text-align: center;
        }
        .search-bar input {
            padding: 10px 15px;
            width: 300px;
            max-width: 100%;
            border: 1px solid #d1d5db;
            border-radius: 6px;
            font-size: 1em;
            color: #1f2a44;
            background: rgba(255, 255, 255, 0.8);
            backdrop-filter: blur(5px);
        }
        body.dark-mode .search-bar input {
            border: 1px solid #4b5563;
            color: #e5e7eb;
            background: rgba(31, 41, 68, 0.8);
        }
        .search-bar input:focus {
            outline: none;
            border-color: #2563eb;
        }
        body.dark-mode .search-bar input:focus {
            border-color: #93c5fd;
        }
        .theme-toggle {
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 8px 12px;
            background-color: #1e3a8a;
            color: #fff;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            transition: background-color 0.3s ease;
        }
        .theme-toggle:hover {
            background-color: #2563eb;
        }
        body.dark-mode .theme-toggle {
            background-color: #60a5fa;
            color: #1f2a44;
        }
        body.dark-mode .theme-toggle:hover {
            background-color: #93c5fd;
        }
        .domains-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 15px;
        }
        .domain-entry {
            background-color: #fff;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 10px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        body.dark-mode .domain-entry {
            background-color: #1f2a44;
            border: 1px solid #4b5563;
        }
        .domain-entry.hidden {
            display: none;
        }
        .domain-entry:hover {
            transform: translateY(-3px);
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.1);
        }
        .screenshot {
            margin-bottom: 8px;
            text-align: center;
        }
        .screenshot img {
            max-width: 100%;
            height: auto;
            border-radius: 6px;
            border: 1px solid #e5e7eb;
        }
        body.dark-mode .screenshot img {
            border: 1px solid #4b5563;
        }
        .domain-info {
            display: block;
        }
        .domain-info strong.domain {
            font-weight: 600;
            color: #1e3a8a;
        }
        body.dark-mode .domain-info strong.domain {
            color: #60a5fa;
        }
        .domain-info strong.tech {
            color: #2563eb;
        }
        body.dark-mode .domain-info strong.tech {
            color: #93c5fd;
        }
        .domain-info strong.port {
            color: #16a34a;
        }
        body.dark-mode .domain-info strong.port {
            color: #4ade80;
        }
        a {
            color: #1e3a8a;
            text-decoration: none;
        }
        body.dark-mode a {
            color: #60a5fa;
        }
        a:hover {
            text-decoration: underline;
            color: #2563eb;
        }
        body.dark-mode a:hover {
            color: #93c5fd;
        }
        .tech-tag, .port-tag, .method-tag {
            background-color: #e5e7eb;
            color: #4b5563;
            padding: 2px 6px;
            border-radius: 5px;
            margin-right: 5px;
            font-size: 0.85em;
            display: inline-block;
            border: 1px solid #d1d5db;
        }
        body.dark-mode .tech-tag, body.dark-mode .port-tag, body.dark-mode .method-tag {
            background-color: #4b5563;
            color: #e5e7eb;
            border: 1px solid #6b7280;
        }
        .scroll-top {
            position: fixed;
            bottom: 20px;
            right: 20px;
            padding: 10px 15px;
            background-color: #1e3a8a;
            color: #fff;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            display: none;
            transition: background-color 0.3s ease;
        }
        .scroll-top:hover {
            background-color: #2563eb;
        }
        body.dark-mode .scroll-top {
            background-color: #60a5fa;
            color: #1f2a44;
        }
        body.dark-mode .scroll-top:hover {
            background-color: #93c5fd;
        }
        /* Media Queries pour ajuster la mise en page sur différents écrans */
        @media (min-width: 2100px) {
            .domains-grid {
                grid-template-columns: repeat(7, 1fr);
            }
        }
        @media (min-width: 1800px) and (max-width: 2099px) {
            .domains-grid {
                grid-template-columns: repeat(6, 1fr);
            }
        }
        @media (min-width: 1500px) and (max-width: 1799px) {
            .domains-grid {
                grid-template-columns: repeat(5, 1fr);
            }
        }
        @media (min-width: 1200px) and (max-width: 1499px) {
            .domains-grid {
                grid-template-columns: repeat(4, 1fr);
            }
        }
        @media (min-width: 900px) and (max-width: 1199px) {
            .domains-grid {
                grid-template-columns: repeat(3, 1fr);
            }
        }
        @media (min-width: 600px) and (max-width: 899px) {
            .domains-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }
        @media (max-width: 599px) {
            .domains-grid {
                grid-template-columns: 1fr;
            }
        }
        @media (max-width: 767px) {
            body {
                padding: 15px;
            }
            h1 {
                font-size: 1.8em;
            }
            .tab {
                padding: 8px 15px;
                font-size: 0.9em;
            }
            .domain-entry {
                padding: 10px;
            }
            .domain-info {
                font-size: 0.9em;
            }
        }
        @media (max-width: 479px) {
            h1 {
                font-size: 1.5em;
            }
            .tab {
                padding: 6px 10px;
                font-size: 0.85em;
            }
            .domain-entry {
                padding: 8px;
            }
            .domain-info {
                font-size: 0.85em;
            }
            .theme-toggle {
                top: 10px;
                right: 10px;
            }
        }
    """

    # Nettoyer le nom du programme pour les identifiants HTML (remplacer les tirets par des underscores)
    tab_id = program_name.lower().replace('-', '_')

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Recon-it Report - {program_name}</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
        <style>
            {style}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Recon-it Report for Program: {program_name}</h1>
                <div class="tabs">
                    <div class="tab active">{program_name}</div>
                </div>
                <div class="search-bar">
                    <input type="text" id="search-input" placeholder="Search domains..." onkeyup="searchDomains()">
                </div>
            </div>
            <div id="tab-{tab_id}" class="tab-content active">
                <div class="domains-grid" id="domains-{tab_id}">
    """

    for domain_data in domains_data:
        #domain_name, http_status, ip, title, techno, open_port, screen, spfdmarc, ssltls, method, comment = domain_data
        domain_name, http_status, ip, title, techno, open_port, screen, phash, spfdmarc, ssltls, method, comment = domain_data
        info_text = (
            f"<strong class='domain'><svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'></circle><line x1='2' y1='12' x2='22' y2='12'></line><path d='M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z'></path></svg> Domain:</strong> <a href='https://{domain_name}' target='_blank'>{domain_name}</a><br>"
            f"<strong><svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='20 6 9 17 4 12'></polyline></svg> Http status:</strong> {http_status}<br>"
        )

        # Gestion conditionnelle des méthodes HTTP
        method_text = "<strong><svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M4 12h16'></path><path d='M12 4v16'></path></svg> Http method:</strong> "
        # Nettoyer la chaîne method pour supprimer le préfixe comme "https:" et extraire les méthodes
        methods = []
        if method and method != "None":
            # Supprimer le préfixe (par exemple, "https:") et tout ce qui est avant les méthodes
            method_cleaned = method.split(":")[-1].strip() if ":" in method else method.strip()
            # Séparer les méthodes sur les virgules et nettoyer les espaces
            methods = [m.strip().upper() for m in method_cleaned.split(",") if m.strip()]  # Convertir en majuscules pour comparaison

        # Vérifier si au moins une méthode valide existe dans la liste
        valid_methods = [m for m in methods if m in VALID_HTTP_METHODS]
        if valid_methods:  # Si des méthodes valides existent
            # Entourer chaque méthode valide d'une balise method-tag
            method_text += "".join(f"<span class='method-tag'>{m}</span>" for m in valid_methods)
        else:
            # "No method found" ne doit pas être entouré d'une balise method-tag
            method_text += "No methods found"
        info_text += method_text + "<br>"

        info_text += (
            f"<strong><svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M6 9H4.5a2.5 2.5 0 0 1 0-5H6'></path><path d='M18 9h1.5a2.5 2.5 0 0 0 0-5H18'></path><path d='M4 22h16'></path><path d='M10 14.66V17c0 1.1-.9 2-2 2H4'></path><path d='M10 14.66L9.5 12c-.5-1-1.5-2-2.5-2H4'></path><path d='M14 14.66V17c0 1.1.9 2 2 2h4'></path><path d='M14 14.66L14.5 12c.5-1 1.5-2 2.5-2H20'></path></svg> Ssl/tls:</strong> {ssltls}<br>"
            f"<strong><svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2'></path><circle cx='12' cy='7' r='4'></circle></svg> IP:</strong> {ip}<br>"
            f"<strong><svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z'></path><line x1='4' y1='22' x2='4' y2='15'></line></svg> Title:</strong> {title}<br>"
            #f"<strong><svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><rect x='3' y='3' width='18' height='18' rx='2' ry='2'></rect><circle cx='8.5' cy='8.5' r='1.5'></circle><polyline points='21 15 16 10 5 21'></polyline></svg> Phash:</strong> {phash}<br>"
        )

        tech_text = "<strong class='tech'><svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='3'></circle><path d='M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l-.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h-.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l-.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v-.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l-.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z'></path></svg> Tech:</strong> "
        tech = str(techno)
        if tech and tech != "None":
            tech_text += "".join(
                f"<span class='tech-tag'>{techsplit.strip()}</span>"
                for techsplit in tech.split(",")
            )
        else:
            tech_text += "None"
        info_text += tech_text + "<br>"

        ports_text = "<strong class='port'><svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21 2H3v6h18V2z'></path><path d='M7 14v6'></path><path d='M17 14v6'></path></svg> Open port:</strong> "
        open_ports = str(open_port)
        if open_ports and open_ports != "None":
            ports_text += "".join(
                f"<span class='port-tag'>{port.strip()}</span>"
                for port in open_ports.split(",")
            )
        else:
            ports_text += "None"
        info_text += ports_text + "<br>"

        info_text += f"<strong><svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z'></path><polyline points='22,6 12,13 2,6'></polyline></svg> Spf/Dmarc:</strong> {spfdmarc}<br>"
        if comment:
            info_text += f"<strong><svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z'></path></svg> Comment:</strong> {comment}"

        screenshot_html = ""
        if screen:
            screenshot_html = f'<img src="data:image/png;base64,{screen}" alt="Screenshot" loading="lazy">'
        else:
            screenshot_html = "No screenshot available."

        html_content += f"""
                    <div class="domain-entry">
                        <div class="screenshot">{screenshot_html}</div>
                        <div class="domain-info">{info_text}</div>
                    </div>
        """

    html_content += """
                </div>
            </div>
            <button class="theme-toggle" onclick="toggleTheme()">Toggle Dark Mode</button>
            <button class="scroll-top" id="scroll-top" onclick="scrollToTop()">⬆ Top</button>
        </div>
        <script>
            window.onload = function() {
                window.addEventListener('scroll', toggleScrollTopButton);
            };

            function searchDomains() {
                const searchInput = document.getElementById('search-input').value.toLowerCase();
                const entries = document.getElementsByClassName('domain-entry');
                Array.from(entries).forEach(entry => {
                    const text = entry.textContent.toLowerCase();
                    if (text.includes(searchInput)) {
                        entry.classList.remove('hidden');
                        entry.style.display = 'block';
                    } else {
                        entry.classList.add('hidden');
                        entry.style.display = 'none';
                    }
                });
            }

            function toggleTheme() {
                document.body.classList.toggle('dark-mode');
            }

            function toggleScrollTopButton() {
                const scrollTopButton = document.getElementById('scroll-top');
                if (window.scrollY > 300) {
                    scrollTopButton.style.display = 'block';
                } else {
                    scrollTopButton.style.display = 'none';
                }
            }

            function scrollToTop() {
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }
        </script>
    </body>
    </html>
    """
    return html_content


# Fonction pour démarrer un serveur web temporaire
class TempHTTPRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, html_content=None, **kwargs):
        self.html_content = html_content
        super().__init__(*args, **kwargs)

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(self.html_content.encode("utf-8"))

def start_temp_web_server(html_content, port=8000, duration=10):
    """Démarre un serveur web temporaire pour servir le rapport HTML."""
    server_address = ('', port)
    httpd = HTTPServer(server_address, lambda *args, **kwargs: TempHTTPRequestHandler(*args, html_content=html_content, **kwargs))

    # Démarrer le serveur dans un thread séparé
    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    # Afficher l'URL avec l'IP publique de votre VPS
    vps_ip = "75.119.141.158"  # Remplacez par l'IP publique de votre VPS
    url = f"http://{vps_ip}:{port}/"
    console.print(f"[bold green]Please open this URL in your browser: {url}[/bold green]")
    # Note : Vous pouvez copier-coller cette URL dans votre navigateur local

    # Attendre un certain temps avant d'arrêter le serveur
    time.sleep(duration)
    httpd.shutdown()
    httpd.server_close()
    console.print("[bold green]Temporary web server stopped.[/bold green]")

def enum_domain(domain_name, method="passive"):
    """Enumère les sous-domaines d'un domaine."""
    result_lines = set()

    if method == "passive":
        console.print(f"❗️ Enumeration passive for domain: [bold]{domain_name}[/bold]")
        tools = {
            "Subfinder": f"subfinder -d {domain_name} -silent -all -recursive",
            "Amass": f"amass enum -passive -d {domain_name}",
        }
    else:
        console.print(f"❗️ Enumeration active for domain: [bold]{domain_name}[/bold]")
        tools = {
            "Shuffledns": f"shuffledns -d {domain_name} -list all.txt -r resolvers.txt",
        }

    for tool, command in tools.items():
        console.print(f"✔️  {tool}")
        result = run_command(command)
        result_lines.update(result)

    return "\n".join(sorted(result_lines))

def display_screenshot_with_imgcat(screenshot_data, width=50):
    """Affiche une capture d'écran avec imgcat."""
    if not screenshot_data:
        console.print("[bold red]No screenshot available.[/bold red]")
        return

    try:
        image_data = base64.b64decode(screenshot_data)
        temp_image_path = "/tmp/temp_screenshot.png"
        with open(temp_image_path, "wb") as img_file:
            img_file.write(image_data)

        if subprocess.run("command -v imgcat", shell=True, capture_output=True).returncode == 0:
            subprocess.run(["imgcat", "--width", str(width), temp_image_path])
        else:
            console.print(f"[yellow]⚠️ imgcat not available. Screenshot saved to {temp_image_path}[/yellow]")
            return

        os.remove(temp_image_path)
    except Exception as e:
        console.print(f"❌ Error displaying screenshot: {e}")

def display_screenshot_with_imgcattt(screenshot_data):
    """Affiche une capture d'écran avec imgcat."""
    try:
        image_data = base64.b64decode(screenshot_data)
        temp_image_path = "/tmp/temp_screenshot.png"
        with open(temp_image_path, "wb") as img_file:
            img_file.write(image_data)
        os.system(f"imgcat {temp_image_path}")
        #os.system(f'kitty +kitten icat "{temp_image_path}"')
        os.remove(temp_image_path)
    except Exception as e:
        console.print(f"❌ Error displaying screenshot: {e}")


def add_program(program_name):
    """Ajoute un programme à la base de données."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT OR IGNORE INTO programs (program_name) VALUES (?)', (program_name,))
            conn.commit()
            console.print(f"✔️  Program '[bold]{program_name}[/bold]' added successfully.")
        except Exception as e:
            console.print(f"❌ Failed to add program '[bold]{program_name}[/bold]': {e}")




def show(program_name):
    """Génère un rapport HTML pour un programme."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM programs WHERE program_name = ?', (program_name,))
        program = cursor.fetchone()

        if not program:
            return

        program_id = program[0]
        cursor.execute('''
            SELECT domains.domain_name, domain_details.http_status, domain_details.ip, domain_details.title,
                   domain_details.techno, domain_details.open_port, domain_details.screen, domain_details.phash,
                   domain_details.spfdmarc, domain_details.ssltls, domain_details.method, domain_details.com
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
            html_content = generate_html_report(domains, program_name)
            threading.Thread(target=start_temp_web_server, args=(html_content,), daemon=True).start()

# Mise à jour de la fonction show
def showw(program_name):
    """Affiche les détails d'un programme."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM programs WHERE program_name = ?', (program_name,))
        program = cursor.fetchone()

        if not program:
            console.print(f"❌ Program '[bold]{program_name}[/bold]' not found.")
            return

        program_id = program[0]
        cursor.execute('SELECT COUNT(*) FROM domains WHERE program_id = ?', (program_id,))
        domain_count = cursor.fetchone()[0]
        console.print(f"📝 Number of domains for program '[bold]{program_name}[/bold]': [bold]{domain_count}[/bold]")

        cursor.execute('''
            SELECT domains.domain_name, domain_details.http_status, domain_details.ip, domain_details.title,
                   domain_details.techno, domain_details.open_port, domain_details.screen, domain_details.phash,
                   domain_details.spfdmarc, domain_details.ssltls, domain_details.method, domain_details.com
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
            console.print(f"\n📄 List of domains for program '[bold]{program_name}[/bold]':")
            for domain in domains:
                domain_name, http_status, ip, title, techno, open_port, screen, phash, spfdmarc, ssltls, method, comment = domain
                console.rule(f"[bold grey][ {domain_name} ][/bold grey]", style="grey")
                console.print(f"[dim]🌐 Domain:[/dim] [bold][link=https://{domain_name}]{domain_name}[/link][/bold]")
                console.print(f"[dim]✅ Http status:[/dim] [bold]{http_status}[/bold]")
                console.print(f"[dim]🔄 Http method:[/dim] [bold]{method}[/bold]")
                console.print(f"[dim]📜 Ssl/tls:[/dim] [bold]{ssltls}[/bold]")
                console.print(f"[dim]🖥️ IP:[/dim] [bold]{ip}[/bold]")
                console.print(f"[dim]🏷️ Title:[/dim] [bold]{title}[/bold]")

                console.print(f"[dim]🛠️ Tech:[/dim]", end=" ")
                tech = str(techno)
                for techsplit in tech.split(","):
                    console.print(f"[grey85 on black][black on grey85]{techsplit}[/black on grey85]", end=" ")
                console.print()

                console.print(f"[dim]🔓 Open port:[/dim]", end=" ")
                open_ports = str(open_port)
                for port in open_ports.split(","):
                    console.print(f"[grey85 on black][black on grey85]{port}[/black on grey85]", end=" ")
                console.print()

                console.print(f"[dim]✉️ Spf/Dmarc:[/dim] [bold]{spfdmarc}[/bold]")
                if comment:
                    console.print(f"[dim]📝 Comment:[/dim] [bold]{comment}[/bold]")
                if screen:
                    display_screenshot_with_imgcat(screen)
                else:
                    console.print("[bold red]No screenshot available.[/bold red]")

            # Générer le rapport HTML et l'ouvrir dans le navigateur
            console.print(f"\n📄 Generating HTML report for program '[bold]{program_name}[/bold]':")
            html_content = generate_html_report(domains, program_name)
            threading.Thread(target=start_temp_web_server, args=(html_content,), daemon=True).start()
        else:
            console.print(f"❌ No domains found for program '[bold]{program_name}[/bold]'.")

def search(search_text, program_name, style="dark_minimal"):
    """Recherche dans la liste des domaines et affiche dans le terminal."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM programs WHERE program_name = ?', (program_name,))
        program = cursor.fetchone()

        if not program:
            console.print(f"❌ Program '[bold]{program_name}[/bold]' not found.")
            return

        program_id = program[0]
        search_wildcard = f'%{search_text}%'
        cursor.execute('''
            SELECT domains.domain_name, domain_details.http_status, domain_details.ip, domain_details.title,
                   domain_details.techno, domain_details.open_port, domain_details.screen, domain_details.spfdmarc,
                   domain_details.ssltls, domain_details.method, domain_details.com
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
                OR domain_details.ssltls LIKE ?
                OR domain_details.method LIKE ?
                OR domain_details.com LIKE ?
            )
            ORDER BY domain_details.screen IS NOT NULL DESC,
                     domain_details.ip IS NOT NULL DESC
        ''', (program_id, search_wildcard, search_wildcard, search_wildcard, search_wildcard,
              search_wildcard, search_wildcard, search_wildcard, search_wildcard, search_wildcard, search_wildcard, search_wildcard))
        domains = cursor.fetchall()

        if domains:
            console.print(f"[bold green]📄 List of domains matching '[bold]{search_text}[/bold]' in program '[bold]{program_name}[/bold]':[/bold green]")
            for domain in domains:
                domain_name, http_status, ip, title, techno, open_port, screen, spfdmarc, ssltls, method, com = domain
                console.rule(f"[bold grey][ {domain_name} ][/bold grey]", style="grey")

                info_text = (
                    f"[dim]🌐 Domain:[/dim] [bold][link=https://{domain_name}]{domain_name}[/link][/bold]\n"
                    f"[dim]✅ Status:[/dim] {http_status}\n"
                    f"[dim]🔄 Method:[/dim] {method}\n"
                    f"[dim]📜 SSL/TLS:[/dim] {ssltls}\n"
                    f"[dim]🖥️ IP:[/dim] {ip}\n"
                    f"[dim]🏷️ Title:[/dim] {title}\n"
                )

                console.print(f"[dim]🛠️ Tech:[/dim]", end=" ")
                tech = str(techno)
                if tech and tech != "None":
                    for techsplit in tech.split(","):
                        console.print(f"[grey85 on black][black on grey85]{techsplit.strip()}[/black on grey85]", end=" ")
                else:
                    console.print("[red]None[/red]")
                console.print()

                console.print(f"[dim]🔓 Open port:[/dim]", end=" ")
                open_ports = str(open_port)
                if open_ports and open_ports != "None":
                    for port in open_ports.split(","):
                        console.print(f"[grey85 on black][black on grey85]{port.strip()}[/black on grey85]", end=" ")
                else:
                    console.print("[red]None[/red]")
                console.print()

                console.print(f"[dim]✉️ Spf/Dmarc:[/dim] [bold]{spfdmarc}[/bold]")
                if com:
                    console.print(f"[dim]📝 Comment:[/dim] [bold]{com}[/bold]")

                if screen:
                    display_screenshot_with_imgcat(screen)
                else:
                    console.print("[dim]🖼️ Screenshot:[/dim] [red]Not available[/red]")
                console.print()
        else:
            console.print(f"[bold red]❌ No domains found containing '[bold]{search_text}[/bold]' in any field in program '[bold]{program_name}[/bold]'.[/bold red]")


def add_com(target_type, target_name, comment):
    """
    Ajoute ou met à jour un commentaire pour un programme ou un domaine.
    :param target_type: Le type de cible ('program' ou 'domain')
    :param target_name: Le nom du programme ou du domaine
    :param comment: Le commentaire à ajouter ou mettre à jour
    """
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    try:
        if target_type == 'program':
            # Vérifier si le programme existe
            cursor.execute('SELECT id FROM programs WHERE program_name = ?', (target_name,))
            program = cursor.fetchone()

            if program:
                program_id = program[0]
                # Ajouter ou mettre à jour le commentaire du programme
                cursor.execute('UPDATE programs SET com = ? WHERE id = ?', (comment, program_id))
                conn.commit()
                print(f"✔️ Comment added to program '{target_name}'")
            else:
                print(f"❌ Program '{target_name}' not found.")
        elif target_type == 'domain':
            # Vérifier si le domaine existe
            cursor.execute('SELECT id FROM domains WHERE domain_name = ?', (target_name,))
            domain = cursor.fetchone()

            if domain:
                domain_id = domain[0]
                # Ajouter ou mettre à jour le commentaire du domaine
                cursor.execute('UPDATE domain_details SET com = ? WHERE domain_id = ?', (comment, domain_id))
                conn.commit()
                print(f"✔️ Comment added to domain '{target_name}'")
            else:
                print(f"❌ Domain '{target_name}' not found.")
        else:
            print(f"❌ Invalid target type. Use 'program' or 'domain'.")

    finally:
        # Fermer le curseur avant la connexion
        cursor.close()
        conn.close()

def search(search_text, program_name):
    """Recherche dans la liste des domaines."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM programs WHERE program_name = ?', (program_name,))
        program = cursor.fetchone()

        if not program:
            console.print(f"❌ Program '[bold]{program_name}[/bold]' not found.")
            return

        program_id = program[0]
        search_wildcard = f'%{search_text}%'
        cursor.execute('''
            SELECT domains.domain_name, domain_details.http_status, domain_details.ip, domain_details.title,
                   domain_details.techno, domain_details.open_port, domain_details.screen, domain_details.spfdmarc,
                   domain_details.ssltls, domain_details.method, domain_details.com
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
                OR domain_details.ssltls LIKE ?
                OR domain_details.method LIKE ?
                OR domain_details.com LIKE ?
            )
            ORDER BY domain_details.screen IS NOT NULL DESC,
                     domain_details.ip IS NOT NULL DESC
        ''', (program_id, search_wildcard, search_wildcard, search_wildcard, search_wildcard,
              search_wildcard, search_wildcard, search_wildcard, search_wildcard, search_wildcard, search_wildcard, search_wildcard))
        domains = cursor.fetchall()

        if domains:
            console.print(f"[bold green]📄 List of domains matching '[bold]{search_text}[/bold]' in program '[bold]{program_name}[/bold]':[/bold green]")
            for domain in domains:
                domain_name, http_status, ip, title, techno, open_port, screen, spfdmarc, ssltls, method, com = domain
                console.rule(f"[bold grey][ {domain_name} ][/bold grey]", style="grey")
                console.print(f"[dim]🌐 Domain:[/dim] [bold][link=https://{domain_name}]{domain_name}[/link][/bold]")
                console.print(f"[dim]✅ Http status:[/dim] [bold]{http_status}[/bold]")
                console.print(f"[dim]🔄 Http method:[/dim] [bold]{method}[/bold]")
                console.print(f"[dim]📜 Ssl/tls:[/dim] [bold]{ssltls}[/bold]")
                console.print(f"[dim]🖥️ IP:[/dim] [bold]{ip}[/bold]")
                console.print(f"[dim]🏷️ Title:[/dim] [bold]{title}[/bold]")

                # Affichage des technologies avec le style spécifié
                console.print(f"[dim]🛠️ Tech:[/dim]", end=" ")
                tech = str(techno)
                for techsplit in tech.split(","):
                    console.print(f"[black on grey100]{techsplit}[/black on grey100]", end=" ")
                console.print()  # Nouvelle ligne

                # Affichage des ports ouverts avec le style spécifié
                console.print(f"[dim]🔓 Open port:[/dim]", end=" ")
                open_ports = str(open_port)
                for port in open_ports.split(","):
                    console.print(f"[black on grey100]{port}[/black on grey100]", end=" ")
                console.print()  # Nouvelle ligne

                console.print(f"[dim]✉️ Spf/Dmarc:[/dim] [bold]{spfdmarc}[/bold]")
                if com:
                    console.print(f"[dim]📝 Comment:[/dim] [bold]{com}[/bold]")

                if screen:
                    display_screenshot_with_imgcat(screen)
                else:
                    console.print("[bold red]No screenshot available.[/bold red]")
        else:
            console.print(f"[bold red]❌ No domains found containing '[bold]{search_text}[/bold]' in any field in program '[bold]{program_name}[/bold]'.[/bold red]")



def llist(entity_type, program_name=None, filters=None):
    """
    Liste les programmes, domaines, IP ou URLs avec des filtres optionnels.

    :param entity_type: Type d'entité à lister ('program', 'domain', 'ip', 'url').
    :param program_name: Nom du programme (obligatoire pour 'domain', 'ip', 'url').
    :param filters: Chaîne de filtres au format "critère:valeur" (ex: "http_status:200,techno:wordpress").
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        clipboard_content = ""

        # Découper les filtres s'ils sont fournis
        filter_dict = {}
        if filters:
            for filter_item in filters.split(","):
                if ":" in filter_item:
                    key, value = filter_item.split(":", 1)
                    filter_dict[key.strip()] = value.strip()

        if entity_type == 'program':
            cursor.execute('SELECT id, program_name, com FROM programs')
            programs = cursor.fetchall()

            if programs:
                console.print("\n📄 List of programs:")
                for program in programs:
                    console.print(f"Program: [bold]{program[1]}[/bold] - Comment: [bold]{program[2]}[/bold]")
            else:
                console.print("❌ No programs found.")

        elif entity_type == 'domain':
            if program_name:
                cursor.execute('SELECT id FROM programs WHERE program_name = ?', (program_name,))
                program = cursor.fetchone()

                if program:
                    program_id = program[0]
                    query = '''
                        SELECT domains.domain_name
                        FROM domains
                        INNER JOIN domain_details ON domains.id = domain_details.domain_id
                        WHERE domains.program_id = ?
                    '''
                    params = [program_id]

                    # Ajouter des filtres dynamiques
                    for key, value in filter_dict.items():
                        if key in ["http_status", "techno", "ip", "title", "open_port", "spfdmarc", "ssltls", "method", "com"]:
                            query += f" AND domain_details.{key} LIKE ?"
                            params.append(f"%{value}%")

                    query += " ORDER BY domains.domain_name"
                    cursor.execute(query, params)
                    domains = cursor.fetchall()

                    if domains:
                        console.print(f"\n📄 List of domains for program '[bold]{program_name}[/bold]' with filters '[bold]{filters}[/bold]':")
                        for domain in domains:
                            domain_name = domain[0]
                            console.print(f"[bold]{domain_name}[/bold]")
                            clipboard_content += f"{domain_name}\n"
                    else:
                        console.print(f"❌ No domains found for program '[bold]{program_name}[/bold]' with filters '[bold]{filters}[/bold]'.")
                else:
                    console.print(f"❌ Program '[bold]{program_name}[/bold]' not found.")
            else:
                console.print("❌ Please specify a program name to list domains.")

        elif entity_type == 'ip':
            if program_name:
                cursor.execute('SELECT id FROM programs WHERE program_name = ?', (program_name,))
                program = cursor.fetchone()

                if program:
                    program_id = program[0]
                    query = '''
                        SELECT DISTINCT domain_details.ip FROM domain_details
                        JOIN domains ON domains.id = domain_details.domain_id
                        WHERE domains.program_id = ? AND domain_details.ip IS NOT NULL
                    '''
                    params = [program_id]

                    # Ajouter des filtres dynamiques
                    for key, value in filter_dict.items():
                        if key in ["http_status", "techno", "ip", "title", "open_port", "spfdmarc", "ssltls", "method", "com"]:
                            query += f" AND domain_details.{key} LIKE ?"
                            params.append(f"%{value}%")

                    query += " ORDER BY domain_details.ip"
                    cursor.execute(query, params)
                    ips = cursor.fetchall()

                    if ips:
                        console.print(f"\n📄 List of IP addresses for program '[bold]{program_name}[/bold]' with filters '[bold]{filters}[/bold]':")
                        for ip in ips:
                            console.print(f"[bold]{ip[0]}[/bold]")
                            clipboard_content += f"{ip[0]}\n"
                    else:
                        console.print(f"❌ No IP addresses found for program '[bold]{program_name}[/bold]' with filters '[bold]{filters}[/bold]'.")
                else:
                    console.print(f"❌ Program '[bold]{program_name}[/bold]' not found.")
            else:
                console.print("❌ Please specify a program name to list IP addresses.")

        elif entity_type == 'url':
            if program_name:
                cursor.execute('SELECT id FROM programs WHERE program_name = ?', (program_name,))
                program = cursor.fetchone()

                if program:
                    program_id = program[0]
                    cursor.execute('SELECT url FROM programs WHERE id = ?', (program_id,))
                    urls = cursor.fetchall()

                    if urls:
                        console.print(f"\n📄 List of URLs for program '[bold]{program_name}[/bold]':")
                        for url in urls:
                            console.print(f"[bold]{url[0]}[/bold]")
                    else:
                        console.print(f"❌ No URLs found for program '[bold]{program_name}[/bold]'.")
                else:
                    console.print(f"❌ Program '[bold]{program_name}[/bold]' not found.")
            else:
                console.print("❌ Please specify a program name to list URLs.")

        else:
            console.print("❌ Invalid entity type. Use 'program', 'domain', 'ip', or 'url'.")

        # Copier dans le presse-papier avec iTerm2
        if clipboard_content.strip():
            try:
                b64_text = base64.b64encode(clipboard_content.encode()).decode()
                iterm_clipboard_cmd = f'echo "\\e]52;c;{b64_text}\\a"'
                subprocess.run(iterm_clipboard_cmd, shell=True, check=True)
                console.print("📋 Copied to clipboard (iTerm2)!")
            except Exception as e:
                console.print(f"⚠️ Error copying to clipboard: {e}")


def lllist(entity_type, program_name=None):
    """Liste les programmes, domaines, IP ou URLs."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        clipboard_content = ""

        if entity_type == 'program':
            cursor.execute('SELECT id, program_name, com FROM programs')
            programs = cursor.fetchall()

            if programs:
                console.print("\n📄 List of programs:")
                for program in programs:
                    console.print(f"Program: [bold]{program[1]}[/bold] - Comment: [bold]{program[2]}[/bold]")
            else:
                console.print("❌ No programs found.")

        elif entity_type == 'domain':
            if program_name:
                cursor.execute('SELECT id FROM programs WHERE program_name = ?', (program_name,))
                program = cursor.fetchone()

                if program:
                    program_id = program[0]
                    cursor.execute('SELECT domain_name FROM domains WHERE program_id = ? ORDER BY domain_name', (program_id,))
                    domains = cursor.fetchall()

                    if domains:
                        console.print(f"\n📄 List of domains for program '[bold]{program_name}[/bold]':")
                        for domain in domains:
                            console.print(f"[bold]{domain[0]}[/bold]")
                            clipboard_content += f"{domain[0]}\n"
                    else:
                        console.print(f"❌ No domains found for program '[bold]{program_name}[/bold]'.")
                else:
                    console.print(f"❌ Program '[bold]{program_name}[/bold]' not found.")
            else:
                console.print("❌ Please specify a program name to list domains.")

        elif entity_type == 'ip':
            if program_name:
                cursor.execute('SELECT id FROM programs WHERE program_name = ?', (program_name,))
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
                        console.print(f"\n📄 List of IP addresses for program '[bold]{program_name}[/bold]':")
                        for ip in ips:
                            console.print(f"[bold]{ip[0]}[/bold]")
                            clipboard_content += f"{ip[0]}\n"
                    else:
                        console.print(f"❌ No IP addresses found for program '[bold]{program_name}[/bold]'.")
                else:
                    console.print(f"❌ Program '[bold]{program_name}[/bold]' not found.")
            else:
                console.print("❌ Please specify a program name to list IP addresses.")

        elif entity_type == 'url':
            if program_name:
                cursor.execute('SELECT id FROM programs WHERE program_name = ?', (program_name,))
                program = cursor.fetchone()

                if program:
                    program_id = program[0]
                    cursor.execute('SELECT url FROM programs WHERE id = ?', (program_id,))
                    urls = cursor.fetchall()

                    if urls:
                        console.print(f"\n📄 List of URLs for program '[bold]{program_name}[/bold]':")
                        for url in urls:
                            console.print(f"[bold]{url[0]}[/bold]")
                    else:
                        console.print(f"❌ No URLs found for program '[bold]{program_name}[/bold]'.")
                else:
                    console.print(f"❌ Program '[bold]{program_name}[/bold]' not found.")
            else:
                console.print("❌ Please specify a program name to list URLs.")

        else:
            console.print("❌ Invalid entity type. Use 'program', 'domain', 'ip', or 'url'.")

        # Copier dans le presse-papier avec iTerm2
        if clipboard_content.strip():
            try:
                b64_text = base64.b64encode(clipboard_content.encode()).decode()
                iterm_clipboard_cmd = f'echo "\\e]52;c;{b64_text}\\a"'
                subprocess.run(iterm_clipboard_cmd, shell=True, check=True)
                console.print("📋 Copied to clipboard (iTerm2)!")
            except Exception as e:
                console.print(f"⚠️ Error copying to clipboard: {e}")

def main():
    """Fonction principale."""
    if len(sys.argv) > 1:
        session = PromptSession()
        lolcat("\n【Welcome to Recon-it v2.0 by _frHaKtal_】")
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
                                domain_enum = enum_domain(domain.lstrip('*.'), "passive")
                                domains.extend(domain_enum.splitlines())
                                console.print(f"✔️  [bold]{len(domain_enum.splitlines())}[/bold] domains found.")
                            else:
                                domains.append(domain)
                        maintest(domains, program_name)
                        #add_domains_in_parallel(program_name, domains)
                    elif command == 'show':
                        #style="executive_suite"
                        show(program_name)
                    elif command == 'search':
                        search(args[0], program_name)
                    elif command == 'list':
                        if args:
                            if len(args) >= 2:
                                llist(args[0], program_name, args[1])
                            else:
                                llist(args[0], program_name)
                        else:
                            console.print("❌ Usage: list [domain|program|ip|url] [http_status:|techno]")

                    elif command == 'add_com':
                        if len(args) >= 3:
                            target_type = args[0]
                            target_name = args[1]
                            comment = " ".join(args[2:])  # Prendre le reste des arguments comme commentaire
                            add_com(target_type, target_name, comment)
                        else:
                            print("❌ Usage: add_com [program|domain] [name] [comment]")
                    elif command == 'rm':
                        rm(args[0], args[1])

                    elif command == 'clear':
                        os.system('clear')
                    elif command == 'exit':
                        console.print("Exiting...")
                        break
            except (KeyboardInterrupt, EOFError):
                console.print("Exiting...")
                break
    else:
        llist('program')

if __name__ == "__main__":
    main()
