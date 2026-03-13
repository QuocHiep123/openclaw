"""
Telegram Bot interface for the AI Research Lab.

Features:
    - All slash commands (/paper, /experiment, /daily, /todo, etc.)
    - Free-text routed through LangGraph orchestrator
    - Conversation memory per user (chat history)
    - Scheduled daily pipeline via APScheduler
    - Inline keyboard buttons for paper actions
    - Document upload & analysis (PDF/TXT)
    - Vietnamese & English language support
"""
from __future__ import annotations

import asyncio
import io
import logging
from functools import wraps
from typing import List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict, TimedOut, NetworkError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config.settings import settings
from memory.research_memory import research_memory
from orchestrator.graph import run_workflow

logger = logging.getLogger(__name__)

# Max Telegram message length
_MAX_MSG = 4096

# In-memory conversation buffer per user (lightweight, keeps last N turns)
_chat_buffers: dict[int, list[dict[str, str]]] = {}
_MAX_HISTORY = 10  # Keep last 10 exchanges


# ---- Auth guard -----------------------------------------------------------

def _authorised(user_id: int) -> bool:
    allowed = settings.allowed_user_ids
    return not allowed or user_id in allowed


def auth_required(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or not _authorised(user.id):
            if update.message:
                await update.message.reply_text("⛔ Unauthorised.")
            return
        return await func(update, context)
    return wrapper


# ---- Chat history helpers -------------------------------------------------

def _get_history(user_id: int) -> list[dict[str, str]]:
    """Get conversation history for a user."""
    return _chat_buffers.get(user_id, [])


def _append_history(user_id: int, role: str, content: str):
    """Append a message to the user's chat buffer."""
    if user_id not in _chat_buffers:
        _chat_buffers[user_id] = []
    _chat_buffers[user_id].append({"role": role, "content": content[:1000]})
    # Trim to max history
    if len(_chat_buffers[user_id]) > _MAX_HISTORY * 2:
        _chat_buffers[user_id] = _chat_buffers[user_id][-_MAX_HISTORY * 2:]


# ---- Message helpers ------------------------------------------------------

async def _safe_reply(update: Update, text: str, reply_markup=None) -> None:
    """Send *text* split into Telegram-sized chunks at paragraph boundaries."""
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return

    if len(text) <= _MAX_MSG:
        await msg.reply_text(text, reply_markup=reply_markup)
        return

    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n"):
        line = paragraph + "\n"
        if len(current) + len(line) > _MAX_MSG:
            if current:
                chunks.append(current)
            while len(line) > _MAX_MSG:
                chunks.append(line[:_MAX_MSG])
                line = line[_MAX_MSG:]
            current = line
        else:
            current += line
    if current.strip():
        chunks.append(current)

    for i, chunk in enumerate(chunks):
        # Only add reply_markup to the last chunk
        rm = reply_markup if i == len(chunks) - 1 else None
        await msg.reply_text(chunk.strip(), reply_markup=rm)


async def _run_and_reply(update: Update, user_input: str, reply_markup=None):
    """Run the workflow with user context and reply."""
    user_id = update.effective_user.id if update.effective_user else 0

    # Get chat history
    history = _get_history(user_id)

    # Record user message
    _append_history(user_id, "user", user_input)

    # Run workflow
    result = await run_workflow(user_input, user_id=user_id, chat_history=history)

    # Record assistant response
    _append_history(user_id, "assistant", result)

    await _safe_reply(update, result, reply_markup=reply_markup)


# ---- Inline keyboard helpers ---------------------------------------------

def _paper_keyboard(query: str) -> InlineKeyboardMarkup:
    """Create inline buttons after a paper search."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💡 Generate Ideas", callback_data=f"ideas:{query[:50]}"),
            InlineKeyboardButton("📌 Save as Task", callback_data=f"save:{query[:50]}"),
        ],
        [
            InlineKeyboardButton("🔍 Search More", callback_data=f"more:{query[:50]}"),
        ],
    ])


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    """Main menu inline keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📄 Search Papers", callback_data="menu:paper"),
            InlineKeyboardButton("🧪 Run Experiment", callback_data="menu:experiment"),
        ],
        [
            InlineKeyboardButton("📊 Status", callback_data="menu:status"),
            InlineKeyboardButton("📋 Tasks", callback_data="menu:tasks"),
        ],
        [
            InlineKeyboardButton("🗓️ Daily Report", callback_data="menu:daily"),
        ],
    ])


# ---- Error handler --------------------------------------------------------

