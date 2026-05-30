# OMS+WMS+TMS 一体化供应链管理系统

企业级订单管理(OMS)、仓储管理(WMS)、终端管理(TMS)一体化系统。

## 技术栈

- **后端**: Python 3.12+ / FastAPI
- **数据库**: PostgreSQL 16
- **缓存**: Redis 7
- **消息队列**: RabbitMQ
- **部署**: Docker + Nginx

## 开发环境

### 前置要求
- Python 3.12+
- Docker & Docker Compose

### 快速开始

```bash
# 安装依赖
pip install .

# 复制环境配置
cp .env.example .env

# 启动基础设施 (PostgreSQL + Redis + RabbitMQ)
docker-compose up -d postgres redis rabbitmq

# 启动应用
uvicorn src.main:app --reload

# 访问API文档
# http://localhost:8000/docs
```

### Docker 一键启动

```bash
docker-compose up -d
```

### 运行测试

```bash
pip install pytest pytest-asyncio pytest-cov httpx
pytest --cov=src --cov-report=term -v
```

## 项目结构

```
oms-wms-tms/
├── src/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 全局配置
│   ├── api/                 # API 路由
│   ├── core/                # 核心工具
│   ├── models/              # SQLAlchemy 模型
│   ├── oms/                 # 订单管理
│   ├── wms/                 # 仓储管理
│   ├── tms/                 # 终端管理
│   ├── barcode/             # 条码服务
│   └── ml/                  # 机器学习
├── tests/                   # 测试用例
├── docker/                  # Docker 配置
└── docker-compose.yml       # 服务编排
```
