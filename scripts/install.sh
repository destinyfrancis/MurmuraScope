#!/bin/bash
set -e

# MurmuraScope One-liner Installer
# Usage: curl -fsSL https://... | bash

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================= ⬡ MurmuraScope ⬡ =========================${NC}"
echo -e "正在初始化 MurmuraScope 部署環境..."

# 1. 檢測作業系統
OS="$(uname -s)"
case "${OS}" in
    Linux*)     machine=Linux;;
    Darwin*)    machine=Mac;;
    *)          machine="UNKNOWN:${OS}"
esac

echo -e "偵測到作業系統: ${machine}"

# 2. 檢測 Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}錯誤: 未偵測到 Docker。${NC}"
    echo -e "請先安裝 Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo -e "${RED}錯誤: Docker 已安裝但未啟動。${NC}"
    echo -e "請啟動 Docker Desktop 或 Docker Engine。"
    exit 1
fi

# 3. 獲取代碼 (如果不存在)
if [ ! -d "MurmuraScope" ]; then
    echo -e "正在從 GitHub 克隆存儲庫..."
    git clone https://github.com/destinyfrancis/MurmuraScope.git
    cd MurmuraScope
else
    echo -e "已在 MurmuraScope 目錄中。"
fi

# 4. 設置環境變量
if [ ! -f ".env" ]; then
    echo -e "正在生成 .env 文件..."
    cp .env.example .env
    # 生成驗證密鑰
    AUTH_SECRET=$(openssl rand -hex 32)
    sed -i '' "s/your-secret-key-here/${AUTH_SECRET}/g" .env 2>/dev/null || \
    sed -i "s/your-secret-key-here/${AUTH_SECRET}/g" .env
fi

# 5. 引導模式選擇
echo -e "\n${BLUE}模式選擇 (Mode Selection):${NC}"
echo -e "1) 展示模式 (Demo Mode) - 無需 API Key，使用預置腳本"
echo -e "2) 實戰模式 (Live Mode) - 需要 OpenRouter API Key"
read -p "請輸入選擇 (1 或 2, 默認為 1): " MODE_CHOICE

if [ "$MODE_CHOICE" == "2" ]; then
    read -p "請輸入 OpenRouter API Key: " OR_KEY
    if [ -n "$OR_KEY" ]; then
        sed -i '' "s/DEMO_MODE=false/DEMO_MODE=false/g" .env 2>/dev/null || \
        sed -i "s/DEMO_MODE=false/DEMO_MODE=false/g" .env
        
        # Replace key placeholder
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s/OPENROUTER_API_KEY=.*/OPENROUTER_API_KEY=${OR_KEY}/g" .env
        else
            sed -i "s/OPENROUTER_API_KEY=.*/OPENROUTER_API_KEY=${OR_KEY}/g" .env
        fi
    else
        echo -e "${RED}未檢測到 Key，將回退到展示模式。${NC}"
        sed -i '' "s/DEMO_MODE=false/DEMO_MODE=true/g" .env 2>/dev/null || \
        sed -i "s/DEMO_MODE=false/DEMO_MODE=true/g" .env
    fi
else
    echo -e "已選擇展示模式。"
    sed -i '' "s/DEMO_MODE=false/DEMO_MODE=true/g" .env 2>/dev/null || \
    sed -i "s/DEMO_MODE=false/DEMO_MODE=true/g" .env
fi

# 6. 啟動容器
echo -e "\n${BLUE}正在啟動服務...${NC}"
docker compose pull
docker compose up -d

# 7. 等待健康檢查
echo -e "正在等待服務就緒..."
MAX_RETRIES=30
COUNT=0
until $(curl --output /dev/null --silent --head --fail http://localhost:5001/api/health); do
    printf '.'
    sleep 2
    COUNT=$((COUNT+1))
    if [ $COUNT -eq $MAX_RETRIES ]; then
        echo -e "${RED}\n超時: 服務啟動失敗，請查看 docker logs。${NC}"
        exit 1
    fi
done

echo -e "${GREEN}\n================================================================${NC}"
echo -e "${GREEN}⬡ 部署成功！${NC}"
echo -e "後端 API: http://localhost:5001"
echo -e "前端 UI: http://localhost:8080"
echo -e "${GREEN}================================================================${NC}"

# 8. 打開瀏覽器 (Mac)
if [[ "$OSTYPE" == "darwin"* ]]; then
    open http://localhost:8080
fi