async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors globally — suppress noisy Conflict/network errors."""
    err = context.error
    if isinstance(err, Conflict):
        logger.warning("Conflict: another getUpdates instance detected — ignoring.")
        return
    if isinstance(err, (TimedOut, NetworkError)):
        logger.warning("Network issue: %s", err)
        return
    logger.error("Unhandled exception", exc_info=context.error)


# ---- Command Handlers -----------------------------------------------------

@auth_required
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = settings.bot_language
    if lang == "vi":
        text = (
            "🔬 **AI Research Lab** đã online!\n\n"
            "Tôi là trợ lý nghiên cứu AI, có thể:\n"
            "• 📄 Tìm và tóm tắt papers trên arXiv\n"
            "• 🧪 Thiết kế và chạy thí nghiệm\n"
            "• 📋 Quản lý task nghiên cứu\n"
            "• 📊 Báo cáo tiến độ hàng ngày\n\n"
            "Dùng /help để xem danh sách lệnh, hoặc nhắn gì tôi cũng hiểu! 🚀"
        )
    else:
        text = (
            "🔬 **AI Research Lab** is online!\n\n"
            "I'm your AI research assistant. I can:\n"
            "• 📄 Search & summarise arXiv papers\n"
            "• 🧪 Design & run ML experiments\n"
            "• 📋 Manage research tasks\n"
            "• 📊 Generate daily progress reports\n\n"
            "Use /help to see commands, or just chat with me! 🚀"
        )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=_main_menu_keyboard())


@auth_required
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = settings.bot_language
    if lang == "vi":
        text = (
            "**📖 Danh sách lệnh:**\n\n"
            "/paper `<query>` — Tìm & tóm tắt papers\n"
            "/experiment `<name>` — Chạy thí nghiệm\n"
            "/daily — Chạy pipeline hàng ngày\n"
            "/todo `<text>` — Thêm task mới\n"
            "/tasks — Xem danh sách tasks\n"
            "/report — Báo cáo tiến độ\n"
            "/status — Trạng thái hệ thống\n"
            "/clear — Xóa lịch sử chat\n\n"
            "💬 Hoặc nhắn gì cũng được, tôi sẽ hiểu!"
        )
    else:
        text = (
            "**📖 Commands:**\n\n"
            "/paper `<query>` — Search & summarise papers\n"
            "/experiment `<name>` — Run an experiment\n"
            "/daily — Trigger daily pipeline\n"
            "/todo `<text>` — Add a task\n"
            "/tasks — List tasks\n"
            "/report — Progress report\n"
            "/status — System status\n"
            "/clear — Clear chat history\n\n"
            "💬 Or just send any message!"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


@auth_required
async def cmd_paper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args) if context.args else "latest AI research"
    await update.message.reply_text(f"🔍 Searching papers: *{query}*…", parse_mode="Markdown")
    await _run_and_reply(update, f"/paper {query}", reply_markup=_paper_keyboard(query))


@auth_required
async def cmd_experiment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = " ".join(context.args) if context.args else "default_experiment"
    await update.message.reply_text(f"🧪 Running experiment: *{name}*…", parse_mode="Markdown")
    await _run_and_reply(update, f"/experiment {name}")


@auth_required
async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Running daily pipeline…")
    await _run_and_reply(update, "/daily")


@auth_required
async def cmd_todo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args) if context.args else ""
    if not text:
        lang = settings.bot_language
        msg = "Cú pháp: /todo <mô tả task>" if lang == "vi" else "Usage: /todo <task description>"
        await update.message.reply_text(msg)
        return
    await _run_and_reply(update, f"/todo add task: {text}")


@auth_required
async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _run_and_reply(update, "/todo list tasks")


@auth_required
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Generating report…")
    await _run_and_reply(update, "/todo report")


@auth_required
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _run_and_reply(update, "/status")


@auth_required
async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear chat history for the current user."""
    user_id = update.effective_user.id
    _chat_buffers.pop(user_id, None)
    lang = settings.bot_language
    msg = "🗑️ Đã xóa lịch sử chat." if lang == "vi" else "🗑️ Chat history cleared."
    await update.message.reply_text(msg)


# ---- Inline button callback handler ---------------------------------------

@auth_required
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    action, _, param = data.partition(":")

    if action == "ideas":
        await query.message.reply_text("💡 Generating research ideas…")
        await _run_and_reply(update, f"Generate 5 novel research ideas based on: {param}")

    elif action == "save":
        await _run_and_reply(update, f"/todo add task: Review papers about {param}")

    elif action == "more":
        await query.message.reply_text(f"🔍 Searching more about: {param}…")
        await _run_and_reply(update, f"/paper {param} latest developments", reply_markup=_paper_keyboard(param))

    elif action == "menu":
        if param == "paper":
            await query.message.reply_text("📄 Send me a topic to search, e.g.:\n`/paper transformer attention`", parse_mode="Markdown")
        elif param == "experiment":
            await query.message.reply_text("🧪 Send me an experiment, e.g.:\n`/experiment ppo_attention`", parse_mode="Markdown")
        elif param == "status":
            await _run_and_reply(update, "/status")
        elif param == "tasks":
            await _run_and_reply(update, "/todo list tasks")
        elif param == "daily":
            await query.message.reply_text("⏳ Running daily pipeline…")
            await _run_and_reply(update, "/daily")


# ---- Document upload handler ----------------------------------------------

