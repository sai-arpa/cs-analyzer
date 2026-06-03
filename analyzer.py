# analyzer.py
# Core analysis module: fetch CS markdown from DB, send to Gemini, return structured insights.
# Run directly: python analyzer.py [doc_no] [purchaser|cxo]

import os
import sys
import json
import urllib.parse
from sqlalchemy import create_engine
from dotenv import load_dotenv
from google import genai
from google.genai import types

# ── Resolve project root & load env ──────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

load_dotenv(os.path.join(PROJECT_ROOT, "langchain", ".env"))

from utils.token_counter import count_openai_tokens

# ── DB config — all values from .env ─────────────────────────────────────────
def _build_conn_str() -> str:
    ip       = os.getenv("IP_ADDRESS")
    database = os.getenv("CS_DATABASE")
    user     = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")

    missing = [k for k, v in {
        "IP_ADDRESS": ip, "CS_DATABASE": database,
        "DB_USER": user,  "DB_PASSWORD": password,
    }.items() if not v]
    if missing:
        raise RuntimeError(f"Missing required .env keys: {', '.join(missing)}")

    odbc = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={ip};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        "TrustServerCertificate=yes;"
        "Connect Timeout=90;"
    )
    return f"mssql+pyodbc:///?odbc_connect={urllib.parse.quote_plus(odbc)}"


# ── JSON output schema ────────────────────────────────────────────────────────
INSIGHT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "num":     {"type": "integer", "description": "Point number 1-10"},
            "heading": {"type": "string",  "description": "Short heading label"},
            "body":    {"type": "string",  "description": "Insight text with **bold** markers on key terms"},
        },
        "required": ["num", "heading", "body"],
    },
    "minItems": 10,
    "maxItems": 10,
}

# ── Shared bold rule ──────────────────────────────────────────────────────────
_BOLD_RULE = (
    "MANDATORY OUTPUT RULE:\n"
    "In every body string, wrap important words with **double asterisks**.\n"
    "Always bold: rupee amounts (e.g. **\u20b98,545.56**), vendor names (e.g. **FIPL SUPPLIER 02**),\n"
    "item codes, quantities, dates, and decision words (e.g. **NEGOTIATE**, **TOPAY**, **expired**).\n"
    "Minimum 3 bolded terms per body. A body with no bold markers is incorrect output.\n"
    "Example of a correct body string:\n"
    '  "**FIPL SUPPLIER 02** is L1 at **\u20b98,545.56** including GST. '
    'Quote **632** expires **20 Oct 2020**. Action: **NEGOTIATE**."\n\n'
)

# ── Shared JSON footer ────────────────────────────────────────────────────────
_JSON_FOOTER = (
    "\nOutput format: a JSON array of exactly 10 objects.\n"
    'Each object: {{"num": <int>, "heading": "<label>", "body": "<text with **bold** markers>"}}\n'
    "Raw JSON only — no code fences, no markdown wrapper.\n"
    "\n---\n\n{cs_markdown}\n"
)

# ── Prompts ───────────────────────────────────────────────────────────────────
PURCHASER_PROMPT = (
    _BOLD_RULE
    + "Analyze this Comparative Statement as a Senior Procurement Consultant.\n"
    "Give exactly 10 short decision-ready insights for a Purchaser. Each body under 30 words.\n"
    "Cover in order:\n"
    "1. Price Movement - Count and total Rs amount of items Costlier / Cheaper / Same vs last PO.\n"
    "2. Biggest Cost Jump - One item, last rate, current rate, extra Rs amount.\n"
    "3. Save Here - Best negotiation or make-substitution opportunity with exact Rs saving.\n"
    "4. Competition Health - Invited vs quoted vs regret count. One-word competition strength.\n"
    "5. Discount Alarm - Item where discount is missing or inconsistent. Flag overpriced vs last PO.\n"
    "6. Freight Watch - Which vendor is TOPAY vs FOR. Estimated Rs freight impact on landed cost.\n"
    "7. Delay Alert - Days since RFQ. Quotation validity status. One-line urgency flag.\n"
    "8. Compliance - Flag expired validity, unauthorized CS, self-authorization, make deviation.\n"
    "9. Total Outgo - L1 value + GST + freight = final landed cost in one line.\n"
    "10. Decision - One action word: AWARD / NEGOTIATE / HOLD / RE-TENDER. Top 2 conditions only.\n"
    + _JSON_FOOTER
)

