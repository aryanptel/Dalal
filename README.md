<div align="center">
  <h1>🚀 Dalal AI</h1>
  <p><strong>The Ultimate Web Chat Orchestrator</strong></p>
  <p>
    <img src="https://img.shields.io/badge/Python-3.9%2B-blue.svg" alt="Python 3.9+" />
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License MIT" />
    <img src="https://img.shields.io/badge/UI-Streamlit-FF4B4B.svg" alt="Streamlit UI" />
  </p>
  <p>Connect to major AI models simultaneously, avoid API limits, and orchestrate them all from one powerful interface.</p>
</div>

---

## 🐝 Flagship Feature: AI Swarm Mode

Unleash the combined power of multiple AI models! Dalal AI's exclusive **Swarm Mode** allows you to assign a **Lead Moderator** (e.g., ChatGPT) and multiple **Worker Models** (e.g., Claude, Gemini, DeepSeek). 

In an intelligent 4-Phase Swarm Loop, the Moderator analyzes your complex prompt, delegates sub-tasks to the chosen Worker models, synthesizes their distinct perspectives, and delivers a comprehensive, unified answer.

> *"Why consult one AI when you can have a board of AI directors?"*

---

## ✨ Key Features

- **🌐 Unified Hub:** Chat with **ChatGPT, Claude, Gemini, DeepSeek, Kimi, HuggingChat,** and **Meta AI** without switching tabs.
- **💰 Zero API Costs:** Connects directly to your browser's DOM via remote debugging. Bypass API fees by using your existing web sessions!
- **🧠 Seamless Context:** Preserves your chat history across sessions and models. Switch between AI models mid-conversation without losing context.
- **💻 Dual Interface:** Enjoy the sleek **Streamlit UI** or run directly in your terminal via **CLI Mode**.
- **⚙️ Highly Configurable:** Fine-tune delays, selectors, and browser behaviors via `config.yaml`.

---

## 🛠️ Prerequisites

- **Python 3.9+**
- A compatible Chromium-based browser (Edge or Brave by default)
- Required Python packages: `playwright`, `pyyaml`, `pyperclip`, `colorama`, `streamlit`, `scikit-learn`, `numpy`

---

## 📦 Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/Dalal.git
   cd Dalal
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

---

## 🚀 Setup & Usage

### 1. Launch Browser with Remote Debugging
Dalal AI connects to a live browser session. You must start your browser with the remote debugging port open.
   
**Windows (Edge Example):**
```cmd
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --user-data-dir="C:\selenium\AutomationProfile"
```
*(You can adjust the path to your browser of choice)*

### 2. Log into AI Platforms
Open tabs to the platforms you want to use (ChatGPT, Claude, Gemini, etc.) and log in manually.

### 3. Run the Orchestrator
   
**For the graphical UI:**
```bash
streamlit run dalal_ai/ui/app.py
```
*(Or simply run the included `run_ui.py` / `run.bat` helpers)*

**For the terminal CLI:**
```bash
python main.py
```

---

## 📚 Documentation

For a deeper dive into how Dalal AI is built and how to use its advanced features, check out our dedicated documentation:
- [📖 User Guide](documents/GUIDE.md) - Comprehensive setup and usage instructions.
- [🏗️ Detailed Design](documents/DETAILED_DESIGN.md) - Architecture and component breakdown.
- [🤖 LLM Reference](documents/DALAL_AI_COMPLETE_LLM_REFERENCE.md) - Technical reference for the underlying LLM logic.

---

## ⚙️ Configuration

All settings—including timing logic and CSS selectors for the models—are located in `config.yaml`. If any platform changes their DOM structure, you can easily update the selectors there without touching the code!

---

## 🤝 Contributing

We love contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to get started, report bugs, or submit pull requests.

## 📜 Code of Conduct

Please review our [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) to ensure a welcoming environment for everyone.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
