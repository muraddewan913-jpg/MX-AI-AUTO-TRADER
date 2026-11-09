import os
import time
import logging
import threading
from datetime import datetime, timezone
from collections import deque

import requests
import telebot
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "90"))
DEMO_STAKE = float(os.getenv("DEMO_STAKE", "1"))
DEMO_START_BALANCE = float(os.getenv("DEMO_START_BALANCE", "100"))
PAPER_PAYOUT = float(os.getenv("PAPER_PAYOUT", "0.80"))
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "75"))

if not BOT_TOKEN:
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN in .env")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Major FX pairs. Twelve Data uses slash notation.
PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "USD/CAD", "NZD/USD"
]

# In-memory demo ledger. It resets when the bot restarts.
demo = {}  # chat_id -> {"balance": float, "open": list, "history": deque}
auto_demo = set()
last_scan = {}

def get_account(chat_id):
    if chat_id not in demo:
        demo[chat_id] = {
            "balance": DEMO_START_BALANCE,
            "open": [],
            "history": deque(maxlen=100)
        }
    return demo[chat_id]

def fetch_candles(pair, interval="1min", outputsize=80):
    if not TWELVE_DATA_API_KEY:
        raise RuntimeError("Twelve Data API key is not configured. Add TWELVE_DATA_API_KEY to .env")
    url = "https://api.twelvedata.com/time_series"
    response = requests.get(url, params={
        "symbol": pair,
        "interval": interval,
        "outputsize": outputsize,
        "timezone": "UTC",
        "apikey": TWELVE_DATA_API_KEY
    }, timeout=20)
    response.raise_for_status()
    data = response.json()
    if "values" not in data:
        raise RuntimeError(data.get("message", data.get("code", "No candle data returned")))
    rows = list(reversed(data["values"]))
    candles = []
    for r in rows:
        candles.append({
            "time": r["datetime"],
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        })
    return candles

def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = alpha * value + (1 - alpha) * result
    return result

def rsi(values, period=14):
    if len(values) <= period:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0)) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))

def analyze(candles):
    if len(candles) < 35:
        return None
    closes = [c["close"] for c in candles]
    last = candles[-1]
    prev = candles[-2]
    fast = ema(closes[-35:], 9)
    slow = ema(closes[-35:], 21)
    momentum = rsi(closes[-35:], 14)
    candle_range = max(last["high"] - last["low"], 1e-12)
    body = abs(last["close"] - last["open"])
    upper_wick = last["high"] - max(last["open"], last["close"])
    lower_wick = min(last["open"], last["close"]) - last["low"]
    recent = candles[-21:-1]
    support = min(c["low"] for c in recent)
    resistance = max(c["high"] for c in recent)
    near_support = (last["close"] - support) / max(last["close"], 1e-12) < 0.0007
    near_resistance = (resistance - last["close"]) / max(last["close"], 1e-12) < 0.0007

    score_up = 0
    score_down = 0
    reasons_up, reasons_down = [], []

    if fast and slow and fast > slow:
        score_up += 30; reasons_up.append("EMA 9 > EMA 21")
    elif fast and slow and fast < slow:
        score_down += 30; reasons_down.append("EMA 9 < EMA 21")

    if momentum is not None and 50 < momentum < 68:
        score_up += 20; reasons_up.append(f"RSI {momentum:.1f} bullish zone")
    elif momentum is not None and 32 < momentum < 50:
        score_down += 20; reasons_down.append(f"RSI {momentum:.1f} bearish zone")

    if last["close"] > last["open"] and body / candle_range > 0.45:
        score_up += 20; reasons_up.append("strong bullish candle")
    elif last["close"] < last["open"] and body / candle_range > 0.45:
        score_down += 20; reasons_down.append("strong bearish candle")

    if lower_wick / candle_range > 0.45 and near_support:
        score_up += 30; reasons_up.append("lower-wick rejection near support")
    if upper_wick / candle_range > 0.45 and near_resistance:
        score_down += 30; reasons_down.append("upper-wick rejection near resistance")

    if prev["close"] < prev["open"] and last["close"] > last["open"] and last["close"] > prev["open"]:
        score_up += 10; reasons_up.append("bullish engulfing-like candle")
    if prev["close"] > prev["open"] and last["close"] < last["open"] and last["close"] < prev["open"]:
        score_down += 10; reasons_down.append("bearish engulfing-like candle")

    if score_up >= MIN_CONFIDENCE and score_up > score_down:
        return {"side": "CALL", "score": min(score_up, 100), "reasons": reasons_up, "price": last["close"], "time": last["time"]}
    if score_down >= MIN_CONFIDENCE and score_down > score_up:
        return {"side": "PUT", "score": min(score_down, 100), "reasons": reasons_down, "price": last["close"], "time": last["time"]}
    return {"side": "WAIT", "score": max(score_up, score_down), "reasons": [], "price": last["close"], "time": last["time"]}

