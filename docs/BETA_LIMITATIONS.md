# Beta Limitations

ILX AI CLI v0.3 is in **limited public beta**. Known limitations:

## Sandbox

**Status:** Policy-level only  
A permitted subprocess can access the filesystem outside your workspace. Use `permission_mode = ask` and review every command before approving.

See [SANDBOXING.md](SANDBOXING.md) for the full security model.

## MCP Compatibility

**Status:** stdio beta  
JSON-RPC initialize, tools/list, and tools/call are implemented. Not all real-world MCP servers have been tested. MCP resources are not yet supported.

Label: **MCP stdio: beta**

## Platform Support

**Primary:** Windows 11, Python 3.12 (fully tested)  
**Best-effort:** Linux, macOS (CI coverage being added)  
Note: Some readline features require `pyreadline3` on Windows (`pip install ilx-ai-cli[readline]`).

## Live Model Quality

Output quality depends entirely on your configured AI model. Local models (Ollama) vary widely. Tests that evaluate model output are non-deterministic by nature and excluded from release CI.

## Patch Editing

The test-fix loop uses `git apply` for patches. Fuzzy patching may fail on files with significant drift from the training context. Rollback on failed patches is not yet automatic.

## Streaming Interruption

If a streaming response is interrupted (network cut, Ctrl+C during stream), the response will be truncated. The partial response is not automatically retried.

## Reporting Issues

https://github.com/ilxstudio/ilx-ai-cli/issues
