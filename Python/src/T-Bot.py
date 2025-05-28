import sys
import json
import os
import requests
import telegram
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

# 将项目根目录添加到模块搜索路径
_project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(_project_root))
from utils.log_utils import LogUtils


# --------------------------
# 配置模块
# --------------------------
class Config:
    """全局配置类"""
    # 时间格式
    MESSAGE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
    INFO_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

    # 文件路径
    DEFAULT_DOWNLOAD_DIR = "../downloads"
    DEFAULT_OUTPUT_DIR = "../output"

    # Telegram配置
    TELEGRAM_LIMITS = {
        'images': 10 * 1024 * 1024,  # 10MB
        'videos': 50 * 1024 * 1024,  # 50MB
        'caption': 1024  # 消息截断长度
    }

    # 业务参数
    MAX_DOWNLOAD_ATTEMPTS = 10  # 重试次数
    ERROR_TRUNCATE = 50  # 错误信息截断长度
    NOTIFICATION_TRUNCATE = 200  # 通知消息截断长度

    @classmethod
    def get_env_vars(cls) -> Dict[str, str]:
        """环境变量获取"""
        return {
            'bot_token': os.getenv('BOT_TOKEN'),
            'chat_id': os.getenv('CHAT_ID'),
            'lark_key': os.getenv('LARK_KEY')
        }


# --------------------------
# 异常类
# --------------------------
class FileTooLargeError(Exception):
    """文件大小超过平台限制异常"""
    pass


class MaxAttemptsError(Exception):
    """达到最大尝试次数异常"""
    pass


# 引入日志模块
logger = LogUtils().get_logger()
logger.info("🔄 T-Bot 初始化完成")


# --------------------------
# 通知模块
# --------------------------
class Notifier:
    """通知处理器"""

    @staticmethod
    def send_lark_message(message: str) -> bool:
        """发送普通飞书消息"""
        lark_key = Config.get_env_vars()['lark_key']
        if not lark_key:
            return False

        webhook_url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{lark_key}"
        try:
            payload = {
                "msg_type": "text",
                "content": {"text": f"📢 动态更新\n{message}"}
            }
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("📨 飞书动态消息发送成功")
            return True
        except Exception as e:
            logger.error(f"✗ 飞书消息发送失败: {str(e)}")
            return False

    @staticmethod
    def send_lark_alert(message: str) -> bool:
        """发送飞书通知"""
        if not Config.get_env_vars()['lark_key']:
            return False

        # 消息截断
        truncated_msg = f"{message[:Config.NOTIFICATION_TRUNCATE]}..." if len(
            message) > Config.NOTIFICATION_TRUNCATE else message
        webhook_url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{Config.get_env_vars()['lark_key']}"

        try:
            payload = {
                "msg_type": "text",
                "content": {"text": f"📢 XT-Bot处理告警\n{truncated_msg}"}
            }
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("📨 飞书通知发送成功")
            return True
        except Exception as e:
            logger.error(f"✗ 飞书通知发送失败: {str(e)}")
            return False


# --------------------------
# 文件处理模块
# --------------------------
class FileProcessor:
    """文件处理器"""

    def __init__(self, json_path: str, download_dir: str):
        self.json_path = Path(json_path)
        self.download_path = Path(download_dir)
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """目录创建"""
        self.download_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"📂 下载目录已就绪: {self.download_path}")

    def load_data(self) -> List[Dict[str, Any]]:
        """加载JSON数据"""
        try:
            with self.json_path.open('r+', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"📄 已加载JSON数据，共{len(data)}条记录")
                return data
        except Exception as e:
            logger.error(f"✗ JSON文件加载失败: {str(e)}")
            raise

    def save_data(self, data: List[Dict[str, Any]]) -> None:
        """保存JSON数据"""
        try:
            with self.json_path.open('r+', encoding='utf-8') as f:
                f.seek(0)
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.truncate()
        except Exception as e:
            logger.error(f"✗ JSON保存失败: {str(e)}")
            raise


