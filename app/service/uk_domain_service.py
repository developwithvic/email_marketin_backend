import os
import logging
import csv
import json
from urllib.parse import urlparse
from typing import List, Set

logger = logging.getLogger(__name__)

# --- STATE FILES ---
STATE_FILE = "cdx_resume_state.txt"
KNOWN_DOMAINS_FILE = "known_domains.txt"
CSV_FALLBACK_FILE = os.path.join(os.path.dirname(__file__), "my_uk_list.csv")

# Comprehensive Pool of Top UK Domains across key industries & sectors
FALLBACK_UK_DOMAINS = [
    # Media & News
    "bbc.co.uk", "theguardian.com", "telegraph.co.uk", "independent.co.uk",
    "sky.com", "dailymail.co.uk", "mirror.co.uk", "express.co.uk",
    "standard.co.uk", "manchestereveningnews.co.uk", "walesonline.co.uk",
    "birminghammail.co.uk", "scotsman.com", "heraldscotland.com", "chroniclelive.co.uk",
    # Government & Public Services
    "gov.uk", "nhs.uk", "police.uk", "ordnancesurvey.co.uk",
    # Higher Education
    "ox.ac.uk", "cam.ac.uk", "imperial.ac.uk", "ucl.ac.uk", "manchester.ac.uk",
    "kcl.ac.uk", "ed.ac.uk", "warwick.ac.uk", "bristol.ac.uk", "gla.ac.uk",
    # Retail & Consumer
    "boots.com", "argos.co.uk", "currys.co.uk", "superdrug.com",
    "sainsburys.co.uk", "tesco.com", "asda.com", "marksandspencer.com",
    "next.co.uk", "johnlewis.com", "halfords.com", "screwfix.com",
    "toolstation.com", "wickes.co.uk", "bmstores.co.uk", "homebase.co.uk",
    "dunelm.com", "dfshome.co.uk", "very.co.uk", "waterstones.com",
    # Real Estate & Vehicles
    "rightmove.co.uk", "zoopla.co.uk", "onthemarket.com", "autotrader.co.uk",
    "carwow.co.uk", "evanshalshaw.com", "lookers.co.uk", "arnoldclark.com",
    # Business Directories & Services
    "trustpilot.com", "yell.com", "thomsonlocal.com", "cylex-uk.co.uk",
    "freeindex.co.uk", "checkatrade.com", "trustatrader.com", "mybuilder.com",
    "ratedpeople.com", "bark.com", "reed.co.uk", "totaljobs.com",
    # Banking & Finance
    "monzo.com", "revolut.com", "starlingbank.com", "barclays.co.uk",
    "hsbc.co.uk", "natwest.com", "lloydsbank.com", "halifax.co.uk",
    "santander.co.uk", "nationwide.co.uk", "tsb.co.uk", "virginmoney.com",
    # Technology & Telecoms
    "bt.com", "ee.co.uk", "vodafone.co.uk", "o2.co.uk", "three.co.uk",
    "talktalk.co.uk", "plus.net", "virginmedia.com"
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


def _load_csv_fallback_domains() -> List[str]:
    """Loads fallback domains from local my_uk_list.csv if present."""
    domains = []
    if os.path.exists(CSV_FALLBACK_FILE):
        try:
            with open(CSV_FALLBACK_FILE, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f)
                for row in reader:
                    if row and row[0] and row[0].strip() != 'Domain Name':
                        d = row[0].strip()
                        if d.startswith('www.'):
                            d = d[4:]
                        if d:
                            domains.append(d)
        except Exception as e:
            logger.warning(f"Could not read CSV fallback file {CSV_FALLBACK_FILE}: {e}")
    return domains


def _generate_synthetic_uk_domains() -> List[str]:
    """Generates structured UK business domain patterns for large fallback requests."""
    cities = [
        'london', 'manchester', 'birmingham', 'leeds', 'glasgow', 'edinburgh',
        'bristol', 'liverpool', 'sheffield', 'newcastle', 'nottingham', 'cardiff',
        'belfast', 'southampton', 'oxford', 'cambridge', 'york', 'bath', 'norwich',
        'exeter', 'plymouth', 'derby', 'leicester', 'aberdeen', 'dundee', 'coventry',
        'reading', 'brighton', 'luton', 'miltonkeynes', 'northampton', 'portsmouth',
        'swindon', 'bournemouth', 'slough', 'chelmsford', 'gloucester', 'cheltenham'
    ]
    services = [
        'plumbing', 'roofing', 'electrical', 'accountants', 'solicitors', 'legal',
        'dental', 'clinic', 'estates', 'properties', 'construction', 'builders',
        'cleaning', 'logistics', 'transport', 'design', 'marketing', 'digital',
        'consulting', 'recruitment', 'caterers', 'auto', 'garage', 'security',
        'finance', 'vet', 'tech', 'solutions', 'services', 'group', 'direct',
        'media', 'studios', 'hvac', 'glazing', 'interiors', 'renovations'
    ]
    generated = []
    for c in cities:
        for s in services:
            generated.append(f"{c}{s}.co.uk")
            generated.append(f"{c}-{s}.co.uk")
            generated.append(f"{c}{s}.uk")
    return generated


def _apply_cdx_patch():
    """Patches cdx_toolkit to gracefully handle malformed JSON lines and non-200 responses."""
    try:
        import cdx_toolkit
        from cdx_toolkit import CaptureObject

        if getattr(cdx_toolkit, '_safe_patch_applied', False):
            return

        orig_cdx_to_captures = cdx_toolkit.cdx_to_captures

        def safe_cdx_to_captures(resp, wb=None, warc_download_prefix=None):
            # Ignore non-200 responses (e.g. 503 HTML error pages)
            if getattr(resp, 'status_code', 200) != 200:
                return []

            text = getattr(resp, 'text', '')
            if text.startswith('{'):
                lines = text.splitlines()
                ret = []
                for line in lines:
                    try:
                        ret.append(CaptureObject(json.loads(line), wb=wb, warc_download_prefix=warc_download_prefix))
                    except Exception:
                        continue
                return ret

            try:
                return orig_cdx_to_captures(resp, wb=wb, warc_download_prefix=warc_download_prefix)
            except Exception:
                return []

        cdx_toolkit.cdx_to_captures = safe_cdx_to_captures
        cdx_toolkit._safe_patch_applied = True
    except Exception as patch_err:
        logger.debug(f"Could not patch cdx_toolkit: {patch_err}")


def discover_uk_domains(target_new_domains: int = 20) -> List[str]:
    """
    Resumes from the last known position and fetches N entirely new domains.
    Includes error resilience for CDX API failures, malformed JSON stream lines,
    timeout protection, and multi-tiered fallback pool (CSV list + curated top domains + sector domain generator).
    """
    records_to_skip = _load_resume_index()
    known_domains = _load_known_domains()
    new_domains = set()
    current_record_index = 0

    print(f"\n📚 Resuming discovery... Fast-forwarding past {records_to_skip} old records.")

    # Apply safety patch to cdx_toolkit before iterating
    _apply_cdx_patch()

    # 1. Attempt CDX API Discovery with timeout protection & item-level error handling
    try:
        import signal

        def cdx_timeout_handler(signum, frame):
            raise TimeoutError("CDX API request timed out (5s limit reached)")

        # Enable SIGALRM timeout for CDX network fetch (Linux)
        if hasattr(signal, 'SIGALRM'):
            signal.signal(signal.SIGALRM, cdx_timeout_handler)
            signal.alarm(5)

        import cdx_toolkit
        cdx = cdx_toolkit.CDXFetcher(source='cc')
        results = cdx.iter("*.uk/*", filter=['=status:200', '=mime:text/html'])
        results_iter = iter(results)

        consecutive_errors = 0
        max_consecutive_errors = 10

        while len(new_domains) < target_new_domains and consecutive_errors < max_consecutive_errors:
            current_record_index += 1

            try:
                obj = next(results_iter)
                consecutive_errors = 0
            except StopIteration:
                break
            except Exception as item_err:
                consecutive_errors += 1
                logger.debug(f"Skipping malformed CDX item ({consecutive_errors}/{max_consecutive_errors}): {item_err}")
                continue

            # FAST FORWARD: Skip records processed in previous runs
            if current_record_index <= records_to_skip:
                continue

            try:
                url = obj.data.get('url') if hasattr(obj, 'data') and isinstance(obj.data, dict) else None
                if url:
                    domain = urlparse(url).netloc
                    if domain.startswith('www.'):
                        domain = domain[4:]

                    if domain and domain not in known_domains and domain not in new_domains:
                        new_domains.add(domain)
                        print(f"  [+] Discovered new target from CDX: {domain}")

                        if len(new_domains) >= target_new_domains:
                            break
            except Exception as item_parse_err:
                logger.debug(f"Skipping malformed CDX domain item: {item_parse_err}")
                continue

    except Exception as e:
        print(f"⚠️ CDX API Error encountered: {e}. Switching to UK Domain Fallback Pool.")
        logger.warning(f"CDX API Error: {e}")
    finally:
        # Disable SIGALRM timeout
        if hasattr(signal, 'SIGALRM'):
            signal.alarm(0)

    # Fallback Tier 1: Local CSV list (my_uk_list.csv)
    if len(new_domains) < target_new_domains:
        csv_domains = _load_csv_fallback_domains()
        if csv_domains:
            for fallback in csv_domains:
                clean_dom = fallback[4:] if fallback.startswith('www.') else fallback
                if clean_dom and clean_dom not in known_domains and clean_dom not in new_domains:
                    new_domains.add(clean_dom)
                    if len(new_domains) >= target_new_domains:
                        break

    # Fallback Tier 2: Static curated top UK domains
    if len(new_domains) < target_new_domains:
        for fallback in FALLBACK_UK_DOMAINS:
            clean_dom = fallback[4:] if fallback.startswith('www.') else fallback
            if clean_dom and clean_dom not in known_domains and clean_dom not in new_domains:
                new_domains.add(clean_dom)
                if len(new_domains) >= target_new_domains:
                    break

    # Fallback Tier 3: Sector business domain generator (for large target limits up to 10,000)
    if len(new_domains) < target_new_domains:
        synthetic_domains = _generate_synthetic_uk_domains()
        for fallback in synthetic_domains:
            if fallback not in known_domains and fallback not in new_domains:
                new_domains.add(fallback)
                if len(new_domains) >= target_new_domains:
                    break

    if len(new_domains) < target_new_domains:
        print(f"🔄 Supplemented discovery with fallback pool! Yielded {len(new_domains)} domains out of {target_new_domains} requested.")

    # Save state
    total_records_processed = records_to_skip + max(0, current_record_index - records_to_skip)
    _save_resume_index(total_records_processed)
    _save_known_domains(new_domains)

    return list(new_domains)