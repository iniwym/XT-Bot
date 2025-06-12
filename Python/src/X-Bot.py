import sys
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

# 将项目根目录添加到模块搜索路径
_project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(_project_root))
from utils.log_utils import LogUtils


# --------------------
# 配置区
# --------------------
class Config:
    # 分片配置
    MAX_ENTRIES_PER_SHARD = 10000  # 单个分片最大条目数
    SHARD_DIR = "../dataBase/"  # 分片存储目录
    FORMAT_SHARDS = True  # 是否格式化分片文件
    SHARD_PREFIX = "processed_entries_"

    # 路径配置
    DEFAULT_INPUT_DIR = "../../TypeScript/tweets/"  # 默认输入目录
    DEFAULT_OUTPUT_DIR = "../output/"  # 默认输出目录

    # 日期格式
    DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"  # 时间戳格式
    YEAR_MONTH_DAY = "%Y-%m-%d"  # 年月日格式
    YEAR_MONTH = "%Y-%m"  # 年月格式


# 引入日志模块
logger = LogUtils().get_logger()
logger.info("🔄 X-Bot 初始化完成")


# --------------------
# 分片管理器
# --------------------
class ShardManager:
    """管理已处理条目的分片存储"""

    def __init__(self):
        self._ensure_shard_dir()

    def _ensure_shard_dir(self):
        """确保分片目录存在"""
        if not os.path.exists(Config.SHARD_DIR):
            os.makedirs(Config.SHARD_DIR)
            logger.info(f"📁 创建分片目录: {Config.SHARD_DIR}")

    def get_current_shard_info(self):
        """获取当前分片信息"""
        year_month = datetime.now().strftime(Config.YEAR_MONTH)
        max_shard = self._get_max_shard_number(year_month)
        return {
            "year_month": year_month,
            "current_max": max_shard,
            "next_shard": max_shard + 1
        }

    def _get_max_shard_number(self, year_month):
        """获取指定年月最大分片号"""
        max_num = 0
        for file_path in self._list_shard_files():
            if f"_{year_month}-" in file_path:
                num = self._parse_shard_number(file_path)
                max_num = max(max_num, num)
        return max_num

    def _list_shard_files(self):
        """列出所有分片文件"""
        return [
            os.path.join(Config.SHARD_DIR, f)
            for f in os.listdir(Config.SHARD_DIR)
            if f.startswith(Config.SHARD_PREFIX) and f.endswith(".json")
        ]

    @staticmethod
    def _parse_shard_number(file_path):
        """从文件路径解析分片编号"""
        filename = os.path.basename(file_path)
        return int(filename.split("-")[-1].split(".")[0])

    def save_entry_id(self, entry_id):
        """保存条目ID到合适的分片"""
        shard_info = self.get_current_shard_info()
        candidate_path = self._build_shard_path(shard_info["year_month"], shard_info["current_max"])

        # 尝试写入现有分片
        if os.path.exists(candidate_path):
            try:
                with open(candidate_path, "r+") as f:
                    entries = json.load(f)
                    if len(entries) < Config.MAX_ENTRIES_PER_SHARD:
                        entries.append(entry_id)
                        f.seek(0)
                        json.dump(entries, f, indent=2 if Config.FORMAT_SHARDS else None)
                        logger.debug(f"📥 条目 {entry_id} 已写入现有分片: {candidate_path}")
                        return candidate_path
            except json.JSONDecodeError:
                logger.warning("🔄 检测到损坏分片，尝试修复...")
                return self._handle_corrupted_shard(candidate_path, entry_id)

        # 创建新分片
        new_path = self._build_shard_path(shard_info["year_month"], shard_info["next_shard"])
        self._write_shard(new_path, [entry_id])
        logger.info(f"✨ 创建新分片: {new_path}")
        return new_path

    def _build_shard_path(self, year_month, shard_number):
        """构建分片文件路径"""
        return os.path.join(
            Config.SHARD_DIR,
            f"{Config.SHARD_PREFIX}{year_month}-{shard_number:04d}.json"
        )

    def _handle_corrupted_shard(self, path, entry_id):
        """处理损坏的分片文件"""
        try:
            self._write_shard(path, [entry_id])
            logger.warning(f"✅ 成功修复损坏分片: {path}")
            return path
        except Exception as e:
            logger.error(f"❌ 修复分片失败: {str(e)}")
            raise

    def _write_shard(self, path, data):
        """写入分片文件"""
        with open(path, "w") as f:
            json.dump(data, f, indent=2 if Config.FORMAT_SHARDS else None)

    def load_processed_entries(self):
        """加载所有已处理条目"""
        processed = set()
        for file_path in self._list_shard_files():
            try:
                with open(file_path, "r") as f:
                    entries = json.load(f)
                    processed.update(entries)
                    logger.debug(f"📖 加载分片: {file_path} (条目数: {len(entries)})")
            except Exception as e:
                logger.warning(f"⚠️ 跳过损坏分片 {file_path}: {str(e)}")
        logger.info(f"🔍 已加载历史条目总数: {len(processed)}")
        return processed


