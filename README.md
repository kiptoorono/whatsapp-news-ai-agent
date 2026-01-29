## AI Agent Trial

This repository contains experiments and utilities for news summarization, semantic search, web scraping, and messaging agents (for example, a WhatsApp agent that uses SambaNova models).

### Prerequisites

- **Python**: 3.10+ recommended
- **Pip**: for installing dependencies
- **SambaNova API access**: valid API keys

### Environment Variables

The project expects the following environment variables to be set:

- **`SAMBA_API_KEY`**: API key for general chat and summarization.
- **`SAMBA_CATEGORIZE_API_KEY`**: API key for categorization and classification.

On Windows PowerShell, you can set them like this (replace with your real keys):

```powershell
$env:SAMBA_API_KEY = "your-samba-chat-key"
$env:SAMBA_CATEGORIZE_API_KEY = "your-samba-categorize-key"
```

For a permanent setting, you can use:

```powershell
setx SAMBA_API_KEY "your-samba-chat-key"
setx SAMBA_CATEGORIZE_API_KEY "your-samba-categorize-key"
```

Restart your terminal after using `setx`.

### WhatsApp Agent Script

The `whats app agent loop.py` script:

- **Opens WhatsApp Web** in a Brave browser instance using Selenium.
- **Monitors incoming messages** from a configured contact.
- **Classifies** whether a message is news-related using SambaNova.
- **Answers** with either:
  - A summarized news answer using the Qdrant search pipeline, or
  - A general chat response via SambaNova.

To run it:

1. **Install dependencies** (example):

   ```powershell
   pip install selenium openai qdrant-client
   ```

2. **Ensure ChromeDriver / Brave paths are correct** in `whats app agent loop.py`.
3. **Set the environment variables** as described above.
4. Run:

   ```powershell
   python "whats app agent loop.py"
   ```

### Other Components

- **`quantsearch.py`**: Search and summarization over Qdrant-stored articles.
- **`gpt_selenium_test.py`** and **web scrapers**: Scripts for scraping news, embedding, and uploading to Qdrant.

Because this repository is experimental, some scripts may be prototypes or partially configured. Review individual files before running them in production settings.

