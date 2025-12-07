# scripts/build_fundamentals.py
#
# EDGAR → data/<TICKER>.json builder
# - Fetches SEC "companyfacts" for each ticker
# - Extracts key fundamentals
# - Writes them in the JSON format your site expects (AAPL_RAW-style)

import json
import os
import time
from typing import Any, Dict, List, Optional

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


HEADERS = {
    "User-Agent": "TransparentMetrics/0.1 (contact: transparant.metrics@atomicmail.io)"
}

# Where to write JSON (repo root / data)
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT_DIR, "data")


# -----------------------------
# HELPERS
# -----------------------------

def fetch_company_facts(cik: str) -> Dict[str, Any]:
    """Fetch SEC companyfacts JSON for a given CIK."""
    url = f"{SEC_BASE}/CIK{cik}.json"
    print(f"[HTTP] GET {url}")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def pick_latest_annual_entry(facts: Dict[str, Any], concept: str) -> Optional[Dict[str, Any]]:
    """
    Return the latest annual 10-K FY entry for a given us-gaap concept (USD units),
    or None if not found.
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
    return annual[0]


def pick_latest_annual_usd(facts: Dict[str, Any], concept: str) -> Optional[float]:
    """Convenience wrapper returning just the numeric value."""
    entry = pick_latest_annual_entry(facts, concept)
    if entry is None:
        return None
    return entry.get("val")


def build_multi_year_series(
    facts: Dict[str, Any],
    concept: str,
    limit_years: int = 10
) -> List[Dict[str, Any]]:
    """
    Build a simple [{fy: 2024, value: ...}, ...] list for up to limit_years
    using annual 10-K FY USD values for a given concept.
    """
    try:
        entries = facts["us-gaap"][concept]["units"]["USD"]
    except KeyError:
        return []

    annual = [
        e for e in entries
        if e.get("form") == "10-K"
        and e.get("fp") == "FY"
        and "val" in e
        and "fy" in e
    ]
    if not annual:
        return []

    # sort newest -> oldest
    annual.sort(key=lambda e: e.get("fy", 0), reverse=True)

    out: List[Dict[str, Any]] = []
    seen_years = set()

    for e in annual:
        fy = e["fy"]
        if fy in seen_years:
            continue
        seen_years.add(fy)
        out.append({"fy": fy, "value": e["val"]})
        if len(out) >= limit_years:
            break

    # reverse to oldest -> newest for nicer reading
    out.reverse()
    return out


def build_raw_from_edgar(company_facts: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert EDGAR companyfacts JSON into your simplified RAW structure.
    Only fills a set of key fields; the rest can stay null.
    """
    facts = company_facts.get("facts", {})

    def latest(concept: str) -> Optional[float]:
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

    # derived
    working_capital = None
    if current_assets is not None and current_liabilities is not None:
        working_capital = current_assets - current_liabilities

    retained_earnings = latest("RetainedEarningsAccumulatedDeficit")

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

    # ---------- Multi-year histories ----------
    ten_year_profit_history = build_multi_year_series(
        facts, "NetIncomeLoss", limit_years=10
    )
    revenue_history = build_multi_year_series(
        facts, "Revenues", limit_years=10
    ) or build_multi_year_series(
        facts, "SalesRevenueNet", limit_years=10
    )
    fcf_history = []  # could be built from OCF & Capex per year later

    # ---------- asOf: try to infer last FY end date ----------
    as_of = None
    ref_entry = (
        pick_latest_annual_entry(facts, "Assets")
        or pick_latest_annual_entry(facts, "Revenues")
        or pick_latest_annual_entry(facts, "NetIncomeLoss")
    )
    if ref_entry is not None:
        # 'end' is usually like '2024-09-28'
        as_of = ref_entry.get("end") or str(ref_entry.get("fy"))
    else:
        # fallback to entityName if nothing else
        as_of = company_facts.get("entityName", "")

    # ---------- Build RAW object ----------
    raw: Dict[str, Any] = {
        "asOf": as_of,
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
                "retainedEarnings": retained_earnings,
                "workingCapital": working_capital,
                "tenYearProfitHistory": ten_year_profit_history,
                "segmentRevenue": []
            },
            "multiYearFinancials": {
                "revenue": revenue_history,
                "ebitda": [],
                "netIncome": ten_year_profit_history,
                "freeCashFlow": fcf_history,
                "bookValue": []
            },
            "financingDetail": {
                "shareRepurchases": None,
                "shareIssuances": None
            }
        }
    }

    return raw


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    for ticker in TICKERS:
        cik = CIK_MAP.get(ticker)
        if not cik:
            print(f"[WARN] No CIK mapping for {ticker}, skipping.")
            continue

        try:
            print(f"[INFO] Fetching companyfacts for {ticker} (CIK {cik})")
            facts = fetch_company_facts(cik)
            raw = build_raw_from_edgar(facts)

            out_path = os.path.join(DATA_DIR, f"{ticker}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(raw, f, indent=2)

            print(f"[OK] Wrote {out_path}")
        except requests.HTTPError as e:
            print(f"[ERROR] HTTP error for {ticker}: {e}")
        except Exception as e:
            print(f"[ERROR] Unexpected error for {ticker}: {e}")

        # Be nice to SEC; small pause between requests
        time.sleep(0.25)


if __name__ == "__main__":
    main()