@auth_required
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded documents (PDF, TXT, etc.)."""
    doc = update.message.document
    if not doc:
        return

    file_name = doc.file_name or "unknown"
    file_size = doc.file_size or 0

    # Limit file size (5MB max)
    if file_size > 5 * 1024 * 1024:
        await update.message.reply_text("⚠️ File too large. Max 5MB.")
        return

    lang = settings.bot_language
    await update.message.reply_text(
        f"📎 Đang phân tích: *{file_name}*…" if lang == "vi" else f"📎 Analysing: *{file_name}*…",
        parse_mode="Markdown",
    )

    try:
        tg_file = await doc.get_file()
        file_bytes = await tg_file.download_as_bytearray()

        # Extract text based on file type
        if file_name.lower().endswith(".txt") or file_name.lower().endswith(".md"):
            content = file_bytes.decode("utf-8", errors="replace")
        elif file_name.lower().endswith(".py"):
            content = file_bytes.decode("utf-8", errors="replace")
        elif file_name.lower().endswith(".json"):
            content = file_bytes.decode("utf-8", errors="replace")
        elif file_name.lower().endswith(".csv"):
            content = file_bytes.decode("utf-8", errors="replace")
        else:
            # For PDF and other binary formats, try basic text extraction
            try:
                content = file_bytes.decode("utf-8", errors="replace")
            except Exception:
                content = f"[Binary file: {file_name}, size: {file_size} bytes]"

        # Truncate to reasonable size
        if len(content) > 10000:
            content = content[:10000] + "\n\n[... truncated ...]"

        # Send to LLM for analysis
        prompt = (
            f"The user uploaded a document: **{file_name}**\n\n"
            f"Content:\n```\n{content}\n```\n\n"
            "Please analyse this document and provide:\n"
            "1. A brief summary\n"
            "2. Key points / findings\n"
            "3. Suggestions or next steps"
        )
        await _run_and_reply(update, prompt)

    except Exception as exc:
        logger.error("Document processing error: %s", exc)
        await update.message.reply_text(f"❌ Error processing document: {exc}")


# ---- Free-text handler ----------------------------------------------------

@auth_required
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Free-text handler — route through the orchestrator with chat history."""
    text = update.message.text or ""
    if not text.strip():
        return
    await _run_and_reply(update, text)


# ---- Scheduled daily report -----------------------------------------------

async def _scheduled_daily_report(app: Application) -> None:
    """Send the daily pipeline report to the configured chat."""
    chat_id = settings.daily_report_chat_id
    if not chat_id:
        logger.warning("Daily report: no DAILY_REPORT_CHAT_ID configured, skipping.")
        return

    logger.info("Running scheduled daily pipeline…")
    try:
        result = await run_workflow("/daily", user_id=0)
        # Split and send
        if len(result) <= _MAX_MSG:
            await app.bot.send_message(chat_id=int(chat_id), text=result)
        else:
            chunks = [result[i:i+_MAX_MSG] for i in range(0, len(result), _MAX_MSG)]
            for chunk in chunks:
                await app.bot.send_message(chat_id=int(chat_id), text=chunk)
        logger.info("Daily report sent to chat %s", chat_id)
    except Exception as exc:
        logger.error("Scheduled daily report failed: %s", exc)


# ---- Bot builder ----------------------------------------------------------

def build_telegram_app() -> Application:
    """Construct the python-telegram-bot Application."""
    token = settings.telegram_bot_token
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set in .env")

    builder = Application.builder().token(token)

    # Increase connection timeout for slow / restricted networks
    builder = (builder
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(30)
        .get_updates_write_timeout(30)
        .get_updates_pool_timeout(30)
    )

    # Proxy support (required if Telegram API is blocked)
    if settings.proxy_url:
        builder = builder.proxy(settings.proxy_url)
        logger.info("Using proxy: %s", settings.proxy_url)

    app = builder.build()

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("paper", cmd_paper))
    app.add_handler(CommandHandler("experiment", cmd_experiment))
    app.add_handler(CommandHandler("run_experiment", cmd_experiment))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("todo", cmd_todo))
    app.add_handler(CommandHandler("tasks", cmd_tasks))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("clear", cmd_clear))

    # Inline button callback handler
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Document upload handler
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Free-text message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Global error handler
    app.add_error_handler(_error_handler)

    return app


def start_bot() -> None:
    """Start the Telegram bot (blocking) with optional scheduled jobs."""
    logger.info("Starting Telegram bot…")
    app = build_telegram_app()

    # Setup scheduled daily report if configured
    if settings.daily_report_enabled and settings.daily_report_chat_id:
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger

            scheduler = AsyncIOScheduler()
            scheduler.add_job(
                _scheduled_daily_report,
                trigger=CronTrigger(
                    hour=settings.daily_report_hour,
                    minute=settings.daily_report_minute,
                ),
                args=[app],
                id="daily_report",
                name="Daily Research Report",
                replace_existing=True,
            )
            scheduler.start()
            logger.info(
                "Scheduled daily report at %02d:%02d UTC",
                settings.daily_report_hour,
                settings.daily_report_minute,
            )
        except ImportError:
            logger.warning("APScheduler not installed — daily report scheduling disabled.")
        except Exception as exc:
            logger.error("Failed to setup scheduler: %s", exc)

    app.run_polling(drop_pending_updates=True, bootstrap_retries=3)
