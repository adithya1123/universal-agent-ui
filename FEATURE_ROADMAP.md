# Universal Agent UI — Feature Roadmap

_Last updated: 2026-06-27_

Prioritized list of features to implement, from highest impact to nice-to-have.

---

## Short-term (high impact, small scope)

| Feature | What's missing | Why it matters |
|---|---|---|
| **Agent selector UI** | Backend has `GET /api/agents`, frontend hardcodes `DEFAULT_AGENT_ID` | Users can't switch between multiple registered agents |
| **Delete confirmation dialog** | Session delete is immediate, no confirmation | Accidental deletes are irreversible |
| **Session search/filter** | No search input in chats tab | Hard to find specific conversations as list grows |
| **Connection status indicator** | No visual indicator for backend reachability | All API failures are silent; users see blank chat with no explanation |

## Medium-term (moderate scope, good UX wins)

| Feature | What's missing | Why it matters |
|---|---|---|
| **File/multimodal upload** | Paperclip button renders but has no handler | Component is named `MultimodalInput` but only supports text |
| **Session date grouping** | `formatDate()` in `utils.ts` is dead code; sessions aren't grouped by "Today" / "Yesterday" | Long session lists are hard to navigate |
| **Code syntax highlighting** | Code blocks render as plain `<pre><code>` | Reduces readability for technical users (primary audience) |
| **Error state + retry in session list** | Session fetch fails silently — shows "No chat history" while loading or after error | Users can't distinguish "loading" from "empty" from "broken" |
| **Message copy button** | No copy button on messages or code blocks | Standard chat UX users expect |
| **Scroll-to-bottom button** | No FAB to jump to latest in long conversations | Auto-scroll on new message disrupts reading history |

## Long-term (larger scope, new functionality)

| Feature | What's missing | Why it matters |
|---|---|---|
| **Results index UI** | Backend has `GET /sessions/{id}/results`, frontend never calls it | Users can't see per-turn CSV metadata from the UI |
| **`delete_all_memories` endpoint** | `UserMemoryService.delete_all_memories()` exists but is not exposed via API | No way to bulk-clear memories |
| **Checkpoint history / forking** | `AsyncLangGraphSupervisor.get_checkpoint_history()` and `update_checkpoint_state()` exist but have no API routes | Time travel and conversation branching not accessible from frontend |
| **Session metadata endpoint** | Backend has `GET /sessions/{id}/metadata` but frontend never calls it | Thread metadata (user_id, correlation_id, created_at) not surfaced in UI |
| **`list_threads_for_correlation` endpoint** | Client + service methods exist but no API route | Can't query threads by correlation_id via HTTP |

## Tech debt (cleanup, no user-facing change)

| Item | Location | Impact |
|---|---|---|
| Remove `console.log` statements | `route.ts`, `chat.tsx`, `page.tsx` | Production noise, minor performance |
| Remove unused dependencies | `@copilotkit/react-ui`, `date-fns`, `framer-motion` in `package.json` | Smaller install, cleaner deps |
| Remove dead code | `app/auth.py`, `app/adapters/`, `TestReport` class, `_NS_MESSAGES`, unused props in `chat-header.tsx` and `message.tsx` | Less code to maintain |
| Remove paperclip button | `multimodal-input.tsx` — placeholder with no handler | Misleading UI element |
| CORS restriction | Backend only allows `localhost:3000` | Breaks if frontend runs on different port/domain |

---

## How to contribute

Each feature should get a playbook entry in `AGENTS/playbooks/` when implemented.
See the [Codebase Documenter](AGENTS/00_agent_instructions.md) skill for the
incremental update workflow.
