# 看服务在不在
Get-Process ollama* -ErrorAction SilentlyContinue

# 停
Get-Process ollama* | Stop-Process -Force

# 起（桌面版就点图标；命令行就）
ollama serve

# 跑模型
ollama run risk-qwen

# 退出对话
/bye