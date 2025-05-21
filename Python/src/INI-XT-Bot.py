import sys
import json
import os
import subprocess
import telegram
from datetime import datetime
from pathlib import Path
from typing import List, Dict

# 将项目根目录添加到模块搜索路径
_project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(_project_root))
from utils.log_utils import LogUtils


# --------------------------
# 配置常量
# --------------------------
class EnvConfig:
    """环境变量配置"""
    BOT_TOKEN = os.getenv("BOT_TOKEN")  # Telegram机器人Token
    CHAT_ID = os.getenv("CHAT_ID")  # Telegram频道/群组ID
    LARK_KEY = os.getenv("LARK_KEY")  # 飞书机器人Webhook Key


class PathConfig:
    """路径配置"""
    CONFIG_PATH = Path("../../config/config.json")  # 配置文件路径
    OUT_PUT_DIR = Path("../output/")  # 用户数据目录
    USER_DATA_DIR = Path("../../TypeScript/tweets/user/")  # 用户数据目录


class MsgConfig:
    """消息模板"""
    TELEGRAM_ALERT = "#{screen_name} #x"  # Telegram通知模板

    NOTIFICATION_TRUNCATE = 40  # 通知消息截断长度


# 引入日志模块
logger = LogUtils().get_logger()
logger.info("🔄 INI-XT-Bot 初始化完成")


