import telegram.error
import logging
import time
import asyncio
from telegram.ext import Application
from typing import Optional, Callable, Awaitable, Dict, Any

# راه‌اندازی لاگر
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self, token: str, persistence_path: Optional[str] = None):
        """
        مدیریت اتصال به API تلگرام
        
        Args:
            token: توکن ربات تلگرام
            persistence_path: مسیر فایل ذخیره‌سازی وضعیت (اختیاری)
        """
        self.token = token
        self.persistence_path = persistence_path
        self.application = None
        self.connection_status = {
            "is_connected": False,
            "last_connected": None,
            "last_disconnect": None,
            "reconnect_attempts": 0,
            "connection_errors": []
        }
        
    def build_application(self) -> Application:
        """ساخت و پیکربندی نمونه Application"""
        builder = Application.builder().token(self.token)
        
        # افزودن persistence در صورت نیاز
        if self.persistence_path:
            from telegram.ext import PicklePersistence
            persistence = PicklePersistence(filepath=self.persistence_path)
            builder = builder.persistence(persistence)
        
        # تنظیم timeoutها برای ارتباط پایدار
        builder = builder.read_timeout(60).write_timeout(60).connect_timeout(60)
        
        self.application = builder.build()
        return self.application
    
    async def start_polling(self, 
                           setup_handlers_func: Callable[[Application], Awaitable[None]],
                           post_startup_func: Optional[Callable[[], Awaitable[None]]] = None):
        """
        شروع پردازش ربات بدون پیچیدگی اتصال مجدد
        
        Args:
            setup_handlers_func: تابعی برای تنظیم هندلرها
            post_startup_func: تابعی که بعد از راه‌اندازی اجرا می‌شود
        """
        # ساخت application اگر قبلاً ساخته نشده
        if not self.application:
            self.application = self.build_application()
        
        # تنظیم هندلرها
        await setup_handlers_func(self.application)
        
        logger.info("ربات در حال راه‌اندازی...")
        
        # به‌روزرسانی وضعیت اتصال
        self.connection_status["is_connected"] = True
        self.connection_status["last_connected"] = time.time()
        
        # اگر تابع پس از راه‌اندازی وجود دارد، اجرا می‌کنیم
        if post_startup_func:
            await post_startup_func()
        
        logger.info("ربات با موفقیت راه‌اندازی شد!")
        
        # شروع کار ربات
        await self.application.run_polling(drop_pending_updates=True)
    
    async def shutdown(self):
        """خاموش کردن برنامه"""
        if not self.application:
            return
        
        try:
            # به‌روزرسانی وضعیت اتصال
            self.connection_status["is_connected"] = False
            self.connection_status["last_disconnect"] = time.time()
            
            await self.application.stop()
            await self.application.shutdown()
            
            logger.info("ربات با موفقیت متوقف شد.")
        except Exception as e:
            logger.error(f"خطا در خاموش کردن برنامه: {str(e)}")
        finally:
            self.application = None
    
    def get_connection_status(self) -> Dict[str, Any]:
        """دریافت وضعیت فعلی اتصال"""
        return self.connection_status 
