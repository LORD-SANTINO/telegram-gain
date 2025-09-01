import os
import json
import asyncio
import logging
import phonenumbers
from pyrogram import Client
from pyrogram.errors import FloodWait, UserAlreadyParticipant, UserPrivacyRestricted, PeerFlood

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Config ---
API_ID = 123456   # your api_id
API_HASH = "your_api_hash"
BOT_TOKEN = "your_bot_token"

# Storage
os.makedirs("sessions", exist_ok=True)
os.makedirs("contacts", exist_ok=True)
USER_DATA_FILE = "user_data.json"

# Load / Save user data
if os.path.exists(USER_DATA_FILE):
    with open(USER_DATA_FILE, "r") as f:
        user_data = json.load(f)
else:
    user_data = {}

def save_user_data():
    with open(USER_DATA_FILE, "w") as f:
        json.dump(user_data, f, indent=2)

# --- Telegram Bot Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me your phone number to log in (with country code).")

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    phone = update.message.text.strip()
    try:
        number = phonenumbers.parse(phone, None)
        if not phonenumbers.is_valid_number(number):
            await update.message.reply_text("❌ Invalid phone number.")
            return
    except:
        await update.message.reply_text("❌ Please enter a valid phone number.")
        return

    session_file = f"sessions/{user_id}.session"
    app = Client(session_file, api_id=API_ID, api_hash=API_HASH)

    try:
        await app.connect()
        sent = await app.send_code(phone)
        context.user_data["phone"] = phone
        context.user_data["phone_hash"] = sent.phone_code_hash
        await update.message.reply_text("📩 Enter the login code you received:")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
    finally:
        await app.disconnect()

async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    phone = context.user_data.get("phone")
    phone_hash = context.user_data.get("phone_hash")
    code = update.message.text.strip()

    session_file = f"sessions/{user_id}.session"
    app = Client(session_file, api_id=API_ID, api_hash=API_HASH)

    try:
        await app.connect()
        await app.sign_in(phone, phone_hash, code)
        await app.disconnect()
        await update.message.reply_text("✅ Logged in successfully!")
    except Exception as e:
        await update.message.reply_text(f"Login failed: {e}")
    finally:
        await app.disconnect()

async def upload_vcf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    file = await update.message.document.get_file()
    file_path = f"contacts/{user_id}.vcf"
    await file.download_to_drive(file_path)

    # Parse VCF
    contacts = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("TEL:"):
                contacts.append(line.strip().split(":")[1])

    with open(f"contacts/{user_id}.json", "w") as f:
        json.dump(contacts, f)

    await update.message.reply_text(f"📂 Saved {len(contacts)} contacts!")

async def set_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Usage: /setchannel @ChannelUsername")
        return
    channel = context.args[0]
    user_data[user_id] = {"channel": channel}
    save_user_data()
    await update.message.reply_text(f"✅ Channel set to {channel}")

async def add_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    session_file = f"sessions/{user_id}.session"
    contact_file = f"contacts/{user_id}.json"

    if not os.path.exists(session_file):
        await update.message.reply_text("⚠️ Please log in first with your phone.")
        return
    if not os.path.exists(contact_file):
        await update.message.reply_text("⚠️ Please upload a VCF file first.")
        return
    if user_id not in user_data or "channel" not in user_data[user_id]:
        await update.message.reply_text("⚠️ Please set a channel first with /setchannel")
        return

    channel = user_data[user_id]["channel"]
    with open(contact_file, "r") as f:
        contacts = json.load(f)

    app = Client(session_file, api_id=API_ID, api_hash=API_HASH)

    await app.connect()
    success, failed = 0, 0

    for phone in contacts:
        try:
            user = await app.import_contacts([phone])
            if user.users:
                u = user.users[0]
                await app.add_chat_members(channel, u.id)
                success += 1
                await asyncio.sleep(5)  # delay to prevent flood
        except UserAlreadyParticipant:
            continue
        except UserPrivacyRestricted:
            failed += 1
        except (PeerFlood, FloodWait) as e:
            logger.warning(f"Flood control: {e}")
            await asyncio.sleep(60)
            continue
        except Exception as e:
            logger.error(f"Error adding {phone}: {e}")
            failed += 1

    await app.disconnect()
    await update.message.reply_text(f"✅ Added {success}, ❌ Failed {failed}")

# --- Main ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setchannel", set_channel))
    app.add_handler(CommandHandler("addmembers", add_members))
    app.add_handler(MessageHandler(filters.Document.FileExtension("vcf"), upload_vcf))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

    app.run_polling()

if __name__ == "__main__":
    main()
