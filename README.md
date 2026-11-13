# RecallForge

RecallForge is a local AI study coach built for [DeltaHacks × Backboard.io](https://deltahacksxbackboard.devpost.com/). It uses a student's earlier mistakes to help choose what to practice next.

## Run locally

Use Python 3.10 or newer. Get a key from [Backboard](https://app.backboard.io/) under **Settings → API Keys**. Set `BACKBOARD_API_KEY` in your local `.env` file and keep it private.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and set BACKBOARD_API_KEY.
.\.venv\Scripts\python.exe app.py
```

### macOS or Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# Edit .env and set BACKBOARD_API_KEY.
.venv/bin/python app.py
```

Open [RecallForge](http://127.0.0.1:5000). A configured status means the app has a key. Ask a question to check that Backboard accepts it.

## Demo

1. Select **Cell biology** and ask how mitosis and meiosis differ.
2. Generate a practice question and choose a wrong answer. Show the correct choice, the explanation, and the updated attempt count.
3. Click **New session** and ask, “Which concept did I miss in my previous quiz, and what should I practice next?” Compare the answer with the earlier feedback.
4. Generate a follow-up question to see how the tutor uses any retrieved context. Give Backboard a moment to extract a new memory and retry the recall prompt if it does not appear on the first attempt.

## How it works

The browser calls Flask for tutoring, quiz generation, and grading. Flask uses Backboard’s `/threads/messages` endpoint with Memory Lite set to `Auto`. A fresh session omits the previous thread ID and reuses the assistant ID stored in the browser. Backboard holds the conversation and extracted memories. The browser stores the assistant ID and aggregate quiz statistics.

Flask checks that each quiz contains four choices and an answer marker. The grading endpoint validates a signed quiz token tied to its topic and session. Tokens expire after an hour or when the server restarts. The app runs on localhost as a single-learner demo.

## Tests

Run the automated tests from the project directory with the virtual environment's Python.

```bash
python -m unittest discover -s tests -v
```

The tests use simulated Backboard responses and cover quiz parsing, malformed-reply retries, grading, error handling, and assistant reuse across threads. The tutor-to-quiz flow was also checked in Edge at desktop and mobile widths using simulated responses. An authenticated Backboard test passed for live tutoring, four-option quiz generation, grading and feedback for an incorrect answer, and exact recall of a study cue in a new thread under the same assistant.

## Event requirements

The event asks teams of two eligible college students aged 17 or older to build with Backboard.io. Devpost lists the venue in Hamilton, Ontario, and a submission deadline of 10:00 p.m. EST on 12 November 2026, equivalent to 03:00 GMT on 13 November. Judging gives 10 points each to creativity, Backboard integration, and usefulness. The Devpost form lists no required website, ZIP, video, or custom submission questions. [Event page](https://deltahacksxbackboard.devpost.com/) · [Official rules](https://deltahacksxbackboard.devpost.com/rules)