# --------------------
# 条目处理器
# --------------------
class EntryProcessor:
    """处理推文条目中的媒体资源"""

    @staticmethod
    def generate_entry_id(filename, username, media_type):
        """生成唯一条目ID"""
        return f"{filename}_{username}_{media_type}"

    @staticmethod
    def create_entry_template(filename, user_info, media_type, url):
        """创建标准条目模板"""
        return {
            "tweet_id": "",
            "file_name": filename,
            "user": {
                "screen_name": user_info["screen_name"],
                "name": user_info.get("name", "N/A")
            },
            "media_type": media_type,
            "url": url,
            "read_time": datetime.now().strftime(Config.DATE_FORMAT),
            "is_uploaded": False,
            "upload_info": {},
            "is_downloaded": False,
            "download_info": {},
            "full_text": "",
            "publish_time": ""
        }

    def process_entry(self, entry, user_info, processed_ids):
        """处理单个推文条目"""
        new_entries = []

        # 提取条目中的 tweet_id
        tweet_id = self._extract_tweet_id(entry.get("tweet_url", ""))

        # 处理普通媒体
        new_entries.extend(self._process_media(entry, user_info, processed_ids, "images"))
        new_entries.extend(self._process_media(entry, user_info, processed_ids, "videos"))

        # 处理特殊链接
        new_entries.extend(self._process_special_urls(entry, user_info, processed_ids))

        # 补充元数据
        for e in new_entries:
            e.update({
                "tweet_id": tweet_id,
                "full_text": entry.get("full_text", ""),
                "publish_time": entry.get("publish_time", "")
            })

        return new_entries

    def _process_media(self, entry, user_info, processed_ids, media_type):
        """处理图片/视频类媒体"""
        entries = []
        for url in entry.get(media_type, []):
            filename = self._extract_filename(url)
            entry_id = self.generate_entry_id(filename, user_info["screen_name"], media_type)

            if entry_id in processed_ids:
                continue

            new_entry = self.create_entry_template(filename, user_info, media_type, url)
            entries.append(new_entry)
            logger.debug(f"📷 发现新{media_type}条目: {filename}")

        return entries

    def _process_special_urls(self, entry, user_info, processed_ids):
        """处理广播/空间链接"""
        entries = []
        for url in entry.get("expand_urls", []):
            media_type = self._detect_media_type(url)
            if not media_type:
                continue

            filename = self._extract_filename(url)
            entry_id = self.generate_entry_id(filename, user_info["screen_name"], media_type)

            if entry_id in processed_ids:
                continue

            new_entry = self.create_entry_template(filename, user_info, media_type, url)
            entries.append(new_entry)
            logger.debug(f"🔗 发现特殊链接: {media_type} - {filename}")

        return entries

    @staticmethod
    def _extract_tweet_id(tweet_url):
        """从推文URL提取唯一ID"""
        if not tweet_url:
            return ""

        # 查找/status/后的部分作为推文ID
        parts = tweet_url.split("/status/")
        if len(parts) > 1:
            # 获取ID部分，并移除可能存在的查询参数
            tweet_id = parts[1].split("?")[0].split("/")[0]
            # 确保ID是纯数字
            if tweet_id.isdigit():
                return tweet_id

        return ""

    @staticmethod
    def _extract_filename(url):
        """从URL提取文件名"""
        return url.split("?")[0].split("/")[-1]

    @staticmethod
    def _detect_media_type(url):
        """识别链接类型"""
        if "/broadcasts/" in url:
            return "broadcasts"
        if "/spaces/" in url:
            return "spaces"
        return None


