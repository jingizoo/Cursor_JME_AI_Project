from pathlib import Path
import datetime as dt
import duckdb
import pandas as pd
import numpy as np

def period_range(period: str):
    p = pd.Period(period, freq="M")
    start = p.to_timestamp(how="start")
    end = p.to_timestamp(how="end")
    return start, end

def monthly_pl(con, period: str):
    start, end = period_range(period)
    rev = con.execute("SELECT COALESCE(SUM(taxable_value),0) FROM invoices WHERE invoice_date BETWEEN ? AND ?", [start,end]).fetchone()[0]
    exp = con.execute("SELECT COALESCE(SUM(taxable_value),0) FROM expenses WHERE expense_date BETWEEN ? AND ?", [start,end]).fetchone()[0]
    net = float(rev) - float(exp)
    prev = (pd.Period(period,'M')-1).strftime('%Y-%m')
    s2,e2 = period_range(prev)
    rev_prev = con.execute("SELECT COALESCE(SUM(taxable_value),0) FROM invoices WHERE invoice_date BETWEEN ? AND ?", [s2,e2]).fetchone()[0]
    exp_prev = con.execute("SELECT COALESCE(SUM(taxable_value),0) FROM expenses WHERE expense_date BETWEEN ? AND ?", [s2,e2]).fetchone()[0]
    summary = pd.DataFrame([
        {"Metric":"Revenue (Taxable)", "Amount": float(rev)},
        {"Metric":"Expenses (Taxable)", "Amount": float(exp)},
        {"Metric":"Net Profit (simple)", "Amount": float(net)},
    ])
    variance = pd.DataFrame([{
        "period": period, "prev_period": prev,
        "revenue_change": float(rev) - float(rev_prev),
        "expense_change": float(exp) - float(exp_prev),
    }])
    return summary, variance

def cashflow(con, period: str, opening_cash: float = 1500000.0):
    start, end = period_range(period)
    inflow = con.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE payment_date BETWEEN ? AND ?", [start,end]).fetchone()[0]
    outflow = con.execute("SELECT COALESCE(SUM(paid_amount),0) FROM expenses WHERE expense_date BETWEEN ? AND ?", [start,end]).fetchone()[0]
    closing = opening_cash + float(inflow) - float(outflow)
    return pd.DataFrame([
        {"Metric":"Opening Cash", "Amount": opening_cash},
        {"Metric":"Collections", "Amount": float(inflow)},
        {"Metric":"Payments", "Amount": float(outflow)},
        {"Metric":"Closing Cash", "Amount": float(closing)},
    ])

def gst(con, period: str):
    start, end = period_range(period)
    out_gst = con.execute("SELECT COALESCE(SUM(gst_amount),0) FROM invoices WHERE invoice_date BETWEEN ? AND ?", [start,end]).fetchone()[0]
    itc = con.execute("SELECT COALESCE(SUM(gst_amount),0) FROM expenses WHERE expense_date BETWEEN ? AND ?", [start,end]).fetchone()[0]
    return pd.DataFrame([
        {"Metric":"Output GST", "Amount": float(out_gst)},
        {"Metric":"ITC", "Amount": float(itc)},
        {"Metric":"Net GST Liability", "Amount": float(out_gst)-float(itc)},
    ])

def tds(con, period: str):
    start, end = period_range(period)
    tds_amt = con.execute("SELECT COALESCE(SUM(tds_amount),0) FROM expenses WHERE expense_date BETWEEN ? AND ?", [start,end]).fetchone()[0]
    p = pd.Period(period, "M")
    nm = (p+1).to_timestamp(how="start").date()
    due = dt.date(nm.year, nm.month, 7)
    return pd.DataFrame([
        {"Metric":"TDS to Deposit (month)", "Amount": float(tds_amt)},
        {"Metric":"Indicative due date", "Amount": due.isoformat()},
    ])

