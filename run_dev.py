#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
اسکریپت اجرای ربات در محیط توسعه
"""

import os
import subprocess
import logging

# تنظیم لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    """اجرای ربات در محیط توسعه"""
    logger.info("شروع اجرای ربات در محیط توسعه...")
    
    # ایجاد پوشه logs اگر وجود نداشته باشد
    if not os.path.exists("logs"):
        os.makedirs("logs")
        logger.info("پوشه logs ایجاد شد")
    
    try:
        # اجرای فایل bot.py
        logger.info("اجرای ربات...")
        subprocess.run(["python", "bot.py"], check=True)
    except KeyboardInterrupt:
        logger.info("ربات با دستور کاربر متوقف شد")
    except subprocess.CalledProcessError as e:
        logger.error(f"خطا در اجرای ربات: {e}")
    except Exception as e:
        logger.error(f"خطای غیرمنتظره: {e}")
    
    logger.info("پایان اجرای برنامه")

if __name__ == "__main__":
    main() 