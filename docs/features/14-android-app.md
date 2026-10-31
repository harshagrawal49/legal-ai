# 14 · Android app

## What it does
The user-facing app:
- **Home:** *My cases* and *All my documents* tabs, and a feature tour on first use.
- **New case:** describe the case (or skip) and attach PDFs or photos.
- **Case home:** chat, documents, similar cases, brief, and the case summary with sources and conflicts.
- **My documents:** upload, live status, retry, delete (with confirmation), and Timeline & flags.
- **Document view:** *Explained* (language toggle, summary, clauses, legal terms, things to check, Ask
  about this document), the extracted details, and the page text with OCR confidence per page.
- **Chat:** streaming answers, 📎 attachments, `@` document suggestions, citation links and a Sources list.
- **Brief** and **judgment** screens.

## How it is implemented
- **Kotlin + Jetpack Compose (Material 3)**, one ViewModel per screen, Navigation-Compose with optional
  route arguments (e.g. open chat with a document already mentioned, open a document at a cited page).
- **Networking:** Retrofit with kotlinx.serialization; OkHttp SSE for streaming chat into an unbounded
  buffer. Multipart upload uses the system document picker (PDF, JPEG, PNG).
- **Robustness:**
  - background work is polled ("Reading and extracting facts…");
  - every request goes through one error mapper that shows the backend's message;
  - chat tracks each reply's own position, so uploads or a slow history load can't misdirect streamed text;
  - Send and attach are disabled until history has loaded;
  - cancelled explanation requests are ignored.
- **No secrets:** the app talks only to the backend; LLM keys stay on the server.

## Why
| Alternative | Why not |
|---|---|
| Flutter / React Native | The existing app was native Kotlin; Compose gives a modern declarative UI without a rewrite |
| A web app only | The target users are phone-first; photos of documents come from the phone camera |

## Results
- **Built and run successfully** by the team in Android Studio.
- Before the first build, an independent static review found no compile errors and **9 runtime issues**,
  all fixed, including a crash on duplicate list keys, stream events being dropped, and a race that
  wrote text into the wrong chat bubble. A second review of the fixes found nothing new.
- An automated **journey test** calls the backend in the same order as the app's screens and checks that
  every response can be decoded by the app's Kotlin models. That covers 30 data classes and 19 API
  endpoints, all matching.
