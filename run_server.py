#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
اسکریپت اجرای ربات در محیط سرور با قابلیت‌های پیشرفته:
- مدیریت پروسه
- اجرای دوباره خودکار در صورت خطا
- ذخیره لاگ‌ها
- نظارت بر منابع سیستم
- چرخش خودکار فایل‌های لاگ
- پاکسازی خودکار نسخه‌های پشتیبان قدیمی
"""

import os
import sys
import time
import signal
import psutil
import logging
import subprocess
import shutil
import argparse
import json
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta

# تنظیم لاگ
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_LEVEL = logging.INFO
LOG_FILE = "logs/server_manager.log"
LOG_MAX_SIZE = 10 * 1024 * 1024  # 10 مگابایت
LOG_BACKUP_COUNT = 5  # تعداد فایل‌های پشتیبان لاگ

# تنظیمات
MAX_RETRIES = 5  # حداکثر تلاش‌های مجدد در صورت خطا
RETRY_DELAY = 10  # تاخیر بین هر تلاش مجدد (ثانیه)
MEMORY_THRESHOLD = 90  # درصد استفاده از حافظه برای هشدار
CPU_THRESHOLD = 80  # درصد استفاده از CPU برای هشدار
BACKUP_INTERVAL = 86400  # فاصله زمانی تهیه پشتیبان (ثانیه) - 1 روز
MAX_BACKUP_AGE_DAYS = 7  # حداکثر سن پشتیبان‌ها (روز)
HEALTH_CHECK_INTERVAL = 300  # فاصله زمانی بررسی سلامت (ثانیه)


class ServerManager:
    """کلاس مدیریت اجرای ربات در سرور"""
    
    def __init__(self, bot_args=None):
        self.setup_logging()
        self.process = None
        self.running = True
        self.retry_count = 0
        self.last_backup_time = time.time()
        self.last_health_check_time = time.time()
        self.bot_args = bot_args or []
        self.setup_signal_handlers()
        self.logger.info("مدیریت سرور راه‌اندازی شد")
        
    def setup_logging(self):
        """راه‌اندازی سیستم لاگ"""
        if not os.path.exists("logs"):
            os.makedirs("logs")
            
        self.logger = logging.getLogger("ServerManager")
        self.logger.setLevel(LOG_LEVEL)
        
        # تنظیم لاگ فایل با چرخش خودکار
        file_handler = RotatingFileHandler(
            LOG_FILE, 
            maxBytes=LOG_MAX_SIZE, 
            backupCount=LOG_BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        self.logger.addHandler(file_handler)
        
        # تنظیم لاگ کنسول
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        self.logger.addHandler(console_handler)
        
    def setup_signal_handlers(self):
        """تنظیم مدیریت سیگنال‌ها"""
        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)
        self.logger.info("مدیریت‌کننده سیگنال‌ها راه‌اندازی شد")
        
    def handle_exit(self, signum, frame):
        """مدیریت سیگنال‌های خروج"""
        signals = {
            signal.SIGINT: "SIGINT",
            signal.SIGTERM: "SIGTERM"
        }
        self.logger.info(f"سیگنال {signals.get(signum, signum)} دریافت شد. در حال خروج...")
        self.running = False
        if self.process and self.process.poll() is None:
            self.logger.info("در حال توقف مناسب ربات...")
            try:
                self.process.terminate()
                # صبر برای توقف مناسب
                for _ in range(10):  # 10 ثانیه مهلت
                    if self.process.poll() is not None:
                        break
                    time.sleep(1)
                # اگر هنوز متوقف نشده، با زور متوقف کن
                if self.process.poll() is None:
                    self.logger.warning("ربات به درخواست توقف پاسخ نداد. اجبار به توقف...")
                    self.process.kill()
            except Exception as e:
                self.logger.error(f"خطا در توقف ربات: {e}")
        self.logger.info("فرایند ربات متوقف شد")
        sys.exit(0)
        
    def create_backup(self):
        """ایجاد نسخه پشتیبان از فایل‌های مهم"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = f"backups/backup_{timestamp}"
            
            if not os.path.exists("backups"):
                os.makedirs("backups")
                
            os.makedirs(backup_dir)
            
            # کپی فایل‌های مهم
            important_files = ["channel_stats.json", "config.json", "data.db"]
            for file in important_files:
                if os.path.exists(file):
                    shutil.copy2(file, f"{backup_dir}/{file}")
                    
            # کپی لاگ‌ها
            if os.path.exists("logs"):
                shutil.copytree("logs", f"{backup_dir}/logs", dirs_exist_ok=True)
                
            self.logger.info(f"نسخه پشتیبان با موفقیت در {backup_dir} ایجاد شد")
            self.last_backup_time = time.time()
            
            # پاکسازی پشتیبان‌های قدیمی
            self.cleanup_old_backups()
            
        except Exception as e:
            self.logger.error(f"خطا در ایجاد نسخه پشتیبان: {e}")
    
    def cleanup_old_backups(self):
        """پاکسازی پشتیبان‌های قدیمی"""
        try:
            if not os.path.exists("backups"):
                return
                
            now = datetime.now()
            cutoff_date = now - timedelta(days=MAX_BACKUP_AGE_DAYS)
            
            for backup_dir in os.listdir("backups"):
                try:
                    backup_path = os.path.join("backups", backup_dir)
                    if not os.path.isdir(backup_path) or not backup_dir.startswith("backup_"):
                        continue
                        
                    # استخراج تاریخ از نام پوشه
                    date_str = backup_dir.replace("backup_", "")[:8]  # فرمت YYYYMMDD
                    backup_date = datetime.strptime(date_str, "%Y%m%d")
                    
                    if backup_date < cutoff_date:
                        self.logger.info(f"حذف پشتیبان قدیمی: {backup_dir}")
                        shutil.rmtree(backup_path)
                except Exception as e:
                    self.logger.error(f"خطا در بررسی پشتیبان {backup_dir}: {e}")
        except Exception as e:
            self.logger.error(f"خطا در پاکسازی پشتیبان‌های قدیمی: {e}")
            
    def monitor_resources(self):
        """نظارت بر منابع سیستم"""
        try:
            # بررسی حافظه
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_usage_mb = memory.used / (1024 * 1024)  # تبدیل به مگابایت
            
            # بررسی CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # بررسی دیسک
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            disk_free_gb = disk.free / (1024 * 1024 * 1024)  # تبدیل به گیگابایت
            
            # نمایش مصرف منابع
            self.logger.info(f"مصرف منابع: RAM: {memory_percent}% ({memory_usage_mb:.1f} MB), "
                           f"CPU: {cpu_percent}%, دیسک: {disk_percent}% (فضای آزاد: {disk_free_gb:.1f} GB)")
            
            # هشدار در صورت افزایش مصرف
            if memory_percent > MEMORY_THRESHOLD:
                self.logger.warning(f"هشدار! مصرف حافظه بالا: {memory_percent}%")
                
            if cpu_percent > CPU_THRESHOLD:
                self.logger.warning(f"هشدار! مصرف CPU بالا: {cpu_percent}%")
                
            if disk_percent > 90:
                self.logger.warning(f"هشدار! فضای دیسک پر شده: {disk_percent}%")
            
            # ذخیره آمار منابع
            self.save_resource_stats(memory_percent, cpu_percent, disk_percent)
                
        except Exception as e:
            self.logger.error(f"خطا در نظارت بر منابع: {e}")
    
    def save_resource_stats(self, memory_percent, cpu_percent, disk_percent):
        """ذخیره آمار منابع برای تجزیه و تحلیل"""
        try:
            stats_dir = "stats"
            if not os.path.exists(stats_dir):
                os.makedirs(stats_dir)
                
            stats_file = os.path.join(stats_dir, "resource_stats.json")
            timestamp = datetime.now().isoformat()
            
            stats_data = {
                "timestamp": timestamp,
                "memory_percent": memory_percent,
                "cpu_percent": cpu_percent,
                "disk_percent": disk_percent
            }
            
            # خواندن داده‌های موجود
            existing_data = []
            if os.path.exists(stats_file):
                try:
                    with open(stats_file, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                except Exception:
                    pass
            
            # محدود کردن تعداد رکوردها به 1000 مورد آخر
            existing_data.append(stats_data)
            if len(existing_data) > 1000:
                existing_data = existing_data[-1000:]
                
            # ذخیره داده‌ها
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            self.logger.error(f"خطا در ذخیره آمار منابع: {e}")
    
    def health_check(self):
        """بررسی سلامت ربات و سیستم"""
        try:
            # بررسی وضعیت پروسه
            if self.process and self.process.poll() is None:
                # بررسی مصرف منابع پروسه
                try:
                    p = psutil.Process(self.process.pid)
                    process_memory = p.memory_info().rss / (1024 * 1024)  # مگابایت
                    process_cpu = p.cpu_percent(interval=0.5)
                    
                    self.logger.info(f"وضعیت ربات - PID: {self.process.pid}, "
                                   f"مصرف حافظه: {process_memory:.1f} MB, "
                                   f"مصرف CPU: {process_cpu:.1f}%")
                    
                    # بررسی نشت حافظه
                    if process_memory > 500:  # بیش از 500 مگابایت
                        self.logger.warning(f"هشدار! مصرف حافظه ربات بالاست: {process_memory:.1f} MB")
                        
                except Exception as e:
                    self.logger.error(f"خطا در بررسی وضعیت پروسه: {e}")
            
            # بررسی فضای لاگ
            if os.path.exists(LOG_FILE):
                log_size_mb = os.path.getsize(LOG_FILE) / (1024 * 1024)
                self.logger.info(f"اندازه فایل لاگ: {log_size_mb:.2f} MB")
                
        except Exception as e:
            self.logger.error(f"خطا در بررسی سلامت: {e}")
            
    def run_bot(self):
        """اجرای ربات"""
        try:
            self.logger.info("در حال اجرای ربات...")
            
            # ساخت دستور اجرای ربات
            cmd = ["python", "bot.py"]
            if "--server-mode" not in self.bot_args:
                cmd.append("--server-mode")
            
            # اضافه کردن پارامترهای اضافی
            cmd.extend(self.bot_args)
            
            self.logger.info(f"دستور اجرا: {' '.join(cmd)}")
            
            # اجرای ربات در حالت سرور
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            self.logger.info(f"ربات اجرا شد با PID: {self.process.pid}")
            self.retry_count = 0
            
            # آغاز پردازش خروجی استاندارد و خطا در پس‌زمینه
            self.start_output_processing()
            
            # انتظار برای پایان ربات
            return_code = self.process.wait()
            
            if return_code != 0 and self.running:
                self.logger.error(f"ربات با کد خطای {return_code} خارج شد")
                return False
            else:
                self.logger.info("ربات با موفقیت پایان یافت")
                return True
                
        except Exception as e:
            self.logger.error(f"خطا در اجرای ربات: {e}")
            return False
    
    def start_output_processing(self):
        """پردازش خروجی ربات در پس‌زمینه"""
        import threading
        
        def process_output(stream, log_level):
            for line in stream:
                line = line.strip()
                if line:
                    if log_level == logging.INFO:
                        self.logger.info(f"ربات: {line}")
                    else:
                        self.logger.error(f"ربات (خطا): {line}")
        
        if self.process:
            # پردازش خروجی استاندارد
            stdout_thread = threading.Thread(
                target=process_output,
                args=(self.process.stdout, logging.INFO)
            )
            stdout_thread.daemon = True
            stdout_thread.start()
            
            # پردازش خروجی خطا
            stderr_thread = threading.Thread(
                target=process_output,
                args=(self.process.stderr, logging.ERROR)
            )
            stderr_thread.daemon = True
            stderr_thread.start()
            
    def run(self):
        """اجرای اصلی برنامه مدیریت سرور"""
        self.logger.info("آغاز اجرای مدیر سرور...")
        
        while self.running:
            # بررسی نیاز به تهیه نسخه پشتیبان
            if time.time() - self.last_backup_time > BACKUP_INTERVAL:
                self.create_backup()
            
            # بررسی نیاز به بررسی سلامت
            current_time = time.time()
            if current_time - self.last_health_check_time > HEALTH_CHECK_INTERVAL:
                self.health_check()
                self.last_health_check_time = current_time
                
            # نظارت بر منابع
            self.monitor_resources()
            
            # اجرای ربات
            success = self.run_bot()
            
            # مدیریت خطا و اجرای مجدد
            if not success and self.running:
                self.retry_count += 1
                if self.retry_count <= MAX_RETRIES or MAX_RETRIES <= 0:  # اگر MAX_RETRIES <= 0 باشد، بی‌نهایت تلاش مجدد
                    retry_msg = f"تلاش مجدد {self.retry_count}"
                    if MAX_RETRIES > 0:
                        retry_msg += f"/{MAX_RETRIES}"
                    self.logger.warning(f"{retry_msg} بعد از {RETRY_DELAY} ثانیه...")
                    time.sleep(RETRY_DELAY)
                else:
                    self.logger.error(f"تعداد تلاش‌های مجدد به حداکثر رسید ({MAX_RETRIES}). خروج...")
                    break
                    
        self.logger.info("مدیر سرور با موفقیت پایان یافت")


def parse_arguments():
    """تجزیه آرگومان‌های خط فرمان"""
    parser = argparse.ArgumentParser(description="مدیریت اجرای ربات در محیط سرور")
    
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES,
                       help=f"حداکثر تعداد تلاش‌های مجدد (پیش‌فرض: {MAX_RETRIES})")
    
    parser.add_argument("--retry-delay", type=int, default=RETRY_DELAY,
                       help=f"تاخیر بین تلاش‌های مجدد به ثانیه (پیش‌فرض: {RETRY_DELAY})")
    
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                       default="INFO", help="سطح لاگ (پیش‌فرض: INFO)")
    
    parser.add_argument("--backup-interval", type=int, default=BACKUP_INTERVAL // 3600,
                       help=f"فاصله زمانی تهیه پشتیبان به ساعت (پیش‌فرض: {BACKUP_INTERVAL // 3600})")
    
    parser.add_argument("--bot-args", type=str, default="",
                       help="آرگومان‌های اضافی برای ارسال به ربات (با نقل قول)")
    
    args = parser.parse_args()
    
    # تنظیم متغیرهای سراسری بر اساس آرگومان‌ها
    global MAX_RETRIES, RETRY_DELAY, LOG_LEVEL, BACKUP_INTERVAL
    MAX_RETRIES = args.max_retries
    RETRY_DELAY = args.retry_delay
    LOG_LEVEL = getattr(logging, args.log_level)
    BACKUP_INTERVAL = args.backup_interval * 3600
    
    # تجزیه آرگومان‌های ربات
    bot_args = []
    if args.bot_args:
        import shlex
        bot_args = shlex.split(args.bot_args)
        
    return bot_args
    

if __name__ == "__main__":
    bot_args = parse_arguments()
    manager = ServerManager(bot_args)
    manager.run() 