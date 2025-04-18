import psutil
import platform
import time
import datetime
import sqlite3
import os
from typing import Dict, Any

class ServerMonitor:
    def __init__(self):
        self.start_time = time.time()
    
    def get_uptime(self) -> str:
        """محاسبه زمان فعالیت ربات"""
        uptime_seconds = time.time() - self.start_time
        uptime = datetime.timedelta(seconds=int(uptime_seconds))
        return str(uptime)
    
    def get_memory_usage(self) -> Dict[str, float]:
        """دریافت میزان استفاده از حافظه"""
        memory = psutil.virtual_memory()
        return {
            "total_gb": round(memory.total / (1024 ** 3), 2),
            "used_gb": round(memory.used / (1024 ** 3), 2),
            "percent": memory.percent
        }
    
    def get_cpu_usage(self) -> float:
        """دریافت میزان استفاده از پردازنده"""
        return psutil.cpu_percent(interval=1)
    
    def get_system_info(self) -> Dict[str, str]:
        """دریافت اطلاعات سیستم"""
        return {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor()
        }
    
    def get_disk_usage(self) -> Dict[str, float]:
        """دریافت میزان استفاده از دیسک"""
        disk = psutil.disk_usage('/')
        return {
            "total_gb": round(disk.total / (1024 ** 3), 2),
            "used_gb": round(disk.used / (1024 ** 3), 2),
            "percent": disk.percent
        }
    
    def get_database_stats(self) -> Dict[str, int]:
        """دریافت آمار دیتابیس"""
        if not os.path.exists('bot_database.db'):
            return {"users": 0, "groups": 0, "channels": 0, "db_size_mb": 0}
        
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        
        try:
            users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            groups = c.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
            channels = c.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
            
            # محاسبه حجم دیتابیس
            db_size = os.path.getsize('bot_database.db') / (1024 ** 2)  # MB
            
            return {
                "users": users,
                "groups": groups,
                "channels": channels,
                "db_size_mb": round(db_size, 2)
            }
        except Exception as e:
            print(f"Error getting database stats: {str(e)}")
            return {"users": 0, "groups": 0, "channels": 0, "db_size_mb": 0}
        finally:
            conn.close()
    
    def get_server_status(self) -> Dict[str, Any]:
        """دریافت کامل وضعیت سرور"""
        return {
            "uptime": self.get_uptime(),
            "memory": self.get_memory_usage(),
            "cpu": self.get_cpu_usage(),
            "disk": self.get_disk_usage(),
            "system": self.get_system_info(),
            "database": self.get_database_stats()
        }
    
    def format_status_message(self) -> str:
        """فرمت‌دهی پیام وضعیت سرور"""
        status = self.get_server_status()
        
        message = "📊 وضعیت سرور و ربات:\n\n"
        
        # زمان فعالیت
        message += f"⏱ زمان فعالیت: {status['uptime']}\n\n"
        
        # اطلاعات سیستم
        message += "💻 اطلاعات سیستم:\n"
        message += f"├ سیستم‌عامل: {status['system']['system']} {status['system']['release']}\n"
        message += f"└ معماری: {status['system']['machine']}\n\n"
        
        # استفاده از منابع
        message += "🔧 استفاده از منابع:\n"
        message += f"├ CPU: {status['cpu']}%\n"
        message += f"├ رم: {status['memory']['used_gb']}/{status['memory']['total_gb']} GB ({status['memory']['percent']}%)\n"
        message += f"└ دیسک: {status['disk']['used_gb']}/{status['disk']['total_gb']} GB ({status['disk']['percent']}%)\n\n"
        
        # آمار دیتابیس
        message += "🗃 آمار دیتابیس:\n"
        message += f"├ کاربران: {status['database']['users']}\n"
        message += f"├ گروه‌ها: {status['database']['groups']}\n"
        message += f"├ کانال‌ها: {status['database']['channels']}\n"
        message += f"└ حجم دیتابیس: {status['database']['db_size_mb']} MB\n"
        
        return message 
