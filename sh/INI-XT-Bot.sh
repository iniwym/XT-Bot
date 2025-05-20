#!/bin/bash
# GitHub Actions 自动化控制器(macOS)
# 需要安装 GitHub CLI (gh) 并登录 (gh auth login)

# 配置区
REPO="iniwym/XT-Bot"
AOTO_WORKFLOW_FILE="XT-Bot.yml"
INI_WORKFLOW_FILE="INI-XT-Bot.yml"
BRANCH="main"
TERMINAL_THEME="Pro"

# 路径配置（使用绝对路径）
SCRIPT_DIR=$(cd "$(dirname "$0")"; pwd)
ARTIFACTS_DIR="${SCRIPT_DIR}/../logs/action-artifacts"

# 创建统一目录
mkdir -p "${ARTIFACTS_DIR}"

# 通用函数：处理手动执行流程
handle_manual_workflow() {
  local WORKFLOW_FILE=$1
  local WORKFLOW_NAME=$2

  # 触发工作流
  echo "🔄 触发工作流 $WORKFLOW_NAME (文件: $WORKFLOW_FILE) 分支: $BRANCH..."
  local TRIGGER_RESULT
  TRIGGER_RESULT=$(gh api -X POST "/repos/${REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches" \
    -F ref="${BRANCH}" 2>&1)

  if [[ $? -ne 0 ]]; then
    echo "❌ 触发失败: ${TRIGGER_RESULT}"
    exit 1
  fi

  # 获取 Run ID（带重试）
  echo "⏳ 获取运行 ID..."
  local RUN_ID
  for i in {1..10}; do
    RUN_ID=$(gh run list --workflow="${WORKFLOW_FILE}" --branch "${BRANCH}" --limit 1 \
      --json databaseId,status --jq '.[] | select(.status != "completed").databaseId')
    [[ -n "$RUN_ID" ]] && break
    sleep 5
  done

  if [[ ! "$RUN_ID" =~ ^[0-9]+$ ]]; then
    echo "❌ 获取 Run ID 失败"
    exit 2
  fi
  echo "✅ Run ID: ${RUN_ID}"

  # 启动日志监控
  echo "📜 启动日志监控窗口..."
  osascript <<EOD
tell application "Terminal"
  activate
  set tab1 to do script "cd \"${SCRIPT_DIR}\" && gh run watch ${RUN_ID} --exit-status"
  set current settings of tab1 to settings set "${TERMINAL_THEME}"
end tell
EOD

  # 监控运行状态（最长2小时）
  echo "⏳ 监控运行状态（最长2小时）..."
  local start=$(date +%s)
  while true; do
    local STATUS=$(gh run view ${RUN_ID} --json status --jq '.status')

    case $STATUS in
      "completed")
        break
        ;;
      "in_progress"|"queued")
        ;;
      *)
        echo "❌ 异常状态: ${STATUS}"
        exit 3
        ;;
    esac

    # 2小时超时判断（7200秒）
    if (( $(( $(date +%s) - start )) > 7200 )); then
      echo "⏰ 运行超时（2小时）"
      exit 4
    fi
    sleep 20
  done

  # 下载产物
  echo "📦 下载到集中存储目录..."
  gh run download ${RUN_ID} -n "workflow_${RUN_ID}" -D "${ARTIFACTS_DIR}/${RUN_ID}" 2>&1

  # 结果验证
  local RESP_DIR="${ARTIFACTS_DIR}/${RUN_ID}/"
  if [[ -d "${RESP_DIR}" ]]; then
    echo "✅ 文件已保存至：${RESP_DIR}"
  else
    echo "⚠️ "
    exit 5
  fi
}

# 主流程
echo "获取最新状态信息..."
gh workflow list
echo "----------------------------"
echo "请选择操作:"
echo "  [0] 禁用工作流程 $AOTO_WORKFLOW_FILE"
echo "  [1] 启用工作流程 $AOTO_WORKFLOW_FILE"
echo "  [2] 手动执行流程 $AOTO_WORKFLOW_FILE"
echo "  [3] 手动执行流程 $INI_WORKFLOW_FILE"
read -p "输入数字 (0-3): " CHOICE

# 输入验证
if [[ ! "$CHOICE" =~ ^[0-3]$ ]]; then
  echo "错误：输入必须为 0-3！"
  exit 1
fi

case $CHOICE in
  0|1)
    # 启用/禁用逻辑
    ACTION="$([[ $CHOICE -eq 1 ]] && echo "enable" || echo "disable")"

    echo "正在将 $AOTO_WORKFLOW_FILE 设置为 $ACTION..."
    if gh workflow "$ACTION" "$AOTO_WORKFLOW_FILE"; then
      echo "✅ 操作成功！等待 2 秒获取最新状态信息..."
      sleep 2
      gh workflow list
    else
      echo "❌ 操作失败，请检查以下可能原因:"
      echo "  1. 是否已安装 GitHub CLI (gh) 并登录 (gh auth login)"
      echo "  2. 文件 $AOTO_WORKFLOW_FILE 是否存在 (gh workflow list)"
      echo "  3. 是否有仓库管理员权限"
      exit 1
    fi
    ;;

  2)
    handle_manual_workflow "$AOTO_WORKFLOW_FILE" "XT-Bot 主流程"
    ;;
  3)
    handle_manual_workflow "$INI_WORKFLOW_FILE" "INI 初始化流程"
    ;;
esac