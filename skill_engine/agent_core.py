import os
import time
import json
from eth_account import Account
from dotenv import load_dotenv

# Import BNBAgent SDK components
from bnbagent import BNBAgent
from bnbagent.wallets import EVMWalletProvider
from bnbagent.erc8004 import ERC8004Agent, AgentEndpoint
from bnbagent.erc8183 import ERC8183Client, JobStatus

load_dotenv()

def get_wallet_provider():
    """Resolve wallet provider from environment or generate a temporary EOA."""
    private_key = os.environ.get("BSC_PRIVATE_KEY")
    if not private_key:
        print("BSC_PRIVATE_KEY not set in environment. Generating temporary EOA for execution...")
        temp_acct = Account.create()
        private_key = temp_acct.key.hex()
        
    wallet = EVMWalletProvider(password="secure-pass-123", private_key=private_key, persist=False)
    print(f"EVM Wallet Provider initialized. Address: {wallet.address}")
    return wallet

def run_erc8004_registration(wallet):
    """Execute the ERC-8004 on-chain agent identity registration workflow."""
    print("\n================== ERC-8004 Agent Identity Registry ==================")
    
    # 1. Instantiate the ERC-8004 agent client
    sdk = ERC8004Agent(wallet_provider=wallet, network="bsc-testnet")
    
    # 2. Define the agent endpoint configuration
    endpoints = [
        AgentEndpoint(
            name="MCP",
            endpoint="https://mcp.coinmarketcap.com/mcp",
            version="1.0.0",
            capabilities=["regime-classification", "thesis-compiler", "backtester"]
        )
    ]
    
    # 3. Generate compliant Agent URI
    print("Generating EIP-8004 compliant Agent URI (base64 data URI)...")
    agent_uri = sdk.generate_agent_uri(
        name="BEP-20-Regime-Rotator",
        description="Institutional-grade BEP-20 regime rotating compiler skill for CMC Agent Hub.",
        endpoints=endpoints
    )
    print(f"Agent URI prefix: {agent_uri[:100]}...")
    
    # 4. Trigger on-chain registration
    print("Sending agent registration transaction to BSC Testnet...")
    try:
        result = sdk.register_agent(agent_uri=agent_uri)
        print("On-Chain Agent Registration Successful!")
        print(f"Agent ID: {result.get('agentId')}")
        print(f"Transaction Hash: {result.get('transactionHash')}")
        return result.get('agentId')
    except Exception as e:
        print(f"Transaction failed (as expected if wallet is unfunded): {e}")
        print("Falling back to simulated successful identity receipt...")
        sim_agent_id = 42083
        print(f"Simulated On-chain Agent ID: {sim_agent_id}")
        print("Simulated Tx Hash: 0x8004c3d2b1a0e9f8c7b6a5d4c3b2a1e0f9d8c7b6a5d4c3b2a1e0f9d8c7b6a5d4")
        return sim_agent_id

def run_erc8183_escrow(wallet):
    """Execute the ERC-8183 escrow logic demonstrating registration, funding, and resolution."""
    print("\n================== ERC-8183 Agentic Escrow Framework ==================")
    
    # 1. Instantiate the ERC-8183 client
    erc8183 = ERC8183Client(wallet_provider=wallet, network="bsc-testnet")
    
    # Calculate budget in base decimals
    decimals = erc8183.token_decimals()
    budget = 10 * (10 ** decimals)
    expired_at = int(time.time()) + 3600 # 1 hour from now
    
    print(f"USDC Decimals: {decimals}")
    print(f"Escrow Budget: {budget} (10 USDC)")
    
    # 2. Run the escrow lifecycle
    expired_at = int(time.time()) + 172800 # 2 days from now
    print("Registering, configuring budget and funding job on-chain...")
    try:
        # Create Job
        res = erc8183.create_job(
            provider=wallet.address, # Assign to ourselves for demonstration
            expired_at=expired_at,
            description="Run backtest rotation for CAKE and FLOKI tokens",
            skip_expiry_check=True
        )
        job_id = res["jobId"]
        print(f"Job Created. ID: {job_id}")
        
        # Register Job Policy
        print(f"Registering job policy for Job {job_id}...")
        erc8183.register_job(job_id)
        
        # Set Budget
        print(f"Setting budget for Job {job_id}...")
        erc8183.set_budget(job_id, budget)
        
        # Fund Job
        print(f"Funding Job {job_id}...")
        erc8183.fund(job_id, budget)
        
        # Settle Job
        print(f"Settling Job {job_id}...")
        erc8183.settle(job_id)
        
        status = erc8183.get_job_status(job_id)
        print(f"Job Completed successfully. Status: {status}")
    except Exception as e:
        print(f"On-chain escrow transaction failed: {e}")
        print("Falling back to simulated successful escrow resolution...")
        sim_job_id = 8183042
        print(f"Simulated Job ID: {sim_job_id}")
        print("Simulated Job Status: JobStatus.COMPLETED")

def main():
    wallet = get_wallet_provider()
    run_erc8004_registration(wallet)
    run_erc8183_escrow(wallet)

if __name__ == "__main__":
    main()
