# RK3588S 端侧可验证控制 Agent

在 Orange Pi 5（RK3588S / 8GB）上，把自然语言变成 **可验证、可执行、可审计** 的设备动作。

```
自然语言
  ├─ 规则层（越权/注入/越界/歧义/易混淆通道）── 微秒级拒答或澄清
  └─ RKLLM（合法软控制）→ Schema 校验 → JSON 修复重试
           → 高危二次确认 → MockDevice → AuditLog
```

**不是聊天机器人，也不是知识库 RAG。** 面试主线：端侧约束下的可控生成 + 消融证据。

简历表述见 [docs/简历表述.md](docs/简历表述.md)。

## 实机结果（可写进简历）

硬件：Orange Pi 5 / `rk3588s` / 8GB / TF；RKLLM **1.2.1**（板载 1.0.1 不兼容，已旁路）。

### 模型推理对照

| 模型 | 加载 | TTFT | tok/s | RSS |
| --- | ---: | ---: | ---: | ---: |
| Qwen2.5-**0.5B** W8A8 | 1.2 s | **82 ms** | **26.2** | 640 MiB |
| Qwen2.5-**1.5B** W8A8 | 2.3 s | 199 ms | 10.9 | 1.6 GiB |

### 消融：规则+LLM vs 纯 LLM（30 条评测集）

| 方案 | 正确率 | 说明 |
| --- | ---: | --- |
| **Hybrid（规则+LLM）** | **30/30 = 100%** | 规则命中率 60% |
| LLM-only | 14/30 = **46.7%** | 合法指令仍约 91%，安全类全挂 |
| 提升 | **+53.3 pt** | 见 `bench/logs/ablation_summary.json` |

纯 LLM 在 forbidden / inject / out_of_range / ambiguous / unsupported 上正确率 **0%**；合法简单类仍有 ~91%。说明：**小模型能执行，但不能独自守安全边界。**

### 控制链路延迟（0.5B）

| 类型 | Hybrid P50 | LLM-only P50 |
| --- | ---: | ---: |
| 越权拒答 | **0.04 ms** | 2503 ms |
| 歧义澄清 | **0.05 ms** | 973 ms |
| 合法调阈值 | ~1.3 s | ~1.3 s |
| 高危静音（待确认） | ~2.2 s | ~2.2 s |

安全路径不走 NPU；合法路径才付推理成本。

## 目录

```
├── schemas/              动作 JSON Schema
├── configs/              system prompt / policy
├── python/               规则、校验、流水线、评测、HTTP、延迟压测
├── cpp/                  rkllm_smoke / rkllm_control（常驻）
├── third_party/rkllm/    RKLLM 1.2.1 头文件 + aarch64 .so
├── data/eval/            评测集 cases.jsonl
├── bench/logs/           消融与延迟摘要
├── scripts/              同步、消融、演示、HTTP 启动
└── docs/                 计划 / 简历表述
```

## 板上命令

工作目录：`/root/control_agent`

```bash
# 消融一键
bash scripts/run_ablation_on_board.sh

# 1 分钟演示（合法 / 拒答 / 确认 / 审计）
CONTROL_BACKEND=rkllm bash scripts/demo_once.sh

# HTTP
bash scripts/start_http_on_board.sh   # :8787
# POST /v1/control  {"text":"把检测灵敏度调到 0.7"}
```

本机假模型：

```bash
python3 python/run_eval.py --backend fake
python3 python/demo_cli.py
```

## 技术要点（面试可讲）

1. **版本对齐**：板载 `librkllmrt` 1.0.1 加载 1.2.1 模型直接 abort；仓库锁定 1.2.1 runtime。
2. **常驻推理**：`rkllm_control` stdin/stdout JSON 协议，避免每条指令冷加载。
3. **可验证输出**：Schema + 策略；校验失败可 1 次修复重试；高危需「确认执行」。
4. **消融证据**：不用感觉说「规则有用」，用 46.7% → 100% 和拒答延迟对比说话。

## 范围边界

不做：通用闲聊、开放联网、真 root 权限、7B 硬上、从零预训练。  
执行器第一版为 `MockDevice`，接口与真设备解耦。
