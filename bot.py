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

BOT_TOKEN = "8125634898:AAEGiT7nt_uTrG7NiJKDIVlmJqo8uRcHtIg"

# Replace with your Telegram user ID(s)
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
    first_name = update.message.from_user.first_name

    reply_keyboard = [
        ["/IMA__Analysis"], ["/ETF__Analysis"],
        ["/CSA__Analysis"],
        ["📘 Guidance_Book"]
    ]

    await update.message.reply_text(
        f"Welcome {first_name} 👋\n\n"
        "This bot analyzes the live crypto market for you and creates clear reports "
        "backed by signal evidence.\n\n"
        "Tap Guidance Book button below to learn how to understand and use the reports.",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard,
            resize_keyboard=True,
            one_time_keyboard=False
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
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to do this.")
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
    if update.message.from_user.id not in ADMIN_IDS:
        return

    guide_key = context.user_data.get("uploading_guide")
    if not guide_key:
        return

    document = update.message.document

    if not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("❌ Please upload a valid PDF file.")
        return

    file = await document.get_file()
    file_path = GUIDE_PATHS[guide_key]

    await file.download_to_drive(file_path)

    context.user_data.pop("uploading_guide")

    await update.message.reply_text(
        f"✅ {guide_key.upper()} Guide uploaded successfully!"
    )

async def ima_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # (Optional) Restrict to admins
    # if update.message.from_user.id not in ADMIN_IDS:
    #     await update.message.reply_text("❌ You are not authorized.")
    #     return

    await update.message.reply_text(
        "🔍 Running IMA Analysis...\n"
        "This may take 1–2 minutes ⏳"
    )

    loop = asyncio.get_running_loop()

    try:
        summary, report_path = await loop.run_in_executor(
            None, run_ima_analysis_for_bot
        )

        # Send summary (Markdown enabled)
        await update.message.reply_text(
            summary,
            parse_mode="Markdown"
        )

        # Send Excel report
        if report_path and os.path.exists(report_path):
            with open(report_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.message.chat_id,
                    document=f,
                    filename=report_path,
                )

    except Exception as e:
        await update.message.reply_text(
            f"❌ IMA Analysis failed:\n{str(e)}"
        )

async def etf_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🔍 Running ETF Analysis...\n"
        "This may take 1–2 minutes ⏳"
    )

    loop = asyncio.get_running_loop()

    try:
        summary, report_path = await loop.run_in_executor(
            None, run_etf_analysis_for_bot
        )

        # Send summary
        await update.message.reply_text(
            summary,
            parse_mode="Markdown"
        )

        # Send Excel report
        if report_path and os.path.exists(report_path):
            with open(report_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.message.chat_id,
                    document=f,
                    filename=os.path.basename(report_path),
                )

    except Exception as e:
        await update.message.reply_text(
            f"❌ ETF Analysis failed:\n{str(e)}"
        )

async def csa_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Run CSA analysis for user-provided pairs.
    """
    if not context.args:
        await update.message.reply_text("Kindly send the pairs you want this engine to analyze.:\n Example:\n/CSA__Analysis BTC-USD ETH-USD")
        return

    pairs = context.args
    await update.message.reply_text(
        "🔍 Running CSA Analysis...\nThis may take 1–3 minutes ⏳"
    )

    import asyncio
    loop = asyncio.get_running_loop()

    try:
        summary, report_path = await loop.run_in_executor(
            None, run_csa_analysis_for_bot, pairs
        )

        # Send summary
        await update.message.reply_text(summary)

        # Send Excel report
        if report_path and os.path.exists(report_path):
            with open(report_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.message.chat_id,
                    document=f,
                    filename=report_path,
                )

    except Exception as e:
        await update.message.reply_text(f"❌ CSA Analysis failed:\n{str(e)}")

# ================== MAIN ==================

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
    app.add_handler(
        CallbackQueryHandler(upload_select, pattern="^upload_")
    )
    app.add_handler(
        MessageHandler(filters.Document.PDF, receive_pdf)
    )

    # Shared
    app.add_handler(
        CallbackQueryHandler(send_guide, pattern="^guide_")
    )

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