def ar_aging(con, as_of: str):
    q = """
    WITH paid AS (
        SELECT invoice_id, COALESCE(SUM(amount),0) AS paid_amount
        FROM payments
        GROUP BY invoice_id
    )
    SELECT
      i.client,
      i.invoice_id,
      i.invoice_date,
      i.due_date,
      i.invoice_total,
      COALESCE(p.paid_amount,0) AS paid_amount,
      (COALESCE(i.invoice_total,0) - COALESCE(p.paid_amount,0)) AS outstanding,
      GREATEST(0, CAST(? AS DATE) - CAST(i.due_date AS DATE)) AS days_past_due
    FROM invoices i
    LEFT JOIN paid p ON p.invoice_id = i.invoice_id
    WHERE (COALESCE(i.invoice_total,0) - COALESCE(p.paid_amount,0)) > 1
    ORDER BY days_past_due DESC
    """
    df = con.execute(q, [as_of]).df()
    def bucket(d):
        if d <= 30: return "0-30"
        if d <= 60: return "31-60"
        if d <= 90: return "61-90"
        return "90+"
    df["bucket"] = df["days_past_due"].apply(bucket)
    aging = df.groupby(["client","bucket"])["outstanding"].sum().reset_index()
    return aging, df

def bank_reco(con, period: str):
    start, end = period_range(period)
    bank = con.execute("SELECT * FROM bank_txns WHERE txn_date BETWEEN ? AND ?", [start,end]).df()
    pays = con.execute("SELECT amount FROM payments WHERE payment_date BETWEEN ? AND ?", [start,end]).df()
    exps = con.execute("SELECT paid_amount FROM expenses WHERE expense_date BETWEEN ? AND ?", [start,end]).df()
    bank["matched"] = False
    pay_amts = set(round(x,2) for x in pays["amount"].dropna().tolist())
    exp_amts = set(round(x,2) for x in exps["paid_amount"].dropna().tolist())
    for idx, r in bank.iterrows():
        if pd.isna(r["amount"]):
            continue
        a2 = round(float(r["amount"]),2)
        if r["direction"] == "IN" and a2 in pay_amts:
            bank.loc[idx,"matched"] = True
        if r["direction"] == "OUT" and a2 in exp_amts:
            bank.loc[idx,"matched"] = True
    summary = pd.DataFrame([
        {"Metric":"Bank txns", "Amount": int(len(bank))},
        {"Metric":"Matched", "Amount": int(bank["matched"].sum())},
        {"Metric":"Unmatched", "Amount": int((~bank["matched"]).sum())},
    ])
    return summary, bank[~bank["matched"]]

def generate_report_pack(db_path: Path, out_dir: Path, period: str, opening_cash: float = 1500000.0):
    con = duckdb.connect(str(db_path))
    pl_sum, pl_var = monthly_pl(con, period)
    cash_df = cashflow(con, period, opening_cash=opening_cash)
    gst_df = gst(con, period)
    tds_df = tds(con, period)
    aging, ar_detail = ar_aging(con, as_of=str(pd.Period(period,"M").to_timestamp(how="end").date()))
    bank_sum, bank_unmatched = bank_reco(con, period)

    out_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = out_dir / f"ai_report_pack_{period}.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        pl_sum.to_excel(w, sheet_name="P&L", index=False)
        pl_var.to_excel(w, sheet_name="P&L_Variance", index=False)
        cash_df.to_excel(w, sheet_name="Cashflow", index=False)
        gst_df.to_excel(w, sheet_name="GST", index=False)
        tds_df.to_excel(w, sheet_name="TDS", index=False)
        aging.to_excel(w, sheet_name="AR_Aging", index=False)
        ar_detail.to_excel(w, sheet_name="AR_Detail", index=False)
        bank_sum.to_excel(w, sheet_name="BankReco", index=False)
        bank_unmatched.to_excel(w, sheet_name="Bank_Unmatched", index=False)
    return xlsx_path