def scan_pair(pair):
    candles = fetch_candles(pair)
    return analyze(candles)

def fmt_signal(pair, signal):
    if not signal:
        return f"⚪ <b>{pair}</b>: পর্যাপ্ত candle data নেই"
    if signal["side"] == "WAIT":
        return f"⏸ <b>{pair}</b> — WAIT\nScore: {signal['score']}/100\nPrice: {signal['price']}"
    why = "\n".join("• " + x for x in signal["reasons"])
    return (
        f"📊 <b>{pair}</b> — <b>{signal['side']}</b>\n"
        f"Setup score: {signal['score']}/100 (জয়ের সম্ভাবনা নয়)\n"
        f"শেষ মূল্য: {signal['price']}\nসময়: {signal['time']} UTC\n"
        f"কারণ:\n{why}\n"
        f"⚠️ এটি বিশ্লেষণভিত্তিক সিগন্যাল, নিশ্চিত ফল নয়।"
    )

def settle_due(chat_id):
    account = get_account(chat_id)
    still_open = []
    for trade in account["open"]:
        if time.time() < trade["settle_at"]:
            still_open.append(trade)
            continue
        try:
            candles = fetch_candles(trade["pair"], outputsize=5)
            exit_price = candles[-1]["close"]
            won = (exit_price > trade["entry"]) if trade["side"] == "CALL" else (exit_price < trade["entry"])
            if exit_price == trade["entry"]:
                result = "DRAW"
            elif won:
                result = "WIN"
                account["balance"] += trade["stake"] * PAPER_PAYOUT
            else:
                result = "LOSS"
                account["balance"] -= trade["stake"]
            account["history"].append({"pair": trade["pair"], "side": trade["side"], "result": result,
                                       "entry": trade["entry"], "exit": exit_price, "stake": trade["stake"]})
        except Exception as e:
            logging.warning("Could not settle paper trade: %s", e)
            still_open.append(trade)
    account["open"] = still_open

def place_paper_trade(chat_id, pair, signal):
    account = get_account(chat_id)
    if signal["side"] not in ("CALL", "PUT") or signal["score"] < MIN_CONFIDENCE:
        return False
    if account["balance"] < DEMO_STAKE:
        return False
    # One open paper position per pair per chat.
    if any(t["pair"] == pair for t in account["open"]):
        return False
    account["open"].append({
        "pair": pair, "side": signal["side"], "entry": signal["price"],
        "stake": DEMO_STAKE, "opened_at": time.time(), "settle_at": time.time() + 60
    })
    return True

def scan_chat(chat_id, auto=False):
    settle_due(chat_id)
    messages = []
    for pair in PAIRS:
        try:
            signal = scan_pair(pair)
            messages.append(fmt_signal(pair, signal))
            if auto and signal and signal["side"] in ("CALL", "PUT"):
                if place_paper_trade(chat_id, pair, signal):
                    messages.append(f"🧪 Demo paper trade opened: {pair} {signal['side']} — ${DEMO_STAKE:.2f} virtual, 60 sec")
        except Exception as e:
            logging.warning("Scan failed for %s: %s", pair, e)
            messages.append(f"⚠️ <b>{pair}</b>: data পাওয়া যায়নি ({str(e)[:120]})")
        time.sleep(0.2)
    return "\n\n".join(messages)

