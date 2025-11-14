import dns.resolver

def check_spf(domain):
    try:
        # Résolution de l'enregistrement TXT pour le domaine
        result = dns.resolver.resolve(domain, 'TXT')
        for rdata in result:
            # Vérification de la présence de l'enregistrement SPF
            if rdata.to_text().startswith('v=spf1'):
                return f"SPF Record found: {rdata.to_text()}"
        return "No SPF record found"
    except Exception as e:
        return f"Error checking SPF: {str(e)}"

def check_dmarc(domain):
    try:
        # Résolution de l'enregistrement TXT pour _dmarc du domaine
        result = dns.resolver.resolve(f'_dmarc.{domain}', 'TXT')
        for rdata in result:
            # Vérification de la présence de l'enregistrement DMARC
            if rdata.to_text().startswith('v=DMARC1'):
                return f"DMARC Record found: {rdata.to_text()}"
        return "No DMARC record found"
    except Exception as e:
        return f"Error checking DMARC: {str(e)}"

def main():
    domain = input("Enter the domain to check: ")
    
    # Vérification du SPF
    spf_result = check_spf(domain)
    print(spf_result)
    
    # Vérification du DMARC
    dmarc_result = check_dmarc(domain)
    print(dmarc_result)

if __name__ == "__main__":
    main()
