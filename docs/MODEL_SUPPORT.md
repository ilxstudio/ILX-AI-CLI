# Model Support

## Supported Providers

| Provider | Status | Setup |
|----------|--------|-------|
| Ollama (local) | Stable | Install Ollama, run `ollama pull <model>` |
| Anthropic | Stable | API key required |
| OpenAI | Stable | API key required |
| Groq | Beta | API key required |
| Google Gemini | Beta | API key required |
| Meta Llama (via Ollama) | Stable | Use Llama models through local Ollama |

## Recommended Local Models (Free, Private)

| Use Case | Model | Pull Command |
|----------|-------|-------------|
| General coding | `codellama:7b` | `ollama pull codellama:7b` |
| Fast chat | `llama3.2:3b` | `ollama pull llama3.2:3b` |
| Deep analysis | `llama3.1:8b` | `ollama pull llama3.1:8b` |
| Code review | `deepseek-coder:7b` | `ollama pull deepseek-coder:7b` |
| Fast code | `qwen2.5-coder:3b` | `ollama pull qwen2.5-coder:3b` |

## Recommended Cloud Models

| Provider | Model | Speed | Notes |
|----------|-------|-------|-------|
| Anthropic | `claude-sonnet-4-6` | Medium | Excellent coding; prompt caching supported |
| Anthropic | `claude-haiku-4-5-20251001` | Fast | Good for quick tasks |
| OpenAI | `gpt-4o` | Medium | Strong reasoning |
| OpenAI | `gpt-4o-mini` | Fast | Cost-efficient |
| Groq | `llama-3.3-70b-versatile` | Very Fast | Good quality, low latency |

## Model Routing

ILX includes automatic model routing (`/route`):

| Strategy | Behavior |
|----------|----------|
| `auto` | Routes by task complexity |
| `free-only` | Local/free models only |
| `local-only` | Forces Ollama |
| `quality` | Always uses highest-quality configured model |

Configure with: `/route set <strategy>`

## Setting Up a Provider

```
# In the ILX REPL:
/provider anthropic
/apikey set          # stored securely in OS keychain
/model claude-sonnet-4-6
/status              # verify configuration
```

## Context Windows

| Provider | Model | Context |
|----------|-------|---------|
| Ollama | Most models | 4096 tokens (use `/numctx` to adjust) |
| Anthropic | claude-sonnet-4-6 | 200k tokens |
| OpenAI | gpt-4o | 128k tokens |
| Groq | llama-3.3-70b | 128k tokens |

Use `/numctx <N>` to set the context window for local Ollama models.
Use `/compact` to summarize long conversations and free up context.
