"""
LLM 调用封装
统一封装大模型调用，支持 JSON 模式输出
"""
import os
import json
import re
import time
import subprocess
import warnings
from typing import Optional, Any, Dict
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("LLM_API_KEY", "")
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
JUDGE_MODEL = os.getenv("LLM_JUDGE_MODEL", "gpt-4o")
# 最大重试次数
MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
# 重试间隔（秒）
RETRY_DELAY = float(os.getenv("LLM_RETRY_DELAY", "2"))
# 请求超时（秒）
TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))
# OpenRouter 需要的额外 header
EXTRA_HEADERS = {}
if "openrouter" in BASE_URL.lower():
    EXTRA_HEADERS = {
        "HTTP-Referer": os.getenv("APP_URL", "https://market-intel.local"),
        "X-Title": os.getenv("APP_NAME", "Market Intelligence Platform"),
    }


def chat(
    prompt: str,
    system_prompt: str = "你是一个专业的分析师。",
    json_mode: bool = False,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 1000,
) -> str:
    """
    调用 LLM，返回文本结果
    使用 curl 子进程以规避 macOS 系统 Python LibreSSL 兼容性问题
    """
    use_model = model or MODEL
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    body: Dict[str, Any] = {
        "model": use_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if json_mode:
        body["response_format"] = {"type": "json_object"}

    # 带重试的请求
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            content = _curl_post(
                url=f"{BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                    **EXTRA_HEADERS,
                },
                body=body,
                timeout=TIMEOUT,
            )
            return content
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAY * (attempt + 1)
                err_short = str(e)[:80]
                print(f"[LLM] 请求失败（第 {attempt+1}/{MAX_RETRIES} 次）: {err_short}，{delay}s 后重试...")
                time.sleep(delay)
            else:
                print(f"[LLM Error] 重试 {MAX_RETRIES} 次后仍然失败: {e}")
                raise last_error


def _curl_post(url: str, headers: dict, body: dict, timeout: int = 120) -> str:
    """
    使用 curl 子进程发送 POST 请求，返回响应中的 message.content
    规避 Python LibreSSL 的 TLS 兼容性问题
    """
    import tempfile

    # 把 body 写到临时文件，避免命令行参数过长
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(body, f, ensure_ascii=False)
        body_file = f.name

    try:
        cmd = ["curl", "-s", "-X", "POST", url]
        for k, v in headers.items():
            cmd += ["-H", f"{k}: {v}"]
        cmd += ["--data-binary", f"@{body_file}"]
        cmd += ["--max-time", str(timeout)]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )

        if result.returncode != 0:
            raise RuntimeError(f"curl 失败 (code={result.returncode}): {result.stderr[:200]}")

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"响应不是合法 JSON: {result.stdout[:200]}") from e

        if "error" in data:
            raise RuntimeError(f"API 错误: {data['error']}")

        if "choices" not in data or not data["choices"]:
            raise RuntimeError(f"响应格式异常，缺少 choices: {str(data)[:200]}")

        content = data["choices"][0]["message"]["content"]
        if content is None:
            # 有些 reasoning 模型 content 可能为空，试试 reasoning 字段
            content = data["choices"][0]["message"].get("reasoning", "")
            if not content:
                raise RuntimeError("响应内容为空")

        # GLM 等 reasoning 模型可能在 content 里输出推理过程 + JSON
        # 如果 content 很长且不含 {，尝试从 reasoning 字段提取
        if "{" not in content:
            reasoning = data["choices"][0]["message"].get("reasoning", "")
            if "{" in reasoning:
                content = reasoning

        return content

    finally:
        try:
            os.unlink(body_file)
        except Exception:
            pass


def chat_json(
    prompt: str,
    system_prompt: str = "你是一个专业的分析师，必须输出合法的 JSON。",
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 1000,
    use_json_mode: bool = True,
) -> dict:
    """
    调用 LLM 并解析为 JSON 对象
    支持 response_format=json_object 和 纯文本+提取 两种模式
    """
    # 尝试用 json_mode（如果模型支持）
    if use_json_mode:
        try:
            content = chat(
                prompt=prompt,
                system_prompt=system_prompt,
                json_mode=True,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception:
            # json_mode 失败，降级为普通模式
            content = chat(
                prompt=prompt,
                system_prompt=system_prompt,
                json_mode=False,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
    else:
        content = chat(
            prompt=prompt,
            system_prompt=system_prompt,
            json_mode=False,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    return _extract_json(content)


def _extract_json(text: str) -> dict:
    """
    从模型输出中提取 JSON 对象
    处理：markdown 代码块、思维过程前缀、多余文本、截断等
    """
    text = text.strip()

    # 1. 尝试直接解析
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2. 去掉 markdown 代码块
    if "```" in text:
        match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except Exception:
                pass

    # 3. 找第一个 { 和最后一个 } 之间的内容
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    # 4. 部分 JSON 修复（模型输出被截断，JSON 不完整）
    if start != -1:
        candidate = text[start:]
        # 逐个补全缺失的闭合括号
        for suffix in ['"}', '}', '"}', '"}']:
            try:
                return json.loads(candidate + suffix)
            except Exception:
                pass
        # 尝试按行截取到最后一个完整的字段
        lines = candidate.split("\n")
        for i in range(len(lines), 0, -1):
            fragment = "\n".join(lines[:i]).rstrip().rstrip(",")
            for suffix in ['}', '"}', '"}']:
                try:
                    return json.loads(fragment + suffix)
                except Exception:
                    pass

    # 5. 尝试逐行找 JSON
    lines = text.split("\n")
    for i in range(len(lines)):
        for j in range(len(lines), i, -1):
            candidate = "\n".join(lines[i:j])
            if candidate.strip().startswith("{"):
                try:
                    return json.loads(candidate.strip())
                except Exception:
                    continue

    # 6. 正则提取关键字段（最后兜底）
    result = {}
    m = re.search(r'"summary_zh"\s*:\s*"([^"]*)"', text)
    if m:
        result["summary_zh"] = m.group(1)
    m = re.search(r'"importance"\s*:\s*(\d+)', text)
    if m:
        result["importance"] = int(m.group(1))
    m = re.search(r'"source_name"\s*:\s*"([^"]*)"', text)
    if m:
        result["source_name"] = m.group(1)
    m = re.search(r'"source_url"\s*:\s*"([^"]*)"', text)
    if m:
        result["source_url"] = m.group(1)
    tags_match = re.search(r'"tags"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if tags_match:
        tags = re.findall(r'"([^"]*)"', tags_match.group(1))
        if tags:
            result["tags"] = tags
    if result:
        return result

    raise ValueError(f"无法从输出中提取 JSON: {text[:200]}")
