#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
سرور مدیریت ربات تلگرام
این اسکریپت برای راه‌اندازی و مدیریت ربات در حالت سرور استفاده می‌شود
"""

import os
import sys
import signal
import time
import subprocess
import argparse
import logging
import datetime

# تنظیمات
BOT_SCRIPT = "bot.py"  # نام فایل اسکریپت اصلی ربات
LOG_FOLDER = "logs"    # پوشه لاگ
LOG_FILE = "server.log"  # فایل لاگ سرور
RESTART_DELAY = 5      # تاخیر بین راه‌اندازی‌های مجدد (ثانیه)

# تنظیمات لاگینگ
if not os.path.exists(LOG_FOLDER):
    os.makedirs(LOG_FOLDER)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_FOLDER, LOG_FILE), encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("server")

def get_timestamp():
    """دریافت زمان فعلی به صورت رشته"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def start_bot():
    """راه‌اندازی ربات"""
    logger.info("در حال راه‌اندازی ربات...")
    
    # بررسی وجود فایل اسکریپت ربات
    if not os.path.exists(BOT_SCRIPT):
        logger.error(f"فایل اسکریپت ربات '{BOT_SCRIPT}' یافت نشد!")
        sys.exit(1)
    
    # شروع پروسه ربات
    try:
        process = subprocess.Popen([sys.executable, BOT_SCRIPT])
        return process
    except Exception as e:
        logger.error(f"خطا در راه‌اندازی ربات: {str(e)}")
        return None

def stop_bot(process):
    """توقف ربات"""
    if process is None:
        return
    
    logger.info("در حال توقف ربات...")
    
    try:
        # ارسال سیگنال SIGTERM برای خاتمه
        process.send_signal(signal.SIGTERM)
        
        # انتظار برای خاتمه (حداکثر 10 ثانیه)
        for _ in range(10):
            if process.poll() is not None:
                break
            time.sleep(1)
        
        # اگر هنوز متوقف نشده، با زور متوقف می‌کنیم
        if process.poll() is None:
            logger.warning("ربات به طور عادی متوقف نشد. در حال توقف اجباری...")
            process.kill()
            
        logger.info("ربات با موفقیت متوقف شد")
    except Exception as e:
        logger.error(f"خطا در توقف ربات: {str(e)}")

def restart_bot(process):
    """راه‌اندازی مجدد ربات"""
    logger.info("در حال راه‌اندازی مجدد ربات...")
    
    # توقف ربات فعلی
    stop_bot(process)
    
    # تاخیر کوتاه قبل از راه‌اندازی مجدد
    time.sleep(RESTART_DELAY)
    
    # راه‌اندازی مجدد
    return start_bot()

def monitor_bot(process):
    """نظارت بر وضعیت اجرای ربات"""
    if process is None:
        return False
    
    # بررسی وضعیت پروسه
    return process.poll() is None

def handle_signal(sig, frame):
    """مدیریت سیگنال‌های دریافتی"""
    global is_running, bot_process
    
    if sig == signal.SIGINT or sig == signal.SIGTERM:
        logger.info("سیگنال توقف دریافت شد. در حال خاتمه دادن به سرور...")
        is_running = False
        
        # توقف ربات
        stop_bot(bot_process)
        
        # خروج از برنامه
        sys.exit(0)

def start_server():
    """راه‌اندازی سرور"""
    global is_running, bot_process
    
    # ثبت مدیریت‌کننده‌های سیگنال
    signal.signal(signal.SIGINT, handle_signal)   # کنترل+C
    signal.signal(signal.SIGTERM, handle_signal)  # خاتمه توسط سیستم
    
    logger.info("سرور مدیریت ربات شروع به کار کرد")
    
    # راه‌اندازی اولیه ربات
    bot_process = start_bot()
    
    # حلقه اصلی نظارت بر ربات
    is_running = True
    consecutive_failures = 0
    
    while is_running:
        try:
            # بررسی وضعیت ربات
            if not monitor_bot(bot_process):
                # ربات متوقف شده، راه‌اندازی مجدد
                logger.warning("ربات متوقف شده است. در حال راه‌اندازی مجدد...")
                
                # افزایش شمارنده خطاهای متوالی
                consecutive_failures += 1
                
                # اگر تعداد خطاها زیاد است، تاخیر بیشتری بین راه‌اندازی‌ها ایجاد می‌کنیم
                delay = min(RESTART_DELAY * (1 + consecutive_failures * 0.5), 60)
                logger.info(f"تاخیر {delay:.1f} ثانیه قبل از راه‌اندازی مجدد...")
                time.sleep(delay)
                
                # راه‌اندازی مجدد ربات
                bot_process = restart_bot(bot_process)
            else:
                # ربات در حال اجراست، ریست کردن شمارنده خطاها
                consecutive_failures = 0
            
            # انتظار کوتاه قبل از بررسی مجدد
            time.sleep(5)
                
        except KeyboardInterrupt:
            # توقف توسط کاربر
            logger.info("سرور توسط کاربر متوقف شد")
            is_running = False
            stop_bot(bot_process)
            break
            
        except Exception as e:
            # خطا در نظارت
            logger.error(f"خطا در نظارت بر ربات: {str(e)}")
            time.sleep(10)  # تاخیر بیشتر در صورت خطا
    
    logger.info("سرور مدیریت ربات متوقف شد")

def parse_arguments():
    """پردازش آرگومان‌های خط فرمان"""
    parser = argparse.ArgumentParser(description='سرور مدیریت ربات تلگرام')
    parser.add_argument('action', choices=['start', 'stop', 'restart'], 
                        help='عملیات مورد نظر: start (شروع), stop (توقف), restart (راه‌اندازی مجدد)')
    
    return parser.parse_args()

def main():
    """تابع اصلی"""
    args = parse_arguments()
    
    if args.action == 'start':
        # راه‌اندازی سرور
        start_server()
    elif args.action == 'stop':
        # توقف سرور (ارسال سیگنال SIGTERM به پروسه سرور)
        # این حالت واقعا در این اسکریپت کار نمی‌کند، نیاز به پیاده‌سازی پیشرفته‌تر دارد
        logger.warning("عملیات 'stop' به طور مستقیم پشتیبانی نمی‌شود. از CTRL+C برای توقف استفاده کنید.")
    elif args.action == 'restart':
        # راه‌اندازی مجدد سرور (توقف و راه‌اندازی مجدد)
        # این حالت واقعا در این اسکریپت کار نمی‌کند، نیاز به پیاده‌سازی پیشرفته‌تر دارد
        logger.warning("عملیات 'restart' به طور مستقیم پشتیبانی نمی‌شود. ربات را متوقف و مجددا اجرا کنید.")

if __name__ == "__main__":
    # متغیرهای سراسری
    bot_process = None
    is_running = False
    
    main() 