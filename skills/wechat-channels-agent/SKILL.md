---
name: wechat-channels-agent
description: Upload vertical commentary videos to a WeChat Channels (视频号) creator account with Playwright. Supports persistent QR login, short title, description/hashtags, optional cover and optional original declaration. Use only on an account the owner controls, with one video per run and explicit publish approval. This is UI automation, not an official WeChat API.
---

# WeChat Channels Upload (视频号)

This skill adapts `wangzhaobo168/wechat-channels-upload` (MIT) to this repo. It
uses Playwright against `channels.weixin.qq.com`; it is **not** an official API
and is not the Mini Program short-drama VOD API.

## Current account

- Channel name: **linkZag**
- Intended content: Mandarin vertical commentary, 9:16, 45–75 seconds
- Default action: prepare a draft; publishing requires `--publish`

## First run: login

The owner must scan the WeChat QR code once. The browser is intentionally
headed; the persistent profile lives at:

```
~/.config/podcast-youtuber-agent/wechat-channels-profile
```

It is outside the repository and must never be committed. Do not ask for or
store a WeChat password, phone code, or QR session.

On the first run, omit `--publish` and complete the QR login manually. Close the
browser when the draft is ready. Later runs reuse the profile.

## Manifest

```json
{
  "account": "linkZag",
  "items": [
    {
      "video": "build/marketing/wechat/linkZag/clip.mp4",
      "cover": "build/marketing/wechat/linkZag/clip-cover.png",
      "title": "央行掉头买黄金",
      "description": "正文…… #黄金 #央行 #通胀"
    }
  ]
}
```

Short-title rules from the Channels UI:

- at least 6 characters
- no punctuation, emoji, hashtags or symbols
- keep it 6–15 Chinese characters
- put the longer argument and hashtags in the description

## Commands

Validate without opening a browser:

```bash
node skills/wechat-channels-agent/scripts/wechat_channels_upload.js \
  --manifest build/marketing/wechat/linkZag/manifest.json --check
```

Prepare a draft after QR login:

```bash
node skills/wechat-channels-agent/scripts/wechat_channels_upload.js \
  --manifest build/marketing/wechat/linkZag/manifest.json
```

Publish one video after the owner has logged in and approved the draft:

```bash
node skills/wechat-channels-agent/scripts/wechat_channels_upload.js \
  --manifest build/marketing/wechat/linkZag/manifest.json \
  --publish --limit 1
```

Useful flags:

- `--profile <dir>` — alternate persistent browser profile
- `--original` — request the original declaration; **off by default** because
  commentary using source excerpts should not claim full originality
- `--receipt <file>` — write a JSON receipt
- `--limit 1` — never batch more than one item initially

## Guardrails

- One video per run. Do not mass-publish.
- Do not claim original when the video uses someone else's interview, audio or
  clips.
- Do not use this to evade CAPTCHA, bans or rate limits.
- Check the rendered title, cover, description and source attribution before
  clicking publish.
- UI selectors can break after a WeChat redesign. If the script stops, take a
  screenshot and update the selectors; do not loop aggressively.

## Limitations

- No official personal-account Channels publishing API.
- The `wxa/sec/vod/*` APIs upload to Mini Program short-drama VOD, not Channels.
- Browser automation may violate platform expectations and can put the account
  at risk. Use only with the owner's informed consent.
