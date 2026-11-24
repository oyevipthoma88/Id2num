import os, json, shutil

# backups (safety)
for f in ["bot.py","config.py","app.json"]:
    if os.path.exists(f):
        shutil.copy(f, f+".beforefix")

# ---------- config.py ----------
c = open("config.py").read()
c = c.replace('os.environ.get("OWNER_USERNAME", "@PokiePy")', 'os.environ.get("OWNER_USERNAME", "")')
c = c.replace('os.environ.get("OWNER_CONTACT", "@PokiePy")', 'os.environ.get("OWNER_CONTACT", "")')
c = c.replace('os.environ.get("SUPPORT_LINK", "@PokiePy")', 'os.environ.get("SUPPORT_LINK", "")')
c = c.replace('API_URL = "https://cyberking.great-site.net/Apix.php"',
              'API_URL = "https://tele-to-num-by-dimpiii.vercel.app/api/tele"')
c = c.replace('"bdcda8ea69743403f45cb7632347ea238526cc8489b765e8"', '"dimpiii-modz"')
open("config.py","w").write(c)

# ---------- bot.py ----------
b = open("bot.py").read()

# 1) _test_api params fix
b = b.replace(
    'params={"api": "number", "key": API_KEY, "q": query}',
    'params=({"key": API_KEY, "userid": str(query)} if str(query).isdigit() else {"key": API_KEY, "username": str(query).lstrip("@")})',
    1
)

# 2) lookup_tg_id poora replace
si = b.find("async def lookup_tg_id(tg_id):")
ei = b.find("# ===== USERNAME PROFILE SCRAPER =====", si)
new_lookup = '''async def lookup_tg_id(tg_id):
    q = tg_id.lstrip("@").strip()
    last_err = None
    param_key = "userid" if q.isdigit() else "username"
    for i in range(MAX_TRIES):
        try:
            r = requests.get(API_URL,
                params={"key": API_KEY, param_key: q},
                timeout=REQUEST_TIMEOUT).json()
            logger.info(f"[API] {i+1}: {r}")
            if r.get("status") is True:
                phones = r.get("phone") or []
                p0 = phones[0] if phones else {}
                return {"ok": True, "data": {
                    "tg_id": r.get("tg_id", q),
                    "mobile": p0.get("number", "N/A"),
                    "country_code": p0.get("country_code", "N/A"),
                    "country": p0.get("country", "N/A"),
                }}
            last_err = r.get("error") or r.get("message") or "No data found"
        except Exception as e:
            last_err = str(e)
            logger.warning(f"[API] {i+1}: {e}")
        if i < MAX_TRIES - 1:
            await asyncio.sleep(RETRY_DELAY)
    return {"ok": False, "error": last_err or "Unknown"}

'''
if si != -1 and ei != -1:
    b = b[:si] + new_lookup + b[ei:]

# 3) text handler add
if "async def handle_text(" not in b:
    handler = '''async def handle_text(update, context):
    user = update.effective_user
    if not user:
        return
    if not await require_join(update, context):
        return
    text = (update.message.text or "").strip()
    if not text:
        return
    allowed, _ = await can_search(user.id)
    if not allowed:
        gate = await show_referral_gate(None, user, is_edit=False)
        await update.message.reply_text(gate, parse_mode=ParseMode.HTML,
            reply_markup=referral_gate_kb())
        return
    rem = await get_remaining(user.id)
    if rem == 0:
        await update.message.reply_text(
            "❌ Aaj ki free searches khatam. Referral ya Premium le lo.",
            reply_markup=referral_gate_kb())
        return
    msg = await update.message.reply_text("🔎 Searching...")
    res = await lookup_tg_id(text)
    await record_search(user.id)
    if not res.get("ok"):
        await safe_edit_msg(msg, f"❌ Not found: {res.get('error')}",
            reply_markup=no_data_kb())
        return
    d = res["data"]
    out = (f"✅ <b>Result</b>\\n\\n"
           f"🆔 <code>{html.escape(str(d['tg_id']))}</code>\\n"
           f"📱 <code>{html.escape(str(d['mobile']))}</code>\\n"
           f"🌍 {html.escape(str(d['country_code']))} — {html.escape(str(d['country']))}")
    await safe_edit_msg(msg, out, parse_mode=ParseMode.HTML,
        reply_markup=result_kb(str(d['mobile'])))

'''
    marker = "# ===== COMMANDS ====="
    b = b.replace(marker, handler + marker, 1) if marker in b else b + "\n" + handler

# 4) entry point add
if "run_polling" not in b:
    b += '''
# ===== ENTRY POINT =====
def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .get_updates_request(HTTPXRequest(read_timeout=30, connect_timeout=30))
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
'''

open("bot.py","w").write(b)

# ---------- app.json ----------
a = json.load(open("app.json"))
a.setdefault("env", {})
a["env"].pop("API_ID", None)
a["env"].pop("API_HASH", None)
a["env"]["TG_API_ID"] = {"description":"Telegram API ID (optional)","value":"","required":False}
a["env"]["TG_API_HASH"] = {"description":"Telegram API HASH (optional)","value":"","required":False}
if "formation" in a and "worker" in a["formation"]:
    a["formation"]["worker"]["size"] = "eco"
json.dump(a, open("app.json","w"), indent=2, ensure_ascii=False)

# ---------- junk delete ----------
for f in ["bot.py.pokie.bak","app.json.pokie.bak","bot.py.bak2","app.json.bak2"]:
    if os.path.exists(f):
        os.remove(f)

print("✅ ALL FIXES APPLIED")