# --------------------------
# 下载模块
# --------------------------
class DownloadManager:
    """下载管理器"""

    @classmethod
    def process_item(cls, item: Dict[str, Any], processor: FileProcessor) -> None:
        """处理单个文件下载"""
        if item.get('is_downloaded'):
            return

        # 特殊类型处理
        if item.get('media_type') in ['spaces', 'broadcasts']:
            item.update({
                "is_downloaded": True,
                "download_info": {
                    "success": True,
                    "size": 0,
                    "size_mb": 0,
                    "timestamp": datetime.now().strftime(Config.INFO_DATE_FORMAT),
                    "download_attempts": 0
                }
            })
            logger.info(f"⏭ 跳过特殊类型下载: {item['file_name']}")
            return

        # 重试计数器位置
        download_info = item.setdefault('download_info', {})
        current_attempts = download_info.get('download_attempts', 0)

        if current_attempts >= Config.MAX_DOWNLOAD_ATTEMPTS:
            logger.warning(f"⏭ 已达最大下载尝试次数: {item['file_name']}")
            item['upload_info'] = cls._build_error_info(
                MaxAttemptsError("连续下载失败10次"),
                "max_download_attempts",
                existing_info=item.get('upload_info', {})
            )
            return

        try:
            logger.info(f"⏬ 开始下载: {item['file_name']}")
            response = requests.get(item['url'], stream=True, timeout=30)
            response.raise_for_status()

            file_path = processor.download_path / item['file_name']
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # 更新下载状态
            file_size = os.path.getsize(file_path)
            download_info.update({
                "success": True,
                "size": file_size,
                "size_mb": round(file_size / 1024 / 1024, 2),
                "timestamp": datetime.now().strftime(Config.INFO_DATE_FORMAT),
                "download_attempts": 0  # 重置计数器
            })
            item['is_downloaded'] = True
            logger.info(f"✓ 下载成功: {item['file_name']} ({file_size // 1024}KB)")

        except Exception as e:
            download_info['download_attempts'] = current_attempts + 1
            # error错误信息进行截取
            error_msg = f"✗ 下载失败: {item['file_name']} - {str(e)[:Config.ERROR_TRUNCATE]}"
            logger.error(error_msg)
            # debug查看完整的错误信息
            debug_msg = f"✗ 下载失败: {item['file_name']} - {str(e)}"
            logger.debug(debug_msg)

            if download_info['download_attempts'] >= Config.MAX_DOWNLOAD_ATTEMPTS:
                item['upload_info'] = {
                    "success": False,
                    "error_type": "max_download_attempts",
                    "message": str(e),
                    "timestamp": datetime.now().strftime(Config.INFO_DATE_FORMAT),
                    "notification_sent": False
                }

    @classmethod
    def _build_error_info(
            cls,
            error: Exception,
            error_type: str,
            existing_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """构建错误信息时保留原有 notification_sent 状态"""
        # 如果已有错误信息且包含时间戳，则复用
        if existing_info and "timestamp" in existing_info:
            timestamp = existing_info["timestamp"]
        else:
            timestamp = datetime.now().strftime(Config.INFO_DATE_FORMAT)
        # 如果已有信息，则继承 notification_sent，否则初始化为 False
        notification_sent = existing_info.get("notification_sent", False) if existing_info else False

        return {
            "success": False,
            "error_type": error_type,
            "message": str(error),
            "timestamp": timestamp,
            "notification_sent": notification_sent
        }


# --------------------------
# 上传模块
# --------------------------
class UploadManager:
    """上传管理器"""

    def __init__(self):
        env_vars = Config.get_env_vars()
        if not env_vars['bot_token'] or not env_vars['chat_id']:
            logger.error("❌ 必须配置 BOT_TOKEN 和 CHAT_ID 环境变量！")
            sys.exit(1)
        self.bot = telegram.Bot(token=env_vars['bot_token'])
        self.chat_id = env_vars['chat_id']

    def process_item(self, item: Dict[str, Any], processor: FileProcessor) -> None:
        """处理文件上传"""
        if not self._should_upload(item):
            return

        try:
            # 处理特殊类型
            if item.get('media_type') in ['spaces', 'broadcasts']:
                message_id = self._send_text_message(item)
            else:
                message_id = self._send_media_file(item, processor)

            # 更新上传状态
            item.update({
                "is_uploaded": True,
                "upload_info": self._build_success_info(message_id)
            })
        except Exception as e:
            self._handle_upload_error(e, item)

    def _should_upload(self, item: Dict[str, Any]) -> bool:
        """上传判断逻辑"""
        if item.get('is_uploaded'):
            return False
        # 检查不可恢复的错误
        upload_info = item.get('upload_info', {})
        error_type = upload_info.get('error_type')

        if error_type in ['file_too_large', 'max_download_attempts']:
            # 判断通知标识
            if not upload_info.get('notification_sent'):
                # 发送告警信息
                self._send_unrecoverable_alert(item, error_type)
                # 标记已通知
                upload_info['notification_sent'] = True
            logger.warning(f"⏭ 跳过不可恢复的错误: {item['file_name']} ({error_type})")
            return False
        # 特殊类型直接上传
        if item.get('media_type') in ['spaces', 'broadcasts']:
            return True
        # 常规类型需要下载成功
        return item.get('is_downloaded', False)

    def _send_unrecoverable_alert(self, item: Dict[str, Any], error_type: str) -> None:
        """发送不可恢复错误通知"""
        alert_msg = (
            "🔴 推送失败\n"
            f"文件名: {item['file_name']}\n"
            f"类型: {error_type}\n"
            # 截取错误信息
            f"错误: {item['upload_info']['message'][:Config.ERROR_TRUNCATE]}"
        )
        Notifier.send_lark_alert(alert_msg)

    def _send_text_message(self, item: Dict[str, Any]) -> int:
        """发送文本消息到 Telegram 和飞书"""
        # 生成基础文本
        screen_name = item['user']['screen_name']
        media_type = item['media_type']
        publish_time = datetime.fromisoformat(item['publish_time']).strftime(Config.MESSAGE_DATE_FORMAT)
        url = item['url']
        base_text = f"#{screen_name} #{media_type}\n{publish_time}\n{url}"

        # 截断逻辑
        max_length = Config.TELEGRAM_LIMITS['caption']
        if len(base_text) > max_length:
            truncated = base_text[:max_length - 3] + "..."
        else:
            truncated = base_text

        # 发送到 Telegram
        msg = self.bot.send_message(chat_id=self.chat_id, text=truncated)
        logger.info(f"✓ 文本消息已发送: {msg.message_id}")

        # 同时发送到飞书（如果配置）
        if Config.get_env_vars()['lark_key']:
            success = Notifier.send_lark_message(truncated)
            if success:
                logger.info(f"✓ 动态消息已同步至飞书")
        return msg.message_id

    def _send_media_file(self, item: Dict[str, Any], processor: FileProcessor) -> int:
        """发送媒体文件"""
        file_path = processor.download_path / item['file_name']
        caption = self._build_caption(item)

        # 文件大小校验
        media_type = 'images' if item['media_type'] == 'images' else 'videos'
        file_size = os.path.getsize(file_path)
        if file_size > Config.TELEGRAM_LIMITS[media_type]:
            raise FileTooLargeError(
                f"{media_type}大小超标 ({file_size // 1024 // 1024}MB > {Config.TELEGRAM_LIMITS[media_type] // 1024 // 1024}MB)"
            )

        with open(file_path, 'rb') as f:
            if media_type == 'images':
                msg = self.bot.send_photo(chat_id=self.chat_id, photo=f, caption=caption)
            else:
                msg = self.bot.send_video(chat_id=self.chat_id, video=f, caption=caption)

        logger.info(f"✓ 媒体文件已上传: {msg.message_id}")
        return msg.message_id

    def _build_caption(self, item: Dict[str, Any]) -> str:
        """构建caption"""
        user_info = f"#{item['user']['screen_name']} {item['user']['name']}"
        publish_time = datetime.fromisoformat(item['publish_time']).strftime(Config.MESSAGE_DATE_FORMAT)
        base_info = f"{user_info}\n{publish_time}"
        remaining = Config.TELEGRAM_LIMITS['caption'] - len(base_info) - 1

        # 截断逻辑
        text = item['full_text']
        if len(text) > remaining:
            truncated = text[:remaining - 3] + "..."
        else:
            truncated = text

        return f"{base_info}\n{truncated}"

    @staticmethod
    def _build_success_info(message_id: int) -> Dict[str, Any]:
        """包含消息ID的上传成功信息"""
        return {
            "success": True,
            "message_id": message_id,
            "timestamp": datetime.now().strftime(Config.INFO_DATE_FORMAT)
        }

    def _handle_upload_error(self, error: Exception, item: Dict[str, Any]) -> None:
        """错误处理"""
        # 错误类型判断
        if isinstance(error, FileTooLargeError):
            error_type = 'file_too_large'
        else:
            error_type = 'api_error'
            # 其他错误类型直接通知（无标记检查）
            Notifier.send_lark_alert(
                f"🔴 上传失败\n文件名: {item['file_name']}\n"
                f"错误类型: {error.__class__.__name__}\n"
                f"错误详情: {str(error)[:Config.ERROR_TRUNCATE]}"
            )

        # 更新错误信息
        item['upload_info'] = self._build_error_info(error, error_type)

        # 重置下载状态（允许重试）
        item['is_downloaded'] = False
        # error错误信息进行截取
        error_msg = f"✗ 上传失败: {item['file_name']} - {str(error)[:Config.ERROR_TRUNCATE]}"
        logger.error(error_msg)
        # debug查看完整的错误信息
        debug_msg = f"✗ 上传失败: {item['file_name']} - {str(error)}"
        logger.debug(debug_msg)

    @staticmethod
    def _build_error_info(error: Exception, error_type: str) -> Dict[str, Any]:
        """构建错误信息"""
        return {
            "success": False,
            "error_type": error_type,
            "message": str(error),
            "timestamp": datetime.now().strftime(Config.INFO_DATE_FORMAT),
            "notification_sent": False
        }


# --------------------------
# 主流程
# --------------------------
def process_single(json_path: str, download_dir: str = Config.DEFAULT_DOWNLOAD_DIR) -> None:
    """处理单个文件"""
    try:
        logger.info(f"\n{'-' * 40}\n🔍 开始处理: {json_path}")
        processor = FileProcessor(json_path, download_dir)
        data = processor.load_data()

        download_manager = DownloadManager()
        upload_manager = UploadManager()

        for item in data:
            # 处理顺序：先下载再上传
            if not item.get('is_downloaded'):
                download_manager.process_item(item, processor)

            if not item.get('is_uploaded'):
                upload_manager.process_item(item, processor)

        processor.save_data(data)
        logger.info(f"✅ 文件处理完成\n{'-' * 40}\n")

    except Exception as e:
        logger.error(f"💥 处理异常: {str(e)}", exc_info=True)
        Notifier.send_lark_alert(f"处理异常: {str(e)[:Config.NOTIFICATION_TRUNCATE]}")
        raise


def batch_process(days: int = 7) -> None:
    """批量处理"""
    base_dir = Path(Config.DEFAULT_OUTPUT_DIR)
    for i in range(days, -1, -1):  # 倒序处理
        target_date = datetime.now() - timedelta(days=i)
        date_str = target_date.strftime("%Y-%m-%d")
        json_path = base_dir / f"{date_str[:7]}/{date_str}.json"

        if json_path.exists():
            process_single(str(json_path))
        else:
            logger.info(f"⏭ 跳过不存在文件: {json_path}")


def main():
    args = sys.argv[1:]  # 获取命令行参数

    if len(args) == 2:
        process_single(args[0], args[1])
    elif len(args) == 1:
        process_single(args[0])
    elif len(args) == 0:
        batch_process()
    else:
        logger.error("错误：参数数量不正确。")
        logger.error("使用方法：python T-Bot.py [<JSON文件路径> <下载目录>]")
        logger.error("示例：")
        logger.error("使用参数：python T-Bot.py ../output/2000-01/2000-01-01.json ../downloads(默认)")
        logger.error("使用默认：python T-Bot.py")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
        logger.info("🏁 所有处理任务已完成！")
    except KeyboardInterrupt:
        logger.warning("⏹️ 用户中断操作")
        sys.exit(0)
    except Exception as e:
        logger.error(f"💥 未处理的异常: {str(e)}")
        sys.exit(1)
