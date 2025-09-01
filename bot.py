import os
import json
import asyncio
from telethon import TelegramClient, errors
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =====================
# BOT + TELETHON CONFIG
# =====================
BOT_TOKEN = "YOUR_BOT_TOKEN"
API_ID = 1234567  # replace with your API ID
API_HASH = "YOUR_API_HASH"

SESSIONS_DIR = "sessions"
CONTACTS_DIR = "contacts"
DATA_FILE = "user_data.json"

os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(CONTACTS_DIR, exist_ok=True)

# =====================
# USER DATA HANDLING
# =====================
def load_user_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_user_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

user_data = load_user_data()

# =====================
# BOT COMMAND HANDLERS
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome! Please send me your phone number to log in (format: +123456789)."
    )

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    phone = update.message.text.strip()
    session_path = os.path.join(SESSIONS_DIR, f"{user_id}.session")
    client = TelegramClient(session_path, API_ID, API_HASH)

    await client.connect()
    if not await client.is_user_authorized():
        try:
            sent = await client.send_code_request(phone)
            context.user_data["phone"] = phone
            context.user_data["hash"] = sent.phone_code_hash
            await update.message.reply_text("Enter the code you received:")
        except errors.PhoneNumberInvalidError:
            await update.message.reply_text("Invalid phone number.")
    else:
        await update.message.reply_text("You’re already logged in.")
    await client.disconnect()

async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    code = update.message.text.strip()
    phone = context.user_data.get("phone")
    phone_hash = context.user_data.get("hash")
    session_path = os.path.join(SESSIONS_DIR, f"{user_id}.session")
    client = TelegramClient(session_path, API_ID, API_HASH)

    await client.connect()
    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_hash)
        await update.message.reply_text("Login successful! 🎉")
    except errors.SessionPasswordNeededError:
        await update.message.reply_text("Your account has 2FA. Send your password:")
        context.user_data["awaiting_password"] = True
    except Exception as e:
        await update.message.reply_text(f"Login failed: {e}")
    await client.disconnect()

async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_password"):
        return
    user_id = str(update.effective_user.id)
    password = update.message.text.strip()
    phone = context.user_data.get("phone")
    session_path = os.path.join(SESSIONS_DIR, f"{user_id}.session")
    client = TelegramClient(session_path, API_ID, API_HASH)

    await client.connect()
    try:
        await client.sign_in(password=password)
        await update.message.reply_text("2FA login successful! 🎉")
    except Exception as e:
        await update.message.reply_text(f"Login failed: {e}")
    await client.disconnect()
    context.user_data["awaiting_password"] = False

async def upload_vcf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not update.message.document:
        await update.message.reply_text("Send a valid VCF file.")
        return
    file = await update.message.document.get_file()
    file_path = os.path.join(CONTACTS_DIR, f"{user_id}.vcf")
    await file.download_to_drive(file_path)
    await update.message.reply_text("VCF uploaded! Now use /setchannel @YourChannel")

async def set_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Usage: /setchannel @ChannelUsername")
        return
    channel = context.args[0]
    user_data[user_id] = {"channel": channel}
    save_user_data(user_data)
    await update.message.reply_text(f"Channel set to {channel}")

async def add_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    session_path = os.path.join(SESSIONS_DIR, f"{user_id}.session")
    vcf_path = os.path.join(CONTACTS_DIR, f"{user_id}.vcf")

    if not os.path.exists(session_path):
        await update.message.reply_text("You must log in first.")
        return
    if not os.path.exists(vcf_path):
        await update.message.reply_text("Upload your contacts first with a VCF file.")
        return
    if user_id not in user_data or "channel" not in user_data[user_id]:
        await update.message.reply_text("Set your channel first using /setchannel.")
        return

    channel = user_data[user_id]["channel"]
    client = TelegramClient(session_path, API_ID, API_HASH)
    await client.connect()

    # Parse VCF
    contacts = []
    with open(vcf_path, "r") as f:
        for line in f:
            if line.startswith("TEL:"):
                contacts.append(line.strip().replace("TEL:", ""))

    added, failed = 0, 0
    for phone in contacts:
        try:
            result = await client( 
                client(functions.channels.InviteToChannelRequest(
                    channel=channel,
                    users=[phone]
                ))
            )
            added += 1
            await asyncio.sleep(5)  # delay to avoid bans
        except errors.FloodWaitError as e:
            await update.message.reply_text(f"FloodWait {e.seconds}s, pausing...")
            await asyncio.sleep(e.seconds + 5)
        except Exception:
            failed += 1
            continue

    await update.message.reply_text(f"✅ Added: {added}, ❌ Failed: {failed}")
    await client.disconnect()

# =====================
# MAIN APP
# =====================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setchannel", set_channel))
    app.add_handler(CommandHandler("addmembers", add_members))

    app.add_handler(MessageHandler(filters.Document.ALL, upload_vcf))
    app.add_handler(MessageHandler(filters.Regex(r"^\+\d+$"), handle_phone))
    app.add_handler(MessageHandler(filters.Regex(r"^\d{5,6}$"), handle_code))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password))

    app.run_polling()

if __name__ == "__main__":
    main()
