from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import sqlite3
from instaloader import Instaloader, Post
from urllib.parse import urlparse
import tempfile
from pathlib import Path
import asyncio
import uuid
from persiantools.jdatetime import JalaliDateTime
import pytz
import requests
import os
import logging
import time
from datetime import datetime
import sys

# ماژول‌های سفارشی برای مدیریت سرور و اتصال
from server_utils import ServerMonitor
from connection_manager import ConnectionManager

# راه‌اندازی لاگر
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

TOKEN = "7869277763:AAHMU_8AvyZ7FIuR5O7I7CCjdz46-PYjZ6s" #آیدی ربات خودتون رو جایگزین 123456789 کنید
ADMIN_IDS = {
    6629718606,  # آیدی عددی خودتون رو جایگزین 123456789 کنید
    123456789,   # اگر میخواید ادمین دیگه ای اضافه کنید آیدی عددیش رو جایگزین 123456789 کنید وگرنه تغییر ندید
    123456789,   # اگر میخواید ادمین دیگه ای اضافه کنید آیدی عددیش رو جایگزین 123456789 کنید وگرنه تغییر ندید
}
REQUIRED_CHANNELS = []

# ایجاد نمونه از مانیتور سرور
server_monitor = ServerMonitor()

# ایجاد نمونه از مدیریت اتصال
connection_manager = ConnectionManager(TOKEN, "bot_persistence.pickle")

ADMIN_COMMANDS = """
دستورات ادمین:
/admin - نمایش پنل ادمین
/add_channel - افزودن کانال جدید
/del_channel - حذف کانال
/channels - مشاهده لیست کانال‌ها
/stats - آمار ربات
/status - وضعیت سرور و ربات
/restart - راه‌اندازی مجدد ربات
"""