# --------------------
# 文件管理器
# --------------------
class FileManager:
    """处理文件IO操作"""

    @staticmethod
    def load_json(path):
        """安全加载JSON文件"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"📂 成功加载文件: {path}")
            return data
        except FileNotFoundError:
            logger.error(f"❌ 文件未找到: {path}")
            raise
        except json.JSONDecodeError:
            logger.error(f"❌ JSON解析失败: {path}")
            raise

    @staticmethod
    def save_output(data, output_path):
        """保存输出文件"""
        output_dir = os.path.dirname(output_path)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            logger.info(f"📁 创建输出目录: {output_dir}")

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 输出已保存至: {output_path}")


# --------------------
# 核心流程
# --------------------
class XBotCore:
    """主处理逻辑"""

    def __init__(self):
        self.shard_manager = ShardManager()
        self.entry_processor = EntryProcessor()
        self.file_manager = FileManager()
        self.processed_ids = self.shard_manager.load_processed_entries()

    def process_single_day(self, data_path, output_path):
        """处理单日数据"""
        logger.info(f"\n{'-' * 40}\n🔍 开始处理: {os.path.basename(data_path)}")

        # 加载数据
        raw_data = self.file_manager.load_json(data_path)
        user_data = self._organize_user_data(raw_data)

        # 处理条目
        all_new_entries = []
        # 遍历所有用户
        for username in user_data:

            user_info = user_data[username]

            user_entries = []
            for entry in user_info["entries"]:
                user_entries.extend(self.entry_processor.process_entry(entry, user_info, self.processed_ids))

            # 保存新条目ID
            for entry in user_entries:
                entry_id = EntryProcessor.generate_entry_id(
                    entry["file_name"],
                    entry["user"]["screen_name"],
                    entry["media_type"]
                )
                self.shard_manager.save_entry_id(entry_id)

            all_new_entries.extend(user_entries)

        # 合并输出
        final_output = self._merge_output(output_path, all_new_entries)
        self.file_manager.save_output(final_output, output_path)
        logger.info(f"🎉 本日处理完成！新增条目: {len(all_new_entries)}\n{'-' * 40}\n")
        return len(all_new_entries)

    def _organize_user_data(self, raw_data):
        """重组用户数据结构"""
        organized = {}
        for item in raw_data:
            user = item.get("user", {})
            username = user.get("screenName")
            if not username:
                continue

            if username not in organized:
                organized[username] = {
                    "screen_name": username,
                    "name": user.get("name", "N/A"),
                    "entries": []
                }

            organized[username]["entries"].append({
                "tweet_url": item.get("tweetUrl", ""),
                "full_text": item.get("fullText", ""),
                "publish_time": item.get("publishTime", ""),
                "images": item.get("images", []),
                "videos": item.get("videos", []),
                "expand_urls": item.get("expandUrls", [])
            })
        return organized

    def _merge_output(self, output_path, new_entries):
        """合并新旧输出文件"""
        existing = []
        if os.path.exists(output_path):
            existing = self.file_manager.load_json(output_path)
            logger.info(f"🔄 合并现有输出文件，已有条目: {len(existing)}")

        existing_ids = {self._get_entry_id(e) for e in existing}
        merged = existing.copy()
        added = 0

        for entry in new_entries:
            entry_id = self._get_entry_id(entry)
            if entry_id not in existing_ids:
                merged.append(entry)
                added += 1

        merged.sort(key=lambda x: x.get("publish_time", ""))
        logger.info(f"🆕 新增条目: {added} | 合并后总数: {len(merged)}")
        return merged

    @staticmethod
    def _get_entry_id(entry):
        """获取条目唯一标识"""
        return f"{entry['file_name']}_{entry['user']['screen_name']}_{entry['media_type']}"


# --------------------
# 命令行接口
# --------------------
def main():
    core = XBotCore()
    args = sys.argv[1:]  # 获取命令行参数

    # 指定输出目录：python X-Bot.py 数据文件 输出文件
    if len(args) == 2:
        data_path = os.path.normpath(args[0])
        output_path = os.path.normpath(args[1])

        if os.path.exists(data_path):
            logger.info(f"🔧 自定义模式处理：{data_path}")
            core.process_single_day(data_path, output_path)
        else:
            logger.info(f"⏭️ 跳过不存在的数据文件：{data_path}")

    # 单参数模式：python X-Bot.py 数据文件
    elif len(args) == 1:
        data_path = os.path.normpath(args[0])
        current_date = datetime.now()

        # 生成当天输出路径
        output_dir = os.path.normpath(
            f"{Config.DEFAULT_OUTPUT_DIR}{current_date.strftime(Config.YEAR_MONTH)}/"
        )
        output_filename = f"{current_date.strftime(Config.YEAR_MONTH_DAY)}.json"
        output_path = os.path.join(output_dir, output_filename)

        if os.path.exists(data_path):
            logger.info(f"⚡ 单文件模式处理：{os.path.basename(data_path)}")
            os.makedirs(output_dir, exist_ok=True)
            new_entries_count = core.process_single_day(data_path, output_path)
            # 返回新增条数
            print(new_entries_count)
        else:
            logger.info(f"⏭️ 跳过不存在的数据文件：{data_path}")
            print(0)

    # 无参数模式：python X-Bot.py
    elif len(args) == 0:
        current_date = datetime.now()

        logger.info("🤖 自动模式：处理最近一周数据")
        for day_offset in reversed(range(8)):  # 包含今天共8天
            target_date = current_date - timedelta(days=day_offset)

            # 输入文件路径（按数据日期）
            data_dir = os.path.normpath(
                f"{Config.DEFAULT_INPUT_DIR}{target_date.strftime(Config.YEAR_MONTH)}/"
            )
            data_filename = f"{target_date.strftime(Config.YEAR_MONTH_DAY)}.json"
            data_path = os.path.join(data_dir, data_filename)

            # 输出文件路径（按数据日期）
            output_dir = os.path.normpath(
                f"{Config.DEFAULT_OUTPUT_DIR}{target_date.strftime(Config.YEAR_MONTH)}/"
            )
            output_path = os.path.join(output_dir, data_filename)

            if os.path.exists(data_path):
                logger.info(f"🔍 正在处理 {target_date.strftime(Config.YEAR_MONTH_DAY)} 数据...")
                os.makedirs(output_dir, exist_ok=True)
                core.process_single_day(data_path, output_path)
            else:
                logger.info(f"⏭️ 跳过不存在的数据文件：{data_filename}")

    # 错误参数处理
    else:
        logger.error("❗ 参数错误！支持以下模式：")
        logger.error("1. 全参数模式：脚本 + 数据文件 + 输出文件")
        logger.error("2. 单文件模式：脚本 + 数据文件（输出到当天目录）")
        logger.error("3. 自动模式：仅脚本（处理最近一周数据）")
        logger.error("示例：")
        logger.error(
            "python X-Bot.py ../../TypeScript/tweets/2000-01/2000-01-01.json ../output/2000-01/2000-01-01.json")
        logger.error("python X-Bot.py ../../TypeScript/tweets/user/xxx.json")
        logger.error("python X-Bot.py")
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
