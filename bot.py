"""MCQ Daily bot.

Each run posts the next unused MCQ to every destination in config.json:
Telegram channels (4-slide album + quiz poll) and Instagram (@scalpelxlab
carousel via the Instagram API). Progress is recorded in state.json, and the
owner is warned privately when MCQs run low or something fails.

  python bot.py                       post for real (needs the env secrets)
  python bot.py --only instagram      post to one destination only
  python bot.py --preview             only draw the slides into out/, post nothing
  python bot.py --check               validate questions.json and print the stock
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
OUT = ROOT / "out"
IGDIR = ROOT / "ig"
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
    for size in sizes:
        if text_block(draw, (0, 0), text, weight, size, width, spacing=spacing, dry=True) <= max_h:
            return size
    return sizes[-1]


def one_line(draw, xy, text, weight, width, sizes, fill):
    """Draw text on one line, shrinking the font until it fits."""
    for size in sizes:
        f = font(weight, size)
        if draw.textlength(text, font=f) <= width:
            break
    draw.text(xy, text, font=f, fill=fill)


def badge(draw, d):
    name = d["badge"].upper()
    f = font("Bold", 26)
    tw = draw.textlength(name, font=f)
    draw.rounded_rectangle((M, 70, M + tw + 48, 126), 28, fill=d["accent"])
    draw.text((M + 24, 82), name, font=f, fill="#FFFFFF")


def header(draw, d, number, page):
    badge(draw, d)
    num = f"#{number:03d}"
    f2 = font("ExtraBold", 34)
    draw.text((W - M - draw.textlength(num, font=f2), 78), num, font=f2, fill=d["accent"])
    f3 = font("SemiBold", 24)
    draw.text((W - M - draw.textlength(page, font=f3), H - 92), page, font=f3, fill=MUTED)


def footer(draw, text, color=MUTED):
    one_line(draw, (M, H - 92), text, "SemiBold", W - 2 * M - 90, (24, 22, 20, 18), color)


def option_rows(draw, q, y, size, mode, d):
    width = W - 2 * M - 140
    for i, opt in enumerate(q["options"]):
        correct = LETTERS[i] == q["answer"]
        hi = mode == "reveal" and correct
        dim = mode == "reveal" and not correct
        th = text_block(draw, (0, 0), opt, "SemiBold", size, width, dry=True)
        h = max(th + 44, 96)
        draw.rounded_rectangle((M, y, W - M, y + h), 24, fill=GREEN_BG if hi else CARD,
                               outline=GREEN if hi else LINE, width=3 if hi else 2)
        cy = y + h // 2
        draw.ellipse((M + 22, cy - 28, M + 78, cy + 28),
                     fill=GREEN if hi else (LINE if dim else d["accent"]))
        lf = font("Bold", 28)
        lw = draw.textlength(LETTERS[i], font=lf)
        draw.text((M + 50 - lw / 2, cy - 18), LETTERS[i], font=lf, fill=MUTED if dim else "#FFFFFF")
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


def tag_text(q, cfg):
    if q.get("chapter"):
        return f"SABISTON 22E · {q['chapter'].upper()}"
    return f"{q['topic'].upper()}  ·  {cfg['level_tag']}"


def slide_question(q, d, cfg, number, total=4):
    img, dr = new_slide()
    header(dr, d, number, f"1 / {total}")
    one_line(dr, (M, 170), tag_text(q, cfg), "SemiBold", W - 2 * M, (24, 22, 20, 18), MUTED)
    top, bottom = 230, H - 130
    for stem_size, opt_size in ((50, 34), (46, 32), (42, 30), (38, 28), (34, 26), (30, 24)):
        need = (text_block(dr, (0, 0), q["stem"], "Bold", stem_size, W - 2 * M, dry=True)
                + 40 + options_height(dr, q, opt_size))
        if need <= bottom - top:
            break
    y = text_block(dr, (M, top), q["stem"], "Bold", stem_size, W - 2 * M)
    option_rows(dr, q, y + 40, opt_size, "ask", d)
    footer(dr, d["swipe_text"], d["accent"])
    return img


def slide_answer(q, d, cfg, number, page="2 / 4"):
    img, dr = new_slide()
    header(dr, d, number, page)
    dr.text((M, 180), "Answer", font=font("ExtraBold", 72), fill=INK)
    dr.text((M + 330, 180), q["answer"], font=font("ExtraBold", 72), fill=GREEN)
    top, bottom = 320, H - 130
    for opt_size, why_size in ((34, 38), (32, 36), (30, 34), (28, 30), (26, 28)):
        need = (options_height(dr, q, opt_size) + 60
                + text_block(dr, (0, 0), q["reason"], "SemiBold", why_size, W - 2 * M, dry=True) + 50)
        if need <= bottom - top:
            break
    y = option_rows(dr, q, top, opt_size, "reveal", d) + 30
    dr.text((M, y), "WHY", font=font("Bold", 24), fill=d["accent"])
    text_block(dr, (M, y + 44), q["reason"], "SemiBold", why_size, W - 2 * M)
    footer(dr, d.get("answer_footer", "Swipe for the explanation  →"), d["accent"])
    return img


def slide_explanation(q, d, cfg, number, page="3 / 4"):
    img, dr = new_slide()
    header(dr, d, number, page)
    dr.text((M, 180), "Explanation", font=font("ExtraBold", 64), fill=INK)
    inner = W - 2 * M - 72
    pearl_size = fit(dr, q["pearl"], "SemiBold", inner, 230, (32, 30, 28, 26, 24))
    pearl_h = text_block(dr, (0, 0), q["pearl"], "SemiBold", pearl_size, inner, dry=True) + 110
    box_top = H - 140 - pearl_h
    body_h = box_top - 300 - 30
    size = fit(dr, q["explanation"], "Regular", W - 2 * M, body_h, (38, 36, 34, 32, 30, 28, 26, 24), 1.45)
    text_block(dr, (M, 300), q["explanation"], "Regular", size, W - 2 * M, spacing=1.45)
    dr.rounded_rectangle((M, box_top, W - M, box_top + pearl_h), 28, fill=d["dark"])
    dr.text((M + 36, box_top + 30), "HIGH-YIELD PEARL", font=font("Bold", 22), fill="#FFD166")
    text_block(dr, (M + 36, box_top + 74), q["pearl"], "SemiBold", pearl_size, inner, fill="#FFFFFF")
    ref = f"Topic ref: Sabiston 22e, {q['chapter'].split(' · ')[0]}. " if q.get("chapter") else ""
    footer(dr, ref + cfg["disclaimer"])
    return img


def slide_cta(q, d, cfg, number):
    img, dr = new_slide(d["dark"])
    badge(dr, d)
    y = text_block(dr, (M, 330), d.get("cta_title", "Got it right?"), "ExtraBold", 92, W - 2 * M, fill="#FFFFFF", spacing=1.1)
    y = text_block(dr, (M, y + 30), d["cta_line"], "SemiBold", 42, W - 2 * M, fill="#D9DEE2", spacing=1.4)
    dr.text((M, y + 70), d["cta_label"], font=font("Bold", 26), fill="#FFD166")
    lf = font("ExtraBold", 50)
    lw = dr.textlength(d["link"], font=lf)
    dr.rounded_rectangle((M, y + 122, M + lw + 80, y + 230), 54, fill="#FFFFFF")
    dr.text((M + 40, y + 144), d["link"], font=lf, fill=d["dark"])
    dr.text((M, y + 290), d.get("cta_footer", "Save this post.  Send it to a co-resident."),
            font=font("SemiBold", 32), fill="#FFFFFF")
    dr.text((M, H - 92), cfg["disclaimer"], font=font("SemiBold", 24), fill="#9AA4AB")
    return img


# ---- Instagram teaser carousel (question / options / Telegram CTA) ----

def slide_q_only(q, d, cfg, number):
    img, dr = new_slide()
    header(dr, d, number, "1 / 3")
    one_line(dr, (M, 170), tag_text(q, cfg), "SemiBold", W - 2 * M, (24, 22, 20, 18), MUTED)
    dr.text((M, 250), "QUESTION", font=font("Bold", 30), fill=d["accent"])
    size = fit(dr, q["stem"], "Bold", W - 2 * M, 760, (72, 66, 60, 56, 52, 48, 44, 40))
    text_block(dr, (M, 320), q["stem"], "Bold", size, W - 2 * M, spacing=1.3)
    footer(dr, "Swipe for the options  \u2192", d["accent"])
    return img


def slide_options_only(q, d, cfg, number):
    img, dr = new_slide()
    header(dr, d, number, "2 / 3")
    dr.text((M, 180), "OPTIONS", font=font("Bold", 30), fill=d["accent"])
    line = d.get("opt_line", "Answer the poll in the comments. Let's see what everyone else thinks.")
    top, bottom = 250, H - 130
    lh = text_block(dr, (0, 0), line, "ExtraBold", 44, W - 2 * M, dry=True, spacing=1.25)
    for op in (40, 38, 36, 34, 32, 30, 28):
        if options_height(dr, q, op) + 20 + lh <= bottom - top:
            break
    y = option_rows(dr, q, top, op, "ask", d)
    text_block(dr, (M, y + 24), line, "ExtraBold", 44, W - 2 * M, fill=d["accent"], spacing=1.25)
    return img


def slide_cta_teaser(q, d, cfg, number):
    dd = dict(d)
    dd.update(cta_title="Not sure which is right?",
              cta_line=f"The answer and full explanation are on our Telegram channel. Look for the post: Answer to Instagram #{number:03d}.",
              cta_label="FIND IT FREE ON TELEGRAM",
              cta_footer="Save this post.  Send it to a co-resident.")
    return slide_cta(q, dd, cfg, number)


def slide_tg_answer(q, d, cfg, number):
    """Telegram answer card for an Instagram question: big question, smaller options."""
    img, dr = new_slide()
    header(dr, d, number, "1 / 2")
    dr.text((M, 170), f"ANSWER TO INSTAGRAM  \u00b7  #{number:03d}", font=font("SemiBold", 24), fill=MUTED)
    dr.text((M, 215), "Answer", font=font("ExtraBold", 72), fill=INK)
    dr.text((M + 330, 215), q["answer"], font=font("ExtraBold", 72), fill=GREEN)
    top, bottom = 330, H - 130
    for st, op, why in ((46, 28, 30), (42, 28, 28), (38, 26, 28), (34, 26, 26), (32, 24, 26), (28, 24, 24)):
        need = (text_block(dr, (0, 0), q["stem"], "Bold", st, W - 2 * M, dry=True) + 36
                + options_height(dr, q, op) + 50
                + text_block(dr, (0, 0), q["reason"], "SemiBold", why, W - 2 * M, dry=True) + 50)
        if need <= bottom - top:
            break
    y = text_block(dr, (M, top), q["stem"], "Bold", st, W - 2 * M)
    y = option_rows(dr, q, y + 36, op, "reveal", d) + 20
    dr.text((M, y), "WHY", font=font("Bold", 24), fill=d["accent"])
    text_block(dr, (M, y + 42), q["reason"], "SemiBold", why, W - 2 * M)
    footer(dr, "Explanation on the next slide  \u2192", d["accent"])
    return img


def render_tg_answer(q, d, cfg, number):
    OUT.mkdir(exist_ok=True)
    p1 = OUT / f"igans_{number:03d}_{q['id']}_1.png"
    p2 = OUT / f"igans_{number:03d}_{q['id']}_2.png"
    slide_tg_answer(q, d, cfg, number).save(p1, optimize=True)
    slide_explanation(q, d, cfg, number, "2 / 2").save(p2, optimize=True)
    return [p1, p2]


def render(q, d, key, cfg, number):
    OUT.mkdir(exist_ok=True)
    paths = []
    if d.get("style") == "teaser":
        slides = (slide_q_only, slide_options_only, slide_cta_teaser)
    elif d.get("no_cta"):
        slides = (lambda *a: slide_question(*a, total=3),
                  lambda *a: slide_answer(*a, page="2 / 3"),
                  lambda *a: slide_explanation(*a, page="3 / 3"))
    elif d.get("answer_in_comment"):  # question + CTA only; answer goes in a comment later
        slides = (lambda *a: slide_question(*a, total=2), slide_cta)
    else:
        slides = (slide_question, slide_answer, slide_explanation, slide_cta)
    for i, fn in enumerate(slides, 1):
        p = OUT / f"{key}_{number:03d}_{q['id']}_{i}.png"
        fn(q, d, cfg, number).save(p, optimize=True)
        paths.append(p)
    return paths


def options_text(q):
    return "\n".join(f"{LETTERS[i]}. {o}" for i, o in enumerate(q["options"]))


def telegram_caption(q, d, cfg, number):
    where = q.get("chapter") or q["topic"]
    return (f"{d['channel_name']} #{number:03d}  |  {where}\n\n{q['stem']}\n\n{options_text(q)}"
            f"\n\nAnswer and explanation on the next slides.")


def instagram_caption(q, d, cfg, number):
    where = q.get("chapter") or q["topic"]
    if d.get("style") == "teaser":
        ask = ""
    elif d.get("answer_in_comment"):
        ask = ("Vote in the poll 👆 or comment A, B, C or D.\n"
               "Answer, explanation and how many of you got it right: in the comments in 12 hours. "
               "Follow so you don't miss it.\n")
    elif d.get("poll"):
        ask = "Answer in the poll 👆 Swipe for the answer and explanation, then see how many got it right in the Poll.\n"
    else:
        ask = "Comment your answer (A, B, C or D), then swipe for the explanation.\n"
    return (f"NEET SS · INI SS Surgery MCQ #{number:03d}\n{where} (Sabiston 22e)\n\n"
            f"{q['stem']}\n\n{options_text(q)}\n\n{ask}"
            "Save it for revision and send it to a co-resident.\n\n"
            f"Want instant answers? 2 more MCQs daily, free on Telegram: {d['link']} (link in bio)\n\n"
            f"{cfg['disclaimer']}\n\n{d['hashtags']}")[:2200]


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
        if len(q.get("options", [])) != 4 or len(set(q.get("options", []))) != 4:
            errors.append(f"{qid}: needs exactly 4 different options")
        if q.get("answer") not in list(LETTERS):
            errors.append(f"{qid}: answer must be A, B, C or D")
        if any(len(o) > 100 for o in q.get("options", [])):
            errors.append(f"{qid}: an option is over 100 characters (Telegram poll limit)")
        if q.get("route") not in (None, "telegram", "instagram"):
            errors.append(f"{qid}: route must be telegram or instagram")
    return qs, errors


def load_state():
    p = ROOT / "state.json"
    return json.loads(p.read_text()) if p.exists() else {"posted": {}}


def save_state(state):
    (ROOT / "state.json").write_text(json.dumps(state, indent=1))


def stock(qs, state, key, d):
    done = set(state["posted"].get(key, []))
    route = d.get("route")
    return [q for q in qs if q["subject"] == d["subject"] and q.get("route") == route and q["id"] not in done]


# ---------- telegram ----------

def tg(method, token, data=None, files=None):
    import requests
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", data=data, files=files, timeout=120)
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {body.get('description')}")
    return body["result"]


def post_telegram(token, chat_id, q, d, cfg, number, paths):
    media, files = [], {}
    for i, p in enumerate(paths):
        files[f"f{i}"] = open(p, "rb")
        item = {"type": "photo", "media": f"attach://f{i}"}
        if i == 0:
            item["caption"] = telegram_caption(q, d, cfg, number)[:1024]
        if i in (1, 2):
            item["has_spoiler"] = True
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


def ig_permalink(ig_token, cfg, state, number):
    """Link to the Instagram post with this number (matched by its caption), or None."""
    links = state.setdefault("ig_links", {})
    if str(number) in links:
        return links[str(number)]
    if not ig_token:
        return None
    try:
        uid = os.environ.get("IG_USER_ID") or cfg.get("ig_user_id")
        res = ig_call(cfg, "GET", f"{uid}/media", fields="permalink,caption", limit=50, access_token=ig_token)
        tag = f"Surgery MCQ #{number:03d}"
        for m in res.get("data", []):
            if tag in (m.get("caption") or "")[:80] and m.get("permalink"):
                links[str(number)] = m["permalink"]
                return m["permalink"]
    except Exception as e:
        print(f"could not get Instagram link for #{number:03d}: {e}")
    return None


def answer_instagram(token, chat_id, cfg, qs, state, before, failed, ig_token=""):
    """Post the answer to each earlier Instagram question into the Telegram channel."""
    d = cfg["destinations"]["instagram"]  # Instagram colours, so it is not mistaken for the daily Telegram MCQ
    done = state.setdefault("ig_answered", [])
    byid = {x["id"]: x for x in qs}
    for i, qid in enumerate(before, 1):
        if qid in done or qid not in byid:
            continue
        q = byid[qid]
        try:
            paths = render_tg_answer(q, d, cfg, i)
            files, media = {}, []
            for n, p in enumerate(paths):
                files[f"f{n}"] = open(p, "rb")
                item = {"type": "photo", "media": f"attach://f{n}"}
                item["has_spoiler"] = True
                if n == 0:
                    where = q.get("chapter") or q["topic"]
                    link = ig_permalink(ig_token, cfg, state, i) or "https://www.instagram.com/scalpelxlab"
                    item["caption"] = (f"Answer to Instagram #{i:03d}  |  {where}\n"
                                       f"(Our quiz on Instagram: {link}\nNot on Instagram? Here is the question.)\n\n"
                                       f"{q['stem']}\n\n{options_text(q)}\n\n"
                                       f"Tap the images to reveal the answer and explanation.")[:1024]
                media.append(item)
            try:
                tg("sendMediaGroup", token, {"chat_id": chat_id, "media": json.dumps(media)}, files)
            finally:
                for f in files.values():
                    f.close()
            done.append(qid)
            save_state(state)
            print(f"telegram: posted answer to instagram {qid} as #{i:03d}")
        except Exception as e:
            failed.append(f"Telegram answer for Instagram #{i:03d}: {e}")


def audience_poll(token, chat_id, cfg, state, key, d):
    month = dt.date.today().strftime("%Y-%m")
    asked = state.setdefault("audience_poll", {})
    if (not cfg.get("monthly_audience_poll") or asked.get(key) == month
            or len(state["posted"].get(key, [])) < 14 * d["posts_per_day"]):
        return
    try:
        tg("sendPoll", token, {"chat_id": chat_id, "is_anonymous": "true",
                               "question": cfg["audience_poll_question"],
                               "options": json.dumps(cfg["audience_poll_options"])})
        asked[key] = month
        save_state(state)
    except Exception as e:
        print("audience poll failed:", e)


# ---------- instagram ----------

def ig_call(cfg, method, path, **params):
    import requests
    host = "graph.facebook.com" if str(params.get("access_token", "")).startswith("EA") else "graph.instagram.com"
    url = f"https://{host}/{cfg['graph_version']}/{path}"
    r = (requests.get(url, params=params, timeout=60) if method == "GET"
         else requests.post(url, data=params, timeout=60))
    body = r.json()
    if "error" in body:
        raise RuntimeError(f"Instagram {path}: {body['error'].get('message')}")
    return body


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def host_images(paths, key, number, qid):
    """Save JPEG copies under ig/, push them, and return public raw URLs."""
    IGDIR.mkdir(exist_ok=True)
    for old in IGDIR.glob("*.jpg"):  # keep only recent posts in the repo
        try:
            if int(old.name.split("_")[0]) < number - 10:
                old.unlink()
        except ValueError:
            pass
    names = []
    for i, p in enumerate(paths, 1):
        name = f"{number:03d}_{qid}_{i}.jpg"
        Image.open(p).convert("RGB").save(IGDIR / name, "JPEG", quality=92)
        names.append(name)
    git("add", "-A", "ig")
    git("commit", "-m", f"Instagram images for #{number:03d}")
    git("push", "origin", "HEAD")
    sha = git("rev-parse", "HEAD")
    repo = os.environ.get("GITHUB_REPOSITORY", "spellcaster2013/mcq-daily")
    urls = [f"https://raw.githubusercontent.com/{repo}/{sha}/ig/{n}" for n in names]
    import requests
    for u in urls:  # wait until GitHub serves the files
        for _ in range(12):
            if requests.head(u, timeout=20).status_code == 200:
                break
            time.sleep(5)
    return urls


def post_instagram(token, q, d, cfg, number, paths):
    ig_id = os.environ.get("IG_USER_ID") or cfg.get("ig_user_id")
    if not ig_id:
        me = ig_call(cfg, "GET", "me", fields="user_id,username", access_token=token)
        ig_id = me.get("user_id") or me["id"]
    urls = host_images(paths, "instagram", number, q["id"])
    children = [ig_call(cfg, "POST", f"{ig_id}/media", image_url=u, is_carousel_item="true",
                        access_token=token)["id"] for u in urls]
    box_args = dict(media_type="CAROUSEL", children=",".join(children),
                    caption=instagram_caption(q, d, cfg, number), access_token=token)
    poll_on = False
    if d.get("poll"):
        poll = {f"option_{c.lower()}": c for c in LETTERS[:len(q["options"])]}
        try:
            box = ig_call(cfg, "POST", f"{ig_id}/media", poll_attachment=json.dumps(poll), **box_args)["id"]
            poll_on = True
        except Exception as e:
            print("poll not accepted, posting without it:", e)
    if not poll_on:
        box = ig_call(cfg, "POST", f"{ig_id}/media", **box_args)["id"]
    for _ in range(30):
        status = ig_call(cfg, "GET", box, fields="status_code", access_token=token).get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram carousel container status {status}")
        time.sleep(5)
    media_id = ig_call(cfg, "POST", f"{ig_id}/media_publish", creation_id=box, access_token=token)["id"]
    return media_id, poll_on


def poll_result(token, cfg, media_id, answer):
    """Return (percent_correct, total_votes) or None."""
    try:
        r = ig_call(cfg, "GET", f"{media_id}/poll_attachment", access_token=token)
    except Exception as e:
        print("poll read failed:", e)
        return None
    print("poll result:", json.dumps(r)[:500])
    data = r.get("data", [r])
    p = data[0] if isinstance(data, list) and data else r
    a = answer.lower()
    pct = None
    for k in (f"option_{a}_votes_percentage", f"option_{a}_percentage", f"option_{a}_vote_percentage"):
        if k in p:
            pct = float(p[k])
    total = p.get("total_votes") or p.get("total_vote_count") or p.get("vote_count")
    if pct is None:
        return None
    if pct <= 1:
        pct *= 100
    return round(pct), total


def answer_comment(q, d, stats):
    i = LETTERS.index(q["answer"])
    lines = [f"✅ Answer: {q['answer']}. {q['options'][i]}"]
    if stats:
        pct, total = stats
        lines.append(f"📊 {pct}% of you got it right" + (f" ({total} votes)" if total else "") + ".")
    lines += ["", f"Why: {q['reason']}", "", q["explanation"], "", f"💎 Pearl: {q['pearl']}", "",
              f"Instant answers + 2 more MCQs daily on Telegram: {d['link']}"]
    return "\n".join(lines)[:2200]


def reveal_instagram(token, cfg, state, qs, d, alerts, min_hours=10):
    """Comment the answer (and poll stats) on earlier posts once they are old enough."""
    pending = state.get("ig_pending", [])
    if not pending:
        return
    by_id = {q["id"]: q for q in qs}
    keep, now = [], dt.datetime.now(dt.timezone.utc)
    for p in pending:
        age = (now - dt.datetime.fromisoformat(p["at"])).total_seconds() / 3600
        q = by_id.get(p["qid"])
        if q is None or age < min_hours:
            keep.append(p) if q else None
            continue
        stats = poll_result(token, cfg, p["media"], q["answer"]) if p.get("poll") else None
        try:
            ig_call(cfg, "POST", f"{p['media']}/comments", message=answer_comment(q, d, stats),
                    access_token=token)
            print(f"instagram: answer comment added to #{p['number']:03d}")
        except Exception as e:
            p["tries"] = p.get("tries", 0) + 1
            if p["tries"] in (1, 4):
                alerts.append(f"Instagram answer comment for #{p['number']:03d} failed: {e}")
            if p["tries"] < 6:
                keep.append(p)
    state["ig_pending"] = keep


def check_ig_token(token, cfg, state, alerts):
    """Track token age; try a weekly refresh; warn the owner before it expires."""
    today = dt.date.today()
    info = state.setdefault("ig_token", {})
    fp = hashlib.sha256(token.encode()).hexdigest()[:12]
    if info.get("fp") != fp:
        info.update(fp=fp, since=today.isoformat(), refreshed=today.isoformat())
    if token.startswith("EA"):  # system-user token from Unified login never expires
        return
    if (today - dt.date.fromisoformat(info["refreshed"])).days >= 7:
        try:
            r = ig_call(cfg, "GET", "refresh_access_token", grant_type="ig_refresh_token", access_token=token)
            info["refreshed"] = today.isoformat()
            if r.get("access_token") == token:  # same token, new expiry
                info["since"] = today.isoformat()
        except Exception as e:
            print("token refresh failed:", e)
    age = (today - dt.date.fromisoformat(info["since"])).days
    if age >= cfg["ig_token_warn_days"] and state.get("token_alert_on") != today.isoformat():
        alerts.append(f"Instagram token is {age} days old and stops working at about 60 days. "
                      "Generate a new one and replace the IG_ACCESS_TOKEN secret.")
        state["token_alert_on"] = today.isoformat()


def tell_owner(token, text):
    owner = os.environ.get("OWNER_CHAT_ID")
    if token and owner:
        try:
            tg("sendMessage", token, {"chat_id": owner, "text": text})
        except Exception as e:
            print("owner alert failed:", e)
    print("[owner]", text)


# ---------- main ----------

def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--only", "--subject", dest="only", choices=list(cfg["destinations"]) + ["answers"])
    args = ap.parse_args()

    qs, errors = load_questions()
    state = load_state()
    state.setdefault("posted", {})
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    ig_token = os.environ.get("IG_ACCESS_TOKEN", "")
    keys = ([] if args.only == "answers" else [args.only]) if args.only else [k for k, v in cfg["destinations"].items() if v.get("enabled", True)]

    if errors:
        tell_owner(tg_token, "MCQ bot stopped: questions.json has problems.\n" + "\n".join(errors[:15]))
        sys.exit(1)
    if args.check:
        for k, d in cfg["destinations"].items():
            if not d.get("enabled", True):
                continue
            left = len(stock(qs, state, k, d))
            print(f"{k}: {left} unused MCQs = {left // d['posts_per_day']} days")
        return

    failed, low, alerts = [], [], []
    ig_before = list(state["posted"].get("instagram", []))
    for k in keys:
        d = cfg["destinations"][k]
        if d["kind"] == "instagram" and not ig_token and not args.preview:
            print("instagram: not connected yet (no IG_ACCESS_TOKEN), skipped")
            continue
        for rep in range(int(d.get("per_run", 1))):
            left = stock(qs, state, k, d)
            number = len(state["posted"].get(k, [])) + 1
            if not left:
                failed.append(f"{d['channel_name']}: no MCQs left, nothing posted")
                break
            q = left[0]
            paths = render(q, d, k, cfg, number)
            if args.preview:
                print(f"{k}: drew {q['id']} as #{number:03d}")
                continue
            try:
                if d["kind"] == "telegram":
                    chat_id = os.environ.get(d["chat_id_env"], "")
                    if not (tg_token and chat_id):
                        raise RuntimeError(f"secret TELEGRAM_BOT_TOKEN or {d['chat_id_env']} is missing")
                    if rep:
                        time.sleep(int(d.get("gap_seconds", 5)))
                    post_telegram(tg_token, chat_id, q, d, cfg, number, paths)
                else:
                    check_ig_token(ig_token, cfg, state, alerts)
                    if d.get("answer_in_comment"):
                        reveal_instagram(ig_token, cfg, state, qs, d, alerts)
                    media_id, poll_on = post_instagram(ig_token, q, d, cfg, number, paths)
                    try:  # grab the post link right away, so the Telegram answer can point to it
                        pl = ig_call(cfg, "GET", media_id, fields="permalink", access_token=ig_token).get("permalink")
                        if pl:
                            state.setdefault("ig_links", {})[str(number)] = pl
                    except Exception as e:
                        print(f"could not read the Instagram link yet: {e}")
                    if d.get("answer_in_comment"):
                        state.setdefault("ig_pending", []).append(
                            {"media": media_id, "qid": q["id"], "number": number, "poll": poll_on,
                             "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
                state["posted"].setdefault(k, []).append(q["id"])
                save_state(state)
                print(f"{k}: posted {q['id']} as #{number:03d}")
                if d["kind"] == "telegram":
                    audience_poll(tg_token, os.environ.get(d["chat_id_env"]), cfg, state, k, d)
            except Exception as e:
                failed.append(f"{d['channel_name']}: {e}")
                break
        left = stock(qs, state, k, d)
        days = len(left) // d["posts_per_day"]
        if left and days <= cfg["low_stock_days"]:
            low.append(f"{d['channel_name']}: {len(left)} MCQs left (about {days} days)")

    if args.preview:
        return
    sd = cfg["destinations"].get("surgery", {})
    if sd.get("answers_ig") and ("surgery" in keys or "instagram" in keys or args.only == "answers") and tg_token and os.environ.get(sd["chat_id_env"]):
        answer_instagram(tg_token, os.environ[sd["chat_id_env"]], cfg, qs, state, state["posted"].get("instagram", []), failed, ig_token)
    today = dt.date.today().isoformat()
    if failed:
        tell_owner(tg_token, "MCQ bot problem:\n" + "\n".join(failed))
    for a in alerts:
        tell_owner(tg_token, a)
    if low and state.get("low_alert_on") != today:
        tell_owner(tg_token, "Running out of MCQs. Add more to questions.json.\n" + "\n".join(low))
        state["low_alert_on"] = today
    save_state(state)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
