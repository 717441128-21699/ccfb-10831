# 运维与操作说明

## 环境准备（一次性）

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

## 分步运行

```powershell
# 1. 建库 + 生成 30 天确定性真值 + 预生成 m4 周报 PDF
.\.venv\Scripts\python.exe -m scripts.init_data

# 2. 启动 4 个仿真市场（保持该终端运行；端口 8011-8014）
.\.venv\Scripts\python.exe -m scripts.run_mocks

# 3. 另开终端，跑完整 30 天采集窗口
.\.venv\Scripts\python.exe -m scripts.collect run_window

# 4. 真值逐条比对，报告同时写入 runtime/reports/truth_verification.json
.\.venv\Scripts\python.exe -m harness.verify

# 5. 启动管理后台（http://127.0.0.1:8000）
.\.venv\Scripts\python.exe -m admin.main
```

也可一键完成 1~4（仿真站由脚本自行起停）：

```powershell
.\.venv\Scripts\python.exe -m scripts.setup_all
```

## 采集 CLI 常用命令

```powershell
python -m scripts.collect day m1 2026-10-20   # 单市场单日
python -m scripts.collect backfill m1         # 只补真缺的开市日（休市自动跳过）
python -m scripts.collect missing m2          # 查看缺数日
python -m scripts.reset_collector             # 清采集库与快照（真值库保留）
```

## 后台五个页面

| 页面 | 路径 | 能力 |
|---|---|---|
| 市场管理 | `/markets` | 市场注册表、允许价格类型、启用/停用、最近采集状态 |
| 采集日历 | `/calendar?market_id=m1` | 开市/休市、应采实采数、缺数日高亮、页面内手动补采 |
| 原始快照 | `/snapshots` | 页面截图、PDF、JSON 报文按类型/市场筛选与预览 |
| 价格库 | `/prices` | 按日期/价格类型/状态筛选，每条可跳原始快照 |
| 异常价格 | `/anomalies` | 扣留单复核：采信转正 / 驳回，带备注 |

## 数据落点（均在 runtime/，已 gitignore）

- `collector.db`：采集端业务库（日历/快照/价格/异常/字体映射/任务）
- `mock_truth.db`：仿真站私有真值库，只供 harness 比对，采集端不读取
- `snapshots/<market>/`：截图、PDF、JSON 报文
- `fonts/m1/`：每日生成的混淆字体及仿真站私有映射（采集端不读映射）
- `pdfs/`：m4 周报 PDF 原件
- `reports/truth_verification.json`：最近一次比对结果

## 关键设计约束

- `prices.price_type` 有 SQLite CHECK 约束，且写入层按市场注册表二次校验，
  批发价/产地价/到岸价物理上无法串写。
- 异常（spike_high/spike_low/cross_mismatch）一律先写 `anomalies` 并在
  `prices` 留 `status='held'` 行；复核前不进入 verified，复核后转正或驳回。
- 仿真真值由 `(市场,商品,类型,日期)` 哈希生成，完全可复现，无随机不可重放问题。