CXO_PROMPT = (
    _BOLD_RULE
    + "Analyze this Comparative Statement as a Senior Procurement Consultant.\n"
    "Give exactly 10 CXO-level insights. Each body under 50 words.\n"
    "Cover in order:\n"
    "1. Price Movement - L1 rate vs last PO for each item. Count: Costlier / Cheaper / Same.\n"
    "2. Biggest Expense Alert - Single item driving maximum cost increase vs last PO.\n"
    "3. Saving Opportunity - Item where substitution or negotiation saves money. Exact Rs saving.\n"
    "4. Vendor Competition Health - Vendors invited vs quoted vs regretted. Flag weak competition.\n"
    "5. Discount Pattern Alarm - Vendor with zero or inconsistent discount. Flag overpriced.\n"
    "6. Hidden Cost Alert - Freight terms difference between vendors. Estimated Rs landed cost impact.\n"
    "7. Process Delay Alarm - Days from RFQ date to CS date. Flag if beyond acceptable TAT.\n"
    "8. Compliance Flag - Expired validity, missing authorization, self-authorization, make deviation.\n"
    "9. Total Spend Summary - L1 total value + GST + freight = estimated landed cost.\n"
    "10. Recommended Action - One word: AWARD / NEGOTIATE / HOLD / RE-TENDER. Top 2 conditions only.\n"
    + _JSON_FOOTER
)

PROMPTS = {
    "purchaser": PURCHASER_PROMPT,
    "cxo":       CXO_PROMPT,
}


# ── DB helpers ────────────────────────────────────────────────────────────────
def get_engine():
    return create_engine(_build_conn_str(), connect_args={"timeout": 90})


def fetch_cs_markdown(engine, doc_no: str) -> str:
    """Call GetCSDetailMarkdown_AI SP and return the markdown string."""
    raw_conn = engine.raw_connection()
    try:
        cursor = raw_conn.cursor()
        cursor.execute(f"exec Purchase.GetCSDetailMarkdown_AI '{doc_no}', Null")
        row = cursor.fetchone()
        cursor.close()
        if row is None or row[0] is None:
            raise ValueError(f"No data returned by SP for doc_no='{doc_no}'")
        return row[0].replace("\r\n", "\n").strip()
    finally:
        raw_conn.close()


# ── Gemini call ───────────────────────────────────────────────────────────────
def analyze_with_gemini(prompt: str, model_name: str = "gemini-2.5-flash") -> dict:
    """Send prompt to Gemini (JSON mode). Returns {'insights': list, 'token_usage': dict}."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set in .env")

    client   = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=INSIGHT_SCHEMA,
        ),
    )

    insights = json.loads(response.text)

    usage = response.usage_metadata
    token_usage = {
        "gemini_input":  getattr(usage, "prompt_token_count",     None),
        "gemini_output": getattr(usage, "candidates_token_count", None),
        "gemini_total":  getattr(usage, "total_token_count",      None),
        "openai_input":  count_openai_tokens(prompt),
        "openai_output": count_openai_tokens(response.text),
    }
    token_usage["openai_total"] = (
        (token_usage["openai_input"] or 0) + (token_usage["openai_output"] or 0)
    )

    return {"insights": insights, "token_usage": token_usage}


# ── Public API ────────────────────────────────────────────────────────────────
def run_analysis(doc_no: str, mode: str = "purchaser") -> tuple[list, dict]:
    """Full pipeline: fetch CS markdown → prompt → Gemini → return (insights, token_usage)."""
    template    = PROMPTS.get(mode, PURCHASER_PROMPT)
    engine      = get_engine()
    cs_markdown = fetch_cs_markdown(engine, doc_no)
    prompt      = template.format(cs_markdown=cs_markdown)
    result      = analyze_with_gemini(prompt)
    return result["insights"], result["token_usage"]


# ── CLI ───────────────────────────────────────────────────────────────────────
def _print_token_summary(token_usage: dict):
    print("\n" + "─" * 52)
    print(f"  {'TOKEN USAGE SUMMARY':^48}")
    print("─" * 52)
    print(f"  {'Metric':<28} {'Gemini':>10} {'OpenAI':>10}")
    print("─" * 52)
    for label, gk, ok in [
        ("Input  (prompt) tokens",   "gemini_input",  "openai_input"),
        ("Output (response) tokens", "gemini_output", "openai_output"),
        ("Total tokens",             "gemini_total",  "openai_total"),
    ]:
        print(f"  {label:<28} {str(token_usage.get(gk, 'N/A')):>10} {str(token_usage.get(ok, 'N/A')):>10}")
    print("─" * 52 + "\n")


if __name__ == "__main__":
    _doc_no = sys.argv[1] if len(sys.argv) > 1 else "000186"
    _mode   = sys.argv[2] if len(sys.argv) > 2 else "purchaser"
    print(f"Analyzing CS document: {_doc_no}  |  mode: {_mode}\n")
    _insights, _token_usage = run_analysis(_doc_no, _mode)
    for c in _insights:
        print(f"{c['num']}. {c['heading']}")
        print(f"   {c['body']}\n")
    _print_token_summary(_token_usage)
