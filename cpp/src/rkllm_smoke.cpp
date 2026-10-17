// 板上 RKLLM smoke（对齐 rknn-llm release-v1.2.1 API）
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <mutex>
#include <string>

#include "rkllm.h"

struct Acc {
  std::mutex mu;
  std::string text;
  int tokens = 0;
  bool error = false;
  std::chrono::steady_clock::time_point first_token{};
  bool got_first = false;
};

static int callback(RKLLMResult* result, void* userdata, LLMCallState state) {
  auto* acc = static_cast<Acc*>(userdata);
  std::lock_guard<std::mutex> lock(acc->mu);
  if (state == RKLLM_RUN_ERROR) {
    acc->error = true;
    return 0;
  }
  if (state == RKLLM_RUN_NORMAL && result && result->text) {
    if (!acc->got_first) {
      acc->first_token = std::chrono::steady_clock::now();
      acc->got_first = true;
    }
    acc->text += result->text;
    acc->tokens += 1;
  }
  return 0;
}

static long read_rss_kb() {
  std::ifstream in("/proc/self/status");
  std::string key;
  long kb = -1;
  while (in >> key) {
    if (key == "VmRSS:") {
      in >> kb;
      break;
    }
    in.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
  }
  return kb;
}

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "Usage: " << argv[0]
              << " <model.rkllm> [user_prompt] [max_new_tokens] [max_context] [system_prompt]\n";
    return 1;
  }
  const char* model = argv[1];
  std::string user = argc > 2 ? argv[2] : "用一句话介绍你自己。";
  int max_new = argc > 3 ? std::atoi(argv[3]) : 64;
  int max_ctx = argc > 4 ? std::atoi(argv[4]) : 512;
  std::string system = argc > 5 ? argv[5] : "You are a helpful assistant.";

  RKLLMParam param = rkllm_createDefaultParam();
  param.model_path = model;
  param.max_context_len = max_ctx;
  param.max_new_tokens = max_new;
  param.top_k = 1;
  param.top_p = 0.9f;
  param.temperature = 0.1f;
  param.repeat_penalty = 1.1f;
  param.frequency_penalty = 0.0f;
  param.presence_penalty = 0.0f;
  param.skip_special_token = true;
  param.extend_param.base_domain_id = 0;
  param.extend_param.embed_flash = 1;

  Acc acc;
  LLMHandle handle = nullptr;
  auto t_load0 = std::chrono::steady_clock::now();
  int ret = rkllm_init(&handle, &param, callback);
  auto t_load1 = std::chrono::steady_clock::now();
  if (ret != 0 || !handle) {
    std::cerr << "rkllm_init failed: " << ret << "\n";
    return 2;
  }
  double load_ms =
      std::chrono::duration<double, std::milli>(t_load1 - t_load0).count();
  long rss_after_load = read_rss_kb();

  // Qwen chat template
  rkllm_set_chat_template(handle, system.c_str(), "<|im_start|>user\n", "<|im_end|>\n<|im_start|>assistant\n");

  RKLLMInput input;
  std::memset(&input, 0, sizeof(input));
  input.input_type = RKLLM_INPUT_PROMPT;
  input.role = "user";
  input.prompt_input = const_cast<char*>(user.c_str());

  RKLLMInferParam infer;
  std::memset(&infer, 0, sizeof(infer));
  infer.mode = RKLLM_INFER_GENERATE;
  infer.keep_history = 0;

  auto t0 = std::chrono::steady_clock::now();
  ret = rkllm_run(handle, &input, &infer, &acc);
  auto t1 = std::chrono::steady_clock::now();
  if (ret != 0 || acc.error) {
    std::cerr << "rkllm_run failed: " << ret << " error=" << acc.error << "\n";
    rkllm_destroy(handle);
    return 3;
  }

  double e2e_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
  double ttft_ms = acc.got_first
                       ? std::chrono::duration<double, std::milli>(acc.first_token - t0).count()
                       : -1.0;
  double toks = acc.tokens > 1 && e2e_ms > ttft_ms
                    ? (acc.tokens - 1) * 1000.0 / (e2e_ms - ttft_ms)
                    : (e2e_ms > 0 ? acc.tokens * 1000.0 / e2e_ms : 0.0);
  long rss_end = read_rss_kb();

  std::cout << "===== OUTPUT =====\n" << acc.text << "\n";
  std::cout << "===== METRICS =====\n";
  std::cout << "load_ms=" << load_ms << "\n";
  std::cout << "ttft_ms=" << ttft_ms << "\n";
  std::cout << "e2e_ms=" << e2e_ms << "\n";
  std::cout << "tokens=" << acc.tokens << "\n";
  std::cout << "tok_s=" << toks << "\n";
  std::cout << "rss_after_load_kb=" << rss_after_load << "\n";
  std::cout << "rss_end_kb=" << rss_end << "\n";
  std::printf(
      "JSON{\"model\":\"%s\",\"load_ms\":%.2f,\"ttft_ms\":%.2f,\"e2e_ms\":%.2f,\"tokens\":%d,"
      "\"tok_s\":%.3f,\"rss_after_load_kb\":%ld,\"rss_end_kb\":%ld}\n",
      model, load_ms, ttft_ms, e2e_ms, acc.tokens, toks, rss_after_load, rss_end);

  rkllm_destroy(handle);
  return 0;
}
