# 阶段 0：板上 RKLLM 点亮（已完成）

## 结论

- 板载 `/usr/lib/librkllmrt.so` 为 **1.0.1**，与 HF 上 1.2.1 模型不兼容（加载即 abort）。
- 已改用仓库内 `third_party/rkllm`（**release-v1.2.1**），`LD_LIBRARY_PATH` / rpath 指向该 `.so`。
- Qwen2.5-0.5B W8A8 已跑通。

## 数字

见 `bench/logs/rkllm_smoke_summary.json`：

- load_ms ≈ 1236
- ttft_ms ≈ 82
- tok_s ≈ 26.2
- rss ≈ 640 MiB

## 告警

`rknpu driver 0.9.6`，runtime 建议 0.9.7。暂不升级驱动，先推进业务。
