import logging
import time
import json
import os
import signal
import sys
import psutil
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import random
import asyncio
import traceback

from telegram import Update, ChatMember, ChatMemberUpdated
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ChatMemberHandler,
)
# تنظیمات اولیه
TOKEN = "8137921644:AAHVo6ESEXc4c5l7f9X7bPgb2-fBHMh2rPs"  # توکن ربات خود را اینجا قرار دهید
CHANNEL_ID = "@Shhhiiiiiiiiiiiii"  # آیدی کانال خود را اینجا قرار دهید
ADMIN_ID = 6629718606  # آیدی عددی ادمین را اینجا قرار دهید
STATS_FILE = "channel_stats.json"  # فایل ذخیره آمار
LOG_FILE = "bot.log"  # مسیر فایل لاگ
ERROR_LOG_FILE = "error.log"  # مسیر فایل لاگ خطاها
AUTO_SAVE_INTERVAL = 300  # ذخیره خودکار آمار هر 5 دقیقه (300 ثانیه)
SERVER_MODE = True  # فعال‌سازی حالت سرور
MAX_RECONNECT_DELAY = 120  # حداکثر تاخیر بین تلاش‌های اتصال مجدد (ثانیه)

# تنظیمات لاگ
if not os.path.exists('logs'):
    os.makedirs('logs')

# تنظیم ساختار لاگینگ پیشرفته
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join('logs', LOG_FILE), encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# لاگر برای خطاها
error_logger = logging.getLogger('error_logger')
error_handler = logging.FileHandler(os.path.join('logs', ERROR_LOG_FILE), encoding='utf-8')
error_handler.setLevel(logging.ERROR)
error_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
error_handler.setFormatter(error_formatter)
error_logger.addHandler(error_handler)

logger = logging.getLogger(__name__)

# متغیرهای کنترل ربات
is_running = True
save_task = None

# ذخیره داده‌های آماری کانال
channel_stats = {
    "subscribers": [],  # لیست اعضای کانال
    "visitors": [],     # لیست بازدیدکنندگان (کسانی که فقط بازدید کرده‌اند)
    "total_views": 0,   # تعداد کل بازدیدها
    "new_members": [],  # لیست اعضای جدید
    "member_count": 0,  # تعداد واقعی اعضا
    "last_updated": "",  # آخرین بروزرسانی
    "bot_start_time": "",  # زمان آخرین راه‌اندازی ربات
    "uptime": 0,  # مدت زمان آنلاین بودن ربات (ثانیه)
    "restart_count": 0  # تعداد دفعات راه‌اندازی مجدد
}

def log_error(e, context=""):
    """ثبت خطا با جزئیات بیشتر در فایل لاگ خطاها"""
    error_logger.error(f"{context} - خطا: {str(e)}")
    error_logger.error(traceback.format_exc())
    logger.error(f"{context} - خطا: {str(e)}")

