# Sterling Email Job Extraction Agent

Automated agent that monitors a Microsoft 365 mailbox and uses Gemini 2.5 Pro to extract structured job order data from construction/trade client emails.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in .env with your credentials
```

## Authentication

```bash
python src/graph.py --login
```

## Usage

```bash
# Poll continuously for unread emails (default)
python src/main.py --output res/results.json

# Single run on unread emails only
python src/main.py --once --output res/results.json

# Bulk run on all emails in inbox
python src/main.py --all --output res/results.json
```
