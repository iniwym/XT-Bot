import sys
import json
import os
import requests
import telegram
from datetime import datetime, timedelta
from pathlib import Path
from typing import (Optional, Dict, Any, List, Tuple, DefaultDict, BinaryIO, IO)
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
        self._initialize_bot()
        self.strategies = {
            'text': self._handle_text_upload,
            'single': self._handle_single_media,
            'group': self._handle_media_group
        }
        self.processor = None  # 文件处理器引用

    def _initialize_bot(self):
        """初始化Telegram机器人"""
        env_vars = Config.get_env_vars()
        if not env_vars['bot_token'] or not env_vars['chat_id']:
            logger.error("❌ 必须配置 BOT_TOKEN 和 CHAT_ID 环境变量！")
            sys.exit(1)
        self.bot = telegram.Bot(token=env_vars['bot_token'])
        self.chat_id = env_vars['chat_id']

    def process_items(self, items: List[Dict[str, Any]], processor: FileProcessor) -> None:
        """
        处理待上传项的主入口
        """
        # 保存处理器引用，供后续使用
        self.processor = processor

        # 过滤出可上传的项
        upload_queue = self._filter_uploadable_items(items)
        if not upload_queue:
            return

        # 策略分发中心
        strategy_map = self._create_strategy_map(upload_queue)

        # 按策略类型处理
        for strategy_type, items_to_upload in strategy_map.items():
            try:
                if strategy_type == 'group':
                    # 按推文分组处理媒体组
                    grouped_items = self._group_by_tweet_id(items_to_upload)
                    for tweet_items in grouped_items:
                        self.strategies[strategy_type](tweet_items, processor)
                else:
                    self.strategies[strategy_type](items_to_upload, processor)
            except Exception as e:
                self._handle_strategy_error(e, items_to_upload, strategy_type)

    def _filter_uploadable_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """过滤出可上传的项"""
        return [
            item for item in items
            if not item.get('is_uploaded') and self._is_eligible_for_upload(item)
        ]

    def _is_eligible_for_upload(self, item: Dict[str, Any]) -> bool:
        """判断项是否适合上传"""
        # 检查不可恢复的错误
        if self._has_unrecoverable_error(item):
            return False
        # 特殊类型（文本）可直接上传
        if item.get('media_type') in ['spaces', 'broadcasts']:
            return True
        # 常规类型需要下载成功
        return item.get('is_downloaded', False)

    def _create_strategy_map(self, items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        创建上传策略映射：
        - 'text': 文本类型项
        - 'single': 单媒体项
        - 'group': 媒体组项
        """
        strategy_map = defaultdict(list)

        for item in items:
            media_type = item['media_type']

            if media_type in ['spaces', 'broadcasts']:
                strategy_map['text'].append(item)

            elif media_type in ['images', 'videos']:
                # 对媒体文件进行分组（媒体数量决定策略）
                media_count = self._get_media_count_in_tweet(items, item['tweet_id'])

                if media_count == 1:
                    strategy_map['single'].append(item)
                else:
                    strategy_map['group'].append(item)

        return dict(strategy_map)

    def _get_media_count_in_tweet(self, all_items: List[Dict[str, Any]], tweet_id: str) -> int:
        """获取同一推文中的媒体项数量"""
        return sum(
            1 for item in all_items
            if item['tweet_id'] == tweet_id
            and item['media_type'] in ['images', 'videos']
            and not item.get('is_uploaded')
        )

    def _group_by_tweet_id(self, items: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """按推文ID分组项"""
        grouped = defaultdict(list)
        for item in items:
            grouped[item['tweet_id']].append(item)
        return list(grouped.values())

    # --------------------------
    # 上传策略实现
    # --------------------------
    def _handle_text_upload(self, items: List[Dict[str, Any]], processor: FileProcessor) -> None:
        """处理文本项上传策略"""
        for item in items:
            self._upload_text_item(item)

    def _handle_single_media(self, items: List[Dict[str, Any]], processor: FileProcessor) -> None:
        """处理单媒体项上传策略"""
        for item in items:
            try:
                self._upload_media_item(item, processor)
            except Exception as e:
                self._handle_single_upload_error(e, item)

    def _handle_media_group(self, items: List[Dict[str, Any]], processor: FileProcessor) -> None:
        """处理媒体组上传策略"""
        tweet_id = items[0]['tweet_id']
        logger.info(f"🖼️ 准备媒体组上传: {tweet_id} ({len(items)}个文件)")

        # 提前检查媒体组大小
        if self._is_group_size_exceeded(items):
            logger.warning(f"⚠️ 媒体组过大({self._get_group_size_mb(items)}MB > 50MB)，回退为单文件上传")
            self._fallback_to_single_upload(items)
            return

        # 构建媒体组
        media_group, included_items = self._prepare_media_group(items, processor)

        if not media_group:
            logger.warning(f"⏭ 无可上传的有效媒体: {tweet_id}")
            return

        try:
            # 发送媒体组
            messages = self.bot.send_media_group(
                chat_id=self.chat_id,
                media=media_group
            )

            # 验证响应
            if len(messages) != len(included_items):
                logger.warning(
                    f"⚠️ 返回消息数量({len(messages)})与媒体组数量({len(included_items)})不匹配，将回退为单文件上传"
                )
                # 使用回退机制处理不匹配情况
                self._fallback_to_single_upload(included_items)
                return

            # 更新状态
            for msg, item in zip(messages, included_items):
                msg_id = msg.message_id
                self._update_upload_status(item, msg_id)
                logger.info(f"✅ 上传成功: {item['file_name']}({msg_id})")

            logger.info(f"✅ 媒体组上传成功: {tweet_id} ({len(media_group)}个文件)")

        except Exception as e:
            self._handle_group_upload_error(e, included_items)

        finally:
            # 确保关闭所有文件句柄
            for media_item in media_group:
                if hasattr(media_item, 'media') and hasattr(media_item.media, 'close'):
                    media_item.media.close()

    # --------------------------
    # 媒体组大小检测和回退
    # --------------------------
    def _handle_strategy_error(self, error: Exception, items: List[Dict[str, Any]], strategy_type: str) -> None:
        """处理策略级错误，优化媒体组处理逻辑"""
        logger.error(f"✗ {strategy_type}策略执行失败: {str(error)[:Config.ERROR_TRUNCATE]}")
        logger.debug(f"✗ {strategy_type}策略执行失败详情: {str(error)}")

        # 对于媒体组错误，检查大小决定是否回退
        if strategy_type == 'group' and self._is_group_size_exceeded(items):
            logger.warning(f"⚠️ 媒体组过大({self._get_group_size_mb(items)}MB > 50MB)，回退为单文件上传")
            self._fallback_to_single_upload(items)
        elif strategy_type in ['group', 'text']:
            # 其他类型的媒体组错误也尝试回退
            self._fallback_to_single_upload(items)

    def _is_group_size_exceeded(self, items: List[Dict[str, Any]]) -> bool:
        """检查媒体组总大小是否超过50MB限制"""
        return self._get_group_size_mb(items) > Config.TELEGRAM_LIMITS['videos'] / (1024 * 1024)

    def _get_group_size_mb(self, items: List[Dict[str, Any]]) -> float:
        """计算媒体组总大小（MB）"""
        total_size_bytes = 0

        for item in items:
            if 'download_info' in item and 'size_mb' in item['download_info']:
                # 使用已有大小信息
                total_size_bytes += item['download_info']['size_mb'] * 1024 * 1024
            else:
                # 尝试从文件系统获取大小
                try:
                    file_path = self.processor.download_path / item['file_name']
                    if file_path.exists():
                        total_size_bytes += os.path.getsize(file_path)
                except Exception:
                    continue

        return round(total_size_bytes / (1024 * 1024), 2)

    def _fallback_to_single_upload(self, items: List[Dict[str, Any]]) -> None:
        """回退为单文件上传策略"""
        logger.info(f"⏮️ 回退为单文件上传: {items[0]['tweet_id']} ({len(items)}个文件)")

        for item in items:
            if item.get('is_uploaded'):
                continue

            try:
                if item['media_type'] in ['spaces', 'broadcasts']:
                    self._upload_text_item(item)
                else:
                    self._upload_media_item(item, self.processor)
            except Exception as inner_error:
                self._update_error_status(inner_error, item)
                self._reset_download_status(item)
                logger.error(f"✗ 单文件上传失败: {item['file_name']} - {str(inner_error)[:Config.ERROR_TRUNCATE]}")
                logger.debug(f"✗ 单文件上传失败详情: {item['file_name']} - {str(inner_error)}")

    # --------------------------
    # 实际上传操作
    # --------------------------
    def _upload_text_item(self, item: Dict[str, Any]) -> None:
        """上传文本消息"""
        # 文本型caption构建
        caption = self._build_text_caption(item)
        msg = self.bot.send_message(chat_id=self.chat_id, text=caption)
        msg_id = msg.message_id
        self._update_upload_status(item, msg_id)

        # 发送飞书通知
        if Config.get_env_vars()['lark_key']:
            Notifier.send_lark_message(caption)

        logger.info(f"✅ 发送成功: {item['file_name']}({msg_id})")

    def _upload_media_item(self, item: Dict[str, Any], processor: FileProcessor) -> None:
        """上传单个媒体文件"""
        with self._get_file_handle(item, processor) as file_obj:
            # 媒体型caption构建
            caption = self._build_media_caption(item)

            if item['media_type'] == 'images':
                msg = self.bot.send_photo(chat_id=self.chat_id, photo=file_obj, caption=caption)
            else:  # videos
                msg = self.bot.send_video(chat_id=self.chat_id, video=file_obj, caption=caption)

            msg_id = msg.message_id
            self._update_upload_status(item, msg_id)
            logger.info(f"✅ 上传成功: {item['file_name']}({msg_id})")

    def _prepare_media_group(self, items: List[Dict[str, Any]], processor: FileProcessor
                             ) -> Tuple[List[telegram.InputMedia], List[Dict[str, Any]]]:
        """
        准备媒体组上传
        返回：媒体组对象列表, 包含的原始项列表
        """
        media_group = []
        included_items = []
        tweet_id = items[0]['tweet_id']

        for idx, item in enumerate(items):
            if item.get('is_uploaded'):
                continue

            try:
                with self._get_file_handle(item, processor) as file_obj:
                    # 仅第一项添加caption
                    caption = self._build_media_caption(item) if idx == 0 else None

                    if item['media_type'] == 'images':
                        media_item = telegram.InputMediaPhoto(file_obj, caption=caption)
                    else:  # videos
                        media_item = telegram.InputMediaVideo(file_obj, caption=caption)

                    media_group.append(media_item)
                    included_items.append(item)

                    # 检查媒体组文件数限制
                    if len(media_group) >= Config.TELEGRAM_LIMITS['media_group']:
                        logger.warning(f"⚠️ 媒体组文件数达到上限: {tweet_id}")
                        break

            except Exception as e:
                self._handle_preparation_error(e, item)

        return media_group, included_items

    # --------------------------
    # caption构建系统
    # --------------------------
    def _build_text_caption(self, item: Dict[str, Any]) -> str:
        """
        文本型caption构建
        格式: #[用户名] #[类型]
              [发布时间]
              [原链接]
        """
        username = item['user']['screen_name']
        media_type = item['media_type']
        publish_time = datetime.fromisoformat(item['publish_time']).strftime(Config.MESSAGE_DATE_FORMAT)
        url = item['url']

        # 组合文本元素
        content = f"#{username} #{media_type}\n{publish_time}\n{url}"
        return self._truncate_text(content, Config.TELEGRAM_LIMITS['caption'])

    def _build_media_caption(self, item: Dict[str, Any]) -> str:
        """
        媒体型caption构建
        格式: #[用户名] [显示名]
              [发布时间]
              [推文文本内容]
        """
        screen_name = item['user']['screen_name']
        display_name = item['user']['name']
        publish_time = datetime.fromisoformat(item['publish_time']).strftime(Config.MESSAGE_DATE_FORMAT)

        # 组合基本信息
        base_info = f"#{screen_name} {display_name}\n{publish_time}"

        # 添加推文内容
        text_content = f"{base_info}\n{item.get('full_text', '')}"
        return self._truncate_text(text_content, Config.TELEGRAM_LIMITS['caption'])

    def _truncate_text(self, text: str, max_length: int) -> str:
        """智能截断文本"""
        if len(text) > max_length:
            truncated = text[:max_length - 3]
            # 确保截断在完整句子后
            if truncated.rfind('.') > max_length - 10:
                truncate_point = truncated.rfind('.') + 1
            else:
                truncate_point = max_length - 3
            return text[:truncate_point] + "..."
        return text

    # --------------------------
    # 辅助方法
    # --------------------------
    def _get_file_handle(self, item: Dict[str, Any], processor: FileProcessor) -> BinaryIO:
        """获取文件句柄并进行大小验证"""
        if item.get('media_type') in ['spaces', 'broadcasts']:
            # 特殊类型直接返回URL
            return item['url']

        # 处理本地文件
        file_path = processor.download_path / item['file_name']
        media_type = item['media_type']

        # 检查文件大小
        file_size = os.path.getsize(file_path)
        if file_size > Config.TELEGRAM_LIMITS[media_type]:
            raise FileTooLargeError(
                f"{media_type}大小超标 ({file_size / (1024 * 1024):.2f}MB > "
                f"{Config.TELEGRAM_LIMITS[media_type] / (1024 * 1024):.2f}MB)"
            )

        return open(file_path, 'rb')

    def _update_upload_status(self, item: Dict[str, Any], message_id: int) -> None:
        """更新上传状态为成功"""
        item.update({
            "is_uploaded": True,
            "upload_info": {
                "success": True,
                "message_id": message_id,
                "timestamp": datetime.now().strftime(Config.INFO_DATE_FORMAT)
            }
        })

    # --------------------------
    # 错误处理系统
    # --------------------------
    def _has_unrecoverable_error(self, item: Dict[str, Any]) -> bool:
        """检查不可恢复错误"""
        upload_info = item.get('upload_info', {})
        error_type = upload_info.get('error_type')

        if error_type in ['file_too_large', 'max_download_attempts']:
            # 发送通知（如果尚未发送）
            if not upload_info.get('notification_sent'):
                self._send_unrecoverable_alert(item, error_type)
                upload_info['notification_sent'] = True
            return True
        return False

    def _send_unrecoverable_alert(self, item: Dict[str, Any], error_type: str) -> None:
        """发送不可恢复错误通知"""
        Notifier.send_lark_alert(
            f"🔴 推送失败\n文件名: {item['file_name']}\n"
            f"类型: {error_type}\n"
            f"错误: {item['upload_info']['message'][:Config.ERROR_TRUNCATE]}"
        )

    def _handle_single_upload_error(self, error: Exception, item: Dict[str, Any]) -> None:
        """处理单文件上传错误"""
        self._update_error_status(error, item)
        self._reset_download_status(item)
        logger.error(f"✗ 单文件上传失败: {item['file_name']} - {str(error)[:Config.ERROR_TRUNCATE]}")
        logger.debug(f"✗ 单文件上传失败详情: {item['file_name']} - {str(error)}")

    def _handle_group_upload_error(self, error: Exception, items: List[Dict[str, Any]]) -> None:
        """处理媒体组上传错误"""
        for item in items:
            self._update_error_status(error, item)
            self._reset_download_status(item)
        tweet_id = items[0]['tweet_id'] if items else "未知"
        logger.error(f"✗ 媒体组上传失败: {tweet_id} - {str(error)[:Config.ERROR_TRUNCATE]}")
        logger.debug(f"✗ 媒体组上传失败详情: {tweet_id} - {str(error)}")

    def _handle_preparation_error(self, error: Exception, item: Dict[str, Any]) -> None:
        """处理媒体组准备过程中的错误"""
        self._update_error_status(error, item)
        self._reset_download_status(item)
        logger.warning(f"✗ 媒体组准备失败: {item['file_name']}")

    def _update_error_status(self, error: Exception, item: Dict[str, Any]) -> None:
        """更新错误状态"""
        error_type = 'file_too_large' if isinstance(error, FileTooLargeError) else 'api_error'

        item['upload_info'] = {
            "success": False,
            "error_type": error_type,
            "message": str(error),
            "timestamp": datetime.now().strftime(Config.INFO_DATE_FORMAT),
            "notification_sent": False
        }

        # 对于非文件大小错误，立即通知
        if error_type != 'file_too_large':
            Notifier.send_lark_alert(
                f"🔴 上传失败\n文件名: {item['file_name']}\n"
                f"错误类型: {error.__class__.__name__}\n"
                f"错误详情: {str(error)[:Config.ERROR_TRUNCATE]}"
            )

    def _reset_download_status(self, item: Dict[str, Any]) -> None:
        """重置下载状态以允许重试"""
        if 'is_downloaded' in item:
            item['is_downloaded'] = False


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
