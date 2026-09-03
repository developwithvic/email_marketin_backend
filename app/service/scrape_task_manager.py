import asyncio
import uuid
from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional, Any
from sqlmodel.ext.asyncio.session import AsyncSession
from app.db.session import engine
from app.model.emails import Category as EmailCategory
from app.service.uk_domain_service import discover_uk_domains
from app.service.scrape_email import AdvancedDomainScraper, process_domain_task
from app.service.email_service import save_extracted_emails

logger = logging.getLogger(__name__)


class ScrapeTaskManager:
    """
    Manages background email scraping jobs in separate async tasks / thread pools.
    Prevents blocking the FastAPI main application thread during long domain discovery
    and web scraping operations.
    """

    def __init__(self):
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self._running_async_tasks: Dict[str, asyncio.Task] = {}

    def create_scrape_to_db_task(
        self,
        email_limit: int,
        domain_limit: int,
        category: str
    ) -> Dict[str, Any]:
        task_id = str(uuid.uuid4())
        task_info = {
            "task_id": task_id,
            "request_type": "scrape_to_db",
            "status": "pending",
            "email_limit": email_limit,
            "domain_limit": domain_limit,
            "category": category,
            "urls": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "completed_at": None,
            "progress": {
                "domains_scraped": 0,
                "total_domains": 0,
                "emails_found": 0,
                "emails_saved": 0,
                "duplicates_skipped": 0,
                "errors": 0
            },
            "results": [],
            "error": None
        }
        self.tasks[task_id] = task_info

        async_task = asyncio.create_task(
            self._run_scrape_to_db_job(task_id, email_limit, domain_limit, category)
        )
        self._running_async_tasks[task_id] = async_task
        return task_info

    def create_bulk_scrape_task(self, urls: List[str]) -> Dict[str, Any]:
        task_id = str(uuid.uuid4())
        task_info = {
            "task_id": task_id,
            "request_type": "bulk_scrape",
            "status": "pending",
            "email_limit": 0,
            "domain_limit": len(urls),
            "category": "WEB",
            "urls": [str(u) for u in urls],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "completed_at": None,
            "progress": {
                "domains_scraped": 0,
                "total_domains": len(urls),
                "emails_found": 0,
                "emails_saved": 0,
                "duplicates_skipped": 0,
                "errors": 0
            },
            "results": [],
            "error": None
        }
        self.tasks[task_id] = task_info

        async_task = asyncio.create_task(
            self._run_bulk_scrape_job(task_id, urls)
        )
        self._running_async_tasks[task_id] = async_task
        return task_info

    async def _run_scrape_to_db_job(
        self,
        task_id: str,
        email_limit: int,
        domain_limit: int,
        category: str
    ):
        task_info = self.tasks[task_id]
        task_info["status"] = "running"
        task_info["started_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"🚀 [Task {task_id}] Started scrape_to_db background job (limit={email_limit}, domains={domain_limit})")

        try:
            # Parse category
            try:
                category_enum = EmailCategory[category.lower()]
            except KeyError:
                category_enum = EmailCategory.web

            # 1. Discover UK domains using asyncio.to_thread so blocking HTTP doesn't freeze FastAPI
            logger.info(f"🔍 [Task {task_id}] Fetching UK domains in background thread...")
            uk_domains = await asyncio.to_thread(discover_uk_domains, target_new_domains=domain_limit)

            if not uk_domains:
                task_info["status"] = "failed"
                task_info["error"] = "No UK domains found from CDX API"
                task_info["completed_at"] = datetime.now(timezone.utc).isoformat()
                return

            task_info["progress"]["total_domains"] = len(uk_domains)
            task_info["urls"] = list(uk_domains)

            semaphore = asyncio.Semaphore(3)
            results = []
            total_emails_found = 0
            total_emails_saved = 0
            duplicates_skipped = 0
            errors = 0
            domains_scraped = 0

            # 2. Open dedicated database session for background worker
            async with AsyncSession(engine) as db:
                for domain_url in uk_domains:
                    if total_emails_found >= email_limit:
                        logger.info(f"Reached email limit of {email_limit}. Stopping scraping task {task_id}.")
                        break

                    try:
                        async with semaphore:
                            scraper = AdvancedDomainScraper(domain_url)
                            emails = await scraper.run()
                            domains_scraped += 1

                            emails_count = len(emails)
                            total_emails_found += emails_count

                            if total_emails_found > email_limit:
                                excess = total_emails_found - email_limit
                                emails = list(emails)[:-excess] if excess < len(emails) else set()
                                total_emails_found = email_limit

                            if emails:
                                save_result = await save_extracted_emails(
                                    set(emails),
                                    category_enum,
                                    db
                                )
                                total_emails_saved += save_result['saved']
                                duplicates_skipped += save_result['duplicates']
                                errors += save_result['failed']

                            res_item = {
                                "domain": str(domain_url),
                                "emails": list(emails),
                                "pages_scanned": len(scraper.visited_urls),
                                "status": "success" if emails else "no_emails_found"
                            }
                            results.append(res_item)

                    except Exception as domain_err:
                        errors += 1
                        results.append({
                            "domain": str(domain_url),
                            "emails": [],
                            "pages_scanned": 0,
                            "status": "error",
                            "error": str(domain_err)
                        })

                    # Update real-time progress
                    task_info["progress"]["domains_scraped"] = domains_scraped
                    task_info["progress"]["emails_found"] = total_emails_found
                    task_info["progress"]["emails_saved"] = total_emails_saved
                    task_info["progress"]["duplicates_skipped"] = duplicates_skipped
                    task_info["progress"]["errors"] = errors
                    task_info["results"] = results

            task_info["status"] = "completed"
            task_info["completed_at"] = datetime.now(timezone.utc).isoformat()
            logger.info(f"✅ [Task {task_id}] Scrape to DB task completed. Saved: {total_emails_saved}, Duplicates: {duplicates_skipped}")

        except Exception as job_err:
            logger.error(f"❌ [Task {task_id}] Background scraping failed: {job_err}", exc_info=True)
            task_info["status"] = "failed"
            task_info["error"] = str(job_err)
            task_info["completed_at"] = datetime.now(timezone.utc).isoformat()

    async def _run_bulk_scrape_job(self, task_id: str, urls: List[str]):
        task_info = self.tasks[task_id]
        task_info["status"] = "running"
        task_info["started_at"] = datetime.now(timezone.utc).isoformat()

        try:
            domains = [str(u) for u in urls]
            semaphore = asyncio.Semaphore(3)
            tasks = [process_domain_task(domain, semaphore) for domain in domains]

            results = await asyncio.gather(*tasks)

            successful = sum(1 for r in results if r.get("status") == "success")
            total_emails = sum(len(r.get("emails", [])) for r in results)

            task_info["progress"]["domains_scraped"] = len(results)
            task_info["progress"]["emails_found"] = total_emails
            task_info["results"] = results
            task_info["status"] = "completed"
            task_info["completed_at"] = datetime.now(timezone.utc).isoformat()
            logger.info(f"✅ [Task {task_id}] Bulk scrape completed. Domains: {len(results)}, Successful: {successful}")

        except Exception as err:
            logger.error(f"❌ [Task {task_id}] Bulk scrape failed: {err}", exc_info=True)
            task_info["status"] = "failed"
            task_info["error"] = str(err)
            task_info["completed_at"] = datetime.now(timezone.utc).isoformat()

    def has_active_task(self) -> tuple[bool, Optional[str]]:
        """Check if any scrape task is currently running or pending."""
        for task_id, task_info in self.tasks.items():
            if task_info["status"] in ("running", "pending"):
                return True, task_id
        return False, None

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.tasks.get(task_id)

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        return list(self.tasks.values())

    def cancel_task(self, task_id: str) -> bool:
        if task_id in self._running_async_tasks:
            async_task = self._running_async_tasks[task_id]
            if not async_task.done():
                async_task.cancel()
                if task_id in self.tasks:
                    self.tasks[task_id]["status"] = "cancelled"
                    self.tasks[task_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
                return True
        return False


# Singleton task manager instance
scrape_task_manager = ScrapeTaskManager()
