# Publishing pipeline

**English** · [Українська](README.uk.md)

The n8n workflow that publishes my LinkedIn posts: a queue in Google Sheets, a draft in Telegram,
one tap to approve or reject, then publication through the LinkedIn API.
`workflow.json` is a sanitized export of the version that runs in production (62 nodes).
My IDs, credentials and prompts are replaced with placeholders, so it does nothing until you fill them in.

## How a post moves

1. **Schedule.** Weekdays at 09:00, with backup runs at 11:00 and 13:00.
2. **Pick.** Reads the queue. Rows with a date that is due go first, and a dated post owns its day. Otherwise the next undated `ready` row.
3. **Reserve.** The row becomes `pending`, so the next run cannot take it twice.
4. **Text.** `type` decides: `raw` is published as written, `temat` and `projekt` are written by Claude from your note.
5. **Approve.** The draft and its media arrive in Telegram with approve and reject buttons. The wait is 20 hours.
6. **Publish.** Text, one image, an image gallery (a Drive folder), a PDF carousel or a video.
7. **Record.** `done` with the time, the final text and the post URL, or `skip` with a message to you.

## Decisions in the workflow

- **A row without an id fills it in by itself.** The first version filtered such rows out without a word, and six planned posts never existed
  for the system while every run reported success. The `Assign missing ids` node removes the cause.
- **Rejecting a draft does not cost the day.** `Backup guard` lets the 11:00 and 13:00 runs take the next row after a rejection.
  If a "no" means an empty slot, people stop pressing it.
- **A run after a stuck `pending` still works.** Only `done` or `pending` from today blocks a backup run.
- **Money in the text gets a warning** on the approval message, because a wrong number is the error you least want published.
- **Dates in many forms are accepted.** An unreadable date sends the row to the normal queue, it is never lost.

## Setup

You need an n8n instance, and credentials for Google Sheets, Google Drive, Telegram, LinkedIn OAuth2 and an HTTP header
(`x-api-key` for the Anthropic API).

1. Create a Google Sheet with the columns from `queue.example.csv`.
2. In `workflow.json` replace `YOUR_SHEET_ID`, `YOUR_TELEGRAM_CHAT_ID` and `YOUR_PERSON_ID` (your LinkedIn member id).
3. Import the file into n8n and attach your credentials to the nodes that show `REPLACE_ME`.
4. Write your own voice into the `System prompt` node. The two prompts in the `Claude` nodes are short placeholders too.
5. Add one `raw` row with `status` = `ready` and run the workflow by hand.
6. The `LinkedIn-Version` headers are pinned to `202606`. LinkedIn retires old versions, so update them when calls start to fail.

Add an error workflow in the workflow settings if you want an alert when a run fails. Mine is a separate two-node workflow that sends a Telegram message.

## Queue columns

| Column | Meaning |
|---|---|
| `id` | unique, filled in automatically when empty |
| `type` | `raw`, `temat` or `projekt` |
| `content` | ready text, a topic or a project note |
| `scheduled_date` | optional, the first number is the day |
| `status` | `ready`, `pending`, `done`, `skip`. Any other value is ignored |
| `posted_at` | set by the workflow |
| `image` | Drive link: a file, or a folder for a gallery |
| `post_text` | the final text |
| `post_url` | the published post |
