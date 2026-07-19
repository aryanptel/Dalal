# Dalal AI — File Upload & Vision (Multimodal) Design Document

## 1. Overview
Currently, Dalal AI relies entirely on text-based prompt injection via the browser's `[contenteditable]` input boxes. To support images and documents, we must build a multimodal integration that allows the local orchestrator to pass files seamlessly to the browser context, wait for them to upload, and attach them to the current prompt.

## 2. Challenges & Constraints
Web-based AI platforms use complex, framework-driven (React/Next.js) drag-and-drop or hidden `<input type="file">` elements.
- Playwright's `page.set_input_files()` requires targeting the exact `<input type="file">` node, which may be deeply nested, dynamically created, or absent until a button is clicked.
- File upload processing takes time (e.g., uploading a 5MB PDF to ChatGPT). Sending the prompt before the upload completes will result in the AI ignoring the file.

## 3. Proposed Architecture

### 3.1 UI Modifications (`dalal_ai/ui/`)
- **File Uploader Widget**: Add a `st.file_uploader` in the Streamlit UI (sidebar or chat area) supporting images (`.png`, `.jpg`) and documents (`.pdf`, `.txt`).
- **State Management**: Uploaded files will be temporarily saved to a local `dalal_ai/temp_uploads/` directory so the Playwright worker process has absolute file paths to attach.

### 3.2 Browser Manager Extensions (`dalal_ai/browser/`)
- **Platform Selectors Update**: `config.yaml` must be updated with two new selectors per platform:
  - `file_input_selector`: The CSS selector for the hidden file input (e.g., `input[type="file"]`).
  - `upload_progress_selector`: A selector or heuristic to detect when the upload is finished (e.g., waiting for a loading spinner inside the attachment pill to disappear).
- **`attach_files(platform, file_paths)` Method**:
  1. Bring tab to front.
  2. Locate the file input. If it doesn't exist, try clicking the "attachment/clip" button first to render it into the DOM.
  3. Execute `page.locator(file_input_selector).set_input_files(file_paths)`.
  4. Poll the DOM to ensure the upload is complete before returning control to the Orchestrator.

### 3.3 Context Management (`dalal_ai/core/`)
- Multimodal context is inherently tricky for our manual flagging system.
- If a user uploads an image, we can inject it into the current model's conversation. However, if they switch to another model, we cannot simply "inject" the image via a text prompt.
- **Limitation**: Files are tied to the specific chat thread in the specific model where they were uploaded. They will **not** be transferred automatically when switching models unless we re-upload them.
- For v3.0, we will label file messages in the UI. If a user red-flags a file message and switches models, Dalal AI will attempt to re-upload the cached file to the new model along with the prompt.

## 4. Implementation Steps (v3.0 Roadmap)
1. Add `st.file_uploader` to Streamlit and save to `temp_uploads/`.
2. Map out `input[type="file"]` selectors for ChatGPT, Claude, Gemini, and DeepSeek.
3. Build the Playwright `set_input_files` routine and upload-wait heuristic.
4. Pass file paths along with text in `Orchestrator.send_message()`.
5. Clear `temp_uploads/` periodically to save disk space.
