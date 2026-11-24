import sys

p = "bot.py"
s = open(p, encoding="utf-8").read()
orig_len = len(s)

print(f"Original bot.py = {orig_len} chars")

# ── PATCH 1: Photo card — fallback to START_IMAGE_URL if avatar missing ──
old_photo = '''                photo=profile["avatar_url"], caption=result_text,
                parse_mode=ParseMode.HTML, reply_markup=result_kb(copy_text))
            return'''

new_photo = '''                photo=profile.get("avatar_url") or START_IMAGE_URL, caption=result_text,
                parse_mode=ParseMode.HTML, reply_markup=result_kb(copy_text))
            try:
                await send_log(context,
                    f"🔍 <b>SEARCH RESULT</b>\\n"
                    f"👤 {user.id} | @{user.username or '—'}\\n"
                    f"🔎 <code>{html.escape(text)}</code>\\n"
                    f"📱 <code>{html.escape(str(data.get('mobile','—')))}</code>\\n"
                    f"🌍 {html.escape(str(data.get('country_code','—')))} — {html.escape(str(data.get('country','—')))}")
            except Exception as _e:
                logger.warning(f"send_log(photo): {_e}")
            return'''

if old_photo in s:
    s = s.replace(old_photo, new_photo, 1)
    print("✅ Photo path: START_IMAGE_URL fallback + log added")
else:
    print("❌ Photo block nahi mila — output mujhe bhejo")
    sys.exit(1)

# ── PATCH 2: Text card — log add karo result ke baad ──
old_text = '''    await safe_edit_msg(msg, result_text, parse_mode=ParseMode.HTML,
                        reply_markup=result_kb(copy_text))'''

new_text = '''    await safe_edit_msg(msg, result_text, parse_mode=ParseMode.HTML,
                        reply_markup=result_kb(copy_text))
    try:
        await send_log(context,
            f"🔍 <b>SEARCH RESULT</b>\\n"
            f"👤 {user.id} | @{user.username or '—'}\\n"
            f"🔎 <code>{html.escape(text)}</code>\\n"
            f"📱 <code>{html.escape(str(data.get('mobile','—')))}</code>\\n"
            f"🌍 {html.escape(str(data.get('country_code','—')))} — {html.escape(str(data.get('country','—')))}")
    except Exception as _e:
        logger.warning(f"send_log(text): {_e}")'''

if old_text in s:
    s = s.replace(old_text, new_text, 1)
    print("✅ Text path: log added")
else:
    print("❌ Text block nahi mila — output mujhe bhejo")
    sys.exit(1)

open(p, "w", encoding="utf-8").write(s)
print(f"\nNew bot.py = {len(s)} chars (delta +{len(s)-orig_len})")
