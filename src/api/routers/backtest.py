"""Backtest API endpoints."""

import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routers.auth import limiter
from src.api.schemas.backtest import (
    BacktestHistoryItem,
    BacktestHistoryResponse,
    BacktestMetrics,
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestTradeResponse,
    EquityPoint,
)
from src.auth.dependencies import get_current_user
from src.models.database import BacktestRun, User
from src.models.session import get_db, get_session
from src.strategy import StrategyRegistry
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

MAX_CONCURRENT_BACKTESTS = 3


@router.get("/strategies")
async def list_strategies(user: User = Depends(get_current_user)):
    """List all available strategies for backtesting."""
    strategies = StrategyRegistry.list_available()
    return {"strategies": strategies}


@router.post("/run")
@limiter.limit("10/minute")
async def start_backtest(
    request: Request,
    body: BacktestRunRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a new backtest. Returns run_id immediately."""
    # Validate strategy exists
    try:
        StrategyRegistry.get(body.strategy_type)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check concurrent limit
    running_count = await db.execute(
        select(func.count(BacktestRun.id)).where(
            BacktestRun.user_id == user.id,
            BacktestRun.status.in_(["pending", "running"]),
        )
    )
    if running_count.scalar() >= MAX_CONCURRENT_BACKTESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Max {MAX_CONCURRENT_BACKTESTS} concurrent backtests allowed",
        )

    # Parse dates
    try:
        start_dt = datetime.fromisoformat(body.start_date)
        end_dt = datetime.fromisoformat(body.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    if end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="end_date must be after start_date")

    # Create DB record
    run = BacktestRun(
        user_id=user.id,
        strategy_type=body.strategy_type,
        symbol=body.symbol,
        timeframe=body.timeframe,
        start_date=start_dt,
        end_date=end_dt,
        initial_capital=body.initial_capital,
        strategy_params=json.dumps(body.strategy_params) if body.strategy_params else None,
        status="pending",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    run_id = run.id

    # Launch background task (record must be committed before the background
    # task opens its own session, otherwise it won't find the record)
    background_tasks.add_task(_execute_backtest, run_id)

    return {"run_id": run_id, "status": "pending"}


async def _execute_backtest(run_id: int):
    """Background worker that runs the backtest and saves results."""
    from src.backtest.strategy_adapter import run_backtest_for_strategy

    async with get_session() as session:
        result_q = await session.execute(
            select(BacktestRun).where(BacktestRun.id == run_id)
        )
        run = result_q.scalar_one_or_none()
        if not run:
            logger.error(f"Backtest run {run_id} not found")
            return

        run.status = "running"
        await session.flush()

        try:
            strategy_params = json.loads(run.strategy_params) if run.strategy_params else None

            bt_result = await run_backtest_for_strategy(
                strategy_type=run.strategy_type,
                symbol=run.symbol,
                timeframe=run.timeframe,
                start_date=run.start_date,
                end_date=run.end_date,
                initial_capital=run.initial_capital,
                strategy_params=strategy_params,
            )

            run.result_metrics = json.dumps(bt_result["metrics"])
            run.equity_curve = json.dumps(bt_result["equity_curve"])
            run.trades = json.dumps(bt_result["trades"])
            run.status = "completed"
            run.completed_at = datetime.utcnow()

        except Exception as e:
            logger.error(f"Backtest {run_id} failed: {e}", exc_info=True)
            run.status = "failed"
            run.error_message = str(e)[:500]
            run.completed_at = datetime.utcnow()


@router.get("/history", response_model=BacktestHistoryResponse)
async def list_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List user's backtest runs (paginated, newest first)."""
    count_q = await db.execute(
        select(func.count(BacktestRun.id)).where(BacktestRun.user_id == user.id)
    )
    total = count_q.scalar() or 0

    result = await db.execute(
        select(BacktestRun)
        .where(BacktestRun.user_id == user.id)
        .order_by(BacktestRun.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    runs = result.scalars().all()

    items = []
    for r in runs:
        metrics = json.loads(r.result_metrics) if r.result_metrics else {}
        items.append(BacktestHistoryItem(
            id=r.id,
            strategy_type=r.strategy_type,
            symbol=r.symbol,
            timeframe=r.timeframe,
            start_date=r.start_date.strftime("%Y-%m-%d"),
            end_date=r.end_date.strftime("%Y-%m-%d"),
            initial_capital=r.initial_capital,
            status=r.status,
            total_return_percent=metrics.get("total_return_percent"),
            win_rate=metrics.get("win_rate"),
            total_trades=metrics.get("total_trades"),
            created_at=r.created_at.isoformat() if r.created_at else "",
        ))

    return BacktestHistoryResponse(runs=items, total=total, page=page, per_page=per_page)


@router.get("/{run_id}", response_model=BacktestRunResponse)
async def get_run(
    run_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get status + results of a backtest run."""
    result = await db.execute(
        select(BacktestRun).where(
            BacktestRun.id == run_id,
            BacktestRun.user_id == user.id,
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")

    metrics = None
    equity_curve = None
    trades = None
    strategy_params = None

    if run.result_metrics:
        metrics = BacktestMetrics(**json.loads(run.result_metrics))
    if run.equity_curve:
        equity_curve = [EquityPoint(**p) for p in json.loads(run.equity_curve)]
    if run.trades:
        trades = [BacktestTradeResponse(**t) for t in json.loads(run.trades)]
    if run.strategy_params:
        strategy_params = json.loads(run.strategy_params)

    return BacktestRunResponse(
        id=run.id,
        strategy_type=run.strategy_type,
        symbol=run.symbol,
        timeframe=run.timeframe,
        start_date=run.start_date.strftime("%Y-%m-%d"),
        end_date=run.end_date.strftime("%Y-%m-%d"),
        initial_capital=run.initial_capital,
        strategy_params=strategy_params,
        status=run.status,
        error_message=run.error_message,
        metrics=metrics,
        equity_curve=equity_curve,
        trades=trades,
        created_at=run.created_at.isoformat() if run.created_at else "",
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


@router.delete("/{run_id}")
async def delete_run(
    run_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a backtest run."""
    result = await db.execute(
        select(BacktestRun).where(
            BacktestRun.id == run_id,
            BacktestRun.user_id == user.id,
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")

    await db.delete(run)
    return {"status": "ok", "message": "Backtest run deleted"}
