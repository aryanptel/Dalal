# Dalal AI 🧠

Dalal AI is a sophisticated local orchestration tool that bridges a single, unified interface (Web UI or CLI) with live web sessions of popular AI models (ChatGPT, Claude, Gemini, DeepSeek, Kimi, HuggingChat, and Meta AI).

It uses advanced Playwright-based browser automation over the Chrome DevTools Protocol (CDP) to seamlessly route your prompts to the right AI tab. When you switch models mid-conversation, Dalal AI injects historical context (either algorithmically or via precise user flags), ensuring your new AI assistant knows exactly what was discussed with the previous one.

## Features

- **Unified Interface:** Chat with several leading AI models from one screen without needing paid API keys.
- **Smart Context Switching:** Switch models mid-chat. Dalal AI automatically injects your past conversation using deterministic red/green flags or a TF-IDF/TextRank mathematical fallback.
- **Thread-Safe Automation:** A robust singleton background worker handles Playwright browser automation, making it completely stable within Streamlit environments.
- **Cross-Platform:** Runs natively on Windows, macOS, and Linux. Built-in compilation scripts generate standalone installers and archives.
- **Organic Interactions:** Simulates human typing, handles JavaScript edge cases (like React event firing), and safely recovers Markdown/LaTeX directly from the DOM using custom JavaScript extractors.

## Setup & Usage

### Prerequisites
- Python 3.8+ (3.10+ recommended)
- Microsoft Edge or Brave browser installed

### Quick Start
1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   python -m playwright install chromium
   ```

2. **Configure your browser:**
   Open `config.yaml` and set `browser.use` to `"edge"` or `"brave"`. The tool will auto-launch the browser on its own separate debug profile.

3. **Run the UI:**
   ```bash
   python -m dalal_ai
   ```
   Or use the terminal CLI:
   ```bash
   python main.py
   ```

## Documentation

For a deep dive into the architecture, configuration, and internal APIs, please see the following documents:

- [User Guide](GUIDE.md) - Detailed setup, configuration, and usage instructions for the Web UI and CLI.
- [Detailed Design Document (DDD & ICD)](DETAILED_DESIGN.md) - Comprehensive technical breakdown of the architecture, Playwright thread management, and context algorithms.
- [Changelog](CHANGELOG) - Version history and updates.

## Building Executables

Dalal AI can be compiled into a standalone application (`.exe`, `.app`, or ELF binary) using PyInstaller.
```bash
python build.py
```
Check the `release/` directory for the output archives and installers.
