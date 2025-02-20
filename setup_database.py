import sqlite3
from enum_task import get_db_connection

def setup_database():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Création de la table des programmes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS programs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_name TEXT UNIQUE,
            com TEXT,
            url TEXT
        )
    ''')

    # Création de la table des domaines
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS domains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_id INTEGER,
            domain_name TEXT UNIQUE,
            FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE
        )
    ''')

    # Création de la table des détails de domaine
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS domain_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            http_status TEXT,
            ip TEXT,
            title TEXT,
            techno TEXT,
            open_port TEXT,
            screen BLOB,
            phash TEXT,
            fuzz TEXT,
            nuclei TEXT,
            spfdmarc TEXT,
            method TEXT,
            domain_id INTEGER,
            com TEXT,
            FOREIGN KEY (domain_id) REFERENCES domains(id) ON DELETE CASCADE
        )
    ''')

    conn.commit()
    conn.close()
