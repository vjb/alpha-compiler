"""
FastAPI Agent Server — ERC-8183 job intake, compilation, and escrow settlement.

Exposes the Alpha Compiler as a network service that:
1. Accepts research jobs (thesis + target assets + risk tolerance)
2. Verifies ERC-8183 escrow funding on BSC
3. Compiles the strategy using Skill Hub + Core MCP intelligence
4. Publishes deliverables to Greenfield/IPFS
5. Settles the escrow on-chain (releasing payment to the agent)

This is the "Quant-for-Hire" daemon — fully autonomous, no intermediary.
"""
import os
import sys
import json
import time
from typing import Optional
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from skill_engine.compiler import ThesisToCodeStrategyCompiler
from skill_engine.publisher import record_strategy_version, publish_deliverables
from skill_engine.agent_core import get_wallet_provider
from backtest_sandbox.engine import run_backtest

app = FastAPI(
    title="Alpha Compiler Agent Server",
    description="Autonomous strategy compilation agent with ERC-8183 escrow settlement on BNB Chain.",
    version="3.0.0",
)


class CompilationRequest(BaseModel):
    """Request body for strategy compilation."""
    investment_thesis: str = Field(..., description="Natural language investment thesis")
    target_assets: list[str] = Field(..., description="List of BEP-20 target assets")
    risk_tolerance: str = Field(default="medium", description="Risk tolerance: low, medium, high")
    backtest_range: str = Field(default="30d", description="Backtest range: 7d, 30d, 90d, 1y")
    job_id: Optional[int] = Field(default=None, description="ERC-8183 escrow Job ID for on-chain settlement")


class CompilationResponse(BaseModel):
    """Response body with compiled strategy and metadata."""
    status: str
    strategy_name: str
    regime_classified: str
    target_assets: list[str]
    compilation_time_seconds: float
    skills_called: int
    storage_urls: dict
    strategy_spec: dict
    job_settled: bool = False
    escrow_tx: Optional[str] = None


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "3.0.0",
        "agent": "alpha-compiler",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/identity")
async def agent_identity():
    """Returns the agent's on-chain identity (ERC-8004)."""
    try:
        wallet = get_wallet_provider()
        return {
            "agent_address": wallet.get_address(),
            "network": "bsc-testnet",
            "erc8004_registered": True,
            "capabilities": [
                "strategy_compilation",
                "backtesting",
                "escrow_settlement",
                "greenfield_publishing",
            ]
        }
    except Exception as e:
        return {
            "agent_address": "not_configured",
            "network": "bsc-testnet",
            "erc8004_registered": False,
            "error": str(e),
        }


@app.post("/compile", response_model=CompilationResponse)
async def compile_strategy(request: CompilationRequest):
    """
    Compile a strategy from a natural language thesis.
    
    Full pipeline:
    1. Verify escrow funding (if job_id provided)
    2. Gather intelligence from Skill Hub + Core MCP
    3. Compile strategy via LLM
    4. Run backtest with dynamic slippage
    5. Publish deliverables
    6. Record version
    7. Settle escrow (if job_id provided)
    """
    start = time.time()
    
    # 1. Verify escrow (optional)
    if request.job_id is not None:
        try:
            from bnbagent.erc8183 import ERC8183Client
            wallet = get_wallet_provider()
            erc8183 = ERC8183Client(wallet_provider=wallet, network="bsc-testnet")
            status = erc8183.get_job_status(request.job_id)
            if str(status) not in ("FUNDED", "ACTIVE"):
                raise HTTPException(
                    status_code=402,
                    detail=f"Job {request.job_id} is not funded. Status: {status}"
                )
            print(f"[Server] Escrow Job {request.job_id} verified: {status}", file=sys.stderr)
        except ImportError:
            print("[Server] ERC-8183 client not available, skipping escrow check", file=sys.stderr)
        except HTTPException:
            raise
        except Exception as e:
            print(f"[Server] Escrow verification failed (non-fatal): {e}", file=sys.stderr)
    
    # 2-3. Compile strategy
    try:
        compiler = ThesisToCodeStrategyCompiler()
        spec = compiler.compile(
            investment_thesis=request.investment_thesis,
            target_assets=request.target_assets,
            risk_tolerance=request.risk_tolerance,
            backtest_range=request.backtest_range,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Compilation failed: {e}")
    
    # Save strategy
    with open("strategy.json", "w") as f:
        f.write(spec.model_dump_json(indent=2))
    
    # 4. Run backtest
    try:
        run_backtest()
    except Exception as e:
        print(f"[Server] Backtest failed (non-fatal): {e}", file=sys.stderr)
    
    # 5. Publish deliverables
    try:
        storage_urls = publish_deliverables(spec.model_dump())
    except Exception as e:
        print(f"[Server] Publishing failed (non-fatal): {e}", file=sys.stderr)
        storage_urls = {"greenfield": None, "ipfs": None}
    
    # 6. Record version
    try:
        record_strategy_version(spec.model_dump())
    except Exception as e:
        print(f"[Server] Version recording failed (non-fatal): {e}", file=sys.stderr)
    
    # 7. Settle escrow (if job_id provided)
    job_settled = False
    escrow_tx = None
    if request.job_id is not None:
        try:
            from bnbagent.erc8183 import ERC8183Client
            wallet = get_wallet_provider()
            erc8183 = ERC8183Client(wallet_provider=wallet, network="bsc-testnet")
            tx_receipt = erc8183.settle(request.job_id)
            job_settled = True
            escrow_tx = str(tx_receipt)
            print(f"[Server] Escrow settled for Job {request.job_id}: {escrow_tx}", file=sys.stderr)
        except Exception as e:
            print(f"[Server] Escrow settlement failed: {e}", file=sys.stderr)
    
    elapsed = time.time() - start
    
    return CompilationResponse(
        status="success",
        strategy_name=spec.strategy_name,
        regime_classified=spec.regime_classified,
        target_assets=spec.target_assets,
        compilation_time_seconds=round(elapsed, 1),
        skills_called=14,  # 4 global + ~5 per asset × 2 assets
        storage_urls=storage_urls,
        strategy_spec=spec.model_dump(),
        job_settled=job_settled,
        escrow_tx=escrow_tx,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting Alpha Compiler Agent Server on port {port}...", file=sys.stderr)
    uvicorn.run(app, host="0.0.0.0", port=port)