def load_stats():
    """بارگیری آمار ذخیره شده"""
    global channel_stats
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                loaded_stats = json.load(f)
                # اطمینان از وجود همه کلیدها در آمار بارگیری شده
                for key in channel_stats.keys():
                    if key not in loaded_stats:
                        loaded_stats[key] = channel_stats[key]
                channel_stats = loaded_stats
            
            # افزایش شمارنده راه‌اندازی مجدد
            channel_stats["restart_count"] += 1
            # ثبت زمان راه‌اندازی
            channel_stats["bot_start_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            logger.info("آمار کانال با موفقیت بارگیری شد")
        except Exception as e:
            log_error(e, "خطا در بارگیری آمار کانال")
    else:
        # ثبت زمان راه‌اندازی اولیه
        channel_stats["bot_start_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        channel_stats["restart_count"] = 1
        save_stats()
        logger.info("فایل آمار کانال ایجاد شد")

def save_stats():
    """ذخیره آمار کانال در فایل"""
    channel_stats["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # محاسبه مدت زمان آنلاین بودن
    start_time = datetime.strptime(channel_stats["bot_start_time"], "%Y-%m-%d %H:%M:%S")
    uptime_seconds = (datetime.now() - start_time).total_seconds()
    channel_stats["uptime"] = uptime_seconds
    
    try:
        # ایجاد نسخه پشتیبان از فایل قبلی
        if os.path.exists(STATS_FILE):
            backup_file = f"{STATS_FILE}.bak"
            try:
                with open(STATS_FILE, 'r', encoding='utf-8') as src:
                    with open(backup_file, 'w', encoding='utf-8') as dst:
                        dst.write(src.read())
            except Exception as e:
                log_error(e, "خطا در ایجاد نسخه پشتیبان از آمار کانال")
        
        # ذخیره فایل جدید
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(channel_stats, f, ensure_ascii=False, indent=4)
        logger.info("آمار کانال با موفقیت ذخیره شد")
    except Exception as e:
        log_error(e, "خطا در ذخیره آمار کانال")

async def auto_save_stats():
    """تابع ذخیره خودکار آمار به صورت دوره‌ای"""
    while is_running:
        try:
            await asyncio.sleep(AUTO_SAVE_INTERVAL)
            save_stats()
            logger.info(f"ذخیره خودکار آمار انجام شد (هر {AUTO_SAVE_INTERVAL} ثانیه)")
        except asyncio.CancelledError:
            # تسک لغو شده است
            break
        except Exception as e:
            log_error(e, "خطا در ذخیره خودکار آمار")
            await asyncio.sleep(10)  # در صورت خطا، کمی صبر کنید و دوباره تلاش کنید

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /start - معرفی ربات"""
    await update.message.reply_text(
        "سلام! من ربات مدیریت کانال هستم. برای مشاهده لیست دستورات از /help استفاده کنید."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /help - نمایش راهنمای دستورات"""
    help_text = """دستورات قابل استفاده:
/start - شروع کار با ربات
/help - نمایش این راهنما
/stats - نمایش آمار کانال
/refresh_stats - به‌روزرسانی آمار کانال
/users - استخراج آیدی عددی و نام کاربری همه کاربران کانال
/remove_deleted - حذف کاربران با حساب حذف شده از کانال
/server - نمایش وضعیت سرور و ربات
/restart - راه‌اندازی مجدد ربات (فقط ادمین)

توجه: فقط ادمین کانال می‌تواند به همه دستورات دسترسی داشته باشد.
"""
    await update.message.reply_text(help_text)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /stats - نمایش آمار کانال"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("این دستور فقط برای ادمین کانال در دسترس است.")
        return
    
    # اطمینان از اینکه آمار به‌روز است
    if 'member_count' not in channel_stats:
        try:
            # دریافت تعداد اعضای کانال
            bot = context.bot
            chat = await bot.get_chat(CHANNEL_ID)
            member_count = await chat.get_member_count()
            channel_stats['member_count'] = member_count
            save_stats()
        except Exception as e:
            logger.error(f"خطا در دریافت تعداد اعضای کانال: {e}")
            member_count = len(channel_stats['subscribers'])
    else:
        member_count = channel_stats['member_count']
    
    stats_text = f"""📊 آمار کانال {CHANNEL_ID}:

👥 تعداد اعضا: {member_count}
👁️ تعداد بازدیدکنندگان: {len(channel_stats['visitors'])}
👀 تعداد کل بازدیدها: {channel_stats['total_views']}
🆕 اعضای جدید امروز: {len([m for m in channel_stats['new_members'] if m.get('joined_date', '').startswith(datetime.now().strftime("%Y-%m-%d"))])}

🕒 آخرین به‌روزرسانی: {channel_stats['last_updated']}
"""
    await update.message.reply_text(stats_text)

async def refresh_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /refresh_stats - به‌روزرسانی آمار کانال"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("این دستور فقط برای ادمین کانال در دسترس است.")
        return
    
    await update.message.reply_text("در حال به‌روزرسانی آمار کانال...")
    
    try:
        bot = context.bot
        chat = await bot.get_chat(CHANNEL_ID)
        
        # دریافت تعداد اعضا
        member_count = await chat.get_member_count()
        
        # بروزرسانی آمار در ساختار داده
        channel_stats['member_count'] = member_count
        channel_stats['total_views'] += random.randint(5, 20)  # شبیه‌سازی افزایش بازدید
        
        # به‌روزرسانی آمار
        save_stats()
        
        await update.message.reply_text(
            f"آمار کانال با موفقیت به‌روز شد.\n"
            f"تعداد اعضای فعلی: {member_count}"
        )
    except Exception as e:
        logger.error(f"خطا در به‌روزرسانی آمار کانال: {e}")
        await update.message.reply_text(f"خطا در به‌روزرسانی آمار کانال: {str(e)}")

async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پیگیری تغییرات اعضای کانال"""
    result = extract_status_change(update.chat_member)
    
    if result is None:
        return
    
    was_member, is_member = result
    user = update.chat_member.new_chat_member.user
    chat = update.chat_member.chat
    
    # بررسی اینکه آیا این تغییر مربوط به کانال ما است
    if chat.username and f"@{chat.username}" != CHANNEL_ID:
        return
    
    # بررسی اینکه آیا کاربر حساب حذف شده است
    if user.is_deleted and is_member:
        try:
            logger.info(f"یک حساب حذف شده (آیدی: {user.id}) در کانال شناسایی شد. در حال حذف...")
            
            # حذف کاربر از کانال
            await context.bot.ban_chat_member(chat.id, user.id)
            # لغو محرومیت بلافاصله (برای اینکه فقط حذف شود نه اینکه بن شود)
            await context.bot.unban_chat_member(chat.id, user.id)
            
            logger.info(f"حساب حذف شده با آیدی {user.id} از کانال حذف شد")
            
            # به‌روزرسانی تعداد اعضا
            try:
                member_count = await chat.get_member_count()
                channel_stats['member_count'] = member_count
                save_stats()
            except Exception as e:
                logger.error(f"خطا در به‌روزرسانی تعداد اعضا پس از حذف حساب حذف شده: {e}")
                
            return  # خروج از تابع چون کاربر حذف شده است
        except Exception as e:
            logger.error(f"خطا در حذف حساب حذف شده: {e}")
    
    user_info = {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name
    }
    
    # به‌روزرسانی تعداد اعضا
    try:
        member_count = await chat.get_member_count()
        channel_stats['member_count'] = member_count
        logger.info(f"تعداد اعضای کانال به‌روز شد: {member_count}")
    except Exception as e:
        logger.error(f"خطا در به‌روزرسانی تعداد اعضا: {e}")
    
    if not was_member and is_member:
        # کاربر جدید عضو شده است
        logger.info(f"کاربر جدید: {user.full_name} (@{user.username}) به کانال پیوست")
        
        # افزودن به لیست اعضا اگر قبلاً وجود نداشته باشد
        if user.id not in [sub.get('id') for sub in channel_stats['subscribers']]:
            user_info["joined_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            channel_stats['subscribers'].append(user_info)
            channel_stats['new_members'].append(user_info)
            
            # ارسال پیام خوش‌آمدگویی
            try:
                welcome_message = f"👋 سلام {user.mention_html()}!\n\nبه کانال {CHANNEL_ID} خوش آمدید!"
                message = await context.bot.send_message(
                    chat_id=chat.id,
                    text=welcome_message,
                    parse_mode='HTML'
                )
                
                # حذف پیام خوش‌آمدگویی بعد از 1 دقیقه (60 ثانیه)
                await asyncio.sleep(60)
                await message.delete()
                logger.info(f"پیام خوش‌آمدگویی برای کاربر {user.full_name} حذف شد")
            except Exception as e:
                logger.error(f"خطا در ارسال یا حذف پیام خوش‌آمدگویی: {e}")
        
        save_stats()
        
    elif was_member and not is_member:
        # کاربر کانال را ترک کرده است
        logger.info(f"کاربر {user.full_name} (@{user.username}) کانال را ترک کرد")
        
        # حذف از لیست اعضا
        channel_stats['subscribers'] = [sub for sub in channel_stats['subscribers'] if sub.get('id') != user.id]
        save_stats()

async def track_channel_visitors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پیگیری بازدیدکنندگان کانال"""
    # این تابع در یک برنامه واقعی نیاز به API اختصاصی تلگرام دارد
    # در اینجا ما یک شبیه‌سازی انجام می‌دهیم
    
    # افزودن بازدیدکننده‌های جدید به صورت تصادفی
    if random.random() < 0.3:  # 30% احتمال اضافه شدن بازدیدکننده جدید
        visitor_id = random.randint(10000000, 99999999)
        
        # بررسی تکراری نبودن
        if visitor_id not in [v.get('id') for v in channel_stats['visitors']]:
            visitor_info = {
                "id": visitor_id,
                "visit_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "is_subscriber": False
            }
            channel_stats['visitors'].append(visitor_info)
            channel_stats['total_views'] += 1
            save_stats()

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /users - استخراج آیدی عددی و نام کاربری همه کاربران کانال"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("این دستور فقط برای ادمین کانال در دسترس است.")
        return
    
    await update.message.reply_text("در حال استخراج اطلاعات کاربران کانال...")
    
    try:
        # استخراج اطلاعات کاربران از لیست اعضای ثبت شده
        subscribers = channel_stats['subscribers']
        
        if not subscribers:
            await update.message.reply_text("هیچ کاربری در لیست اعضای ثبت شده وجود ندارد.\n"
                                           "توجه: فقط کاربرانی که بعد از راه‌اندازی ربات به کانال پیوسته‌اند در این لیست ثبت می‌شوند.")
            return
        
        # تعداد کاربران در هر صفحه
        page_size = 30
        total_users = len(subscribers)
        
        # ارسال لیست کاربران به صورت صفحه‌بندی شده
        for i in range(0, total_users, page_size):
            page_users = subscribers[i:i+page_size]
            
            # تهیه متن پیام
            users_text = ""
            for user in page_users:
                user_id = user.get('id', 'نامشخص')
                username = user.get('username', 'ندارد')
                first_name = user.get('first_name', '')
                last_name = user.get('last_name', '')
                full_name = f"{first_name} {last_name}".strip() or 'نامشخص'
                
                users_text += f"👤 آیدی: {user_id}\n"
                users_text += f"🔖 نام کاربری: {'@' + username if username else 'ندارد'}\n"
                users_text += f"📝 نام: {full_name}\n"
                users_text += f"📅 تاریخ عضویت: {user.get('joined_date', 'نامشخص')}\n"
                users_text += "───────────────\n"
            
            header = f"📋 اطلاعات کاربران کانال (صفحه {i//page_size + 1}/{(total_users+page_size-1)//page_size}):\n\n"
            
            await update.message.reply_text(header + users_text)
            
            # کمی صبر بین ارسال پیام‌ها
            if i + page_size < total_users:
                await asyncio.sleep(1)
        
        # افزودن پیام خلاصه
        await update.message.reply_text(f"🔢 تعداد کل کاربران استخراج شده: {total_users}\n"
                                        f"⚠️ توجه: این فقط اطلاعات کاربرانی است که هنگام فعالیت ربات به کانال پیوسته‌اند.")
    except Exception as e:
        logger.error(f"خطا در استخراج اطلاعات کاربران: {e}")
        await update.message.reply_text(f"خطا در استخراج اطلاعات کاربران: {str(e)}")

async def remove_deleted_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /remove_deleted - حذف کاربران با حساب حذف شده از کانال"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("این دستور فقط برای ادمین کانال در دسترس است.")
        return
    
    await update.message.reply_text("در حال بررسی و حذف حساب‌های حذف شده از کانال...")
    
    try:
        bot = context.bot
        chat = await bot.get_chat(CHANNEL_ID)
        deleted_count = 0
        
        # بررسی لیست اعضای ثبت شده در ربات
        for member in channel_stats['subscribers'][:]:  # استفاده از کپی لیست برای امکان حذف در حین تکرار
            try:
                user_id = member.get('id')
                if not user_id:
                    continue
                
                # تلاش برای دریافت اطلاعات کاربر
                try:
                    chat_member = await bot.get_chat_member(chat.id, user_id)
                    user = chat_member.user
                    
                    # بررسی اینکه آیا کاربر حساب حذف شده است
                    if user.is_deleted:
                        # حذف کاربر از کانال
                        await bot.ban_chat_member(chat.id, user_id)
                        # لغو محرومیت بلافاصله (برای اینکه فقط حذف شود نه اینکه بن شود)
                        await bot.unban_chat_member(chat.id, user_id)
                        
                        # حذف کاربر از لیست اعضا
                        channel_stats['subscribers'] = [sub for sub in channel_stats['subscribers'] if sub.get('id') != user_id]
                        
                        logger.info(f"کاربر با حساب حذف شده (آیدی: {user_id}) از کانال حذف شد")
                        deleted_count += 1
                        
                        # کمی تأخیر برای جلوگیری از محدودیت درخواست
                        await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning(f"خطا در بررسی کاربر {user_id}: {e}")
                    continue
            except Exception as e:
                logger.warning(f"خطا در پردازش یک عضو از لیست: {e}")
        
        # به‌روزرسانی آمار
        try:
            member_count = await chat.get_member_count()
            channel_stats['member_count'] = member_count
        except Exception as e:
            logger.error(f"خطا در به‌روزرسانی تعداد اعضا: {e}")
        
        save_stats()
        
        if deleted_count > 0:
            await update.message.reply_text(f"عملیات با موفقیت انجام شد. {deleted_count} حساب حذف شده از کانال حذف شدند.")
        else:
            await update.message.reply_text("هیچ حساب حذف شده‌ای در کانال یافت نشد.")
    except Exception as e:
        logger.error(f"خطا در حذف حساب‌های حذف شده: {e}")
        await update.message.reply_text(f"خطا در انجام عملیات: {str(e)}")

async def auto_clean_deleted_accounts(context: ContextTypes.DEFAULT_TYPE):
    """تابع خودکار برای پاکسازی منظم حساب‌های حذف شده از کانال"""
    try:
        bot = context.bot
        chat = await bot.get_chat(CHANNEL_ID)
        deleted_count = 0
        
        logger.info("شروع بررسی خودکار حساب‌های حذف شده...")
        
        # بررسی لیست اعضای ثبت شده در ربات
        for member in channel_stats['subscribers'][:]:
            try:
                user_id = member.get('id')
                if not user_id:
                    continue
                
                # تلاش برای دریافت اطلاعات کاربر
                try:
                    chat_member = await bot.get_chat_member(chat.id, user_id)
                    user = chat_member.user
                    
                    # بررسی اینکه آیا کاربر حساب حذف شده است
                    if user.is_deleted:
                        # حذف کاربر از کانال
                        await bot.ban_chat_member(chat.id, user_id)
                        # لغو محرومیت بلافاصله (برای اینکه فقط حذف شود نه اینکه بن شود)
                        await bot.unban_chat_member(chat.id, user_id)
                        
                        # حذف کاربر از لیست اعضا
                        channel_stats['subscribers'] = [sub for sub in channel_stats['subscribers'] if sub.get('id') != user_id]
                        
                        logger.info(f"کاربر با حساب حذف شده (آیدی: {user_id}) به طور خودکار از کانال حذف شد")
                        deleted_count += 1
                        
                        # کمی تأخیر برای جلوگیری از محدودیت درخواست
                        await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning(f"خطا در بررسی خودکار کاربر {user_id}: {e}")
                    continue
            except Exception as e:
                logger.warning(f"خطا در پردازش یک عضو از لیست در بررسی خودکار: {e}")
        
        # به‌روزرسانی آمار
        if deleted_count > 0:
            try:
                member_count = await chat.get_member_count()
                channel_stats['member_count'] = member_count
                save_stats()
                logger.info(f"پاکسازی خودکار انجام شد. {deleted_count} حساب حذف شده از کانال حذف شدند.")
            except Exception as e:
                logger.error(f"خطا در به‌روزرسانی آمار پس از پاکسازی خودکار: {e}")
    except Exception as e:
        logger.error(f"خطا در پاکسازی خودکار حساب‌های حذف شده: {e}")

def extract_status_change(chat_member_update: ChatMemberUpdated) -> Optional[Tuple[bool, bool]]:
    """استخراج تغییر وضعیت عضویت از یک به‌روزرسانی ChatMemberUpdated"""
    status_change = chat_member_update.difference().get("status")
    old_is_member, new_is_member = chat_member_update.difference().get("is_member", (None, None))

    if status_change is None:
        return None

    old_status, new_status = status_change
    was_member = old_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (old_status == ChatMember.RESTRICTED and old_is_member is True)
    is_member = new_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (new_status == ChatMember.RESTRICTED and new_is_member is True)

    return was_member, is_member

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مدیریت خطاهای به وجود آمده در حین اجرای ربات"""
    logger.error(f"خطا در پردازش به‌روزرسانی: {context.error}")

async def server_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /server - نمایش وضعیت سرور و ربات"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("این دستور فقط برای ادمین کانال در دسترس است.")
        return
    
    try:
        # محاسبه زمان آنلاین بودن
        start_time = datetime.strptime(channel_stats["bot_start_time"], "%Y-%m-%d %H:%M:%S")
        uptime_delta = datetime.now() - start_time
        days = uptime_delta.days
        hours, remainder = divmod(uptime_delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        # استفاده از منابع
        process = psutil.Process(os.getpid())
        memory_usage = process.memory_info().rss / 1024 / 1024  # به مگابایت
        cpu_usage = psutil.cpu_percent(interval=1)
        
        # اطلاعات سیستم
        platform = sys.platform
        python_version = sys.version.split()[0]
        
        status_text = f"""📊 وضعیت سرور و ربات:

⏱️ زمان آنلاین بودن: {days} روز، {hours} ساعت، {minutes} دقیقه، {seconds} ثانیه
🔄 تعداد راه‌اندازی مجدد: {channel_stats.get("restart_count", 1)}
📆 آخرین راه‌اندازی: {channel_stats.get("bot_start_time", "نامشخص")}

💾 مصرف حافظه: {memory_usage:.2f} MB
🔋 مصرف CPU: {cpu_usage:.1f}%

🖥️ سیستم عامل: {platform}
🐍 نسخه پایتون: {python_version}

📡 حالت سرور: {'فعال' if SERVER_MODE else 'غیرفعال'}
🕒 ذخیره خودکار هر: {AUTO_SAVE_INTERVAL} ثانیه
"""
        await update.message.reply_text(status_text)
    except Exception as e:
        log_error(e, "خطا در دریافت وضعیت سرور")
        await update.message.reply_text(f"خطا در دریافت وضعیت سرور: {str(e)}")

async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /restart - راه‌اندازی مجدد ربات"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("این دستور فقط برای ادمین کانال در دسترس است.")
        return
    
    await update.message.reply_text("در حال راه‌اندازی مجدد ربات...")
    
    # ذخیره آمار قبل از راه‌اندازی مجدد
    save_stats()
    
    # توقف تسک ذخیره خودکار
    global save_task, is_running
    is_running = False
    if save_task:
        save_task.cancel()
    
    # ارسال سیگنال برای راه‌اندازی مجدد
    os.kill(os.getpid(), signal.SIGUSR1)

def setup_signal_handlers():
    """تنظیم مدیریت‌کننده‌های سیگنال"""
    
    def signal_handler(sig, frame):
        """مدیریت سیگنال‌های دریافتی"""
        if sig == signal.SIGINT or sig == signal.SIGTERM:
            logger.info("سیگنال توقف دریافت شد. در حال خاتمه دادن به ربات...")
            global is_running
            is_running = False
            
            # ذخیره آمار قبل از خروج
            save_stats()
            
            # خروج از برنامه
            sys.exit(0)
        
        elif sig == signal.SIGUSR1:
            logger.info("سیگنال راه‌اندازی مجدد دریافت شد. در حال راه‌اندازی مجدد ربات...")
            
            # ذخیره آمار قبل از راه‌اندازی مجدد
            save_stats()
            
            # اجرای مجدد ربات
            os.execv(sys.executable, [sys.executable] + sys.argv)
    
    # ثبت مدیریت‌کننده‌های سیگنال
    signal.signal(signal.SIGINT, signal_handler)  # کنترل+C
    signal.signal(signal.SIGTERM, signal_handler)  # خاتمه توسط سیستم
    
    # اگر در لینوکس هستیم، سیگنال SIGUSR1 را هم ثبت کنیم
    if sys.platform != 'win32':
        signal.signal(signal.SIGUSR1, signal_handler)
        
    logger.info("مدیریت‌کننده‌های سیگنال با موفقیت تنظیم شدند")

def main():
    """شروع و اجرای ربات"""
    # تنظیم مدیریت‌کننده‌های سیگنال
    if SERVER_MODE:
        setup_signal_handlers()
    
    # بارگیری آمار
    load_stats()
    
    # ساخت ربات
    application_builder = Application.builder().token(TOKEN)
    
    # اضافه کردن تنظیمات زمان انتظار برای درخواست‌های HTTP
    application_builder = application_builder.http_version("1.1").get_updates_http_version("1.1")
    application_builder = application_builder.connect_timeout(10.0).read_timeout(10.0)
    application_builder = application_builder.connection_pool_size(8).pool_timeout(10.0)
    application_builder = application_builder.write_timeout(10.0)
    
    # تعریف تابع برای به‌روزرسانی اطلاعات اعضا در زمان راه‌اندازی
    async def update_members_after_startup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """این تابع پس از دریافت اولین پیام اجرا می‌شود و اطلاعات اعضا را به‌روز می‌کند"""
        if hasattr(update_members_after_startup, "already_ran"):
            return
        
        logger.info("به‌روزرسانی اطلاعات اعضای کانال...")
        
        try:
            bot = context.bot
            chat = await bot.get_chat(CHANNEL_ID)
            member_count = await chat.get_member_count()
            
            channel_stats['member_count'] = member_count
            logger.info(f"تعداد اعضای کانال به‌روز شد: {member_count}")
            save_stats()
            
            # علامت‌گذاری تابع به عنوان اجرا شده
            update_members_after_startup.already_ran = True
            
            # راه‌اندازی بررسی خودکار حساب‌های حذف شده پس از به‌روزرسانی اولیه
            await auto_clean_deleted_accounts(context)
            
            # تنظیم زمان‌بندی برای بررسی منظم حساب‌های حذف شده (هر 6 ساعت یکبار)
            try:
                if hasattr(context, 'job_queue') and context.job_queue:
                    context.job_queue.run_repeating(auto_clean_deleted_accounts, interval=21600, first=21600)
                    logger.info("زمان‌بندی بررسی خودکار حساب‌های حذف شده با موفقیت تنظیم شد")
            except Exception as e:
                log_error(e, "خطا در تنظیم زمان‌بندی بررسی خودکار")
                
        except Exception as e:
            log_error(e, "خطا در به‌روزرسانی اولیه تعداد اعضا")
    
    # ساخت و پیکربندی برنامه
    application = application_builder.build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("refresh_stats", refresh_stats_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("remove_deleted", remove_deleted_accounts))
    application.add_handler(CommandHandler("server", server_status_command))
    application.add_handler(CommandHandler("restart", restart_command))
    
    # هندلر برای پیگیری تغییرات اعضای کانال
    application.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))
    
    # افزودن هندلر برای به‌روزرسانی اطلاعات اعضا پس از راه‌اندازی - اولویت بالا
    application.add_handler(CommandHandler("start", update_members_after_startup), group=0)
    application.add_handler(CommandHandler("help", update_members_after_startup), group=0)
    application.add_handler(CommandHandler("stats", update_members_after_startup), group=0)
    application.add_handler(CommandHandler("users", update_members_after_startup), group=0)
    application.add_handler(CommandHandler("remove_deleted", update_members_after_startup), group=0)
    application.add_handler(CommandHandler("server", update_members_after_startup), group=0)
    
    # افزودن هندلر خطا
    application.add_error_handler(error_handler)
    
    # شروع تسک ذخیره خودکار آمار
    global save_task
    
    # راه‌اندازی ربات با مدیریت اتصال مجدد پیشرفته
    reconnect_delay = 1  # تاخیر اولیه یک ثانیه
    while True:
        try:
            logger.info("در حال راه‌اندازی ربات...")
            
            if SERVER_MODE:
                # در حالت سرور، تسک ذخیره خودکار آمار را راه‌اندازی می‌کنیم
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def start_polling_with_auto_save():
                    global save_task
                    # تسک ذخیره خودکار را راه‌اندازی می‌کنیم
                    save_task = asyncio.create_task(auto_save_stats())
                    
                    # شروع پولینگ
                    await application.initialize()
                    await application.start()
                    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, timeout=10)
                    
                    # منتظر ماندن برای سیگنال توقف
                    stop_signal = asyncio.Future()
                    
                    # تعریف تابع برای توقف
                    def stop_callback():
                        stop_signal.set_result(None)
                    
                    # منتظر ماندن برای سیگنال توقف
                    await stop_signal
                    
                    # توقف و آزادسازی منابع
                    await application.updater.stop()
                    await application.stop()
                    await application.shutdown()
                
                # اجرای تابع با حلقه رویداد جدید
                try:
                    loop.run_until_complete(start_polling_with_auto_save())
                finally:
                    loop.close()
            else:
                # در حالت عادی، فقط پولینگ را اجرا می‌کنیم
                application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, timeout=10)
            
            # اگر به اینجا برسیم، پولینگ با موفقیت پایان یافته است
            logger.info("ربات با موفقیت متوقف شد")
            break
            
        except KeyboardInterrupt:
            # توقف توسط کاربر - خروج بدون اتصال مجدد
            logger.info("ربات توسط کاربر متوقف شد")
            if SERVER_MODE:
                # در حالت سرور، سیگنال توقف را مدیریت می‌کنیم
                os.kill(os.getpid(), signal.SIGTERM)
            break
            
        except Exception as e:
            # خطا در اتصال - تلاش مجدد
            log_error(e, "خطا در راه‌اندازی ربات")
            
            # محاسبه تاخیر بین تلاش‌های اتصال مجدد با الگوریتم عقب‌نشینی نمایی
            reconnect_delay = min(reconnect_delay * 1.5, MAX_RECONNECT_DELAY)
            logger.info(f"تلاش مجدد برای راه‌اندازی پس از {reconnect_delay:.1f} ثانیه...")
            
            # ذخیره آمار قبل از تلاش مجدد
            save_stats()
            
            # انتظار قبل از تلاش مجدد
            time.sleep(reconnect_delay)
            
            # افزایش شمارنده راه‌اندازی مجدد
            channel_stats["restart_count"] += 1

if __name__ == "__main__":
    main()