# --------------------------
# 通知模块
# --------------------------
def send_telegram_alert(screen_name: str) -> bool:
    """
    发送Telegram格式通知
    返回发送状态: True成功 / False失败
    """
    # 检查环境配置
    if not all([EnvConfig.BOT_TOKEN, EnvConfig.CHAT_ID]):
        logger.warning("⏭️ 缺少Telegram环境变量配置，跳过通知发送")
        return False

    try:
        # 生成格式化消息
        formatted_msg = MsgConfig.TELEGRAM_ALERT.format(
            screen_name=screen_name
        )

        # 初始化机器人
        bot = telegram.Bot(token=EnvConfig.BOT_TOKEN)

        # 发送消息(静默模式)
        bot.send_message(
            chat_id=EnvConfig.CHAT_ID,
            text=formatted_msg,
            disable_notification=True
        )
        logger.info(f"📢 Telegram通知发送成功: {formatted_msg}")
        return True

    except telegram.error.TelegramError as e:
        logger.error(f"❌ Telegram消息发送失败: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"🚨 通知发送出现意外错误: {str(e)}", exc_info=True)
        return False


def send_lark_alert(message: str) -> bool:
    """
    发送飞书告警通知
    返回发送状态: True成功 / False失败
    """
    if not EnvConfig.LARK_KEY:
        logger.warning("⏭️ 未配置飞书机器人，跳过通知")
        return False

    try:
        webhook_url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{EnvConfig.LARK_KEY}"
        payload = {
            "msg_type": "text",
            "content": {"text": f"🔔 INI-XT-Bot告警\n{message}"}
        }
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("📨 飞书告警发送成功")
        return True
    except Exception as e:
        logger.error(f"❌ 飞书通知发送失败: {str(e)}")
        return False


# --------------------------
# 核心逻辑
# --------------------------
def load_config() -> List[str]:
    """
    加载配置文件
    返回screen_name列表
    """
    try:
        with open(PathConfig.CONFIG_PATH, "r") as f:
            config = json.load(f)

        # 获取原始列表并过滤空值
        raw_users = config.get("screenName", [])
        users = [u.strip() for u in raw_users if u.strip()]

        logger.info(f"📋 加载到{len(users)}个待处理用户")
        logger.debug(f"用户列表: {', '.join(users)}")
        return users

    except FileNotFoundError:
        logger.error(f"❌ 配置文件不存在: {PathConfig.CONFIG_PATH}")
        return []
    except json.JSONDecodeError:
        logger.error(f"❌ 配置文件解析失败: {PathConfig.CONFIG_PATH}")
        return []
    except Exception as e:
        logger.error(f"🚨 加载配置出现意外错误: {str(e)}")
        return []


def process_user(screen_name: str) -> int:
    """
    处理单个用户数据
    返回新增条目数
    """
    # 构建数据文件路径
    data_file = PathConfig.USER_DATA_DIR / f"{screen_name}.json"
    if not data_file.exists():
        logger.warning(f"⏭️ 用户数据文件不存在: {data_file}")
        return 0

    logger.info("🚀 触发X-Bot执行")

    try:
        # 执行X-Bot处理（实时显示日志）
        process = subprocess.Popen(
            ["python", "-u", "X-Bot.py", str(data_file)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # 合并错误输出
            text=True,
            bufsize=1  # 启用行缓冲
        )

        # 实时打印输出并捕获最后结果
        output_lines = []
        for line in iter(process.stdout.readline, ''):
            line = line.strip()
            if line:  # 过滤空行
                # 实时打印到父进程控制台
                print(f"[X-Bot] {line}", flush=True)
                output_lines.append(line)

        # 等待进程结束
        process.wait()

        # 检查退出码
        if process.returncode != 0:
            raise subprocess.CalledProcessError(
                process.returncode,
                process.args,
                output='\n'.join(output_lines)
            )

        if output_lines:
            if len(output_lines) > 1:
                # 解析倒数第二行作为结果
                new_count = int(output_lines[-2])
            else:
                # 解析倒数第一行作为结果
                new_count = int(output_lines[-1])
        else:
            new_count = 0
        logger.info(f"✅ X-Bot执行成功，用户 {screen_name} 处理完成，新增 {new_count} 条")
        return new_count

    except subprocess.CalledProcessError as e:
        error_msg = f"❌ 用户 {screen_name} 处理失败: {e.output.splitlines()[-1][:MsgConfig.NOTIFICATION_TRUNCATE]}"
        logger.error(error_msg)
        send_lark_alert(error_msg)
        return 0
    except ValueError:
        logger.error(f"⚠️ 无效的输出内容: {output_lines[-2][:200]}")
        return 0
    except Exception as e:
        logger.error(f"🚨 X-Bot未知错误: {str(e)}")
        return 0


def trigger_tbot() -> bool:
    """
    触发下游处理流程
    返回执行状态: True成功 / False失败
    """
    current_date = datetime.now().strftime("%Y-%m-%d")
    json_path = PathConfig.OUT_PUT_DIR / f"{current_date[:7]}/{current_date}.json"

    if not json_path.exists():
        logger.warning(f"⏭️ 推送数据文件不存在: {json_path}")
        return 0

    try:
        logger.info("🚀 触发T-Bot执行")

        # 实时显示T-Bot输出
        process = subprocess.Popen(
            ["python", "-u", "T-Bot.py", str(json_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        # 实时转发输出
        for line in iter(process.stdout.readline, ''):
            print(f"[T-Bot] {line.strip()}", flush=True)

        # 检查结果
        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(
                process.returncode,
                process.args
            )

        logger.info("✅ T-Bot执行成功")
        return True
    except subprocess.CalledProcessError as e:
        error_msg = f"❌ T-Bot执行失败: {str(e)}"
        logger.error(error_msg)
        send_lark_alert(error_msg)
        return False
    except Exception as e:
        logger.error(f"🚨 T-Bot未知错误: {str(e)}")
        return False


# --------------------------
# 主流程
# --------------------------
def main():
    """主处理流程"""
    # 加载配置文件
    users = load_config()
    if not users:
        logger.error("❌ 未获取到有效用户列表，程序终止")
        return

    # 遍历处理用户
    total_new = 0
    for screen_name in users:
        logger.info(f"\n{'=' * 40}\n🔍 开始处理: {screen_name}")
        new_count = process_user(screen_name)

        # 处理新增条目
        if new_count > 0:
            # 发送即时通知
            send_telegram_alert(screen_name)

        # 触发下游流程
        if not trigger_tbot():
            send_lark_alert(f"触发T-Bot失败 - 用户: {screen_name}")

        total_new += new_count
        logger.info(f"✅ 处理完成\n{'=' * 40}\n")

    # 最终状态汇总
    logger.info(f"🎉 所有用户处理完成！总新增条目: {total_new}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"💥 未处理的全局异常: {str(e)}", exc_info=True)
