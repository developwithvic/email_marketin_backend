from fastapi import APIRouter, Depends, HTTPException, status
from app.schema.scrape import (
    BulkScrapeRequest,
    ScrapeToDBRequest,
    ScrapeTaskResponse,
    ScrapeTaskListResponse
)
from app.service.scrape_task_manager import scrape_task_manager
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scrape_email"], prefix="/scrape")


@router.post("/scrape", status_code=status.HTTP_202_ACCEPTED)
async def scrape(request: BulkScrapeRequest):
    """
    Start background scraping job for a list of target URLs.
    Non-blocking: Returns immediately with a task_id to track progress.
    """
    try:
        if not request.urls:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="URL list cannot be empty"
            )

        # Block concurrent scrapes
        is_active, active_task_id = scrape_task_manager.has_active_task()
        if is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A scrape task is already in progress (task_id: {active_task_id}). Wait for it to complete or cancel it."
            )

        task_info = scrape_task_manager.create_bulk_scrape_task(request.urls)
        return {
            "task_id": task_info["task_id"],
            "status": task_info["status"],
            "request_type": task_info["request_type"],
            "message": "Background bulk scrape task started successfully",
            "progress": task_info["progress"],
            "created_at": task_info["created_at"],
            "started_at": task_info["started_at"],
            "completed_at": task_info["completed_at"],
            "error": task_info["error"],
            "results": task_info["results"]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting bulk scrape task: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error starting bulk scrape task: {str(e)}"
        )


@router.post("/scrape-to-db", status_code=status.HTTP_202_ACCEPTED)
async def scrape_to_db(request: ScrapeToDBRequest):
    """
    Automatically fetch UK domains, scrape emails from them, and save to database in a background thread task.
    Non-blocking: Returns immediately with a task_id to track progress.
    """
    try:
        if request.email_limit < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email limit must be at least 1"
            )

        if request.domain_limit < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Domain limit must be at least 1"
            )

        if request.domain_limit > 10000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Domain limit cannot exceed 10000"
            )

        # Block concurrent scrapes
        is_active, active_task_id = scrape_task_manager.has_active_task()
        if is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A scrape task is already in progress (task_id: {active_task_id}). Wait for it to complete or cancel it."
            )

        task_info = scrape_task_manager.create_scrape_to_db_task(
            email_limit=request.email_limit,
            domain_limit=request.domain_limit,
            category=request.category
        )

        logger.info(f"Background scrape-to-db task initialized: task_id={task_info['task_id']}")

        return {
            "task_id": task_info["task_id"],
            "status": task_info["status"],
            "request_type": task_info["request_type"],
            "message": "Background scrape-to-db task started successfully. Use GET /scrape/tasks/{task_id} to view progress.",
            "progress": task_info["progress"],
            "created_at": task_info["created_at"],
            "started_at": task_info["started_at"],
            "completed_at": task_info["completed_at"],
            "error": task_info["error"],
            "results": task_info["results"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting scrape to DB task: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error starting scrape task: {str(e)}"
        )


@router.get("/tasks", response_model=ScrapeTaskListResponse)
async def list_scrape_tasks():
    """
    Get all active and past background scraping tasks.
    """
    all_tasks = scrape_task_manager.get_all_tasks()
    formatted = [
        ScrapeTaskResponse(
            task_id=t["task_id"],
            status=t["status"],
            request_type=t["request_type"],
            message=f"Task is currently {t['status']}",
            progress=t["progress"],
            created_at=t["created_at"],
            started_at=t["started_at"],
            completed_at=t["completed_at"],
            error=t["error"],
            results=t["results"]
        )
        for t in all_tasks
    ]
    return ScrapeTaskListResponse(total=len(formatted), tasks=formatted)


@router.get("/tasks/{task_id}", response_model=ScrapeTaskResponse)
async def get_scrape_task_status(task_id: str):
    """
    Get progress, status, and results for a specific background scraping task.
    """
    t = scrape_task_manager.get_task(task_id)
    if not t:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scraping task with ID {task_id} not found"
        )

    return ScrapeTaskResponse(
        task_id=t["task_id"],
        status=t["status"],
        request_type=t["request_type"],
        message=f"Task status: {t['status']}",
        progress=t["progress"],
        created_at=t["created_at"],
        started_at=t["started_at"],
        completed_at=t["completed_at"],
        error=t["error"],
        results=t["results"]
    )


@router.post("/tasks/{task_id}/cancel")
async def cancel_scrape_task(task_id: str):
    """
    Cancel an in-progress background scraping task.
    """
    success = scrape_task_manager.cancel_task(task_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task {task_id} could not be cancelled or is already completed."
        )

    return {"message": f"Scraping task {task_id} cancelled successfully."}
