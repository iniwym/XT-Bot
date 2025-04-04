#!/bin/zsh
# GitHub Actions 自动化控制器 (macOS 优化版)
# 需要 GitHub CLI ≥ 2.30.0

# 配置区
REPO="iniwym/XT-Bot"
WORKFLOW_FILE="INI-T-Bot.yml"    # 实际工作流文件名
BRANCH="main"
TERMINAL_THEME="Pro"

# 路径配置（使用绝对路径）
SCRIPT_DIR=$(cd "$(dirname "$0")"; pwd)
LOG_DIR="${SCRIPT_DIR}/../logs/action-logs"

# 创建统一目录
mkdir -p "${LOG_DIR}"

# 函数: 带图标的通知
notify() {
  local type=$1
  local msg=$2
  case $type in
    "success")
      osascript -e "display notification \"${msg}\" with title \"工作流完成\" sound name \"Glass\""
      ;;
    "error")
      osascript -e "display notification \"${msg}\" with title \"工作流异常\" sound name \"Basso\""
      ;;
  esac
}

# 步骤 1: 触发工作流
echo "🔄 触发工作流...${WORKFLOW_FILE}...分支...${BRANCH}..."
WORKFLOW_ID=$(gh api "/repos/${REPO}/actions/workflows" --jq ".workflows[] | select(.name == \"INI-T-Bot\") | .id")

TRIGGER_RESULT=$(gh api -X POST "/repos/${REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches" \
  -F ref="${BRANCH}" 2>&1)

if [[ $? -ne 0 ]]; then
  echo "❌ 触发失败: ${TRIGGER_RESULT}"
  notify "error" "触发失败"
  exit 1
fi

# 步骤 2: 可靠获取 Run ID（增加重试机制）
echo "⏳ 获取运行 ID..."
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

echo "📜 启动日志监控窗口..."
# 窗口1: 实时状态跟踪
osascript <<EOD
tell application "Terminal"
  activate
  set tab1 to do script "cd \"${SCRIPT_DIR}\" && gh run watch ${RUN_ID} --exit-status"
  set current settings of tab1 to settings set "${TERMINAL_THEME}"
end tell
EOD

# 窗口2: 详细日志流（自动刷新）
osascript <<EOD
tell application "Terminal"
  activate
  set tab2 to do script "cd \"${SCRIPT_DIR}\" && while true; do gh run view ${RUN_ID} --log; sleep 10; done | tee \"${LOG_DIR}/detail-${RUN_ID}.log\""
  set current settings of tab2 to settings set "${TERMINAL_THEME}"
end tell
EOD

# 步骤 4: 监控状态（增加超时）
echo "⏳ 监控运行状态（最长30分钟）..."
start=$(date +%s)
while true; do
  STATUS=$(gh run view ${RUN_ID} --json status --jq '.status')

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

  if (( $(date +%s) - start > 1800 )); then
    echo "⏰ 运行超时（30分钟）"
    exit 4
  fi
  sleep 20
done
