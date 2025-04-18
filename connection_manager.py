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
        مدیریت اتصال و اتصال مجدد خودکار به API تلگرام
        
        Args:
            token: توکن ربات تلگرام
            persistence_path: مسیر فایل ذخیره‌سازی وضعیت (اختیاری)
        """
        self.token = token
        self.persistence_path = persistence_path
        self.application = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = float('inf')  # بی‌نهایت تلاش برای اتصال مجدد
        self.reconnect_delay = 5  # تاخیر اولیه بین تلاش‌های اتصال مجدد (ثانیه)
        self.max_reconnect_delay = 300  # حداکثر تاخیر بین تلاش‌ها (5 دقیقه)
        self.connection_status = {
            "is_connected": False,
            "last_connected": None,
            "last_disconnect": None,
            "reconnect_attempts": 0,
            "connection_errors": []
        }
        
    async def initialize_application(self) -> Application:
        """راه‌اندازی و پیکربندی نمونه Application"""
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
                           pre_shutdown_func: Optional[Callable[[], Awaitable[None]]] = None,
                           post_startup_func: Optional[Callable[[], Awaitable[None]]] = None):
        """
        شروع پردازش با قابلیت اتصال مجدد خودکار
        
        Args:
            setup_handlers_func: تابعی برای تنظیم هندلرها
            pre_shutdown_func: تابعی که قبل از خاموش شدن اجرا می‌شود
            post_startup_func: تابعی که بعد از راه‌اندازی اجرا می‌شود
        """
        while True:
            try:
                if not self.application:
                    self.application = await self.initialize_application()
                
                # تنظیم هندلرها
                await setup_handlers_func(self.application)
                
                logger.info("ربات در حال راه‌اندازی...")
                
                # به‌روزرسانی وضعیت اتصال
                self.connection_status["is_connected"] = True
                self.connection_status["last_connected"] = time.time()
                self.reconnect_attempts = 0
                
                # اجرای تابع پس از راه‌اندازی (قبل از شروع polling)
                if post_startup_func:
                    await post_startup_func()
                
                logger.info("ربات با موفقیت راه‌اندازی شد!")
                
                # استفاده از روش run_polling که در نسخه‌های جدید python-telegram-bot پشتیبانی می‌شود
                # تنظیم close_loop=False برای حفظ کنترل بر حلقه رویداد
                await self.application.run_polling(
                    drop_pending_updates=True,
                    close_loop=False,
                    stop_signals=None  # غیرفعال کردن توقف خودکار با سیگنال‌ها
                )
                
                # اگر به اینجا برسیم یعنی برنامه به طور عادی متوقف شده است
                # از حلقه خارج می‌شویم
                break
                
            except telegram.error.NetworkError as e:
                await self.handle_connection_error(e, "خطای شبکه")
                
            except telegram.error.TelegramError as e:
                await self.handle_connection_error(e, "خطای تلگرام")
                
            except Exception as e:
                logger.error(f"خطای غیرمنتظره: {str(e)}")
                
                # اگر برنامه در حال اجراست، آن را متوقف می‌کنیم
                if self.application:
                    if pre_shutdown_func:
                        await pre_shutdown_func()
                    await self.shutdown()
                
                # تلاش برای اتصال مجدد
                await self.handle_connection_error(e, "خطای غیرمنتظره")
    
    async def handle_connection_error(self, error: Exception, error_type: str):
        """مدیریت خطاهای اتصال و تلاش برای اتصال مجدد"""
        self.reconnect_attempts += 1
        self.connection_status["is_connected"] = False
        self.connection_status["last_disconnect"] = time.time()
        self.connection_status["reconnect_attempts"] = self.reconnect_attempts
        
        # ذخیره خطا در تاریخچه (حداکثر 10 خطای آخر)
        error_entry = {
            "time": time.time(),
            "type": error_type,
            "message": str(error)
        }
        self.connection_status["connection_errors"].append(error_entry)
        if len(self.connection_status["connection_errors"]) > 10:
            self.connection_status["connection_errors"].pop(0)
        
        # محاسبه تاخیر با استفاده از backoff نمایی
        delay = min(self.reconnect_delay * (2 ** (self.reconnect_attempts - 1)), self.max_reconnect_delay)
        
        logger.warning(f"اتصال قطع شد. نوع خطا: {error_type}, پیام: {str(error)}")
        logger.info(f"تلاش مجدد برای اتصال در {delay:.1f} ثانیه... (تلاش {self.reconnect_attempts})")
        
        # اگر برنامه هنوز اجرا می‌شود، آن را متوقف می‌کنیم
        if self.application:
            await self.shutdown()
        
        # صبر کردن قبل از تلاش مجدد
        await asyncio.sleep(delay)
    
    async def shutdown(self):
        """خاموش کردن برنامه"""
        if not self.application:
            return
        
        try:
            await self.application.stop()
            await self.application.shutdown()
        except Exception as e:
            logger.error(f"خطا در خاموش کردن برنامه: {str(e)}")
        finally:
            self.application = None
    
    def get_connection_status(self) -> Dict[str, Any]:
        """دریافت وضعیت فعلی اتصال"""
        return self.connection_status 
