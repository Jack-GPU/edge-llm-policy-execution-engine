// 常驻 RKLLM 控制进程：stdin 每行一个 JSON {"text":"..."}，stdout 回 {"ok":true,"text":"..."}
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <mutex>
#include <string>

#include "rkllm.h"

// 无外部 json 库：手写极简解析（只取 "text" 字段）
static std::string extract_text_field(const std::string& line) {
  auto key = line.find("\"text\"");
  if (key == std::string::npos) return {};
  auto colon = line.find(':', key);
  if (colon == std::string::npos) return {};
  auto q1 = line.find('"', colon + 1);
  if (q1 == std::string::npos) return {};
  std::string out;
  for (size_t i = q1 + 1; i < line.size(); ++i) {
    char c = line[i];
    if (c == '\\' && i + 1 < line.size()) {
      char n = line[++i];
      if (n == 'n') out.push_back('\n');
      else if (n == 't') out.push_back('\t');
      else if (n == '"') out.push_back('"');
      else if (n == '\\') out.push_back('\\');
      else out.push_back(n);
      continue;
    }
    if (c == '"') break;
    out.push_back(c);
  }
  return out;
}

static std::string json_escape(const std::string& s) {
  std::string o;
  o.reserve(s.size() + 8);
  for (char c : s) {
    switch (c) {
      case '"': o += "\\\""; break;
      case '\\': o += "\\\\"; break;
      case '\n': o += "\\n"; break;
      case '\r': o += "\\r"; break;
      case '\t': o += "\\t"; break;
      default: o.push_back(c);
    }
  }
  return o;
}

struct Acc {
  std::mutex mu;
  std::string text;
  int tokens = 0;
  bool error = false;
  std::chrono::steady_clock::time_point first_token{};
  bool got_first = false;
  void reset() {
    text.clear();
    tokens = 0;
    error = false;
    got_first = false;
  }
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

static std::string read_file(const std::string& path) {
  std::ifstream in(path);
  if (!in) return {};
  return std::string((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "Usage: " << argv[0]
              << " <model.rkllm> [system_prompt_file] [max_new_tokens] [max_context]\n";
    return 1;
  }
  const char* model = argv[1];
  std::string system = argc > 2 ? read_file(argv[2]) : "You are a helpful assistant. Reply with one JSON object only.";
  if (system.empty()) system = "You are a helpful assistant. Reply with one JSON object only.";
  // trim trailing newlines
  while (!system.empty() && (system.back() == '\n' || system.back() == '\r')) system.pop_back();
  int max_new = argc > 3 ? std::atoi(argv[3]) : 128;
  int max_ctx = argc > 4 ? std::atoi(argv[4]) : 1024;

  RKLLMParam param = rkllm_createDefaultParam();
  param.model_path = model;
  param.max_context_len = max_ctx;
  param.max_new_tokens = max_new;
  param.top_k = 1;
  param.top_p = 0.8f;
  param.temperature = 0.1f;
  param.repeat_penalty = 1.05f;
  param.skip_special_token = true;
  param.extend_param.base_domain_id = 0;
  param.extend_param.embed_flash = 1;

  Acc acc;
  LLMHandle handle = nullptr;
  int ret = rkllm_init(&handle, &param, callback);
  if (ret != 0 || !handle) {
    std::cerr << "rkllm_init failed: " << ret << "\n";
    return 2;
  }
  rkllm_set_chat_template(handle, system.c_str(), "<|im_start|>user\n",
                          "<|im_end|>\n<|im_start|>assistant\n");
  std::cerr << "READY\n";
  std::cerr.flush();

  std::string line;
  while (std::getline(std::cin, line)) {
    if (line.empty()) continue;
    if (line == "EXIT") break;
    std::string user = extract_text_field(line);
    if (user.empty()) {
      // 整行当纯文本
      user = line;
    }
    acc.reset();
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
    double e2e = std::chrono::duration<double, std::milli>(t1 - t0).count();
    double ttft = acc.got_first
                      ? std::chrono::duration<double, std::milli>(acc.first_token - t0).count()
                      : -1.0;
    if (ret != 0 || acc.error) {
      std::cout << "{\"ok\":false,\"error\":\"run_failed\",\"rc\":" << ret << "}\n";
      std::cout.flush();
      continue;
    }
    std::cout << "{\"ok\":true,\"text\":\"" << json_escape(acc.text)
              << "\",\"tokens\":" << acc.tokens << ",\"ttft_ms\":" << ttft
              << ",\"e2e_ms\":" << e2e << "}\n";
    std::cout.flush();
  }

  rkllm_destroy(handle);
  return 0;
}
