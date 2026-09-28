"""Capital Simulator API endpoint (Autopilot Phase 7)."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.security import require_api_key
from backend.app.schemas.capital_simulation import (
    CapitalSimulationRequest,
    CapitalSimulationResponse,
)
from backend.app.services.capital_simulator import SimulationError, run_capital_simulation

router = APIRouter(
    prefix="/api/capital-simulation",
    tags=["capital-simulation"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", response_model=CapitalSimulationResponse)
def simulate(
    payload: CapitalSimulationRequest, db: Session = Depends(get_db)
) -> CapitalSimulationResponse:
    result = run_capital_simulation(
        db,
        capital=Decimal(str(payload.capital)),
        max_daily_purchases=payload.max_daily_purchases,
        min_margin=Decimal(str(payload.min_margin)),
    )
    if isinstance(result, SimulationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=result.reason)

    return CapitalSimulationResponse(
        qualifying_opportunities=result.qualifying_opportunities,
        avg_buy_price=float(result.avg_buy_price),
        avg_margin=float(result.avg_margin),
        avg_net_profit_per_sale=float(result.avg_net_profit_per_sale),
        avg_time_to_sale_days=float(result.avg_time_to_sale_days),
        time_to_sale_is_real_data=result.time_to_sale_is_real_data,
        daily_purchases=float(result.daily_purchases),
        daily_capital_deployed=float(result.daily_capital_deployed),
        daily_profit=float(result.daily_profit),
        monthly_profit=float(result.monthly_profit),
        monthly_roi=float(result.monthly_roi),
        capital_rotations_per_month=float(result.capital_rotations_per_month),
        days_to_double_capital=(
            float(result.days_to_double_capital)
            if result.days_to_double_capital is not None
            else None
        ),
    )
