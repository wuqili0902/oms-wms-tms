# dev/ — 开发调试脚本归档

本目录存放一次性/临时开发调试脚本与快照文件,保留用于审计与排查,不代表当前项目资产。

## 内容

| 文件 | 用途 |
|------|------|
| `test_e2e.py` / `test_wms_e2e.py` | 早期本地 E2E 冒烟脚本(连 localhost:8000)。正式 E2E 在 `tests/test_e2e/` |
| `check_tables.py` | 连接本地 PG 列出表(psycopg2) |
| `_list_errors.py` | 列出 ruff 指定规则错误 |
| `pyright_out.txt` / `ruff_remaining.txt` / `temp_cov.txt` | 历史 lint / 覆盖率的输出快照 |

## 维护约定

- 新的临时调试脚本一律放本目录,勿再放进仓库根目录。
- 脚本往往硬编码本机路径/凭据,仅限本地开发使用,勿加入 CI。
