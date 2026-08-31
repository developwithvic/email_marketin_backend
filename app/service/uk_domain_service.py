import os
import logging
from urllib.parse import urlparse
from typing import List, Set

logger = logging.getLogger(__name__)

# --- STATE FILES ---
STATE_FILE = "cdx_resume_state.txt"
KNOWN_DOMAINS_FILE = "known_domains.txt"

# Comprehensive Pool of Top UK Domains as Fallback when CDX API fails, is rate-limited, or returns invalid JSON
FALLBACK_UK_DOMAINS = [
    "bbc.co.uk", "theguardian.com", "telegraph.co.uk", "independent.co.uk",
    "sky.com", "dailymail.co.uk", "mirror.co.uk", "express.co.uk",
    "standard.co.uk", "manchestereveningnews.co.uk", "walesonline.co.uk",
    "birminghammail.co.uk", "scotsman.com", "heraldscotland.com",
    "gov.uk", "nhs.uk", "ox.ac.uk", "cam.ac.uk", "imperial.ac.uk",
    "ucl.ac.uk", "manchester.ac.uk", "kcl.ac.uk", "ed.ac.uk",
    "boots.com", "argos.co.uk", "currys.co.uk", "superdrug.com",
    "sainsburys.co.uk", "tesco.com", "asda.com", "marksandspencer.com",
    "next.co.uk", "johnlewis.com", "halfords.com", "screwfix.com",
    "toolstation.com", "wickes.co.uk", "bmstores.co.uk", "homebase.co.uk",
    "dunelm.com", "dfshome.co.uk", "rightmove.co.uk", "zoopla.co.uk",
    "onthemarket.com", "autotrader.co.uk", "carwow.co.uk", "evanshalshaw.com",
    "lookers.co.uk", "arnoldclark.com", "trustpilot.com", "yell.com",
    "thomsonlocal.com", "cylex-uk.co.uk", "freeindex.co.uk", "checkatrade.com",
    "trustatrader.com", "mybuilder.com", "ratedpeople.com", "monzo.com",
    "revolut.com", "starlingbank.com", "barclays.co.uk", "hsbc.co.uk",
    "natwest.com", "lloydsbank.com", "halifax.co.uk", "santander.co.uk",
    "nationwide.co.uk", "tsb.co.uk", "virginmoney.com"
]


def _load_resume_index() -> int:
    """Reads the 'bookmark' so we know how many records to skip."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                content = f.read().strip()
                return int(content) if content else 0
        except Exception:
            return 0
    return 0


def _save_resume_index(index: int):
    """Saves our place in the Common Crawl database."""
    try:
        with open(STATE_FILE, 'w') as f:
            f.write(str(index))
    except Exception as e:
        logger.warning(f"Could not write state file {STATE_FILE}: {e}")


def _load_known_domains() -> Set[str]:
    """Loads all domains we have ever scraped so we never repeat them."""
    if os.path.exists(KNOWN_DOMAINS_FILE):
        try:
            with open(KNOWN_DOMAINS_FILE, 'r') as f:
                return set(filter(None, f.read().splitlines()))
        except Exception:
            return set()
    return set()


def _save_known_domains(domains: Set[str]):
    """Appends new domains to our permanent list."""
    if not domains:
        return
    try:
        with open(KNOWN_DOMAINS_FILE, 'a') as f:
            for domain in domains:
                f.write(domain + '\n')
    except Exception as e:
        logger.warning(f"Could not save known domains: {e}")


def discover_uk_domains(target_new_domains: int = 20) -> List[str]:
    """
    Resumes from the last known position and fetches N entirely new domains.
    Includes error resilience for CDX API failures and fallback pool.
    """
    records_to_skip = _load_resume_index()
    known_domains = _load_known_domains()
    new_domains = set()
    current_record_index = 0

    print(f"\n📚 Resuming discovery... Fast-forwarding past {records_to_skip} old records.")

    try:
        import cdx_toolkit
        cdx = cdx_toolkit.CDXFetcher(source='cc')
        results = cdx.iter("*.uk/*", filter=['=status:200', '=mime:text/html'])

        for obj in results:
            current_record_index += 1

            # 1. FAST FORWARD: Skip records we've processed in previous runs
            if current_record_index <= records_to_skip:
                continue

            try:
                url = obj.data.get('url') if hasattr(obj, 'data') and isinstance(obj.data, dict) else None
                if url:
                    domain = urlparse(url).netloc
                    if domain.startswith('www.'):
                        domain = domain[4:]

                    # 2. CHECK DUPLICATES: Make sure we've never scraped it before
                    if domain and domain not in known_domains and domain not in new_domains:
                        new_domains.add(domain)
                        print(f"  [+] Discovered new target from CDX: {domain}")

                        # 3. STOP CONDITION: Once we find enough NEW domains, stop
                        if len(new_domains) >= target_new_domains:
                            break
            except Exception as item_err:
                logger.debug(f"Skipping malformed CDX item: {item_err}")
                continue

    except Exception as e:
        print(f"⚠️ CDX API Error encountered: {e}. Switching to UK Domain Fallback Pool.")
        logger.warning(f"CDX API Error: {e}")

    # Fallback Mechanism: If CDX API failed or returned fewer domains than requested
    if len(new_domains) < target_new_domains:
        needed = target_new_domains - len(new_domains)
        print(f"🔄 Supplementing discovery with {needed} UK domains from fallback pool...")
        for fallback in FALLBACK_UK_DOMAINS:
            clean_dom = fallback[4:] if fallback.startswith('www.') else fallback
            if clean_dom not in known_domains and clean_dom not in new_domains:
                new_domains.add(clean_dom)
                if len(new_domains) >= target_new_domains:
                    break

    # Save state
    total_records_processed = records_to_skip + (current_record_index - records_to_skip)
    _save_resume_index(total_records_processed)
    _save_known_domains(new_domains)

    return list(new_domains)