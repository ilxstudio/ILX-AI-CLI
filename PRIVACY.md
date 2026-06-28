# Privacy Policy

## What Data Leaves Your Machine

ILX AI CLI is local-first. Data leaves your machine **only** when you use a cloud provider.

| Action | Data Sent | Destination |
|--------|-----------|-------------|
| Chat with Ollama | Prompt, conversation history | Local Ollama only |
| Chat with Anthropic | Prompt, conversation history | Anthropic API |
| Chat with OpenAI | Prompt, conversation history | OpenAI API |
| Chat with Groq | Prompt, conversation history | Groq API |
| Chat with Gemini | Prompt, conversation history | Google API |
| `/fetch <url>` | The URL you provide | That website |
| `/research` | Search queries | Configured search API |

## What Stays on Your Machine

| Data | Location |
|------|----------|
| Configuration | `~/.ilx_cli/config.json` |
| API keys | OS keychain (via `keyring`) |
| Audit logs | `~/.ilx_cli/logs/audit.log` |
| Session history | `~/.ilx_cli/sessions/` |
| Workspace indexes | `<workspace>/.ilx_cli/` |
| Crash reports | `~/.ilx_cli/crashes/` |

## ILX Studio Collects Nothing

ILX Studio has no servers receiving your data. The tool communicates directly between your machine and the AI provider you configure.

## Local-Only Mode

To run with zero data leaving your machine:

1. Install Ollama locally: https://ollama.ai
2. Run `ilx` → set provider to `ollama` with `/provider ollama`
3. Choose a local model: `/model codellama:7b`

In this configuration, nothing leaves your machine.

## Data Retention

- Audit logs rotate at 5 MB, keeping 5 generations (~25 MB max)
- Session history is stored indefinitely until deleted with `/session clear`
- Crash reports accumulate until cleared with `/crashes clear`
