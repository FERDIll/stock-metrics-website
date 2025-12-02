# scripts/build_fundamentals.py
#
# Minimal EDGAR → data/AAPL.json builder
# - Fetches SEC "companyfacts" for AAPL
# - Extracts a few key fundamentals
# - Writes them in the JSON format your site already expects

import json
import os
import requests

# -----------------------------
# CONFIG
# -----------------------------

# For now, just Apple. You can add more later.
TICKERS = ["AAPL"]

# Map ticker -> CIK (10 digits, zero padded)
CIK_MAP = {
    "AAPL": "0000320193",
}

SEC_BASE = "https://data.sec.gov/api/xbrl/companyfacts"

# IMPORTANT: replace with your email or some contact
HEADERS = {
    "User-Agent": "TransparentMetrics/0.1 (contact: your-email@example.com)"
}


# -----------------------------
# HELPERS
# -----------------------------

def fetch_company_facts(cik: str) -> dict:
    url = f"{SEC_BASE}/CIK{cik}.json"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def pick_latest_annual_usd(facts: dict, concept: str):
    """
    Pick the latest annual 10-K FY value for a given us-gaap concept (USD units).
    Returns None if not found.
    """
    try:
        entries = facts["us-gaap"][concept]["units"]["USD"]
    except KeyError:
        return None

    annual = [
        e for e in entries
        if e.get("form") == "10-K" and e.get("fp") == "FY" and "val" in e
    ]
    if not annual:
        return None

    annual.sort(key=lambda e: e.get("fy", 0), reverse=True)
    return annual[0]["val"]


def build_raw_from_edgar(company_facts: dict) -> dict:
    """
    Convert EDGAR companyfacts JSON into your simplified RAW structure.
    Only fills a few key fields; the rest can stay null.
    """
    facts = company_facts.get("facts", {})

    def latest(concept):
        return pick_latest_annual_usd(facts, concept)

    # ---------- Income statement ----------
    revenue = latest("Revenues") or latest("SalesRevenueNet")
    cogs = latest("CostOfRevenue") or latest("CostOfGoodsAndServicesSold")
    gross_profit = latest("GrossProfit")
    operating_income = latest("OperatingIncomeLoss") or latest("OperatingIncome")
    net_income = latest("NetIncomeLoss")

    # ---------- Balance sheet ----------
    total_assets = latest("Assets")
    total_liabilities = latest("Liabilities")
    equity = (
        latest("StockholdersEquity")
        or latest("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")
    )
    cash = (
        latest("CashAndCashEquivalentsAtCarryingValue")
        or latest("CashAndCashEquivalentsFairValueDisclosure")
    )
    long_term_debt = latest("LongTermDebtNoncurrent") or latest("LongTermDebt")
    short_term_debt = latest("DebtCurrent") or latest("ShortTermBorrowings")
    current_assets = latest("AssetsCurrent")
    current_liabilities = latest("LiabilitiesCurrent")

    # ---------- Cash flow ----------
    ocf = (
        latest("NetCashProvidedByUsedInOperatingActivities")
        or latest("NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")
    )
    capex = (
        latest("PaymentsToAcquirePropertyPlantAndEquipment")
        or latest("CapitalExpenditures")
    )
    if ocf is not None and capex is not None:
        # capex usually negative; ocf + capex ≈ FCF
        fcf = ocf + capex
    else:
        fcf = None

    dividends = latest("PaymentsOfDividends") or latest("PaymentsOfDividendsCommonStock")

    # ---------- Build RAW object ----------
    raw = {
        "asOf": company_facts.get("entityName", ""),
        "market": {
            # you can later add price etc from another source; for now null
            "sharePrice": None,
            "sharesOutstanding": None,
            "marketCap": None,
            "enterpriseValue": None,
            "historicalPrices": []
        },
        "statements": {
            "incomeStatement": {
                "revenue": revenue,
                "cogs": cogs,
                "grossProfit": gross_profit,
                "operatingExpenses": None,
                "depreciationAmort": None,
                "operatingIncomeEBIT": operating_income,
                "ebitda": None,
                "interestExpense": None,
                "pretaxIncome": None,
                "netIncome": net_income,
                "netIncomeExNRI": None
            },
            "balanceSheet": {
                "totalAssets": total_assets,
                "totalCurrentAssets": current_assets,
                "cashAndEquivalents": cash,
                "accountsReceivable": None,
                "inventory": None,
                "otherCurrentAssets": None,
                "totalLiabilities": total_liabilities,
                "currentLiabilities": current_liabilities,
                "accountsPayable": None,
                "longTermDebt": long_term_debt,
                "shortTermDebt": short_term_debt,
                "shareholdersEquity": equity,
                "investedCapital": None
            },
            "cashFlow": {
                "operatingCashFlow": ocf,
                "freeCashFlow": fcf,
                "capitalExpenditures": capex,
                "ownerEarnings": None,
                "dividendsPaid": dividends,
                "cashFlowFromFinancing": None,
                "taxRate": None
            }
        },
        "optional": {
            "quality": {
                "retainedEarnings": None,
                "workingCapital": None,
                "tenYearProfitHistory": [],
                "segmentRevenue": []
            },
            "multiYearFinancials": {
                "revenue": [],
                "ebitda": [],
                "netIncome": [],
                "freeCashFlow": [],
                "bookValue": []
            },
            "financingDetail": {
                "shareRepurchases": None,
                "shareIssuances": None
            }
        }
    }

    return raw


def main():
    os.makedirs("data", exist_ok=True)

    for ticker in TICKERS:
        cik = CIK_MAP.get(ticker)
        if not cik:
            print(f"[WARN] No CIK mapping for {ticker}, skipping.")
            continue

        print(f"[INFO] Fetching companyfacts for {ticker} (CIK {cik})")
        facts = fetch_company_facts(cik)
        raw = build_raw_from_edgar(facts)

        out_path = os.path.join("data", f"{ticker}.json")
        with open(out_path, "w") as f:
            json.dump(raw, f, indent=2)

        print(f"[OK] Wrote {out_path}")


if __name__ == "__main__":
    main()