def auto_loop():
    while True:
        for chat_id in list(auto_demo):
            try:
                msg = scan_chat(chat_id, auto=True)
                bot.send_message(chat_id, "🤖 <b>MX AI AUTO TRADER — Demo Scan</b>\n\n" + msg)
                account = get_account(chat_id)
                settle_due(chat_id)
                bot.send_message(chat_id, f"🧪 Demo balance: ${account['balance']:.2f} | Open paper trades: {len(account['open'])}")
            except Exception as e:
                logging.exception("Auto scan error")
                try:
                    bot.send_message(chat_id, f"Auto scan error: {str(e)[:200]}")
                except Exception:
                    pass
        time.sleep(max(SCAN_INTERVAL, 60))

@bot.message_handler(commands=["start", "help"])
def start(message):
    get_account(message.chat.id)
    bot.reply_to(message,
        "🤖 <b>Welcome to MX AI AUTO TRADER</b>\n\n"
        "এটি signal + virtual demo bot। কোনো আসল Quotex order দেয় না এবং Quotex password চায় না।\n\n"
        "/scan — সব Major Pair scan\n"
        "/demo_on — ১ মিনিটের virtual auto-trading চালু\n"
        "/demo_off — virtual auto-trading বন্ধ\n"
        "/balance — demo balance\n"
        "/history — শেষ demo ফলাফল\n"
        "/status — bot status\n\n"
        "⚠️ Setup score জয়ের নিশ্চয়তা নয়। Binary options অত্যন্ত ঝুঁকিপূর্ণ।")

@bot.message_handler(commands=["scan"])
def scan_cmd(message):
    bot.reply_to(message, "🔎 Major pairs scan করছি... সময় লাগতে পারে।")
    try:
        bot.send_message(message.chat.id, scan_chat(message.chat.id, auto=False))
    except Exception as e:
        bot.send_message(message.chat.id, f"Scan error: {str(e)[:250]}")

@bot.message_handler(commands=["demo_on"])
def demo_on(message):
    get_account(message.chat.id)
    auto_demo.add(message.chat.id)
    bot.reply_to(message, f"🧪 Virtual demo auto mode চালু হয়েছে। প্রতি {max(SCAN_INTERVAL,60)} সেকেন্ডে scan হবে। আসল টাকা ব্যবহার হবে না।")

@bot.message_handler(commands=["demo_off"])
def demo_off(message):
    auto_demo.discard(message.chat.id)
    bot.reply_to(message, "⏹ Virtual demo auto mode বন্ধ হয়েছে।")

@bot.message_handler(commands=["balance"])
def balance(message):
    settle_due(message.chat.id)
    a = get_account(message.chat.id)
    bot.reply_to(message, f"🧪 Demo balance: <b>${a['balance']:.2f}</b>\nOpen paper trades: {len(a['open'])}\nএটি virtual balance; আসল টাকা নয়।")

@bot.message_handler(commands=["history"])
def history(message):
    settle_due(message.chat.id)
    h = list(get_account(message.chat.id)["history"])
    if not h:
        bot.reply_to(message, "এখনো কোনো demo result নেই। /demo_on চালু করো।")
        return
    lines = [f"{x['pair']} {x['side']} — {x['result']} | {x['entry']} → {x['exit']}" for x in h[-15:]]
    wins = sum(1 for x in h if x["result"] == "WIN")
    losses = sum(1 for x in h if x["result"] == "LOSS")
    bot.reply_to(message, "📒 <b>শেষ Demo ফলাফল</b>\n" + "\n".join(lines) +
                 f"\n\nWins: {wins} | Losses: {losses} | Draws: {sum(1 for x in h if x['result']=='DRAW')}")

@bot.message_handler(commands=["status"])
def status(message):
    a = get_account(message.chat.id)
    bot.reply_to(message, f"Bot: Online\nMode: {'Demo auto ON' if message.chat.id in auto_demo else 'Manual scan'}\nPairs: {len(PAIRS)} Major FX pairs\nTimeframe: 1 minute\nReal orders: Disabled\nDemo balance: ${a['balance']:.2f}")

def main():
    threading.Thread(target=auto_loop, daemon=True).start()
    logging.info("MX AI AUTO TRADER started")
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)

if __name__ == "__main__":
    main()
