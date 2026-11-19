"""MCQ Daily bot.

Each run posts the next unused MCQ of every subject to its Telegram channel
(4-slide carousel + quiz poll), records it in state.json, and privately warns
the owner when the stock of unused MCQs is running low.

  python bot.py              post for real (needs the env secrets)
  python bot.py --preview    only draw the slides into out/, post nothing
  python bot.py --check      validate questions.json and print the stock
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
OUT = ROOT / "out"
W, H, M = 1080, 1350, 80
BG, INK, MUTED, CARD, LINE = "#F6F4EF", "#14171A", "#6B7278", "#FFFFFF", "#E3DFD6"
GREEN, GREEN_BG = "#178A4C", "#E4F5EA"
LETTERS = "ABCD"


def font(weight, size):
    return ImageFont.truetype(str(ROOT / "fonts" / f"Inter-{weight}.ttf"), size)


def wrap(draw, text, fnt, width):
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=fnt) <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def text_block(draw, xy, text, weight, size, width, fill=INK, spacing=1.35, dry=False):
    """Draw wrapped text; return the y coordinate just below it."""
    fnt = font(weight, size)
    x, y = xy
    step = int(size * spacing)
    for line in wrap(draw, text, fnt, width):
        if not dry:
            draw.text((x, y), line, font=fnt, fill=fill)
        y += step
    return y


def fit(draw, text, weight, width, max_h, sizes, spacing=1.35):
    """Largest size from `sizes` whose wrapped text fits in max_h."""
    for size in sizes:
        if text_block(draw, (0, 0), text, weight, size, width, spacing=spacing, dry=True) <= max_h:
            return size
    return sizes[-1]


def header(draw, sub, number, page):
    name = sub["channel_name"].upper()
    f = font("Bold", 26)
    tw = draw.textlength(name, font=f)
    draw.rounded_rectangle((M, 70, M + tw + 48, 126), 28, fill=sub["accent"])
    draw.text((M + 24, 82), name, font=f, fill="#FFFFFF")
    num = f"#{number:03d}"
    f2 = font("ExtraBold", 34)
    draw.text((W - M - draw.textlength(num, font=f2), 78), num, font=f2, fill=sub["accent"])
    f3 = font("SemiBold", 24)
    draw.text((W - M - draw.textlength(page, font=f3), H - 92), page, font=f3, fill=MUTED)


def footer(draw, text, color=MUTED):
    draw.text((M, H - 92), text, font=font("SemiBold", 24), fill=color)


def option_rows(draw, q, y, size, mode, sub):
    """mode 'ask' = neutral cards, 'reveal' = correct one highlighted."""
    width = W - 2 * M - 140
    for i, opt in enumerate(q["options"]):
        correct = LETTERS[i] == q["answer"]
        hi = mode == "reveal" and correct
        dim = mode == "reveal" and not correct
        h = text_block(draw, (0, 0), opt, "SemiBold", size, width, dry=True) + 44
        h = max(h, 96)
        draw.rounded_rectangle((M, y, W - M, y + h), 24, fill=GREEN_BG if hi else CARD,
                               outline=GREEN if hi else LINE, width=3 if hi else 2)
        cy = y + h // 2
        draw.ellipse((M + 22, cy - 28, M + 78, cy + 28),
                     fill=GREEN if hi else (LINE if dim else sub["accent"]))
        lf = font("Bold", 28)
        lw = draw.textlength(LETTERS[i], font=lf)
        draw.text((M + 50 - lw / 2, cy - 18), LETTERS[i], font=lf, fill=MUTED if dim else "#FFFFFF")
        th = text_block(draw, (0, 0), opt, "SemiBold", size, width, dry=True)
        text_block(draw, (M + 104, y + (h - th) // 2 + 4), opt, "SemiBold", size, width,
                   fill=MUTED if dim else INK)
        y += h + 18
    return y


def options_height(draw, q, size):
    width = W - 2 * M - 140
    return sum(max(text_block(draw, (0, 0), o, "SemiBold", size, width, dry=True) + 44, 96) + 18
               for o in q["options"])


def new_slide(color=BG):
    img = Image.new("RGB", (W, H), color)
    return img, ImageDraw.Draw(img)


def slide_question(q, sub, cfg, number):
    img, d = new_slide()
    header(d, sub, number, "1 / 4")
    tag = f"{q['topic'].upper()}  ·  {cfg['level_tag']}"
    d.text((M, 170), tag, font=font("SemiBold", 24), fill=MUTED)
    top, bottom = 230, H - 130
    for stem_size, opt_size in ((50, 34), (46, 32), (42, 30), (38, 28), (34, 26), (30, 24)):
        need = (text_block(d, (0, 0), q["stem"], "Bold", stem_size, W - 2 * M, dry=True)
                + 40 + options_height(d, q, opt_size))
        if need <= bottom - top:
            break
    y = text_block(d, (M, top), q["stem"], "Bold", stem_size, W - 2 * M)
    option_rows(d, q, y + 40, opt_size, "ask", sub)
    footer(d, "Swipe for the answer  →", sub["accent"])
    return img


def slide_answer(q, sub, cfg, number):
    img, d = new_slide()
    header(d, sub, number, "2 / 4")
    d.text((M, 180), "Answer", font=font("ExtraBold", 72), fill=INK)
    d.text((M + 330, 180), q["answer"], font=font("ExtraBold", 72), fill=GREEN)
    top, bottom = 320, H - 130
    for opt_size, why_size in ((34, 38), (32, 36), (30, 34), (28, 30), (26, 28)):
        need = (options_height(d, q, opt_size) + 60
                + text_block(d, (0, 0), q["reason"], "SemiBold", why_size, W - 2 * M, dry=True) + 50)
        if need <= bottom - top:
            break
    y = option_rows(d, q, top, opt_size, "reveal", sub) + 30
    d.text((M, y), "WHY", font=font("Bold", 24), fill=sub["accent"])
    text_block(d, (M, y + 44), q["reason"], "SemiBold", why_size, W - 2 * M)
    footer(d, "Swipe for the explanation  →", sub["accent"])
    return img


def slide_explanation(q, sub, cfg, number):
    img, d = new_slide()
    header(d, sub, number, "3 / 4")
    d.text((M, 180), "Explanation", font=font("ExtraBold", 64), fill=INK)
    inner = W - 2 * M - 72
    pearl_size = fit(d, q["pearl"], "SemiBold", inner, 230, (32, 30, 28, 26, 24))
    pearl_h = text_block(d, (0, 0), q["pearl"], "SemiBold", pearl_size, inner, dry=True) + 110
    box_top = H - 140 - pearl_h
    body_h = box_top - 300 - 30
    size = fit(d, q["explanation"], "Regular", W - 2 * M, body_h, (38, 36, 34, 32, 30, 28, 26, 24), 1.45)
    text_block(d, (M, 300), q["explanation"], "Regular", size, W - 2 * M, spacing=1.45)
    d.rounded_rectangle((M, box_top, W - M, box_top + pearl_h), 28, fill=sub["dark"])
    d.text((M + 36, box_top + 30), "HIGH-YIELD PEARL", font=font("Bold", 22), fill="#FFD166")
    text_block(d, (M + 36, box_top + 74), q["pearl"], "SemiBold", pearl_size, inner, fill="#FFFFFF")
    footer(d, cfg["disclaimer"])
    return img


def slide_cta(q, sub, cfg, number):
    img, d = new_slide(sub["dark"])
    f = font("Bold", 26)
    name = sub["channel_name"].upper()
    tw = d.textlength(name, font=f)
    d.rounded_rectangle((M, 70, M + tw + 48, 126), 28, fill=sub["accent"])
    d.text((M + 24, 82), name, font=f, fill="#FFFFFF")
    y = text_block(d, (M, 330), "Got it right?", "ExtraBold", 92, W - 2 * M, fill="#FFFFFF", spacing=1.1)
    per = cfg["posts_per_day"]
    line = (f"{per} fresh MCQs every day" if per > 1 else "One fresh MCQ every day")
    y = text_block(d, (M, y + 30), f"{line} at {cfg['level_tag']}, with the answer and explanation.",
                   "SemiBold", 42, W - 2 * M, fill="#D9DEE2", spacing=1.4)
    d.text((M, y + 70), "JOIN FREE ON TELEGRAM", font=font("Bold", 26), fill="#FFD166")
    lf = font("ExtraBold", 50)
    lw = d.textlength(sub["link"], font=lf)
    d.rounded_rectangle((M, y + 122, M + lw + 80, y + 230), 54, fill="#FFFFFF")
    d.text((M + 40, y + 144), sub["link"], font=lf, fill=sub["dark"])
    d.text((M, y + 290), "Save this post.  Send it to a co-resident.", font=font("SemiBold", 32), fill="#FFFFFF")
    d.text((M, H - 92), cfg["disclaimer"], font=font("SemiBold", 24), fill="#9AA4AB")
    return img


def render(q, sub, cfg, number):
    OUT.mkdir(exist_ok=True)
    paths = []
    for i, fn in enumerate((slide_question, slide_answer, slide_explanation, slide_cta), 1):
        p = OUT / f"{q['subject']}_{number:03d}_{q['id']}_{i}.png"
        fn(q, sub, cfg, number).save(p, optimize=True)
        paths.append(p)
    return paths


def caption(q, sub, cfg, number):
    return (f"{sub['channel_name']} #{number:03d}  |  {q['topic']}\n\n{q['stem']}\n\n"
            + "\n".join(f"{LETTERS[i]}. {o}" for i, o in enumerate(q["options"]))
            + f"\n\nAnswer and explanation on the next slides.\n\n{cfg['disclaimer']}\n"
            + f"More daily MCQs: {sub['link']}\n\n{sub['hashtags']}")


# ---------- data ----------

def load_questions():
    qs = json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))
    errors, seen = [], set()
    for q in qs:
        qid = q.get("id", "?")
        if qid in seen:
            errors.append(f"{qid}: duplicate id")
        seen.add(qid)
        for key in ("subject", "topic", "stem", "options", "answer", "reason", "explanation", "pearl"):
            if not q.get(key):
                errors.append(f"{qid}: missing '{key}'")
        if len(q.get("options", [])) != 4:
            errors.append(f"{qid}: needs exactly 4 options")
        if q.get("answer") not in list(LETTERS):
            errors.append(f"{qid}: answer must be A, B, C or D")
        if any(len(o) > 100 for o in q.get("options", [])):
            errors.append(f"{qid}: an option is over 100 characters (Telegram poll limit)")
    return qs, errors


def load_state():
    p = ROOT / "state.json"
    return json.loads(p.read_text()) if p.exists() else {"posted": {}, "low_alert_on": ""}


def stock(qs, state, subject):
    done = set(state["posted"].get(subject, []))
    return [q for q in qs if q["subject"] == subject and q["id"] not in done]


# ---------- telegram ----------

def tg(method, token, data=None, files=None):
    import requests
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", data=data, files=files, timeout=120)
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {body.get('description')}")
    return body["result"]


def post_telegram(token, chat_id, q, sub, cfg, number, paths):
    media, files = [], {}
    for i, p in enumerate(paths):
        files[f"f{i}"] = open(p, "rb")
        item = {"type": "photo", "media": f"attach://f{i}"}
        if i == 0:
            item["caption"] = caption(q, sub, cfg, number)[:1024]
        if i in (1, 2):
            item["has_spoiler"] = True  # answer + explanation stay blurred until tapped
        media.append(item)
    try:
        tg("sendMediaGroup", token, {"chat_id": chat_id, "media": json.dumps(media)}, files)
    finally:
        for f in files.values():
            f.close()
    if cfg.get("send_quiz_poll"):
        tg("sendPoll", token, {
            "chat_id": chat_id, "type": "quiz", "is_anonymous": "true",
            "question": f"#{number:03d}  Your answer?",
            "options": json.dumps([f"{LETTERS[i]}. {o}"[:100] for i, o in enumerate(q["options"])]),
            "correct_option_id": LETTERS.index(q["answer"]),
            "explanation": q["reason"][:200],
        })


def audience_poll(token, chat_id, cfg, state, subject):
    """Once a month (after the first 2 weeks of posts) ask members what they are preparing for."""
    month = dt.date.today().strftime("%Y-%m")
    asked = state.setdefault("audience_poll", {})
    if (not cfg.get("monthly_audience_poll") or asked.get(subject) == month
            or len(state["posted"].get(subject, [])) < 14 * cfg["posts_per_day"]):
        return
    try:
        tg("sendPoll", token, {
            "chat_id": chat_id, "is_anonymous": "true",
            "question": cfg["audience_poll_question"],
            "options": json.dumps(cfg["audience_poll_options"]),
        })
        asked[subject] = month
        (ROOT / "state.json").write_text(json.dumps(state, indent=1))
    except Exception as e:
        print("audience poll failed:", e)


def tell_owner(token, text):
    owner = os.environ.get("OWNER_CHAT_ID")
    if token and owner:
        try:
            tg("sendMessage", token, {"chat_id": owner, "text": text})
        except Exception as e:  # an alert must never break the run
            print("owner alert failed:", e)
    print("[owner]", text)


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--subject", choices=["surgery", "medicine"])
    args = ap.parse_args()

    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    qs, errors = load_questions()
    state = load_state()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    subjects = [args.subject] if args.subject else list(cfg["subjects"])

    if errors:
        tell_owner(token, "MCQ bot stopped: questions.json has problems.\n" + "\n".join(errors[:15]))
        sys.exit(1)
    if args.check:
        for s in cfg["subjects"]:
            left = len(stock(qs, state, s))
            print(f"{s}: {left} unused MCQs = {left // cfg['posts_per_day']} days")
        return

    failed, low = [], []
    for s in subjects:
        sub = cfg["subjects"][s]
        left = stock(qs, state, s)
        number = len(state["posted"].get(s, [])) + 1
        if not left:
            failed.append(f"{sub['channel_name']}: no MCQs left, nothing posted")
            continue
        q = left[0]
        paths = render(q, sub, cfg, number)
        if args.preview:
            print(f"{s}: drew {q['id']} as #{number:03d}")
            continue
        chat_id = os.environ.get(sub["chat_id_env"], "")
        if not (token and chat_id):
            failed.append(f"{sub['channel_name']}: secret TELEGRAM_BOT_TOKEN or {sub['chat_id_env']} is missing")
            continue
        try:
            post_telegram(token, chat_id, q, sub, cfg, number, paths)
            state["posted"].setdefault(s, []).append(q["id"])
            (ROOT / "state.json").write_text(json.dumps(state, indent=1))
            print(f"{s}: posted {q['id']} as #{number:03d}")
            audience_poll(token, chat_id, cfg, state, s)
        except Exception as e:
            failed.append(f"{sub['channel_name']}: {e}")
        days = (len(left) - 1) // cfg["posts_per_day"]
        if days <= cfg["low_stock_days"]:
            low.append(f"{sub['channel_name']}: {len(left) - 1} MCQs left (about {days} days)")

    if args.preview:
        return
    if failed:
        tell_owner(token, "MCQ bot problem:\n" + "\n".join(failed))
    today = dt.date.today().isoformat()
    if low and state.get("low_alert_on") != today:  # at most one reminder a day
        tell_owner(token, "Running out of MCQs. Add more to questions.json.\n" + "\n".join(low))
        state["low_alert_on"] = today
        (ROOT / "state.json").write_text(json.dumps(state, indent=1))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
