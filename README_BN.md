# MX AI AUTO TRADER — বাংলা সেটআপ

## বট কী করবে
- EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, USD/CAD, NZD/USD স্ক্যান করবে।
- 1-minute candle থেকে EMA 9/21, RSI, candle body/wick এবং সাম্প্রতিক support/resistance দেখে CALL/PUT/WAIT সিগন্যাল দেবে।
- `/demo_on` দিলে শুধু ভার্চুয়াল paper trade করবে; প্রতি পজিশন ৬০ সেকেন্ড পর candle price দিয়ে ফল হিসাব করবে।
- `/scan`, `/balance`, `/history`, `/status`, `/demo_off` কমান্ড আছে।

## খুব গুরুত্বপূর্ণ সীমাবদ্ধতা
- এটি Quotex-এ লগইন করে না এবং কোনো real-money order দেয় না।
- 75/100 setup score মানে 75% win probability নয়।
- 1-minute FX data provider-এর বিলম্ব/সীমা থাকতে পারে। Demo ফলাফল বাস্তব Quotex payout বা execution-এর সমান নয়।
- প্রথমে কয়েক সপ্তাহ paper test ও আলাদা backtest ছাড়া বাস্তব অর্থ ব্যবহার কোরো না।
- Quotex password, email verification code, বা session cookie কোনো Telegram bot-এ দেবে না।

## প্রয়োজন
1. Telegram-এ `@BotFather` খুলে `/newbot` দিয়ে bot বানাও। BotFather থেকে পাওয়া token গোপন রাখো।
2. Twelve Data-তে account খুলে API key নাও: https://twelvedata.com/
3. এই project-এর `.env.example` কপি করে `.env` নাম দাও। দুইটি key বসাও।
4. Python 3.10+ ইনস্টল করা কম্পিউটার/সার্ভারে চালাও:

```bash
pip install -r requirements.txt
python bot.py
```

5. Telegram-এ নিজের bot খুলে `/start`, তারপর `/scan` পাঠাও।
6. ভার্চুয়াল auto mode চালু করতে `/demo_on`; বন্ধ করতে `/demo_off`।

## Render-এ চালানো
1. ZIP extract করে GitHub repository-তে সব ফাইল upload করো।
2. Render → New → Background Worker → GitHub repository connect করো।
3. Build command: `pip install -r requirements.txt`
4. Start command: `python bot.py`
5. Environment Variables-এ `TELEGRAM_BOT_TOKEN` এবং `TWELVE_DATA_API_KEY` যোগ করো।
6. Deploy করো। Render-এ background worker চালাতে paid plan লাগতে পারে।

## ডেটা API
Twelve Data free plan-এ request limit থাকতে পারে। 7টি pair একসাথে scan করতে API quota যথেষ্ট কি না দেখে নিও। Limit শেষ হলে কিছু pair-এর data পাওয়া নাও যেতে পারে।
