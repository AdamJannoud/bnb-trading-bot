from aiohttp import web
from db_manager import get_dashboard_metrics
import traceback

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Owner Analytics Dashboard</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0e1118; color: #fff; margin: 0; padding: 30px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .card {{ background: #181f2c; padding: 20px; border-radius: 12px; border: 1px solid #283347; }}
        .card h3 {{ margin: 0 0 10px 0; color: #8a99ad; font-size: 14px; text-transform: uppercase; }}
        .card .value {{ font-size: 26px; font-weight: bold; color: #00f2fe; }}
        table {{ width: 100%; border-collapse: collapse; background: #181f2c; border-radius: 12px; overflow: hidden; }}
        th, td {{ padding: 14px 18px; text-align: left; border-bottom: 1px solid #283347; font-size: 14px; }}
        th {{ background: #202b3d; color: #8a99ad; }}
        .badge {{ padding: 4px 8px; border-radius: 4px; font-weight: bold; }}
        .badge-buy {{ background: #00c07624; color: #00c076; }}
        .badge-sell {{ background: #ff475724; color: #ff4757; }}
        a {{ color: #00f2fe; text-decoration: none; }}
    </style>
</head>
<body>
    <h1>⚡ Bot Owner Dashboard</h1>
    <div class="grid">
        <div class="card"><h3>Total Users</h3><div class="value">{total_users}</div></div>
        <div class="card"><h3>Total Volume</h3><div class="value">{total_volume} BNB</div></div>
        <div class="card"><h3>Total Earned (1% Fee)</h3><div class="value" style="color: #00c076;">{total_fees} BNB</div></div>
        <div class="card"><h3>Total Trades</h3><div class="value">{total_trades}</div></div>
    </div>
    <h2>Live Trade History</h2>
    <table>
        <tr><th>Type</th><th>Token</th><th>Amount</th><th>Fee</th><th>Tx</th></tr>
        {table_rows}
    </table>
</body>
</html>
"""

async def dashboard_handler(request):
    try:
        data = get_dashboard_metrics()
        rows = ""
        for trade in data["recent_trades"]:
            ttype, token, amt, fee, tx = trade
            token_str = str(token) if token else "Unknown"
            short_token = f"{token_str[:8]}...{token_str[-6:]}" if len(token_str) > 14 else token_str
            
            badge_class = "badge-buy" if ttype == "BUY" else "badge-sell"
            rows += f"""
            <tr>
                <td><span class="badge {badge_class}">{ttype}</span></td>
                <td><code>{short_token}</code></td>
                <td>{amt:.4f} BNB</td>
                <td>{fee:.4f} BNB</td>
                <td><a href="https://bscscan.com/tx/{tx}" target="_blank">BscScan ↗</a></td>
            </tr>
            """
        
        if not rows:
            rows = "<tr><td colspan='5' style='text-align: center; color: #8a99ad;'>No transactions recorded yet.</td></tr>"

        html = HTML_TEMPLATE.format(
            total_users=data["total_users"],
            total_volume=data["total_volume"],
            total_fees=data["total_fees"],
            total_trades=data["total_trades"],
            table_rows=rows
        )
        return web.Response(text=html, content_type="text/html")
        
    except Exception as e:
        error_trace = traceback.format_exc()
        error_html = f"<div style='background:#222; color:#ff4757; padding:20px; font-family:monospace;'><h2>Dashboard Error:</h2><pre>{error_trace}</pre></div>"
        return web.Response(text=error_html, status=500, content_type="text/html")

def create_dashboard_app():
    app = web.Application()
    app.router.add_get("/", dashboard_handler)
    return app