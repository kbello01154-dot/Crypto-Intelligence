import os
import asyncio

from IMA import run_ima_analysis_for_bot
from ETF import run_etf_analysis_for_bot
from CSA_bot_wrapper import run_csa_analysis_for_bot

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================== CONFIG ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")  # 🔐 from Render env
APP_URL = os.getenv("APP_URL")      # https://crypto-intelligence-1.onrender.com

if not BOT_TOKEN or not APP_URL:
    raise RuntimeError("BOT_TOKEN and APP_URL must be set as environment variables")

ADMIN_IDS = [7252074303]

GUIDE_FOLDER = "guides"
os.makedirs(GUIDE_FOLDER, exist_ok=True)

GUIDE_PATHS = {
    "ima": os.path.join(GUIDE_FOLDER, "IMA_Guide.pdf"),
    "etf": os.path.join(GUIDE_FOLDER, "ETF_Guide.pdf"),
    "csa": os.path.join(GUIDE_FOLDER, "CSA_Guide.pdf"),
}

# ================== USER COMMANDS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    first_name = update.effective_user.first_name

    reply_keyboard = [
        ["/IMA__Analysis"],
        ["/ETF__Analysis"],
        ["/CSA__Analysis"],
        ["📘 Guidance_Book"],
    ]

    await update.message.reply_text(
        f"Welcome {first_name} 👋\n\n"
        "This bot analyzes the live crypto market and creates clear reports "
        "backed by signal evidence.\n\n"
        "Tap *Guidance Book* below to learn how to use the reports.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard,
            resize_keyboard=True,
        ),
    )

# ================== GUIDANCE BOOK ==================

async def guidance_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📄 IMA Guide", callback_data="guide_ima")],
        [InlineKeyboardButton("📄 ETF Guide", callback_data="guide_etf")],
        [InlineKeyboardButton("📄 CSA Guide", callback_data="guide_csa")],
    ]

    await update.message.reply_text(
        "Please choose a guidance book:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def send_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    guide_key = query.data.replace("guide_", "")
    file_path = GUIDE_PATHS.get(guide_key)

    if not file_path or not os.path.exists(file_path):
        await query.message.reply_text("❌ This guide is not available yet.")
        return

    with open(file_path, "rb") as f:
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=f,
            filename=os.path.basename(file_path),
        )

# ================== ADMIN: GUIDE UPLOAD ==================

async def guide_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized.")
        return

    keyboard = [
        [InlineKeyboardButton("IMA Guide", callback_data="upload_ima")],
        [InlineKeyboardButton("ETF Guide", callback_data="upload_etf")],
        [InlineKeyboardButton("CSA Guide", callback_data="upload_csa")],
    ]

    await update.message.reply_text(
        "Which guide do you want to upload or update?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def upload_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    guide_key = query.data.replace("upload_", "")
    context.user_data["uploading_guide"] = guide_key

    await query.message.reply_text(
        f"📤 Please upload the PDF for {guide_key.upper()} Guide"
    )

async def receive_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    guide_key = context.user_data.get("uploading_guide")
    if not guide_key:
        return

    document = update.message.document

    if not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("❌ Please upload a valid PDF.")
        return

    file = await document.get_file()
    await file.download_to_drive(GUIDE_PATHS[guide_key])

    context.user_data.pop("uploading_guide", None)

    await update.message.reply_text(
        f"✅ {guide_key.upper()} Guide uploaded successfully!"
    )

# ================== ANALYSIS ==================

async def ima_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Running IMA Analysis...\n⏳ Please wait")

    loop = asyncio.get_running_loop()

    try:
        summary, report_path = await loop.run_in_executor(
            None, run_ima_analysis_for_bot
        )

        await update.message.reply_text(summary, parse_mode="Markdown")

        if report_path and os.path.exists(report_path):
            with open(report_path, "rb") as f:
                await context.bot.send_document(update.effective_chat.id, f)

    except Exception as e:
        await update.message.reply_text(f"❌ IMA failed:\n{e}")

async def etf_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Running ETF Analysis...\n⏳ Please wait")

    loop = asyncio.get_running_loop()

    try:
        summary, report_path = await loop.run_in_executor(
            None, run_etf_analysis_for_bot
        )

        await update.message.reply_text(summary, parse_mode="Markdown")

        if report_path and os.path.exists(report_path):
            with open(report_path, "rb") as f:
                await context.bot.send_document(update.effective_chat.id, f)

    except Exception as e:
        await update.message.reply_text(f"❌ ETF failed:\n{e}")

async def csa_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Example:\n/CSA__Analysis BTC-USD ETH-USD"
        )
        return

    await update.message.reply_text("🔍 Running CSA Analysis...\n⏳ Please wait")

    loop = asyncio.get_running_loop()

    try:
        summary, report_path = await loop.run_in_executor(
            None, run_csa_analysis_for_bot, context.args
        )

        await update.message.reply_text(summary)

        if report_path and os.path.exists(report_path):
            with open(report_path, "rb") as f:
                await context.bot.send_document(update.effective_chat.id, f)

    except Exception as e:
        await update.message.reply_text(f"❌ CSA failed:\n{e}")

# ================== MAIN (WEBHOOK) ==================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # User
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Text("📘 Guidance_Book"), guidance_book))
    app.add_handler(CommandHandler("IMA__Analysis", ima_analysis))
    app.add_handler(CommandHandler("ETF__Analysis", etf_analysis))
    app.add_handler(CommandHandler("CSA__Analysis", csa_analysis))

    # Admin
    app.add_handler(CommandHandler("guide_upload", guide_upload))
    app.add_handler(CallbackQueryHandler(upload_select, pattern="^upload_"))
    app.add_handler(MessageHandler(filters.Document.PDF, receive_pdf))

    # Shared
    app.add_handler(CallbackQueryHandler(send_guide, pattern="^guide_"))

    port = int(os.getenv("PORT", "10000"))
    webhook_path = f"/{BOT_TOKEN}"
    webhook_url = f"{APP_URL}{webhook_path}"

    print("🚀 Starting webhook:", webhook_url)

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        webhook_url=webhook_url,
        webhook_path=webhook_path,
    )

if __name__ == "__main__":
    main()
