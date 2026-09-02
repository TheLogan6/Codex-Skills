---
name: markdown-todo-answerer
description: Read a Markdown file and answer its TODO questions in place. Use when a user asks to complete, respond to, or fill in TODO questions without removing the original TODO text.
---

# Markdown TODO Answerer

Read the specified Markdown file and answer every TODO question directly in that file.

## Instructions

1. Find TODO items that contain a question or request for an answer.
2. Keep each original TODO item unchanged.
3. Add the answer immediately after its TODO item.
4. Use the document's language and match its existing Markdown style.
5. Do not change unrelated content.
6. Save the edited Markdown file.

Use this default format when the document has no established answer format:

```markdown
TODO: <original question>

Answer: <answer>
```

If a TODO is ambiguous or lacks necessary information, keep it and add a short answer stating what information is missing. Never invent unsupported facts.
