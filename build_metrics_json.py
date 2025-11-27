import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
CSV_PATH = ROOT / "data" / "fundamentals.csv"

def to_float(row, key):
    """
    Safely convert a CSV cell to float (or None if empty).
    """
    val = row.get(key, "").strip()
    if val == "":
        return None
    try:
        return float(val)
    except ValueError:
        return None

def build_payload(row):
    """
    Build the JSON structure expected by your frontend from one CSV row.
    """
    return {
        "asOf": row.get("asOf", ""),

        "market": {
            "sharePrice": to_float(row, "sharePrice"),
            "sharesOutstanding": to_float(row, "sharesOut"),
            "marketCap": to_float(row, "marketCap"),
            "enterpriseValue": to_float(row, "enterpriseValue"),
            "historicalPrices": []
        },

        "statements": {
            "incomeStatement": {
                "revenue": to_float(row, "revenue"),
                "cogs": to_float(row, "cogs"),
                "grossProfit": None,  # can derive later if you want
                "operatingExpenses": None,  # not in CSV yet
                "depreciationAmort": None,
                "operatingIncomeEBIT": to_float(row, "opIncome"),
                "ebitda": None,
                "interestExpense": None,
                "pretaxIncome": None,
                "netIncome": to_float(row, "netIncome"),
                "netIncomeExNRI": None
            },
            "balanceSheet": {
                "totalAssets": to_float(row, "totalAssets"),
                "totalCurrentAssets": to_float(row, "currAssets"),
                "cashAndEquivalents": to_float(row, "cash"),
                "accountsReceivable": None,
                "inventory": None,
                "otherCurrentAssets": None,
                "totalLiabilities": None,
                "currentLiabilities": to_float(row, "currLiab"),
                "accountsPayable": None,
                "longTermDebt": to_float(row, "ltDebt"),
                "shortTermDebt": to_float(row, "stDebt"),
                "shareholdersEquity": None,
                "investedCapital": None
            },
            "cashFlow": {
                "operatingCashFlow": to_float(row, "opCF"),
                "freeCashFlow": to_float(row, "fcf"),
                "capitalExpenditures": to_float(row, "capex"),
                "ownerEarnings": None,
                "dividendsPaid": None,
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

def main():
    if len(sys.argv) < 2:
        print("Usage: python build_metrics_json.py TICKER")
        sys.exit(1)

    ticker = sys.argv[1].upper()

    if not CSV_PATH.exists():
        print(f"CSV not found at {CSV_PATH}")
        sys.exit(1)

    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    row_for_ticker = None
    for row in rows:
        if row.get("ticker", "").upper() == ticker:
            row_for_ticker = row
            break

    if row_for_ticker is None:
        print(f"Ticker {ticker} not found in {CSV_PATH}")
        sys.exit(1)

    payload = build_payload(row_for_ticker)

    out_path = ROOT / "data" / f"{ticker}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Wrote {out_path}")

if __name__ == "__main__":
    main()
