import sys
import json
import os
import requests
import telegram
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, DefaultDict
from collections import defaultdict

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
        'caption': 1024,  # 消息截断长度
        'media_group': 10,  # 媒体分组最多文件数
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
        # 处理特殊类型（spaces/broadcasts）直接返回
        if cls._is_special_type(item):
            cls._handle_special_type(item)
            return

        # 如果已下载或达到最大尝试次数，直接返回
        if cls._should_skip_download(item):
            return

        # 执行下载操作
        try:
            logger.info(f"⏬ 开始下载: {item['file_name']}")
            file_path = cls._download_file(item, processor)

            # 处理下载成功
            size_mb = cls._handle_download_success(item, file_path)
            logger.info(f"✓ 下载成功: {item['file_name']} ({size_mb}MB)")

        except Exception as e:
            # 处理下载失败
            cls._handle_download_failure(item, e)

    @classmethod
    def _is_special_type(cls, item: Dict[str, Any]) -> bool:
        """检查是否为特殊类型（spaces/broadcasts）"""
        return item.get('media_type') in ['spaces', 'broadcasts']

    @classmethod
    def _handle_special_type(cls, item: Dict[str, Any]) -> None:
        """处理特殊类型项"""
        if item.get('is_downloaded'):
            return

        item.update({
            "is_downloaded": True,
            "download_info": {
                "success": True,
                "size_mb": 0,
                "timestamp": datetime.now().strftime(Config.INFO_DATE_FORMAT),
                "download_attempts": 0
            }
        })
        logger.info(f"⏭ 跳过特殊类型下载: {item['file_name']}")

    @classmethod
    def _should_skip_download(cls, item: Dict[str, Any]) -> bool:
        """检查是否应该跳过下载"""
        # 已下载的直接跳过
        if item.get('is_downloaded'):
            return True

        download_info = item.setdefault('download_info', {})
        current_attempts = download_info.get('download_attempts', 0)

        # 达到最大尝试次数
        if current_attempts >= Config.MAX_DOWNLOAD_ATTEMPTS:
            # 达到最大尝试次数
            cls._handle_max_attempts(item)
            return True

        return False

    @classmethod
    def _download_file(cls, item: Dict[str, Any], processor: FileProcessor) -> Path:
        """执行文件下载操作"""
        response = requests.get(item['url'], stream=True, timeout=30)
        response.raise_for_status()

        file_path = processor.download_path / item['file_name']
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return file_path

    @classmethod
    def _handle_download_success(cls, item: Dict[str, Any], file_path: Path) -> float:
        """处理下载成功的情况，返回文件大小（MB）"""
        file_size = os.path.getsize(file_path)
        size_mb = round(file_size / 1024 / 1024, 2)

        item.update({
            "is_downloaded": True,
            "download_info": {
                "success": True,
                "size_mb": size_mb,
                "timestamp": datetime.now().strftime(Config.INFO_DATE_FORMAT),
                "download_attempts": 0  # 重置计数器
            }
        })
        return size_mb

    @classmethod
    def _handle_download_failure(cls, item: Dict[str, Any], error: Exception) -> None:
        """处理下载失败的情况"""
        download_info = item.setdefault('download_info', {})
        current_attempts = download_info.get('download_attempts', 0)
        new_attempts = current_attempts + 1

        # 更新下载信息
        download_info.update({
            "success": False,
            "error_type": "download_error",
            "message": str(error),
            "timestamp": datetime.now().strftime(Config.INFO_DATE_FORMAT),
            "download_attempts": new_attempts
        })

        # 错误日志
        truncated_error = str(error)[:Config.ERROR_TRUNCATE]
        error_msg = f"✗ 下载失败: {item['file_name']} - {truncated_error} (尝试 {new_attempts}/{Config.MAX_DOWNLOAD_ATTEMPTS})"
        logger.error(error_msg)

        # 调试日志
        logger.debug(f"✗ 下载失败详情: {item['file_name']} - {str(error)}")

    @classmethod
    def _handle_max_attempts(cls, item: Dict[str, Any]) -> None:
        """处理达到最大尝试次数的情况"""
        # 准备要设置的默认值
        new_info = {
            "success": False,
            "error_type": "max_download_attempts",
            "message": "连续下载失败10次",
            "notification_sent": False
        }

        # 如果已有upload_info，复用其中的某些字段
        if 'upload_info' in item and isinstance(item['upload_info'], dict):
            existing_info = item['upload_info']

            # 保留已有的时间戳（如果有）
            if 'timestamp' in existing_info:
                new_info['timestamp'] = existing_info['timestamp']
            else:
                new_info['timestamp'] = datetime.now().strftime(Config.INFO_DATE_FORMAT)

            # 保留已有的通知状态（如果有）
            if 'notification_sent' in existing_info:
                new_info['notification_sent'] = existing_info['notification_sent']
        else:
            # 没有已有信息，创建新的时间戳
            new_info['timestamp'] = datetime.now().strftime(Config.INFO_DATE_FORMAT)

        # 更新或创建upload_info
        item['upload_info'] = new_info

        logger.warning(f"⏭ 已达最大下载尝试次数: {item['file_name']}")


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

    def process_items(self, items: List[Dict[str, Any]], processor: FileProcessor) -> None:
        """处理文件上传（支持分组）"""
        # 只处理未上传的文件
        pending_items = [item for item in items if not item.get('is_uploaded')]
        if not pending_items:
            return

        tweet_id = pending_items[0]['tweet_id']

        # 1. 处理特殊类型（文本项）
        text_items = [item for item in pending_items
                      if item.get('media_type') in ['spaces', 'broadcasts']]
        for item in text_items:
            self._process_single_item(item, processor)

        # 2. 处理媒体类型（图片/视频）
        media_items = [item for item in pending_items
                       if item.get('media_type') in ['images', 'videos']
                       and not item.get('is_uploaded')]

        if not media_items:
            # 没有媒体文件，跳过
            return

        # 选择上传策略
        if len(media_items) == 1:
            logger.debug(f"↗️ 单文件上传策略: {media_items[0]['file_name']}")
            self._process_single_item(media_items[0], processor)
        else:
            logger.info(f"🖼️ 媒体组上传策略: {tweet_id} (共{len(media_items)}个文件)")
            self._process_group(media_items, processor)

    def _process_group(self, items: List[Dict[str, Any]], processor: FileProcessor) -> None:
        """处理媒体组上传"""
        tweet_id = items[0]['tweet_id']

        try:
            group_caption = self._build_caption(items[0])
            # 获取媒体组和包含的原始项
            media_group, included_items = self._prepare_media_group(items, processor, group_caption)

            if not media_group:
                logger.debug(f"⏭ 推文 {tweet_id} 无可上传的有效媒体")
                return

            # 发送媒体组
            messages = self.bot.send_media_group(
                chat_id=self.chat_id,
                media=media_group
            )

            # 确保消息数量匹配
            if len(messages) != len(included_items):
                raise ValueError(
                    f"返回消息数量{len(messages)}与媒体组数量{len(included_items)}不匹配！"
                )

            # 更新状态
            for idx, msg in enumerate(messages):
                item = included_items[idx]
                msg_id = msg.message_id
                item.update({
                    "is_uploaded": True,
                    "upload_info": self._build_success_info(msg_id)
                })
                logger.info(f"✅ 文件已上传: tweet_id={tweet_id}, 文件名={item['file_name']}, message_id={msg_id}")

            logger.info(f"✅ 媒体组上传成功: {tweet_id} ({len(media_group)}个文件)")

        except Exception as e:
            for item in items:
                if not item.get('is_uploaded'):
                    self._handle_upload_error(e, item)

        finally:
            # 确保关闭所有文件句柄
            for media_item in media_group:
                if hasattr(media_item, 'media') and hasattr(media_item.media, 'close'):
                    media_item.media.close()

    def _prepare_media_group(self, items: List[Dict[str, Any]], processor: FileProcessor, group_caption: str) -> Tuple[
        List, List[Dict]]:
        """准备媒体组"""
        media_group = []
        # 存储包含在媒体组中的原始项
        included_items = []

        for item in items:
            # 跳过已上传的文件
            if item.get('is_uploaded'):
                continue

            # 检查不可恢复的错误
            if self._has_unrecoverable_error(item):
                continue

            # 特殊类型跳过媒体组
            if item.get('media_type') in ['spaces', 'broadcasts']:
                continue

            try:
                is_first_in_group = len(media_group) == 0
                caption = group_caption if is_first_in_group else None

                file_obj = self._get_file(item, processor)
                # 构建媒体类型
                if item['media_type'] == 'images':
                    media_item = telegram.InputMediaPhoto(file_obj, caption=caption)
                elif item['media_type'] == 'videos':
                    media_item = telegram.InputMediaVideo(file_obj, caption=caption)
                else:
                    logger.warning(f"⏭ 跳过未知媒体类型: {item['media_type']}")
                    continue

                media_group.append(media_item)
                included_items.append(item)

                # 检查媒体组文件数限制
                if len(media_group) >= Config.TELEGRAM_LIMITS['media_group']:
                    logger.warning(f"⚠️ 媒体组文件数达到上限: {len(media_group)}")
                    break

            except Exception as e:
                self._handle_upload_error(e, item)
            finally:
                if 'file_obj' in locals() and hasattr(file_obj, 'close'):
                    file_obj.close()

        return media_group, included_items

    def _get_file(self, item: Dict[str, Any], processor: FileProcessor) -> Any:
        """获取文件（内容或路径）"""
        # 特殊类型直接返回URL
        if item.get('media_type') in ['spaces', 'broadcasts']:
            return item['url']

        # 本地文件处理
        file_path = processor.download_path / item['file_name']

        # 文件大小校验
        file_size = os.path.getsize(file_path)
        media_type = item['media_type']
        if file_size > Config.TELEGRAM_LIMITS[media_type]:
            raise FileTooLargeError(
                f"{media_type}大小超标 ({file_size // 1024 // 1024}MB > {Config.TELEGRAM_LIMITS[media_type] // 1024 // 1024}MB)"
            )

        # 直接返回文件路径
        return open(file_path, 'rb')

    def _process_single_item(self, item: Dict[str, Any], processor: FileProcessor) -> None:
        """处理单个文件上传"""
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
        if self._has_unrecoverable_error(item):
            return False
        # 特殊类型直接上传
        if item.get('media_type') in ['spaces', 'broadcasts']:
            return True
        # 常规类型需要下载成功
        return item.get('is_downloaded', False)

    def _has_unrecoverable_error(self, item: Dict[str, Any]) -> bool:
        """检查不可恢复错误"""
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
            return True
        return False

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

        # 1. 按tweet_id分组数据
        grouped_items = defaultdict(list)
        for item in data:
            if 'tweet_id' not in item:
                logger.error(f"⚠️ 数据项缺少tweet_id: 文件名={item.get('file_name', '未知')}, 跳过")
                continue

            grouped_items[item['tweet_id']].append(item)

        download_manager = DownloadManager()
        upload_manager = UploadManager()

        logger.info(f"📊 检测到 {len(grouped_items)} 个推文分组")

        # 2. 按分组处理
        for tweet_id, items in grouped_items.items():
            # 2.1 下载组内所有未下载的文件
            for item in items:
                if not item.get('is_downloaded'):
                    download_manager.process_item(item, processor)

            # 2.2 分组上传策略
            upload_manager.process_items(items, processor)

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