def setup_database():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # اضافه کردن ستون is_banned اگر وجود نداشته باشد
    try:
        c.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        # اگر ستون قبلاً وجود داشته باشد، خطا را نادیده بگیر
        pass
        
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  username TEXT,
                  first_name TEXT,
                  unique_id TEXT,
                  is_banned INTEGER DEFAULT 0,
                  join_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS groups
                 (group_id INTEGER PRIMARY KEY, group_name TEXT, added_by INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS channels
                 (channel_id TEXT PRIMARY KEY, name TEXT, username TEXT)''')
    conn.commit()
    conn.close()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(user_id):
        return []
        
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    channels = c.execute("SELECT channel_id, name, username FROM channels").fetchall()
    conn.close()
    
    if not channels:
        return []
        
    not_subscribed_channels = []
    for channel in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=channel[0], user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                not_subscribed_channels.append({
                    "id": channel[0],
                    "name": channel[1],
                    "username": channel[2]
                })
        except Exception as e:
            print(f"Error checking {channel[2]}: {str(e)}")
            not_subscribed_channels.append({
                "id": channel[0],
                "name": channel[1],
                "username": channel[2]
            })
    return not_subscribed_channels

def get_subscription_keyboard(channels, is_admin=False):
    keyboard = []
    for channel in channels:
        keyboard.append([InlineKeyboardButton(text=channel["name"], url=f"https://t.me/{channel['username'][1:]}")])
    keyboard.append([InlineKeyboardButton(text="بررسی عضویت ✅", callback_data="check_subscription")])
    if is_admin:
        keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

async def save_user(user, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    try:
        existing_user = c.execute(
            "SELECT unique_id FROM users WHERE user_id = ?",
            (user.id,)
        ).fetchone()
        
        if not existing_user:
            # ساخت شناسه یکتا با uuid
            unique_id = str(uuid.uuid4()).split('-')[0].upper()
        else:
            unique_id = existing_user[0]
        
        # تبدیل زمان به تایم‌زون ایران
        tehran_tz = pytz.timezone('Asia/Tehran')
        current_time = JalaliDateTime.now(tehran_tz).strftime("%Y/%m/%d %H:%M:%S")
        
        c.execute(
            """INSERT OR REPLACE INTO users 
               (user_id, username, first_name, unique_id, join_date) 
               VALUES (?, ?, ?, ?, ?)""",
            (user.id, user.username, user.first_name, unique_id, current_time)
        )
        conn.commit()
        return unique_id
        
    except Exception as e:
        print(f"Error saving user: {str(e)}")
        return None
    finally:
        conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if await check_user_ban(user.id):
        await update.message.reply_text(
            "⛔️ شما از استفاده از ربات محروم شده‌اید!"
        )
        return
    
    unique_id = await save_user(user, context)
    
    not_subscribed = await check_subscription(user.id, context)
    
    if not_subscribed:
        channels_text = "\n".join([f"- {channel['name']}" for channel in not_subscribed])
        await update.message.reply_text(
            f"برای استفاده از ربات، لطفا در کانال‌های زیر عضو شوید:\n{channels_text}",
            reply_markup=get_subscription_keyboard(not_subscribed, is_admin(user.id))
        )
        return
    
    profile_text = (
        f"👤 *پروفایل شما*\n\n"
        f"🆔 شناسه یکتا: `{unique_id}`\n"
        f"👤 نام: [{user.first_name}](tg://user?id={user.id})\n"
        f"📝 نام کاربری: {f'@{user.username}' if user.username else 'تنظیم نشده'}\n\n"
        "🎥 برای دانلود ویدیو، لینک پست اینستاگرام را ارسال کنید."
    )
    
    keyboard = []
    
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("🎛 پنل ادمین", callback_data="admin_panel")])
    
    keyboard.append([
        InlineKeyboardButton("➕ افزودن به گروه", callback_data="add_to_group"),
        InlineKeyboardButton("➕ افزودن به کانال", callback_data="add_to_channel")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        profile_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def handle_instagram_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if await check_user_ban(user.id):
        await update.message.reply_text(
            "⛔️ شما از استفاده از ربات محروم شده‌اید!"
        )
        return
    
    not_subscribed = await check_subscription(user.id, context)
    if not_subscribed:
        channels_text = "\n".join([f"- {channel['name']}" for channel in not_subscribed])
        await update.message.reply_text(
            f"برای استفاده از ربات، لطفا در کانال‌های زیر عضو شوید:\n{channels_text}",
            reply_markup=get_subscription_keyboard(not_subscribed, is_admin(user.id))
        )
        return

    message = update.message.text
    
    if "instagram.com" not in message:
        await update.message.reply_text("لطفاً یک لینک معتبر اینستاگرام ارسال کنید.")
        return
    
    if "instagram.com/stories/" in message:
        await handle_instagram_story(update, context)
        return

    status_message = await update.message.reply_text(
        "🔍 در حال پردازش لینک...\n\n"
        "⏳ مراحل دانلود:\n"
        "◾️ بررسی لینک...\n"
        "◾️ دریافت اطلاعات پست...\n"
        "◾️ دانلود ویدیو...\n"
        "◾️ ارسال به تلگرام...\n\n"
        "⏳ لطفاً کمی صبر کنید..."
    )
    
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            await status_message.edit_text(
                "🔍 در حال پردازش لینک...\n\n"
                "⏳ مراحل دانلود:\n"
                "✅ بررسی لینک\n"
                "◾️ دریافت اطلاعات پست...\n"
                "◾️ دانلود ویدیو...\n"
                "◾️ ارسال به تلگرام...\n\n"
                "⏳ لطفاً کمی صبر کنید..."
            )
            
            url_path = urlparse(message).path
            shortcode = url_path.split('/')[-2] if url_path.split('/')[-1] == '' else url_path.split('/')[-1]
            
            L = Instaloader(
                dirname_pattern=temp_dir,
                download_videos=True,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                compress_json=False
            )
            
            await status_message.edit_text(
                "🔍 در حال پردازش لینک...\n\n"
                "⏳ مراحل دانلود:\n"
                "✅ بررسی لینک\n"
                "✅ دریافت اطلاعات پست\n"
                "◾️ دانلود ویدیو...\n"
                "◾️ ارسال به تلگرام...\n\n"
                "⏳ لطفاً کمی صبر کنید..."
            )
            
            post = Post.from_shortcode(L.context, shortcode)
            
            if post.is_video:
                await status_message.edit_text(
                    "🔍 در حال پردازش لینک...\n\n"
                    "⏳ مراحل دانلود:\n"
                    "✅ بررسی لینک\n"
                    "✅ دریافت اطلاعات پست\n"
                    "✅ دانلود ویدیو\n"
                    "◾️ ارسال به تلگرام...\n\n"
                    "⏳ لطفاً کمی صبر کنید..."
                )
                
                L.download_post(post, target=temp_dir)
                
                video_files = list(Path(temp_dir).glob('*.mp4'))
                
                if video_files:
                    video_path = str(video_files[0])
                    try:
                        await status_message.edit_text(
                            "🔍 در حال پردازش لینک...\n\n"
                            "⏳ مراحل دانلود:\n"
                            "✅ بررسی لینک\n"
                            "✅ دریافت اطلاعات پست\n"
                            "✅ دانلود ویدیو\n"
                            "✅ ارسال به تلگرام...\n\n"
                            "⏳ لطفاً کمی صبر کنید..."
                        )
                        
                        await update.message.reply_video(
                            video=video_path,
                            caption="🎥 ویدیو شما با موفقیت دانلود شد!"
                        )
                    except Exception as e:
                        print(f"Error sending video: {str(e)}")
                else:
                    raise Exception("فایل ویدیو پیدا نشد")
            else:
                await status_message.edit_text(
                    "❌ این پست ویدیو نیست.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]),
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            print(f"Error downloading video: {str(e)}")
            keyboard = []
            if is_admin(user.id):
                keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")])
            
            error_message = (
                "❌ خطا در دانلود ویدیو.\n"
                "دلایل احتمالی:\n"
                "• پست خصوصی است\n"
                "• پست حذف شده است\n"
                "• لینک نامعتبر است\n"
                "• این پست ویدیو نیست\n\n"
                "لطفاً دوباره تلاش کنید یا لینک دیگری ارسال کنید."
            )
            await status_message.delete()
            await update.message.reply_text(
                error_message,
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
            )

async def handle_instagram_story(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if await check_user_ban(user.id):
        await update.message.reply_text(
            "⛔️ شما از استفاده از ربات محروم شده‌اید!"
        )
        return
    
    not_subscribed = await check_subscription(user.id, context)
    if not_subscribed:
        channels_text = "\n".join([f"- {channel['name']}" for channel in not_subscribed])
        await update.message.reply_text(
            f"برای استفاده از ربات، لطفا در کانال‌های زیر عضو شوید:\n{channels_text}",
            reply_markup=get_subscription_keyboard(not_subscribed, is_admin(user.id))
        )
        return

    message = update.message.text
    
    status_message = await update.message.reply_text(
        "🔍 در حال پردازش لینک استوری...\n\n"
        "⏳ مراحل دانلود:\n"
        "◾️ بررسی لینک...\n"
        "◾️ دریافت اطلاعات استوری...\n"
        "◾️ دانلود...\n"
        "◾️ ارسال به تلگرام...\n\n"
        "⏳ لطفاً کمی صبر کنید..."
    )
    
    try:
        await status_message.edit_text(
            "🔍 در حال پردازش لینک استوری...\n\n"
            "⏳ مراحل دانلود:\n"
            "✅ بررسی لینک\n"
            "◾️ دریافت اطلاعات استوری...\n"
            "◾️ دانلود...\n"
            "◾️ ارسال به تلگرام...\n\n"
            "⏳ لطفاً کمی صبر کنید..."
        )

        # Extract username from the story link
        username = message.split("instagram.com/stories/")[-1].split("/")[0]

        url = "https://instagram-premium-api-2023.p.rapidapi.com/v1/user/stories/by/username"
        querystring = {"username": username, "amount": "0"}
        headers = {
            "x-rapidapi-key": "ec164931cfmsh029a8d32327b1f5p13c235jsn7e9175855053",  # کلید API خود را اینجا قرار دهید
            "x-rapidapi-host": "instagram-premium-api-2023.p.rapidapi.com"
        }
        response = requests.get(url, headers=headers, params=querystring)
        response_json = response.json()
        print(response_json)

        if response.status_code != 200:
            await status_message.edit_text(f"❌ خطایی رخ داد: {response_json.get('message', 'خطای ناشناخته')}")
            return

        await status_message.edit_text(
            "🔍 در حال پردازش لینک استوری...\n\n"
            "⏳ مراحل دانلود:\n"
            "✅ بررسی لینک\n"
            "✅ دریافت اطلاعات استوری\n"
            "◾️ دانلود...\n"
            "◾️ ارسال به تلگرام...\n\n"
            "⏳ لطفاً کمی صبر کنید..."
        )

        # Process each story item
        if response_json and isinstance(response_json, list):
            for story in response_json:
                media_type = story.get('media_type')
                if media_type == 2:  # Video
                    media_url = story.get('video_url')
                elif media_type == 1:  # Image
                    media_url = story.get('thumbnail_url')
                else:
                    continue

                if not media_url:
                    continue

                # تغییر روش دانلود فایل
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(suffix='.mp4' if media_type == 2 else '.jpg', delete=False) as temp_file:
                        temp_path = temp_file.name
                        session = requests.Session()
                        retries = 3
                        while retries > 0:
                            try:
                                response = session.get(media_url, stream=True, timeout=30)
                                response.raise_for_status()
                                total_size = int(response.headers.get('content-length', 0))
                                block_size = 1024 * 1024
                                with open(temp_path, 'wb') as file:
                                    for data in response.iter_content(block_size):
                                        file.write(data)
                                break
                            except (requests.exceptions.RequestException, IOError) as e:
                                retries -= 1
                                if retries == 0:
                                    raise e
                                await asyncio.sleep(1)

                    if media_type == 2:  # ویدیو
                        await update.message.reply_video(
                            video=open(temp_path, 'rb'),
                            caption="🎥 استوری دانلود شد!"
                        )
                    else:  # عکس
                        await update.message.reply_photo(
                            photo=open(temp_path, 'rb'),
                            caption="📸 استوری دانلود شد!"
                        )

                finally:
                    if temp_path:
                        try:
                            os.unlink(temp_path)
                        except:
                            pass

            # فقط در انتها یک بار پیام موفقیت نمایش داده شود
            keyboard = []
            if is_admin(user.id):
                keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")])
            
            await status_message.delete()  # حذف پیام وضعیت قبلی
            await update.message.reply_text(
                "✅ عملیات با موفقیت انجام شد!",
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
            )

        else:
            keyboard = []
            if is_admin(user.id):
                keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")])
            
            await status_message.delete()  # حذف پیام وضعیت قبلی
            await update.message.reply_text(
                "❌ استوری‌ای برای دانلود پیدا نشد.",
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
            )

    except Exception as e:
        print(f"Error downloading story: {str(e)}")
        keyboard = []
        if is_admin(user.id):
            keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")])
        
        error_message = (
            "❌ خطا در دانلود استوری.\n"
            "دلایل احتمالی:\n"
            "• استوری خصوصی است\n"
            "• استوری حذف شده است\n"
            "• لینک نامعتبر است\n\n"
            "لطفاً دوباره تلاش کنید یا لینک دیگری ارسال کنید."
        )
        await status_message.delete()  # حذف پیام وضعیت قبلی
        await update.message.reply_text(
            error_message,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
        )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ شما دسترسی به این بخش را ندارید.")
        return
    
    context.user_data['waiting_for_broadcast'] = True
    
    keyboard = [[InlineKeyboardButton("❌ لغو", callback_data="cancel_broadcast")]]
    await update.message.reply_text(
        "📬 لطفاً پیام مورد نظر خود را برای ارسال همگانی ارسال کنید.\n"
        "می‌توانید متن، عکس، ویدیو، فایل یا صوت ارسال کنید.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_broadcast_media(update: Update, context: ContextTypes.DEFAULT_TYPE, media_type: str, file_id: str):
    if context.user_data.get('waiting_for_broadcast'):
        context.user_data['broadcast_message'] = {
            'media': file_id,
            'media_type': media_type,
            'text': update.message.caption if update.message.caption else ''
        }
        
        keyboard = [
            [
                InlineKeyboardButton("✅ ارسال", callback_data="confirm_broadcast"),
                InlineKeyboardButton("❌ لغو", callback_data="cancel_broadcast")
            ]
        ]
        
        preview_text = "📬 پیش‌نمایش پیام:\n\n"
        if update.message.caption:
            preview_text += f"متن پیام: {update.message.caption}\n"
        preview_text += f"\nنوع رسانه: {media_type}"
        
        try:
            if media_type == 'photo':
                preview_message = await update.message.reply_photo(
                    photo=file_id,
                    caption=preview_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif media_type == 'video':
                preview_message = await update.message.reply_video(
                    video=file_id,
                    caption=preview_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif media_type == 'document':
                preview_message = await update.message.reply_document(
                    document=file_id,
                    caption=preview_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif media_type == 'audio':
                preview_message = await update.message.reply_audio(
                    audio=file_id,
                    caption=preview_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            context.user_data['preview_message'] = preview_message
            
        except Exception as e:
            print(f"Error sending preview: {str(e)}")
            await update.message.reply_text(
                "❌ خطا در ارسال پیش‌نمایش. لطفاً دوباره تلاش کنید.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="cancel_broadcast")]])
            )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_for_broadcast') and is_admin(update.effective_user.id):
        await handle_broadcast_media(update, context, 'photo', update.message.photo[-1].file_id)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_for_broadcast') and is_admin(update.effective_user.id):
        await handle_broadcast_media(update, context, 'video', update.message.video.file_id)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_for_broadcast') and is_admin(update.effective_user.id):
        await handle_broadcast_media(update, context, 'document', update.message.document.file_id)

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_for_broadcast') and is_admin(update.effective_user.id):
        await handle_broadcast_media(update, context, 'audio', update.message.audio.file_id)

async def handle_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_info = await context.bot.get_me()
    
    if any(member.id == bot_info.id for member in update.message.new_chat_members):
        chat = update.effective_chat
        user = update.effective_user
        
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        
        try:
            c.execute(
                "INSERT OR REPLACE INTO groups (group_id, group_name, added_by) VALUES (?, ?, ?)",
                (chat.id, chat.title, user.id)
            )
            conn.commit()
            
            await update.message.reply_text(
                "✅ ربات با موفقیت به گروه اضافه شد!\n\n"
                "لطفاً مطمئن شوید که ربات دسترسی‌های لازم را دارد:\n"
                "• ارسال پیام\n"
                "• ویرایش پیام\n"
                "• حذف پیام\n"
                "جهت استفاده از ربات در گروه خود، لطفاً دستور /d را ارسال کنید."
            )
        except Exception as e:
            print(f"Error saving group: {str(e)}")
        finally:
            conn.close()

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
        
    keyboard = [
        [InlineKeyboardButton("افزودن کانال جدید ➕", callback_data="add_channel")],
        [InlineKeyboardButton("حذف کانال ➖", callback_data="del_channel")],
        [InlineKeyboardButton("لیست کانال‌ها 📋", callback_data="list_channels")],
        [InlineKeyboardButton("آمار ربات 📊", callback_data="stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔰 پنل مدیریت ربات:",
        reply_markup=reply_markup
    )

async def add_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
        
    if not context.args:
        await update.message.reply_text(
            "برای افزودن کانال، آیدی عددی کانال را وارد کنید:\n"
            "مثال: /add_channel -1001234567890"
        )
        return
        
    channel_id = context.args[0]
    try:
        chat = await context.bot.get_chat(channel_id)
        chat_member = await context.bot.get_chat_member(chat_id=channel_id, user_id=context.bot.id)
        
        if chat_member.status != 'administrator':
            await update.message.reply_text("❌ لطفا ابتدا ربات را در کانال ادمین کنید.")
            return
            
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        channel_username = chat.username if chat.username else str(channel_id)
        c.execute(
            "INSERT OR REPLACE INTO channels (channel_id, name, username) VALUES (?, ?, ?)",
            (channel_id, f"@{channel_username}", f"@{channel_username}")
        )
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ کانال @{channel_username} با موفقیت اضافه شد.")
        
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در افزودن کانال: {str(e)}")

async def del_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
        
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    channels = c.execute("SELECT channel_id, name FROM channels").fetchall()
    
    if not channels:
        await update.message.reply_text("❌ هیچ کانالی در لیست وجود ندارد.")
        conn.close()
        return
        
    if not context.args:
        channels_text = "\n".join([f"{i+1}. {ch[1]} ({ch[0]})" for i, ch in enumerate(channels)])
        await update.message.reply_text(
            "برای حذف کانال، شماره آن را وارد کنید:\n"
            f"{channels_text}\n"
            "مثال: /del_channel 1"
        )
        conn.close()
        return
        
    try:
        index = int(context.args[0]) - 1
        if 0 <= index < len(channels):
            channel = channels[index]
            c.execute("DELETE FROM channels WHERE channel_id = ?", (channel[0],))
            conn.commit()
            await update.message.reply_text(f"✅ کانال {channel[1]} با موفقیت حذف شد.")
        else:
            await update.message.reply_text("❌ شماره کانال نامعتبر است.")
    except:
        await update.message.reply_text("❌ لطفا یک عدد معتبر وارد کنید.")
    finally:
        conn.close()

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
        
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    admin_ids_tuple = tuple(ADMIN_IDS)
    if len(admin_ids_tuple) == 1:
        users_count = c.execute("SELECT COUNT(*) FROM users WHERE user_id != ?", (admin_ids_tuple[0],)).fetchone()[0]
    else:
        users_count = c.execute(f"SELECT COUNT(*) FROM users WHERE user_id NOT IN ({','.join(['?' for _ in admin_ids_tuple])})", admin_ids_tuple).fetchone()[0]
    
    groups_count = c.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
    
    conn.close()
    
    stats_text = (
        "📊 آمار ربات:\n\n"
        f"👤 تعداد کاربران: {users_count}\n"
        f"👥 تعداد گروه‌ها: {groups_count}\n"
        f"📢 تعداد کانال‌ها: {len(REQUIRED_CHANNELS)}"
    )
    
    await update.message.reply_text(stats_text)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message.text
    
    if context.user_data.get('waiting_for_channel_id') and is_admin(user.id):
        context.user_data.pop('waiting_for_channel_id')
        try:
            chat = await context.bot.get_chat(message)
            chat_member = await context.bot.get_chat_member(chat_id=message, user_id=context.bot.id)
            
            if chat_member.status != 'administrator':
                await update.message.reply_text(
                    "❌ لطفا ابتدا ربات را در کانال ادمین کنید.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]])
                )
                return
                
            conn = sqlite3.connect('bot_database.db')
            c = conn.cursor()
            channel_username = chat.username if chat.username else str(message)
            c.execute(
                "INSERT OR REPLACE INTO channels (channel_id, name, username) VALUES (?, ?, ?)",
                (message, f"@{channel_username}", f"@{channel_username}")
            )
            conn.commit()
            conn.close()
            
            await update.message.reply_text(
                f"✅ کانال @{channel_username} با موفقیت اضافه شد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]])
            )
            
        except Exception as e:
            await update.message.reply_text(
                f"❌ خطا در بررسی کانال: {str(e)}\n\nلطفاً یک آیدی معتبر وارد کنید.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]])
            )
        return
    
    if "instagram.com" in message:
        await handle_instagram_link(update, context)
        return

    elif context.user_data.get('waiting_for_broadcast') and is_admin(update.effective_user.id):
        context.user_data['broadcast_message'] = {
            'text': message
        }
        
        keyboard = [
            [
                InlineKeyboardButton("✅ ارسال", callback_data="confirm_broadcast"),
                InlineKeyboardButton("❌ لغو", callback_data="cancel_broadcast")
            ]
        ]
        
        preview_text = "📬 پیش‌نمایش پیام:\n\n"
        preview_text += message
        
        preview_message = await update.message.reply_text(
            preview_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        context.user_data['preview_message'] = preview_message
    
    elif update.message.chat.type in ['group', 'supergroup']:
        await update.message.reply_text(
            "برای دانلود ویدیو از دستور /d استفاده کنید.\n"
            "مثال:\n"
            "/d https://www.instagram.com/p/xxx"
        )
        return
    
    else:
        context.user_data['instagram_link'] = message
        await handle_instagram_link(update, context)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer()
    
    if query.data == "admin_panel" and is_admin(user_id):
        keyboard = [
            [
                InlineKeyboardButton("📊 آمار", callback_data="stats"),
                InlineKeyboardButton("📢 ارسال پیام", callback_data="broadcast_init")
            ],
            [
                InlineKeyboardButton("➕ افزودن کانال", callback_data="add_channel"),
                InlineKeyboardButton("❌ حذف کانال", callback_data="del_channel")
            ],
            [
                InlineKeyboardButton("📡 وضعیت سرور", callback_data="server_status"),
                InlineKeyboardButton("🔄 راه‌اندازی مجدد", callback_data="restart_bot")
            ],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🔰 پنل مدیریت ربات:",
            reply_markup=reply_markup
        )
        return

    if query.data == "back_to_main":
        user = query.from_user
        welcome_message = f"سلام [{user.first_name}](tg://user?id={user.id})!\n"
        welcome_message += "می‌توانید لینک پست اینستاگرام را ارسال کنید تا برایتان ویدیو را بفرستم."
        
        keyboard = []
        if is_admin(user.id):
            keyboard.append([InlineKeyboardButton("🎛 پنل ادمین", callback_data="admin_panel")])
        
        keyboard.append([
            InlineKeyboardButton("➕ افزودن به گروه", callback_data="add_to_group"),
            InlineKeyboardButton("➕ افزودن به کانال", callback_data="add_to_channel")
        ])
        
        await query.edit_message_text(
            welcome_message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if query.data in ["check_subscription", "add_to_group", "back_to_main", "add_to_channel"]:
        if query.data == "add_to_channel":
            bot_info = await context.bot.get_me()
            add_to_channel_link = f"https://t.me/{bot_info.username}?startchannel=true"
            keyboard = [
                [InlineKeyboardButton("➕ افزودن به کانال", url=add_to_channel_link)],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]
            ]
            await query.edit_message_text(
                "برای افزودن ربات به کانال خود:\n\n"
                "1️⃣ روی دکمه زیر کلیک کنید\n"
                "2️⃣ کانال مورد نظر را انتخاب کنید\n"
                "3️⃣ دسترسی‌های لازم را به ربات بدهید",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
            
        elif query.data == "back_to_main":
            keyboard = []
            
            if is_admin(user_id):
                keyboard.append([InlineKeyboardButton("🎛 پنل ادمین", callback_data="admin_panel")])
            
            keyboard.append([
                InlineKeyboardButton("➕ افزودن به گروه", callback_data="add_to_group"),
                InlineKeyboardButton("➕ افزودن به کانال", callback_data="add_to_channel")
            ])
            
            await query.edit_message_text(
                f"سلام [{query.from_user.first_name}](tg://user?id={user_id})!\n"
                "می‌توانید لینک پست اینستاگرام را ارسال کنید تا برایتان ویدیو را بفرستم.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return
            
        elif query.data == "check_subscription":
            not_subscribed = await check_subscription(user_id, context)
            if not not_subscribed:
                await query.edit_message_text(
                    f"✅ عضویت شما تأیید شد.\n"
                    f"می‌توانید لینک پست اینستاگرام را ارسال کنید."
                )
            else:
                channels_text = "\n".join([f"- {channel['name']}" for channel in not_subscribed])
                await query.answer(f"لطفاً در کانال‌های زیر عضو شوید:\n{channels_text}", show_alert=True)
            return
            
        elif query.data == "add_to_group":
            bot_info = await context.bot.get_me()
            add_to_group_link = f"https://t.me/{bot_info.username}?startgroup=new"
            keyboard = [
                [InlineKeyboardButton("➕ افزودن به گروه", url=add_to_group_link)],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]
            ]
            await query.edit_message_text(
                "برای افزودن ربات به گروه خود:\n\n"
                "1️⃣ روی دکمه زیر کلیک کنید\n"
                "2️⃣ گروه مورد نظر را انتخاب کنید\n"
                "3️⃣ دسترسی‌های لازم را به ربات بدهید",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    
    if not is_admin(user_id):
        await query.answer("⛔️ شما دسترسی به این بخش را ندارید.", show_alert=True)
        return
        
    if query.data == "broadcast_init":
        context.user_data['waiting_for_broadcast'] = True
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
        await query.edit_message_text(
            "📝 پیام خود را برای ارسال همگانی ارسال کنید.\n\n"
            "💡 نکات:\n"
            "• می‌توانید پیام را همراه با عکس، ویدیو، صوت یا فایل ارسال کنید\n"
            "• برای لغو، دستور /cancel را ارسال کنید",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == "confirm_broadcast":
        broadcast_data = context.user_data.get('broadcast_message')
        if broadcast_data:
            await query.message.edit_reply_markup(reply_markup=None)
            
            status_message = await query.message.reply_text(
                "⏳ در حال ارسال پیام به کاربران و گروه‌ها...\n"
                "لطفاً صبر کنید."
            )
            
            conn = sqlite3.connect('bot_database.db')
            c = conn.cursor()
            
            try:
                admin_ids_tuple = tuple(ADMIN_IDS)
                if len(admin_ids_tuple) == 1:
                    users = c.execute("SELECT DISTINCT user_id FROM users WHERE user_id != ?", (admin_ids_tuple[0],)).fetchall()
                else:
                    users = c.execute(f"SELECT DISTINCT user_id FROM users WHERE user_id NOT IN ({','.join(['?' for _ in admin_ids_tuple])})", admin_ids_tuple).fetchall()
                
                groups = c.execute("SELECT DISTINCT group_id FROM groups").fetchall()
                
                success = 0
                failed = 0
                
                all_chats = users + groups
                for chat in all_chats:
                    try:
                        if 'media' in broadcast_data:
                            media_type = broadcast_data['media_type']
                            file_id = broadcast_data['media']
                            caption = broadcast_data.get('text', '')
                            
                            if media_type == 'photo':
                                await context.bot.send_photo(
                                    chat_id=chat[0],
                                    photo=file_id,
                                    caption=caption,
                                    parse_mode='HTML'
                                )
                            elif media_type == 'video':
                                await context.bot.send_video(
                                    chat_id=chat[0],
                                    video=file_id,
                                    caption=caption,
                                    parse_mode='HTML'
                                )
                            elif media_type == 'document':
                                await context.bot.send_document(
                                    chat_id=chat[0],
                                    document=file_id,
                                    caption=caption,
                                    parse_mode='HTML'
                                )
                            elif media_type == 'audio':
                                await context.bot.send_audio(
                                    chat_id=chat[0],
                                    audio=file_id,
                                    caption=caption,
                                    parse_mode='HTML'
                                )
                        else:
                            await context.bot.send_message(
                                chat_id=chat[0],
                                text=broadcast_data.get('text', ''),
                                parse_mode='HTML'
                            )
                        success += 1
                        await asyncio.sleep(0.05)
                    except Exception as e:
                        print(f"Error sending to chat {chat[0]}: {str(e)}")
                        failed += 1
                
                keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
                await status_message.edit_text(
                    f"✅ ارسال پیام به پایان رسید!\n\n"
                    f"📊 آمار ارسال:\n"
                    f"👤 تعداد کل: {len(all_chats)}\n"
                    f"✓ ارسال موفق: {success}\n"
                    f"✗ ارسال ناموفق: {failed}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
            except Exception as e:
                keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
                await status_message.edit_text(
                    f"❌ خطا در ارسال پیام: {str(e)}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            finally:
                conn.close()
                context.user_data.pop('broadcast_message', None)
                context.user_data.pop('waiting_for_broadcast', None)
    
    elif query.data == "cancel_broadcast":
        context.user_data.pop('broadcast_message', None)
        context.user_data.pop('waiting_for_broadcast', None)
        
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        await query.message.reply_text(
            "❌ ارسال پیام لغو شد.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "add_channel" and is_admin(user_id):
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
        await query.edit_message_text(
            "برای افزودن کانال جدید، آیدی عددی کانال را وارد کنید.\n\n"
            "⚠️ نکات مهم:\n"
            "• ربات باید در کانال ادمین باشد\n"
            "• آیدی عددی باید با - شروع شود\n"
            "• مثال: -1001234567890\n\n"
            "🔹 برای دریافت آیدی عددی کانال، یک پیام از کانال را فوروارد کنید به @userinfobot",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data['waiting_for_channel_id'] = True
    
    elif query.data == "del_channel" and is_admin(user_id):
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        channels = c.execute("SELECT channel_id, name FROM channels").fetchall()
        conn.close()

        if not channels:
            keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
            await query.edit_message_text(
                "❌ هیچ کانالی در لیست عضویت اجباری وجود ندارد.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        keyboard = []
        for channel in channels:
            keyboard.append([InlineKeyboardButton(
                f"❌ {channel[1]}",
                callback_data=f"remove_channel_{channel[0]}"
            )])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")])
        
        await query.edit_message_text(
            "برای حذف کانال، روی آن کلیک کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith("remove_channel_") and is_admin(user_id):
        channel_id = query.data.replace("remove_channel_", "")
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        try:
            channel_name = c.execute("SELECT name FROM channels WHERE channel_id = ?", (channel_id,)).fetchone()[0]
            c.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
            conn.commit()
            keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
            await query.edit_message_text(
                f"✅ کانال {channel_name} با موفقیت حذف شد.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            await query.answer("❌ خطا در حذف کانال!", show_alert=True)
        finally:
            conn.close()

    elif query.data == "stats" and is_admin(user_id):
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        
        try:
            admin_ids_tuple = tuple(ADMIN_IDS)
            if len(admin_ids_tuple) == 1:
                users_count = c.execute("SELECT COUNT(*) FROM users WHERE user_id != ?", (admin_ids_tuple[0],)).fetchone()[0]
            else:
                users_count = c.execute(f"SELECT COUNT(*) FROM users WHERE user_id NOT IN ({','.join(['?' for _ in admin_ids_tuple])})", admin_ids_tuple).fetchone()[0]
            
            groups_count = c.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
            
            stats_text = (
                "📊 آمار ربات:\n\n"
                f"👤 تعداد کاربران: {users_count}\n"
                f"👥 تعداد گروه‌ها: {groups_count}\n"
                f"📢 تعداد کانال‌ها: {len(REQUIRED_CHANNELS)}"
            )
            
            keyboard = [
                [InlineKeyboardButton("👥 لیست کاربران", callback_data="users_list")],
                [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]
            ]
            await query.edit_message_text(
                stats_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            await query.answer(f"❌ خطا در دریافت آمار: {str(e)}", show_alert=True)
        
        finally:
            conn.close()

    elif query.data == "users_list" or query.data.startswith("users_page_"):
        if not is_admin(user_id):
            return
        
        page = 1
        if query.data.startswith("users_page_"):
            try:
                page = int(query.data.replace("users_page_", ""))
            except ValueError:
                page = 1
        
        USERS_PER_PAGE = 5
        offset = (page - 1) * USERS_PER_PAGE
        
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        try:
            admin_ids_tuple = tuple(ADMIN_IDS)
            
            # ابتدا تعداد کل کاربران را می‌شماریم
            if len(admin_ids_tuple) == 1:
                total_users = c.execute(
                    "SELECT COUNT(*) FROM users WHERE user_id != ?",
                    (admin_ids_tuple[0],)
                ).fetchone()[0]
            else:
                total_users = c.execute(
                    f"SELECT COUNT(*) FROM users WHERE user_id NOT IN ({','.join(['?' for _ in admin_ids_tuple])})",
                    admin_ids_tuple
                ).fetchone()[0]
            
            total_pages = (total_users + USERS_PER_PAGE - 1) // USERS_PER_PAGE
            
            # سپس کاربران صفحه فعلی را دریافت می‌کنیم
            if len(admin_ids_tuple) == 1:
                users = c.execute("""
                    SELECT user_id, username, first_name, unique_id, is_banned, join_date 
                    FROM users 
                    WHERE user_id != ?
                    ORDER BY join_date DESC 
                    LIMIT ? OFFSET ?
                """, (admin_ids_tuple[0], USERS_PER_PAGE, offset)).fetchall()
            else:
                users = c.execute(f"""
                    SELECT user_id, username, first_name, unique_id, is_banned, join_date 
                    FROM users 
                    WHERE user_id NOT IN ({','.join(['?' for _ in admin_ids_tuple])})
                    ORDER BY join_date DESC 
                    LIMIT ? OFFSET ?
                """, (*admin_ids_tuple, USERS_PER_PAGE, offset)).fetchall()
            
            if not users:
                keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="stats")]]
                await query.edit_message_text(
                    "❌ هیچ کاربری یافت نشد!",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
            
            text = f"لیست کاربران (صفحه {page} از {total_pages}):\n\n"
            keyboard = []
            
            for i, user in enumerate(users, offset + 1):
                user_id, username, first_name, unique_id, is_banned, join_date = user
                status = "🚫" if is_banned else "✅"
                text += f"{i}. {status} کاربر: {first_name or 'نامشخص'}\n"
                text += f"├ 🆔 شناسه یکتا: `{unique_id}`\n"
                text += f"├ 👤 آیدی عددی: `{user_id}`\n"
                text += f"├ 📝 نام کاربری: {f'@{username}' if username else 'تنظیم نشده'}\n"
                text += f"├ 📅 تاریخ عضویت: {join_date}\n"
                text += f"└ وضعیت: {'🔒 مسدود' if is_banned else '✅ فعال'}\n\n"
                
                btn_text = f"{'رفع مسدودیت 🔓' if is_banned else 'مسدودسازی 🔒'} کاربر {i}"
                keyboard.append([InlineKeyboardButton(
                    btn_text,
                    callback_data=f"toggle_ban_{user_id}"
                )])
            
            # دکمه‌های پیمایش صفحات
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("◀️ صفحه قبل", callback_data=f"users_page_{page-1}"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("صفحه بعد ▶️", callback_data=f"users_page_{page+1}"))
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            keyboard.append([
                InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="current_page"),
                InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"users_page_{page}")
            ])
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="stats")])
            
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            await query.answer(f"❌ خطا: {str(e)}", show_alert=True)
        finally:
            conn.close()

    elif query.data.startswith("toggle_ban_") and is_admin(user_id):
        target_user_id = int(query.data.replace("toggle_ban_", ""))
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        try:
            # بررسی وضعیت فعلی کاربر
            current_status = c.execute(
                "SELECT is_banned, first_name, username FROM users WHERE user_id = ?", 
                (target_user_id,)
            ).fetchone()
            
            if current_status:
                is_banned, first_name, username = current_status
                new_status = 0 if is_banned else 1
                c.execute(
                    "UPDATE users SET is_banned = ? WHERE user_id = ?",
                    (new_status, target_user_id)
                )
                conn.commit()
                
                user_info = f"{first_name or 'ناشناس'}"
                if username:
                    user_info += f" (@{username})"
                
                # ارسال پیام به کاربر در صورت رفع مسدودیت
                if new_status == 0:
                    try:
                        await context.bot.send_message(
                            chat_id=target_user_id,
                            text="حساب کاربری شما از حالت مسدود خارج شد!\n"
                                 "می‌توانید دوباره از ربات استفاده کنید."
                        )
                    except Exception as e:
                        print(f"Error sending unban message: {str(e)}")
                
                status_text = "مسدود" if new_status else "رفع مسدود"
                await query.answer(
                    f"✅ کاربر {user_info} با موفقیت {status_text} شد!",
                    show_alert=True
                )
                
                # در انتهای بخش موفقیت‌آمیز، به جای بازگشت مستقیم به لیست کاربران:
                # قبل از اجرای دستور toggle_ban، شماره صفحه فعلی را از متن پیام استخراج می‌کنیم
                try:
                    message_text = query.message.text
                    current_page = 1
                    if "صفحه" in message_text:
                        current_page = int(message_text.split("صفحه")[1].split("از")[0].strip())
                except:
                    current_page = 1
                
                # بازگشت به همان صفحه
                await query.data_callback(f"users_page_{current_page}", update, context)
                
            else:
                await query.answer("❌ کاربر مورد نظر یافت نشد!", show_alert=True)
                
        except Exception as e:
            await query.answer(f"❌ خطا در تغییر وضعیت کاربر: {str(e)}", show_alert=True)
        finally:
            conn.close()

    # مدیریت وضعیت سرور
    elif query.data == "server_status" and is_admin(user_id):
        # دریافت وضعیت اتصال
        connection_status = connection_manager.get_connection_status()
        
        # ایجاد پیام وضعیت سرور
        server_status = server_monitor.format_status_message()
        
        # اضافه کردن وضعیت اتصال به پیام
        connection_message = "\n🔌 وضعیت اتصال:\n"
        connection_message += f"├ اتصال فعلی: {'✅ متصل' if connection_status['is_connected'] else '❌ قطع'}\n"
        
        if connection_status['last_connected']:
            last_connected = datetime.fromtimestamp(connection_status['last_connected'])
            connection_message += f"├ آخرین اتصال: {last_connected.strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        if connection_status['last_disconnect']:
            last_disconnect = datetime.fromtimestamp(connection_status['last_disconnect'])
            connection_message += f"├ آخرین قطعی: {last_disconnect.strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        connection_message += f"└ تعداد تلاش‌های اتصال مجدد: {connection_status['reconnect_attempts']}\n"
        
        # ترکیب پیام‌ها
        complete_status = server_status + connection_message
        
        # ایجاد دکمه‌های مدیریتی
        keyboard = [
            [
                InlineKeyboardButton("🔄 به‌روزرسانی", callback_data="refresh_status"),
                InlineKeyboardButton("🔁 راه‌اندازی مجدد", callback_data="restart_bot")
            ],
            [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(
            complete_status,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == "refresh_status" and is_admin(user_id):
        await query.edit_message_text(
            "🔄 در حال به‌روزرسانی وضعیت...",
            reply_markup=None
        )
        
        # ارسال مجدد وضعیت
        await query.data_callback("server_status", update, context)
    
    elif query.data == "restart_bot" and is_admin(user_id):
        restart_message = await query.edit_message_text(
            "🔄 در حال راه‌اندازی مجدد ربات...\n"
            "⏳ لطفاً صبر کنید...",
            reply_markup=None
        )
        
        logger.info(f"راه‌اندازی مجدد ربات توسط ادمین {user_id} درخواست شد")
        
        # ذخیره اطلاعات راه‌اندازی مجدد برای پیگیری بعد از راه‌اندازی
        context.bot_data["restart_info"] = {
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
            "time": time.time(),
            "requested_by": user_id
        }
        
        # قطع اتصال فعلی و راه‌اندازی مجدد
        await connection_manager.shutdown()
        
        logger.info("ربات به زودی دوباره راه‌اندازی خواهد شد...")

async def check_user_ban(user_id: int) -> bool:
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    try:
        result = c.execute(
            "SELECT is_banned FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return bool(result and result[0])
    finally:
        conn.close()

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.strip().lower() == "/d":
        command_parts = update.message.text.split(maxsplit=1)
        if len(command_parts) > 1:
            not_subscribed = await check_subscription(update.effective_user.id, context)
            if not_subscribed:
                channels_text = "\n".join([f"- {channel['name']}" for channel in not_subscribed])
                await update.message.reply_text(
                    f"برای استفاده از ربات، لطفا در کانال‌های زیر عضو شوید:\n{channels_text}",
                    reply_markup=get_subscription_keyboard(not_subscribed, is_admin(update.effective_user.id))
                )
                return
                
            context.user_data['instagram_link'] = command_parts[1]
            await handle_instagram_link(update, context)
        else:
            await update.message.reply_text(
                "لطفاً لینک پست اینستاگرام را بعد از دستور /d وارد کنید.\n"
                "مثال:\n"
                "/d https://www.instagram.com/p/xxx"
            )
    else:
        await update.message.reply_text(
            "لطفاً لینک پست اینستاگرام را بعد از دستور /d وارد کنید.\n"
            "مثال:\n"
            "/d https://www.instagram.com/p/xxx"
        )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور نمایش وضعیت سرور و ربات"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("⛔️ شما دسترسی به این بخش را ندارید.")
        return
    
    # دریافت وضعیت اتصال
    connection_status = connection_manager.get_connection_status()
    
    # ایجاد پیام وضعیت سرور
    server_status = server_monitor.format_status_message()
    
    # اضافه کردن وضعیت اتصال به پیام
    connection_message = "\n🔌 وضعیت اتصال:\n"
    connection_message += f"├ اتصال فعلی: {'✅ متصل' if connection_status['is_connected'] else '❌ قطع'}\n"
    
    if connection_status['last_connected']:
        last_connected = datetime.fromtimestamp(connection_status['last_connected'])
        connection_message += f"├ آخرین اتصال: {last_connected.strftime('%Y-%m-%d %H:%M:%S')}\n"
    
    if connection_status['last_disconnect']:
        last_disconnect = datetime.fromtimestamp(connection_status['last_disconnect'])
        connection_message += f"├ آخرین قطعی: {last_disconnect.strftime('%Y-%m-%d %H:%M:%S')}\n"
    
    connection_message += f"└ تعداد تلاش‌های اتصال مجدد: {connection_status['reconnect_attempts']}\n"
    
    # ترکیب پیام‌ها
    complete_status = server_status + connection_message
    
    # ایجاد دکمه‌های مدیریتی
    keyboard = [
        [
            InlineKeyboardButton("🔄 به‌روزرسانی", callback_data="refresh_status"),
            InlineKeyboardButton("🔁 راه‌اندازی مجدد", callback_data="restart_bot")
        ],
        [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]
    ]
    
    await update.message.reply_text(
        complete_status,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور راه‌اندازی مجدد ربات"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("⛔️ شما دسترسی به این بخش را ندارید.")
        return
    
    restart_message = await update.message.reply_text(
        "🔄 در حال راه‌اندازی مجدد ربات...\n"
        "⏳ لطفاً صبر کنید..."
    )
    
    # راه‌اندازی مجدد نرم‌افزاری
    logger.info("راه‌اندازی مجدد ربات توسط ادمین درخواست شد")
    
    # ذخیره اطلاعات راه‌اندازی مجدد برای پیگیری بعد از راه‌اندازی
    context.bot_data["restart_info"] = {
        "chat_id": update.effective_chat.id,
        "message_id": restart_message.message_id,
        "time": time.time(),
        "requested_by": user.id
    }
    
    # قطع اتصال فعلی و راه‌اندازی مجدد
    await connection_manager.shutdown()
    
    # به دلیل ساختار حلقه در connection_manager، ربات به صورت خودکار دوباره راه‌اندازی می‌شود
    # اما بهتر است اینجا هم یک پیام لاگ بگذاریم
    logger.info("ربات به زودی دوباره راه‌اندازی خواهد شد...")

def main():
    setup_database()
    
    # راه‌اندازی ربات با استفاده از ConnectionManager
    asyncio.run(run_bot())

async def setup_handlers(application: Application):
    """تنظیم هندلرهای ربات"""
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_chat_members))
    
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("add_channel", add_channel_command))
    application.add_handler(CommandHandler("del_channel", del_channel_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    application.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photo))
    application.add_handler(MessageHandler(filters.VIDEO & ~filters.COMMAND, handle_video))
    application.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, handle_document))
    application.add_handler(MessageHandler(filters.AUDIO & ~filters.COMMAND, handle_audio))
    
    application.add_handler(CommandHandler("d", download_command))
    
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("restart", restart_command))

async def post_startup():
    """عملیات پس از راه‌اندازی ربات"""
    logger.info("ربات با موفقیت راه‌اندازی شد!")
    
    # بررسی اطلاعات راه‌اندازی مجدد
    application = connection_manager.application
    if application and hasattr(application, "bot_data") and "restart_info" in application.bot_data:
        restart_info = application.bot_data["restart_info"]
        try:
            restart_time = datetime.fromtimestamp(restart_info["time"])
            now = datetime.now()
            restart_duration = (now - restart_time).total_seconds()
            
            await application.bot.edit_message_text(
                f"✅ ربات با موفقیت راه‌اندازی مجدد شد.\n"
                f"⏱ زمان راه‌اندازی: {restart_duration:.2f} ثانیه",
                chat_id=restart_info["chat_id"],
                message_id=restart_info["message_id"]
            )
            
            # پاک کردن اطلاعات راه‌اندازی مجدد
            del application.bot_data["restart_info"]
            
        except Exception as e:
            logger.error(f"خطا در ارسال پیام راه‌اندازی مجدد: {str(e)}")

async def run_bot():
    """راه‌اندازی ربات"""
    logger.info("در حال راه‌اندازی ربات...")
    
    # راه‌اندازی ساده ربات
    try:
        await connection_manager.start_polling(
            setup_handlers_func=setup_handlers,
            post_startup_func=post_startup
        )
    except Exception as e:
        logger.error(f"خطا در راه‌اندازی ربات: {str(e)}")

if __name__ == '__main__':
    main()
