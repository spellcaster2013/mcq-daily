# MCQ Daily bot

Posts one MCQ to each channel on every run: **Surgery MCQ Daily** and **Medicine MCQ Daily**.
Runs twice a day on GitHub Actions (07:30 and 19:30 IST), so 2 MCQs per channel per day.

## Files
- `questions.json` : the ONE file holding every MCQ for both subjects. Add new ones at the bottom.
- `config.json`    : channel names, links, colours, hashtags, `low_stock_days` (reminder threshold).
- `bot.py`         : draws the 4 slides, posts to Telegram, sends the owner reminders.
- `state.json`     : created automatically; remembers which MCQs were posted.
- `.github/workflows/daily.yml` : the schedule.

## Each Telegram post
1. Album of 4 slides: question, answer (blurred until tapped), explanation (blurred), join slide.
2. A quiz poll so members can tap their answer.

Once a month (after the first 2 weeks) each channel also gets an audience poll: "What are you preparing for right now?" Edit or switch it off in `config.json`.

## Reminders sent privately to the owner
- "Running out of MCQs" once a day when a channel has 7 days or less of stock.
- Any failure (missing secret, Telegram error, mistake in questions.json).

## GitHub secrets needed
`TELEGRAM_BOT_TOKEN`, `SURGERY_CHAT_ID`, `MEDICINE_CHAT_ID`, `OWNER_CHAT_ID`

## Adding MCQs
Copy an existing block in `questions.json`, give it a new `id` (S011, M011 ...), set `answer` to A, B, C or D.
Options must be 100 characters or less. Order in the file = order of posting.

## Commands
- `python bot.py --check`   : validates the file and prints how many days of stock are left
- `python bot.py --preview` : draws the next slides into `out/` without posting
