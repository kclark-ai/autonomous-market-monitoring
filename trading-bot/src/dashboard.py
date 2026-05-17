import threading
from flask import Flask, jsonify, request, Response
import src.state as state

app = Flask(__name__)

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0"/>
  <meta name="apple-mobile-web-app-capable" content="yes"/>
  <title>Trading Bot</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #0d1117; color: #e6edf3; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 16px; max-width: 600px; margin: 0 auto; }
    h1 { font-size: 1.3rem; font-weight: 600; margin-bottom: 4px; }
    .subtitle { font-size: 0.8rem; color: #7d8590; margin-bottom: 20px; }
    .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 16px; margin-bottom: 14px; }
    .card h2 { font-size: 0.75rem; text-transform: uppercase; letter-spacing: .08em; color: #7d8590; margin-bottom: 12px; }
    .row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
    .stat-label { font-size: 0.85rem; color: #7d8590; }
    .stat-value { font-size: 0.95rem; font-weight: 600; }
    .big-value { font-size: 1.6rem; font-weight: 700; }
    .green { color: #3fb950; } .red { color: #f85149; } .gray { color: #7d8590; }
    .pill { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }
    .pill-green { background: #1a3a2a; color: #3fb950; }
    .pill-red { background: #3a1a1a; color: #f85149; }
    table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
    th { text-align: left; color: #7d8590; font-weight: 500; padding: 4px 6px; border-bottom: 1px solid #30363d; }
    td { padding: 7px 6px; border-bottom: 1px solid #21262d; vertical-align: middle; }
    tr:last-child td { border-bottom: none; }
    .btn { display: inline-block; padding: 10px 24px; border-radius: 8px; border: none; font-size: 0.9rem; font-weight: 600; cursor: pointer; }
    .btn-stop { background: #da3633; color: #fff; }
    .btn-start { background: #238636; color: #fff; }
    .btn-row { display: flex; gap: 10px; margin-top: 4px; }
    .empty { color: #7d8590; font-size: 0.85rem; text-align: center; padding: 12px 0; }
    #last-updated { font-size: 0.75rem; color: #7d8590; text-align: right; margin-top: -10px; margin-bottom: 16px; }
  </style>
</head>
<body>
  <h1>Trading Bot</h1>
  <div class="subtitle">Auto-refreshes every 30s</div>
  <div id="last-updated"></div>
  <div class="card">
    <h2>Portfolio</h2>
    <div class="big-value" id="portfolio-value">-</div>
    <div style="margin-top:12px">
      <div class="row"><span class="stat-label">Cash available</span><span class="stat-value" id="cash">-</span></div>
      <div class="row"><span class="stat-label">Daily P&L</span><span class="stat-value" id="daily-pnl">-</span></div>
      <div class="row"><span class="stat-label">Bot status</span><span id="bot-status">-</span></div>
      <div class="row"><span class="stat-label">Last tick</span><span class="stat-value gray" id="last-tick">-</span></div>
    </div>
  </div>
  <div class="card">
    <h2>Controls</h2>
    <div class="btn-row">
      <button class="btn btn-stop" onclick="control('stop')">Stop Bot</button>
      <button class="btn btn-start" onclick="control('start')">Start Bot</button>
    </div>
  </div>
  <div class="card">
    <h2>Open Positions</h2>
    <div id="positions-body"><div class="empty">No open positions</div></div>
  </div>
  <div class="card">
    <h2>Recent Trades</h2>
    <div id="trades-body"><div class="empty">No trades yet</div></div>
  </div>
<script>
function fmt(n,d=2){return n==null?'-':'$'+parseFloat(n).toFixed(d).replace(/\\B(?=(\\d{3})+(?!\\d))/g,',');}
function colorClass(n){return n>=0?'green':'red';}
function pnlStr(n){return n==null?'':(n>=0?'+':'')+fmt(n);}
async function refresh(){
  try{
    const s=await(await fetch('/api/state')).json();
    document.getElementById('portfolio-value').textContent=fmt(s.portfolio_value);
    document.getElementById('cash').textContent=fmt(s.cash);
    const dpnl=document.getElementById('daily-pnl');
    dpnl.textContent=pnlStr(s.daily_pnl);dpnl.className='stat-value '+colorClass(s.daily_pnl);
    document.getElementById('bot-status').innerHTML=s.bot_running?'<span class="pill pill-green">Running</span>':'<span class="pill pill-red">Paused</span>';
    document.getElementById('last-tick').textContent=s.last_tick||'not yet';
    document.getElementById('last-updated').textContent='Updated '+new Date().toLocaleTimeString();
    const pos=Object.entries(s.positions||{});
    const posEl=document.getElementById('positions-body');
    if(pos.length===0){posEl.innerHTML='<div class="empty">No open positions</div>';}
    else{
      let h='<table><thead><tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Now</th><th>P&L</th></tr></thead><tbody>';
      for(const[sym,p]of pos){
        h+=`<tr><td><b>${sym}</b></td><td>${p.qty}</td><td>${fmt(p.entry_price)}</td><td>${fmt(p.current_price)}</td><td class="${colorClass(p.unrealized_pnl)}">${pnlStr(p.unrealized_pnl)}</td></tr>`;
      }
      posEl.innerHTML=h+'</tbody></table>';
    }
    const trades=s.trade_history||[];
    const trEl=document.getElementById('trades-body');
    if(trades.length===0){trEl.innerHTML='<div class="empty">No trades yet</div>';}
    else{
      let h='<table><thead><tr><th>Time</th><th>Action</th><th>Sym</th><th>Price</th><th>P&L</th></tr></thead><tbody>';
      for(const t of trades.slice(0,15)){
        h+=`<tr><td class="gray">${t.time}</td><td>${t.action}</td><td><b>${t.symbol}</b></td><td>${fmt(t.price)}</td><td class="${t.pnl==null?'':colorClass(t.pnl)}">${pnlStr(t.pnl)}</td></tr>`;
      }
      trEl.innerHTML=h+'</tbody></table>';
    }
  }catch(e){document.getElementById('last-updated').textContent='Refresh failed: '+e.message;}
}
async function control(a){await fetch('/api/'+a,{method:'POST'});await refresh();}
refresh();setInterval(refresh,30000);
</script>
</body>
</html>"""


@app.route("/")
def index():
    return Response(_HTML, mimetype="text/html")


@app.route("/api/state")
def api_state():
    return jsonify(state.get())


@app.route("/api/stop", methods=["POST"])
def api_stop():
    state.set_bot_running(False)
    return jsonify({"status": "stopped"})


@app.route("/api/start", methods=["POST"])
def api_start():
    state.set_bot_running(True)
    return jsonify({"status": "started"})


def start_dashboard(host="0.0.0.0", port=8080):
    t = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False),
        daemon=True, name="dashboard",
    )
    t.start()
    print(f"  [DASHBOARD] Running at http://0.0.0.0:{port}")
